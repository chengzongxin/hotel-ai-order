import asyncio
from collections.abc import AsyncIterator
from datetime import datetime

from graph.llm import get_llm, get_llm_run_config
from graph.prompts import PROMPTS_DIR, render_prompt

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from utils.logger_handler import trace_logger
from config.settings import settings
from graph.agent import get_assist_agent
from graph.expected_time import (
    infer_expected_start_time_from_message,
    looks_like_expected_start_time,
    merge_expected_start_time,
    normalize_expected_start_time_text,
)
from graph.order_fields import (
    DEFAULT_URGENCY,
    collect_missing_order_info,
    get_required_order_fields,
    normalize_goods_arrival_status,
    normalize_order_card_update,
)
from graph.products import (
    build_product_search_feedback,
    build_product_search_query,
)
from graph.state import AgentState
from graph.submission import empty_submission, get_effective_service_type, submit_order_from_state
from services.order_workflow import OrderWorkflowService
from services.order_normalizer import normalize_order_defaults
from services.order_context_service import load_order_context
from services.order_state import reset_active_order_state, reset_product_state
from services.order_items import (
    build_effective_order_info,
    build_order_state,
    get_order_items,
    get_primary_order_product,
    strip_item_fields,
    split_order_info,
    sync_primary_item_from_order_info,
    validate_order_items,
)
from services.conversation_service import build_conversation_turn
from services.session_access import ensure_session_access
from memory.postgres_log import save_conversation_log
from memory.readable_sqlite_saver import ReadableAsyncSqliteSaver
from schemas.user import (
    SessionAccessError,
    UserContext,
    require_user,
    user_from_runtime_config,
)
from graph.checkpoint import (
    checkpoint_path,
    get_graph_config,
)
from graph.constants import (
    ACTIVE_ORDER_PHASES,
    MAX_RETRY_COUNT,
    PHASE_CANCELLED,
    PHASE_COLLECTING,
    PHASE_IDLE,
    PHASE_PRE_ORDER,
    PHASE_PRODUCT_SELECTION,
    PHASE_SUBMITTED,
    VALID_MANAGED_REPAIR_SCOPES,
)
from graph.streaming import (
    emit_status,
    emit_token_text,
    message_chunk_to_text,
    run_traced_tool_call,
    stream_llm_text,
)
from graph.text_parsing import (
    build_product_recommendation_text,
    build_selected_product_text,
    detect_service_type,
    format_service_type,
    format_urgency,
    infer_service_type,
    is_cancel_request,
    parse_product_selection,
)
from tools.hosting_coverage import check_hosting_product_coverage
from tools.order_payload_managed import align_order_second_area_with_spu
from tools.product_search import search_product_tool

def get_order_workflow_service() -> OrderWorkflowService:
    return OrderWorkflowService()


class IntentResult(BaseModel):
    intent: str
    room_number: str | None = None
    product: str | None = None
    fault: str | None = None
    area: str | None = None
    urgency: str | None = None
    expected_start_time: str | None = None
    goods_arrival_status: str | None = None
    contacts: str | None = None
    phone: str | None = None
    managed_repair_scope: str | None = None
    user_confirmed: bool = False
    user_cancelled: bool = False


def format_messages(messages: list[BaseMessage]) -> str:
    lines: list[str] = []
    for message in messages:
        role = message.type
        lines.append(f"{role}: {message.content}")
    return "\n".join(lines)


def get_last_human_message(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def get_asked_questions(messages: list[BaseMessage]) -> list[str]:
    return [
        str(message.content)
        for message in messages
        if isinstance(message, AIMessage) and ("?" in str(message.content) or "？" in str(message.content))
    ]


def get_latest_ai_message(messages: list[BaseMessage]) -> AIMessage | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


def has_active_order(state: AgentState) -> bool:
    return state.get("phase") in ACTIVE_ORDER_PHASES


PRODUCT_RESEARCH_FIELDS = {"selected_product", "product_match", "product", "fault"}


def is_collecting_non_product_fields(state: AgentState) -> bool:
    """已选商品后补充时间、区域等字段时，不需要重新做商品检索。"""

    missing_info = state.get("missing_info") or []
    return bool(missing_info) and not any(field in PRODUCT_RESEARCH_FIELDS for field in missing_info)


def clear_product_workflow_state() -> dict[str, object]:
    """服务类型改变后清空依赖旧类型的商品和预下单状态。"""

    return {
        **reset_product_state(),
        "submission": empty_submission(),
    }


def get_product_search_feedback(state: AgentState) -> str | None:
    selected_product = get_primary_order_product(state)
    if not selected_product:
        return None
    return build_product_search_feedback(
        order_info=build_effective_order_info(state),
        selected_product=selected_product,
        service_type=get_effective_service_type(state),
        coverage_result=state.get("coverage_result") or {},
    )


def get_extractor_history(state: AgentState) -> str:
    """提交后的新订单默认只看最新输入，避免已提交订单被重新抽取。"""

    if state.get("last_order") and not state.get("product_request") and not state.get("order"):
        return f"human: {get_last_human_message(state.get('messages', []))}"
    return format_messages(state.get("messages", []))


async def intent_node(state: AgentState) -> dict[str, object]:
    """一次性完成意图识别和订单信息抽取。"""

    emit_status("intent_node", "正在理解您的需求...")
    trace_logger(
        "node.intent.input",
        last_user_message=get_last_human_message(state["messages"]),
        message_count=len(state["messages"]),
        phase=state.get("phase"),
    )
    emit_status("intent_node", "正在识别意图并提取订单信息...")
    llm = get_llm().with_structured_output(IntentResult)
    result = await llm.ainvoke(
        [
            SystemMessage(
                content=render_prompt(
                    "intent/intent.md",
                    conversation_history=get_extractor_history(state),
                    user_input=get_last_human_message(state["messages"]),
                    status=state.get("phase") or PHASE_IDLE,
                    last_order=state.get("last_order", {}),
                )
            ),
        ],
        config=get_llm_run_config(),
    )

    last_user_message = get_last_human_message(state["messages"])
    user_cancelled = result.user_cancelled or (has_active_order(state) and is_cancel_request(last_user_message))
    intent = "cancel_order" if user_cancelled else result.intent
    detected_service_type = detect_service_type(last_user_message)
    if detected_service_type and intent in {"smalltalk", "unknown"}:
        intent = "create_order"
    emit_status("intent_node", f"已识别意图：{intent}")

    phase = state.get("phase")
    if intent in {"create_order", "confirm_order"}:
        phase = PHASE_COLLECTING
        emit_status("intent_node", "正在整理订单信息...")
    elif intent in {"smalltalk", "unknown"} and not has_active_order(state):
        phase = PHASE_IDLE if state.get("phase") == PHASE_SUBMITTED else state.get("phase") or PHASE_IDLE
        emit_status("intent_node", "正在准备辅助回复...")
    elif intent == "cancel_order":
        emit_status("intent_node", "已收到取消请求...")

    detected_fields = {
        "room_number": result.room_number,
        "product": result.product,
        "fault": result.fault,
        "area": result.area,
        "urgency": result.urgency,
        "expected_start_time": result.expected_start_time,
        "goods_arrival_status": normalize_goods_arrival_status(result.goods_arrival_status),
        "contacts": result.contacts,
        "phone": result.phone,
        "managed_repair_scope": result.managed_repair_scope
        if result.managed_repair_scope in VALID_MANAGED_REPAIR_SCOPES
        else None,
        "user_confirmed": result.user_confirmed,
        "user_cancelled": user_cancelled,
    }
    existing_order_info = build_effective_order_info(state) if has_active_order(state) else {}
    if intent in {"smalltalk", "unknown", "cancel_order"}:
        order_info = existing_order_info if has_active_order(state) else {}
        if intent == "cancel_order":
            order_info = {**order_info, "user_confirmed": False, "user_cancelled": True}
    else:
        # 新输入明确了公区，清除旧单遗留的房号和区域，避免 normalize 时房号优先级覆盖公区判断
        cleaned_existing = dict(existing_order_info)
        if detected_fields.get("managed_repair_scope") == "公区":
            cleaned_existing.pop("room_number", None)
            cleaned_existing.pop("area", None)
            cleaned_existing.pop("second_area", None)
            cleaned_existing.pop("managed_repair_scope", None)
        # 新输入明确了房号（客房），清除旧单遗留的公区信息
        elif detected_fields.get("room_number") or detected_fields.get("managed_repair_scope") == "客房":
            cleaned_existing.pop("managed_repair_scope", None)
            cleaned_existing.pop("area", None)
            cleaned_existing.pop("second_area", None)

        order_info = {
            **cleaned_existing,
            **{
                key: value
                for key, value in detected_fields.items()
                if value is not None and key != "expected_start_time"
            },
        }
        merged_expected_time = merge_expected_start_time(
            cleaned_existing.get("expected_start_time"),
            normalize_expected_start_time_text(detected_fields.get("expected_start_time")),
        )
        inferred_expected_time = infer_expected_start_time_from_message(last_user_message)
        merged_expected_time = merge_expected_start_time(merged_expected_time, inferred_expected_time)
        if merged_expected_time:
            order_info["expected_start_time"] = merged_expected_time
        order_info["user_confirmed"] = result.user_confirmed
        order_info["user_cancelled"] = user_cancelled
    current_service_type = state.get("service_type") if has_active_order(state) else None
    service_type = (
        infer_service_type(last_user_message, current_service_type)
        if intent in {"create_order", "confirm_order"}
        else state.get("service_type")
    )
    service_type_changed = bool(
        current_service_type
        and service_type
        and service_type != current_service_type
    )
    primary_product = get_primary_order_product(state)
    detected_product_name = str(detected_fields.get("product") or "").strip()
    current_product_names = {
        str(primary_product.get("service_product_name") or "").strip(),
        str((get_order_items(state)[0] if get_order_items(state) else {}).get("product_name") or "").strip(),
    }
    product_change_requested = bool(
        get_order_items(state)
        and detected_product_name
        and not any(
            name and (detected_product_name in name or name in detected_product_name)
            for name in current_product_names
        )
    )
    output: dict[str, object] = {
        "intent": intent,
        "phase": phase,
        **split_order_info(order_info, keep_product_request=not bool(get_order_items(state))),
        "step": "intent_node",
        "last_user_message": last_user_message,
        "product_change_requested": product_change_requested,
    }
    if get_order_items(state) and intent in {"create_order", "confirm_order"} and not service_type_changed and not product_change_requested:
        output["order"] = build_order_state(
            strip_item_fields(order_info),
            sync_primary_item_from_order_info(get_order_items(state), order_info),
        )
        output["product_request"] = {}
    if intent in {"create_order", "confirm_order"}:
        output["service_type"] = service_type
    if intent in {"create_order", "confirm_order"} and state.get("phase") == PHASE_SUBMITTED:
        output.update(clear_product_workflow_state())
    elif service_type_changed or product_change_requested:
        output.update(clear_product_workflow_state())
        output["product_change_requested"] = product_change_requested
    elif intent in {"smalltalk", "unknown"} and state.get("phase") == PHASE_SUBMITTED:
        output.update({"submission": empty_submission()})
    trace_logger("node.intent.output", **output)
    if intent in {"create_order", "confirm_order"}:
        emit_status("intent_node", "已完成需求理解，准备匹配商品...")
    return output


async def search_product_node(state: AgentState) -> dict[str, object]:
    """根据已抽取的商品和问题，尽早匹配真实可下单商品。"""

    workflow = get_order_workflow_service()
    existing_products = state.get("products") or []
    last_msg = state.get("last_user_message", "")
    selection = parse_product_selection(last_msg)
    if existing_products and selection == 0:
        output = workflow.reject_products(service_type=state.get("service_type"))
        trace_logger("node.search_product.rejected", **output)
        return output

    if (
        existing_products
        and selection is not None
        and 1 <= selection <= len(existing_products)
    ):
        output = workflow.select_existing_product_by_rank(state=state, selection=int(selection))
        trace_logger("node.search_product.selected_by_text", selection=selection, **output)
        return output

    if state.get("intent") == "confirm_order" and get_order_items(state):
        trace_logger(
            "node.search_product.skip",
            reason="confirm_with_existing_products",
            product_count=len(existing_products),
        )
        return {"step": "search_product_node"}

    selected_product = get_primary_order_product(state)
    if state.get("intent") == "create_order" and selected_product and not state.get("product_change_requested"):
        trace_logger(
            "node.search_product.skip",
            reason="supplement_info_with_selected_product",
            missing_info=state.get("missing_info") or [],
            product_count=len(existing_products),
        )
        return {"step": "search_product_node"}

    order_info = build_effective_order_info(state)
    service_type = infer_service_type(last_msg, state.get("service_type"))

    search_query = build_product_search_query(order_info, service_type)
    if not search_query:
        output = {
            "products": [],
            "service_type": service_type,
            "step": "search_product_node",
        }
        trace_logger("node.search_product.skipped", **output)
        return output

    search_params = {
        "query": search_query,
        "top_k": 10,
        "threshold": None,
        "service_type": service_type,
    }
    result = await run_traced_tool_call(
        step="search_product_node",
        name="search_product_tool",
        display_name="商品检索",
        params=search_params,
        action=lambda: asyncio.to_thread(search_product_tool.invoke, search_params),
    )
    data = result.get("data", {})
    products = data.get("products") or []
    search_status = "success" if products else "no_match"
    if result.get("status") != "success":
        search_status = "error"

    emit_status("search_product_node", f"已根据对话确定服务类型：{service_type}")
    normalized_order_info = normalize_order_defaults(
        service_type=service_type,
        order_info=order_info,
        last_user_message=state.get("last_user_message", ""),
    )

    output = workflow.match_products(
        state={**state, **split_order_info(normalized_order_info, keep_product_request=True)},
        products=products,
        service_type=service_type,
    )
    trace_logger(
        "node.search_product.output",
        tool_status=result.get("status"),
        tool_error_code=result.get("error_code"),
        tool_message=result.get("message"),
        search_status=search_status,
        **output,
    )
    return output


async def coverage_node(state: AgentState) -> dict[str, object]:
    """托管维修商品下单前，校验当前用户维保卡是否覆盖该商品。"""

    selected_product = get_primary_order_product(state)
    if (state.get("products") or []) and not selected_product:
        return {
            "effective_service_type": None,
            "coverage_result": {},
            "step": "coverage_node",
        }
    service_type = state.get("service_type")
    if not service_type:
        return {
            "effective_service_type": None,
            "coverage_result": {},
            "step": "coverage_node",
        }

    if service_type != "托管维修":
        return {
            "effective_service_type": service_type,
            "coverage_result": {
                "checked": False,
                "covered": None,
                "reason": "非托管维修商品，无需校验维保卡范围",
                "effective_service_type": service_type,
            },
            "step": "coverage_node",
        }

    emit_status("coverage_node", "正在校验维保卡范围...")
    effective_order_info = build_effective_order_info(state)
    coverage_params = {
        "order_info": effective_order_info,
        "matched_product": selected_product,
        "last_user_message": state.get("last_user_message", ""),
    }
    coverage_result = await run_traced_tool_call(
        step="coverage_node",
        name="check_hosting_product_coverage",
        display_name="维保范围校验",
        params=coverage_params,
        action=lambda: check_hosting_product_coverage(
            order_info=effective_order_info,
            matched_product=selected_product,
            user=user_from_runtime_config(),
            last_user_message=state.get("last_user_message", ""),
        ),
    )
    coverage_data = coverage_result.get("data") or {}
    effective_service_type = coverage_data.get("effective_service_type") or service_type
    order_info = normalize_order_defaults(
        service_type=effective_service_type,
        order_info=effective_order_info,
        last_user_message=state.get("last_user_message", ""),
    )
    spu_detail = coverage_data.get("spu_detail") if isinstance(coverage_data.get("spu_detail"), dict) else {}
    if effective_service_type == "托管维修" and spu_detail:
        order_info, area_match = align_order_second_area_with_spu(
            order_info,
            spu_detail,
            source_text=state.get("last_user_message", ""),
        )
        coverage_data = {**coverage_data, "area_match": area_match}

    if effective_service_type != service_type:
        emit_status("coverage_node", "该商品不在维保范围内，将按单次维修继续下单。")
    elif (coverage_data.get("area_match") or {}).get("matched") is False:
        emit_status("coverage_node", "该商品关联区域需要进一步确认。")
    else:
        emit_status("coverage_node", "该商品在维保范围内，可继续托管维修下单。")

    updated_items = sync_primary_item_from_order_info(get_order_items(state), order_info)
    if updated_items:
        updated_items[0]["coverage"] = coverage_data
    output = {
        "effective_service_type": effective_service_type,
        "coverage_result": coverage_data,
        **split_order_info(order_info, keep_product_request=False),
        "order": build_order_state(strip_item_fields(order_info), updated_items),
        "step": "coverage_node",
    }
    trace_logger(
        "node.coverage.output",
        tool_status=coverage_result.get("status"),
        tool_error_code=coverage_result.get("error_code"),
        service_type=service_type,
        **output,
    )
    return output


async def prepare_order_context_node(state: AgentState) -> dict[str, object]:
    """选择商品后，准备预下单卡片所需的默认值和展示字段。"""

    selected_product = get_primary_order_product(state)
    if not selected_product:
        return {
            "order_context": {},
            "order_card_fields": [],
            "step": "prepare_order_context_node",
        }

    service_type = get_effective_service_type(state)
    workflow_service = get_order_workflow_service()
    prepare_params = {
        "service_type": service_type,
        "order_info": build_effective_order_info(state),
        "product_code": selected_product.get("service_product_code"),
    }
    prepared = await run_traced_tool_call(
        step="prepare_order_context_node",
        name="prepare_pre_order",
        display_name="预下单信息准备",
        params=prepare_params,
        action=lambda: workflow_service.prepare_pre_order(
            state=state,
            service_type=service_type,
            user=user_from_runtime_config(),
        ),
    )
    output = {
        **prepared,
        "step": "prepare_order_context_node",
    }
    trace_logger("node.prepare_order_context.output", service_type=service_type, **output)
    return output


async def validate_order_node(state: AgentState) -> dict[str, object]:
    """按订单类型检查缺失字段，并记录重试次数。"""

    products = state.get("products") or []
    if products and not get_order_items(state):
        return {
            "missing_info": ["selected_product"],
            "retry_count": state.get("retry_count", 0),
            "phase": PHASE_PRODUCT_SELECTION,
            "step": "validate_order_node",
        }

    service_type = get_effective_service_type(state)
    order_info = normalize_order_defaults(
        service_type=service_type,
        order_info=build_effective_order_info(state),
        last_user_message=state.get("last_user_message", ""),
    )
    required_fields = get_required_order_fields(service_type, order_info)
    missing_info = collect_missing_order_info(
        service_type,
        order_info,
        state.get("order_card_fields") or [],
    )
    if "expected_start_time" in required_fields and order_info.get("expected_start_time"):
        if not looks_like_expected_start_time(str(order_info["expected_start_time"])):
            order_info.pop("expected_start_time", None)
            if "expected_start_time" not in missing_info:
                missing_info.append("expected_start_time")

    updated_items = sync_primary_item_from_order_info(get_order_items(state), order_info)
    updated_items, item_missing = validate_order_items(
        service_type,
        strip_item_fields(order_info),
        updated_items,
    )
    missing_info.extend(field for field in item_missing if field not in missing_info)

    retry_count = state.get("retry_count", 0)
    if missing_info:
        retry_count += 1

    output = {
        "missing_info": missing_info,
        **split_order_info(order_info, keep_product_request=False),
        "order": build_order_state(strip_item_fields(order_info), updated_items),
        "retry_count": retry_count,
        "phase": PHASE_PRE_ORDER,
        "step": "validate_order_node",
    }
    trace_logger(
        "node.validate_order.output",
        service_type=service_type,
        required_fields=required_fields,
        **output,
    )
    return output


def build_missing_info_fallback_question(missing_info: list[str]) -> str:
    if not missing_info:
        return "请确认是否提交订单？"

    field = missing_info[0]
    questions = {
        "selected_product": build_product_recommendation_text([]),
        "product_match": "商品库没检索到这个商品，请您再说得更精确一点。",
        "room_number": "请问您住哪个房间？",
        "product": "是哪样东西坏了？",
        "fault": "具体是什么故障呢？",
        "area": "请问是客房还是公区？",
        "second_area": "请问具体在哪个区域？",
        "expected_start_time": "还需补充：期待开工时间。请问具体什么时间？比如明天上午或3月20日",
        "goods_arrival_status": "请问货物是否到场？",
        "contacts": "请问联系人姓名是什么？",
        "phone": "请问联系电话是多少？",
    }
    return questions.get(field, f"请补充{field}。")


async def build_missing_info_question(state: AgentState) -> str:
    missing_info = state.get("missing_info", [])
    if not missing_info:
        return build_missing_info_fallback_question(missing_info)
    if missing_info[0] == "product_match":
        return build_missing_info_fallback_question(missing_info)
    if missing_info[0] == "expected_start_time":
        return build_missing_info_fallback_question(missing_info)
    if missing_info[0] == "goods_arrival_status":
        return build_missing_info_fallback_question(missing_info)

    prompt = render_prompt(
        "ask/missing_info.md",
        order_info=build_effective_order_info(state),
        missing_info=missing_info,
        asked_questions=get_asked_questions(state.get("messages", [])),
        last_user_message=get_last_human_message(state.get("messages", [])),
    )
    question = await stream_llm_text([SystemMessage(content=prompt)], step="ask_node")
    return question or build_missing_info_fallback_question(missing_info)


async def build_topic_boundary_response(state: AgentState) -> str:
    missing_info = state.get("missing_info", [])
    active_order = has_active_order(state)
    next_question = build_missing_info_fallback_question(missing_info) if active_order else ""
    if active_order and not missing_info and not build_effective_order_info(state):
        next_question = "请说房号和故障。"
    prompt = render_prompt(
        "ask/off_topic.md",
        last_user_message=get_last_human_message(state.get("messages", [])),
        active_order=active_order,
        status=state.get("phase") or PHASE_IDLE,
        order_info=build_effective_order_info(state) if active_order else {},
        last_order=state.get("last_order", {}),
        missing_info=missing_info,
        next_question=next_question,
        off_topic_count=state.get("off_topic_count", 0) + 1,
        current_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    answer = await stream_llm_text([SystemMessage(content=prompt)], step="ask_node")
    return answer or render_prompt(
        "ask/unknown_fallback.md",
        next_question=next_question or "如果需要继续报修，请告诉我房号和故障。",
    )


async def ask_node(state: AgentState) -> dict[str, object]:
    """返回追问，让本轮语音对话自然结束。"""

    missing_info = state.get("missing_info", [])
    retry_count = state.get("retry_count", 0)
    off_topic_count = state.get("off_topic_count", 0)
    is_topic_deviation = state.get("intent") in {"unknown", "smalltalk"}
    product_search_feedback = get_product_search_feedback(state)
    products = state.get("products") or []
    selected_product = get_primary_order_product(state)
    last_user_message = get_last_human_message(state.get("messages", []))
    selected_by_text = parse_product_selection(last_user_message) in {1, 2, 3}

    if state.get("product_selection_rejected"):
        question = "好的，请您再详细描述商品和故障现象，我再帮您推荐服务商品。"
        await emit_token_text(question, step="ask_node")
    elif products and not selected_product:
        question = build_product_recommendation_text(products)
        await emit_token_text(question, step="ask_node")
    elif selected_product and selected_by_text and missing_info:
        prefix = build_selected_product_text(selected_product)
        question = f"{prefix}\n{build_missing_info_fallback_question(missing_info)}"
        await emit_token_text(question, step="ask_node")
    elif is_topic_deviation:
        question = await build_topic_boundary_response(state)
        off_topic_count += 1
    elif retry_count > MAX_RETRY_COUNT:
        question = render_prompt(
            "ask/missing_info_retry.md",
            missing_info=", ".join(missing_info),
        )
        await emit_token_text(question, step="ask_node")
    elif product_search_feedback and missing_info:
        question = f"{product_search_feedback}\n{build_missing_info_fallback_question(missing_info)}"
        await emit_token_text(question, step="ask_node")
    else:
        question = await build_missing_info_question(state)

    trace_logger(
        "node.ask.output",
        question=question,
        missing_info=missing_info,
        retry_count=retry_count,
        off_topic_count=off_topic_count,
        intent=state.get("intent"),
    )

    output = {
        "messages": [AIMessage(content=question)],
        "step": "ask_node",
        "phase": state.get("phase") or PHASE_IDLE,
        "off_topic_count": off_topic_count,
    }
    if is_topic_deviation and not has_active_order(state):
        output.update(
            {
                "service_type": None,
                "product_request": {},
                "order": {"items": []},
                "missing_info": [],
                "retry_count": 0,
            }
        )
    return output


async def assist_node(state: AgentState) -> dict[str, object]:
    """使用 LangChain 官方 create_agent middleware 处理非主下单咨询。"""

    trace_logger(
        "node.assist.input",
        message_count=len(state.get("messages", [])),
        intent=state.get("intent"),
        phase=state.get("phase"),
    )
    answer_parts: list[str] = []
    latest_messages: list[BaseMessage] = []
    async for part in get_assist_agent().astream(
        {"messages": state.get("messages", [])},
        config=get_llm_run_config(),
        stream_mode=["messages", "updates"],
        version="v2",
    ):
        part_type = part.get("type")
        data = part.get("data")
        if part_type == "messages" and isinstance(data, tuple):
            message_chunk, _metadata = data
            token = message_chunk_to_text(getattr(message_chunk, "content", ""))
            if token:
                answer_parts.append(token)
                await emit_token_text(token, step="assist_node", chunk_size=4, delay_seconds=0)
        elif part_type == "updates" and isinstance(data, dict):
            for node_update in data.values():
                if isinstance(node_update, dict) and isinstance(node_update.get("messages"), list):
                    latest_messages = node_update["messages"]

    answer = "".join(answer_parts).strip()
    if not answer:
        answer_message = get_latest_ai_message(latest_messages)
        answer = str(answer_message.content) if answer_message else "如果需要下单，请告诉我房号、商品和问题。"
        await emit_token_text(answer, step="assist_node")

    trace_logger(
        "node.assist.output",
        answer=str(answer),
        message_count=len(latest_messages),
    )
    return {
        "messages": [AIMessage(content=str(answer))],
        "step": "assist_node",
        "phase": state.get("phase") or PHASE_IDLE,
    }


async def confirm_node(state: AgentState) -> dict[str, object]:
    """让用户确认订单信息。"""

    order_info = build_effective_order_info(state)
    service_type = get_effective_service_type(state)
    selected_product = get_primary_order_product(state)

    if order_info.get("user_confirmed"):
        trace_logger("node.confirm.skip", reason="user_confirmed")
        return {
            "step": "confirm_node",
        }

    products = state.get("products") or []
    if products:
        confirmation_text = (
            "好的，收到。信息已齐全，已为您生成预下单页面，如需修改，"
            "请直接点击修改下单信息；如确认无误，请对我说”确认“，"
            "或手动点击下方的”确认“按钮。"
        )
        product_search_feedback = get_product_search_feedback(state)
        if product_search_feedback:
            confirmation_text = f"{product_search_feedback}\n\n{confirmation_text}"
        coverage_result = state.get("coverage_result") or {}
        if coverage_result.get("checked") and coverage_result.get("covered") is False:
            confirmation_text = f"{coverage_result.get('reason')}\n{confirmation_text}"
    else:
        confirmation_text = render_prompt(
            "confirm/confirm.md",
            service_type=format_service_type(service_type, order_info),
            room_number=order_info.get("room_number"),
            product=order_info.get("product"),
            fault=order_info.get("fault"),
            area=order_info.get("area"),
            second_area=order_info.get("second_area") or "无",
            urgency=format_urgency(order_info.get("urgency") or DEFAULT_URGENCY),
            expected_start_time=order_info.get("expected_start_time") or "无",
            goods_arrival_status=order_info.get("goods_arrival_status") or "无",
            product_name=selected_product.get("service_product_name") or "未匹配到标准商品",
            product_code=selected_product.get("service_product_code") or "无",
        )
    await emit_token_text(confirmation_text, step="confirm_node")

    trace_logger(
        "node.confirm.output",
        confirmation_text=confirmation_text,
        order_info=order_info,
    )

    return {
        "messages": [AIMessage(content=confirmation_text)],
        "step": "confirm_node",
        "phase": PHASE_PRE_ORDER,
    }


async def cancel_node(state: AgentState) -> dict[str, object]:
    """取消当前预下单，避免旧订单继续参与后续对话。"""

    answer = render_prompt("cancel/cancel.md")
    await emit_token_text(answer, step="cancel_node")
    output = {
        **reset_active_order_state(),
        "messages": [AIMessage(content=answer)],
        "step": "cancel_node",
        "intent": "cancel_order",
        "phase": PHASE_CANCELLED,
        "submission": empty_submission(),
        "retry_count": 0,
        "off_topic_count": 0,
    }
    trace_logger(
        "node.cancel.output",
        answer=answer,
        previous_phase=state.get("phase"),
        previous_order_info=build_effective_order_info(state),
    )
    return output


async def submit_node(state: AgentState) -> dict[str, object]:
    """LangGraph 提交节点，从运行时配置读取当前用户上下文。"""

    return await submit_order_from_state(
        state,
        user_from_runtime_config(),
        emit=True,
        emit_token_text=emit_token_text,
    )


def route_after_intent(state: AgentState) -> str:
    intent = state.get("intent")
    order_info = build_effective_order_info(state)
    if intent == "cancel_order" or order_info.get("user_cancelled"):
        return "cancel_node"
    if state.get("products") and parse_product_selection(state.get("last_user_message", "")) is not None:
        return "search_product_node"
    if intent in {"create_order", "confirm_order"}:
        return "search_product_node"
    if intent in {"smalltalk", "unknown"} and not has_active_order(state):
        return "assist_node"
    return "ask_node"


def route_after_search_product(state: AgentState) -> str:
    if state.get("product_selection_rejected"):
        return "ask_node"
    if "product_match" in (state.get("missing_info") or []):
        return "ask_node"
    products = state.get("products") or []
    if products and not get_order_items(state):
        return "ask_node"
    return "coverage_node"


def route_after_validation(state: AgentState) -> str:
    if state.get("missing_info"):
        return "ask_node"
    return "confirm_node"


def route_after_confirm(state: AgentState) -> str:
    order_info = build_effective_order_info(state)
    if order_info.get("user_confirmed"):
        return "submit_node"
    return END


def build_graph(checkpointer: ReadableAsyncSqliteSaver | None = None):
    graph = StateGraph(AgentState)
    graph.add_node("intent_node", intent_node)
    graph.add_node("search_product_node", search_product_node)
    graph.add_node("coverage_node", coverage_node)
    graph.add_node("prepare_order_context_node", prepare_order_context_node)
    graph.add_node("validate_order_node", validate_order_node)
    graph.add_node("ask_node", ask_node)
    graph.add_node("assist_node", assist_node)
    graph.add_node("confirm_node", confirm_node)
    graph.add_node("cancel_node", cancel_node)
    graph.add_node("submit_node", submit_node)

    graph.add_edge(START, "intent_node")
    graph.add_conditional_edges(
        "intent_node",
        route_after_intent,
        {
            "cancel_node": "cancel_node",
            "search_product_node": "search_product_node",
            "assist_node": "assist_node",
            "ask_node": "ask_node",
        },
    )
    graph.add_conditional_edges(
        "search_product_node",
        route_after_search_product,
        {
            "ask_node": "ask_node",
            "coverage_node": "coverage_node",
        },
    )
    graph.add_edge("coverage_node", "prepare_order_context_node")
    graph.add_edge("prepare_order_context_node", "validate_order_node")
    graph.add_conditional_edges(
        "validate_order_node",
        route_after_validation,
        {
            "ask_node": "ask_node",
            "confirm_node": "confirm_node",
        },
    )
    graph.add_conditional_edges(
        "confirm_node",
        route_after_confirm,
        {
            "submit_node": "submit_node",
            END: END,
        },
    )
    graph.add_edge("ask_node", END)
    graph.add_edge("assist_node", END)
    graph.add_edge("cancel_node", END)
    graph.add_edge("submit_node", END)

    if checkpointer is None:
        return graph.compile()

    return graph.compile(checkpointer=checkpointer)


def get_interrupt_answer(result: dict[str, object]) -> str | None:
    """兼容旧 checkpoint 中可能残留的 interrupt 结果。"""

    interrupts = result.get("__interrupt__")
    if not interrupts:
        return None

    first_interrupt = interrupts[0]
    payload = getattr(first_interrupt, "value", first_interrupt)
    if isinstance(payload, dict):
        question = payload.get("question")
        return str(question) if question else None

    return str(payload)

NODE_STATUS_MESSAGES = {
    "intent_node": "正在理解您的需求并提取订单信息...",
    "search_product_node": "正在匹配可下单的标准商品...",
    "coverage_node": "正在校验商品是否在维保范围内...",
    "prepare_order_context_node": "正在读取下单默认信息...",
    "validate_order_node": "正在检查订单信息是否完整...",
    "ask_node": "正在生成追问问题...",
    "confirm_node": "正在整理订单确认信息...",
    "submit_node": "正在提交订单...",
    "cancel_node": "正在取消当前订单...",
    "assist_node": "正在调用辅助智能体处理问题...",
}

STREAMABLE_TOKEN_NODES: set[str] = set()


async def stream_agent_events(
    user_message: str,
    session_id: str,
    user: UserContext,
) -> AsyncIterator[dict[str, object]]:
    active_user = require_user(user)
    active_session_id = session_id

    trace_logger(
        "agent.stream.start",
        session_id=active_session_id,
        user_id=active_user.user_id,
        user_message=user_message,
    )
    yield {
        "type": "status",
        "step": "intent_node",
        "message": NODE_STATUS_MESSAGES["intent_node"],
    }

    turn_input_state: AgentState = {
        "user_id": active_user.user_id,
        "messages": [HumanMessage(content=user_message)],
        "last_user_message": user_message,
    }

    try:
        async with ReadableAsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
            await checkpointer.setup()
            graph = build_graph(checkpointer)
            config = get_graph_config(active_user, active_session_id)
            existing_snapshot = await graph.aget_state(config)
            if existing_snapshot.values:
                ensure_session_access(existing_snapshot.values, active_user)

            latest_state: dict[str, object] = dict(turn_input_state)
            emitted_token = False
            async for part in graph.astream(
                turn_input_state,
                config=config,
                stream_mode=["updates", "messages", "custom"],
                version="v2",
            ):
                part_type = part.get("type")
                data = part.get("data")

                if part_type == "updates" and isinstance(data, dict):
                    for node_name, node_update in data.items():
                        if not isinstance(node_update, dict):
                            continue

                        latest_state.update(node_update)
                        yield {
                            "type": "status",
                            "step": node_name,
                            "message": NODE_STATUS_MESSAGES.get(node_name, "正在处理您的请求..."),
                        }

                if part_type == "messages" and isinstance(data, tuple):
                    message_chunk, metadata = data
                    if not isinstance(metadata, dict):
                        continue

                    node_name = metadata.get("langgraph_node")
                    if node_name not in STREAMABLE_TOKEN_NODES:
                        continue

                    token = message_chunk_to_text(getattr(message_chunk, "content", ""))
                    if not token:
                        continue

                    if not emitted_token:
                        emitted_token = True
                        yield {
                            "type": "status",
                            "step": node_name,
                            "message": "正在输出回复...",
                        }

                    yield {
                        "type": "token",
                        "step": node_name,
                        "content": token,
                    }

                if part_type == "custom":
                    if isinstance(data, dict) and data.get("type") in {"status", "token", "tool_call"}:
                        yield data
                    else:
                        yield {
                            "type": "status",
                            "message": str(data),
                        }

            snapshot = await graph.aget_state(config)
            final_state = snapshot.values or latest_state
            answer = get_interrupt_answer(final_state) or final_state["messages"][-1].content
            state_messages = final_state.get("messages", [])
            last_message = state_messages[-1] if state_messages else None
            if not isinstance(last_message, AIMessage) or last_message.content != answer:
                await graph.aupdate_state(
                    config,
                    {"messages": [AIMessage(content=answer)]},
                    as_node="ask_node",
                )
            conversation_messages = build_conversation_turn(
                human_content=user_message,
                ai_content=str(answer),
                state=final_state,
            )
            await graph.aupdate_state(
                config,
                {"conversation_messages": conversation_messages},
                as_node="ask_node",
            )

        trace_logger(
            "agent.stream.end",
            session_id=active_session_id,
            answer=answer,
            step=final_state.get("step"),
            intent=final_state.get("intent"),
            service_type=final_state.get("service_type"),
            order_info=build_effective_order_info(final_state),
            missing_info=final_state.get("missing_info"),
        )

        await save_conversation_log(active_session_id, "human", user_message)
        await save_conversation_log(active_session_id, "ai", str(answer))

        yield {
            "type": "final",
            "session_id": active_session_id,
            "conversation_messages": conversation_messages,
        }
    except SessionAccessError:
        raise
    except Exception as exc:
        trace_logger(
            "agent.stream.error",
            session_id=active_session_id,
            error=repr(exc),
        )
        yield {
            "type": "error",
            "message": f"智能体处理失败：{exc}",
        }


async def run_agent(
    user_message: str,
    session_id: str,
    user: UserContext,
) -> dict[str, object]:
    active_user = require_user(user)
    active_session_id = session_id

    trace_logger(
        "agent.run.start",
        session_id=active_session_id,
        user_id=active_user.user_id,
        user_message=user_message,
    )

    turn_input_state: AgentState = {
        "user_id": active_user.user_id,
        "messages": [HumanMessage(content=user_message)],
        "last_user_message": user_message,
    }

    async with ReadableAsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        config = get_graph_config(active_user, active_session_id)
        existing_snapshot = await graph.aget_state(config)
        if existing_snapshot.values:
            ensure_session_access(existing_snapshot.values, active_user)
        result = await graph.ainvoke(
            turn_input_state,
            config=config,
        )
        answer = get_interrupt_answer(result) or result["messages"][-1].content
        state_messages = result.get("messages", [])
        last_message = state_messages[-1] if state_messages else None
        if not isinstance(last_message, AIMessage) or last_message.content != answer:
            await graph.aupdate_state(
                config,
                {"messages": [AIMessage(content=answer)]},
                as_node="ask_node",
            )
        conversation_messages = build_conversation_turn(
            human_content=user_message,
            ai_content=str(answer),
            state=result,
        )
        await graph.aupdate_state(
            config,
            {"conversation_messages": conversation_messages},
            as_node="ask_node",
        )

    trace_logger(
        "agent.run.end",
        session_id=active_session_id,
        answer=answer,
        step=result.get("step"),
        intent=result.get("intent"),
        service_type=result.get("service_type"),
        order_info=build_effective_order_info(result),
        missing_info=result.get("missing_info"),
    )

    await save_conversation_log(active_session_id, "human", user_message)
    await save_conversation_log(active_session_id, "ai", answer)

    return {
        "session_id": active_session_id,
        "conversation_messages": conversation_messages,
    }
