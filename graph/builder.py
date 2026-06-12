import asyncio
import re
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from graph.llm import get_llm, get_llm_run_config
from graph.prompts import PROMPTS_DIR, render_prompt

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.config import get_stream_writer
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
    build_order_card_fields,
    collect_missing_order_info,
    get_required_order_fields,
    normalize_goods_arrival_status,
    normalize_order_card_update,
)
from graph.products import (
    build_product_search_feedback,
    build_product_search_query,
    find_product_by_code,
    get_selected_product,
    resolve_selected_code,
)
from graph.state import AgentState
from graph.submission import empty_submission, get_effective_service_type, submit_order_from_state
from memory.postgres_log import save_conversation_log
from schemas.user import (
    SessionAccessError,
    UserContext,
    build_thread_id,
    require_user,
    user_from_runtime_config,
)
from tools.hosting_coverage import check_hosting_product_coverage
from tools.order_submit import load_managed_repair_order_context
from tools.product_search import search_product_tool

MAX_RETRY_COUNT = 2

CANCEL_ORDER_KEYWORDS = ("取消", "不用了", "不提交", "先算了", "撤销", "放弃", "不要了")
PUBLIC_AREA_KEYWORDS = (
    "公区",
    "公共区域",
    "大厅",
    "大堂",
    "接待区",
    "公区卫生间",
    "公共厕所",
    "布草间",
    "办公室",
    "洗衣房",
    "员工区",
    "走廊",
    "过道",
    "电梯",
    "电梯厅",
    "前台",
    "餐厅",
    "会议室",
    "楼梯间",
    "楼顶",
    "健身房",
    "停车场",
    "仓库",
    "设备间",
)
GUEST_ROOM_KEYWORDS = (
    "客房",
    "房间",
    "房里",
    "屋内",
    "住客区",
    "维修房",
    "客房楼层",
    "卫生间",
    "淋浴间",
)
VALID_MANAGED_REPAIR_SCOPES = {"客房", "公区"}
PRODUCT_NONE_SELECTIONS = {"0", "以上都不符合", "都不符合", "不符合", "没有合适", "没有匹配"}
PHASE_IDLE = "idle"
PHASE_PRODUCT_SELECTION = "product_selection"
PHASE_PRE_ORDER = "pre_order"
PHASE_COLLECTING = "collecting"
PHASE_SUBMITTED = "submitted"
PHASE_CANCELLED = "cancelled"
ACTIVE_ORDER_PHASES = {PHASE_COLLECTING, PHASE_PRODUCT_SELECTION, PHASE_PRE_ORDER}

def resolve_order_submit_route(service_type: str | None) -> str | None:
    route_map = {
        "托管维修": "managed_repair",
        "单次维修服务": "single_repair",
        "单次安装": "single_install",
        "单次测量": "single_measure",
    }
    return route_map.get(service_type or "")


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


def get_optional_stream_writer():
    try:
        return get_stream_writer()
    except RuntimeError:
        return None


def emit_status(step: str, message: str) -> None:
    writer = get_optional_stream_writer()
    if writer:
        writer({"type": "status", "step": step, "message": message})


def has_active_order(state: AgentState) -> bool:
    return state.get("phase") in ACTIVE_ORDER_PHASES


def is_cancel_request(text: str) -> bool:
    normalized_text = text.strip().lower()
    return any(keyword in normalized_text for keyword in CANCEL_ORDER_KEYWORDS)


def parse_product_selection(text: str | None) -> int | None:
    """解析用户对 Top3 商品的选择；0 表示“以上都不符合”。"""

    if not text:
        return None
    normalized = text.strip().lower()
    if normalized in PRODUCT_NONE_SELECTIONS or "以上都不符合" in normalized:
        return 0

    mapping = {
        "第一": 1,
        "第一个": 1,
        "1": 1,
        "选1": 1,
        "选择1": 1,
        "一": 1,
        "第二": 2,
        "第二个": 2,
        "2": 2,
        "选2": 2,
        "选择2": 2,
        "二": 2,
        "第三": 3,
        "第三个": 3,
        "3": 3,
        "选3": 3,
        "选择3": 3,
        "三": 3,
    }
    if normalized in mapping:
        return mapping[normalized]
    match = re.search(r"(?:选|选择|第)?\s*([123])\s*(?:个|项)?", normalized)
    if match:
        return int(match.group(1))
    return None


def build_product_recommendation_text(products: list[dict[str, object]]) -> str:
    if products:
        return "好的，根据您的描述，为您推荐以下服务商品，请在下方卡片中选择您要下单的商品。"
    return "请先选择要下单的服务商品。"


def build_selected_product_text(selected_product: dict[str, object]) -> str:
    name = selected_product.get("service_product_name") or "该商品"
    repair_level = (
        selected_product.get("repair_category")
        or selected_product.get("product_type")
        or selected_product.get("service_order_type")
        or "待确认"
    )
    return f"好的，已为您选择【{name}（{repair_level}）】，正在生成预下单卡片。"


def is_public_area_text(text: str | None) -> bool:
    if not text:
        return False
    return any(keyword in text for keyword in PUBLIC_AREA_KEYWORDS)


def is_guest_room_text(text: str | None) -> bool:
    if not text:
        return False
    return any(keyword in text for keyword in GUEST_ROOM_KEYWORDS)


def extract_room_number(text: str | None) -> str | None:
    if not text:
        return None
    patterns = (
        r"([A-Za-z]栋\s*\d{2,5})",
        r"(\d{2,5})\s*(?:房间|房|号)",
        r"房间\s*(\d{2,5})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).replace(" ", "")
    return None


def format_service_type(service_type: str | None, order_info: dict[str, object]) -> str | None:
    from graph.products import format_service_type_display

    return format_service_type_display(service_type, order_info)  # type: ignore[arg-type]


def format_urgency(value: object) -> str:
    labels = {
        "low": "低优先级",
        "medium": "普通",
        "high": "较急",
        "urgent": "紧急",
    }
    return labels.get(str(value), str(value or "普通"))


def get_product_search_feedback(state: AgentState) -> str | None:
    selected_product = get_selected_product(
        state.get("products") or [],
        state.get("selected_product_code"),
        default_to_first=False,
    )
    if not selected_product:
        return None
    return build_product_search_feedback(
        order_info=state.get("order_info") or {},
        selected_product=selected_product,
        service_type=get_effective_service_type(state) or selected_product.get("service_order_type"),
    )


def normalize_order_defaults(
    service_type: str | None,
    order_info: dict[str, object],
    last_user_message: str = "",
) -> dict[str, object]:
    normalized = dict(order_info)

    if service_type in {"托管维修", "单次维修服务"} and not normalized.get("urgency"):
        normalized["urgency"] = DEFAULT_URGENCY

    if normalized.get("goods_arrival_status"):
        normalized_status = normalize_goods_arrival_status(str(normalized.get("goods_arrival_status")))
        if normalized_status:
            normalized["goods_arrival_status"] = normalized_status
        else:
            normalized.pop("goods_arrival_status", None)

    if service_type == "托管维修":
        if not normalized.get("room_number"):
            inferred_room_number = extract_room_number(last_user_message)
            if inferred_room_number:
                normalized["room_number"] = inferred_room_number

        room_number = str(normalized.get("room_number") or "").strip()
        area = str(normalized.get("area") or "")
        scope = normalized.get("managed_repair_scope")
        if room_number and room_number != "/":
            normalized["managed_repair_scope"] = "客房"
            normalized["area"] = "客房"
        elif scope == "客房" or is_guest_room_text(area) or is_guest_room_text(last_user_message):
            normalized["managed_repair_scope"] = "客房"
            normalized["area"] = "客房"
        elif scope == "公区" or is_public_area_text(area) or is_public_area_text(last_user_message):
            normalized["managed_repair_scope"] = "公区"
            normalized["area"] = "公区"
            normalized["room_number"] = "/"
        elif scope not in VALID_MANAGED_REPAIR_SCOPES:
            normalized.pop("managed_repair_scope", None)

    inferred_time = infer_expected_start_time_from_message(last_user_message)
    existing_time = normalize_expected_start_time_text(
        str(normalized.get("expected_start_time") or "") or None
    )
    merged_time = merge_expected_start_time(existing_time, inferred_time)
    if merged_time:
        normalized["expected_start_time"] = merged_time

    return normalized


async def load_order_context(user: UserContext) -> dict[str, object]:
    try:
        return await load_managed_repair_order_context(user)
    except Exception as exc:
        return {
            "context_error": f"{type(exc).__name__}: {exc}",
            "selected_address": {},
            "contacts": None,
            "phone": None,
        }


def get_extractor_history(state: AgentState) -> str:
    """提交后的新订单默认只看最新输入，避免已提交订单被重新抽取。"""

    if state.get("last_order") and not state.get("order_info"):
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
    emit_status("intent_node", f"已识别意图：{intent}")

    phase = state.get("phase")
    if intent in {"create_order", "confirm_order"}:
        phase = PHASE_COLLECTING
        emit_status("intent_node", "正在整理订单信息...")
    elif intent in {"smalltalk", "unknown"} and not has_active_order(state):
        phase = state.get("phase") or PHASE_IDLE
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
    existing_order_info = state.get("order_info", {}) if has_active_order(state) else {}
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
            cleaned_existing.pop("managed_repair_scope", None)
        # 新输入明确了房号（客房），清除旧单遗留的公区信息
        elif detected_fields.get("room_number") or detected_fields.get("managed_repair_scope") == "客房":
            cleaned_existing.pop("managed_repair_scope", None)
            cleaned_existing.pop("area", None)

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
    output: dict[str, object] = {
        "intent": intent,
        "phase": phase,
        "order_info": order_info,
        "step": "intent_node",
        "last_user_message": last_user_message,
    }
    if intent in {"create_order", "confirm_order"} and state.get("phase") == PHASE_SUBMITTED:
        output.update(
            {
                "products": [],
                "selected_product_code": None,
                "submission": empty_submission(),
                "effective_service_type": None,
                "coverage_result": {},
                "order_submit_route": None,
                "order_context": {},
                "order_card_fields": [],
                "submitted_order": {},
                "product_selection_rejected": False,
            }
        )
    trace_logger("node.intent.output", **output)
    if intent in {"create_order", "confirm_order"}:
        emit_status("intent_node", "已完成需求理解，准备匹配商品...")
    return output


async def search_product_node(state: AgentState) -> dict[str, object]:
    """根据已抽取的商品和问题，尽早匹配真实可下单商品。"""

    existing_products = state.get("products") or []
    last_msg = state.get("last_user_message", "")
    selection = parse_product_selection(last_msg)
    if existing_products and selection == 0:
        output = {
            "products": [],
            "selected_product_code": None,
            "service_type": None,
            "effective_service_type": None,
            "coverage_result": {},
            "order_submit_route": None,
            "order_card_fields": [],
            "product_selection_rejected": True,
            "missing_info": [],
            "phase": PHASE_COLLECTING,
            "step": "search_product_node",
        }
        trace_logger("node.search_product.rejected", **output)
        return output

    if existing_products and selection in {1, 2, 3}:
        selected_product = existing_products[int(selection) - 1] if len(existing_products) >= int(selection) else {}
        if selected_product:
            service_type = selected_product.get("service_order_type") or state.get("service_type")
            normalized_order_info = normalize_order_defaults(
                service_type=service_type,
                order_info=state.get("order_info", {}),
                last_user_message=last_msg,
            )
            output = {
                "selected_product_code": selected_product.get("service_product_code"),
                "service_type": service_type,
                "order_info": normalized_order_info,
                "product_selection_rejected": False,
                "phase": PHASE_PRE_ORDER,
                "step": "search_product_node",
            }
            trace_logger("node.search_product.selected_by_text", selection=selection, **output)
            return output

    if state.get("intent") == "confirm_order" and existing_products:
        trace_logger(
            "node.search_product.skip",
            reason="confirm_with_existing_products",
            selected_product_code=state.get("selected_product_code"),
            product_count=len(existing_products),
        )
        return {"step": "search_product_node"}

    order_info = state.get("order_info", {})
    fault = order_info.get("fault")

    # 无故障时从用户原始消息中补充服务意图关键词（如"安装"），辅助找到正确商品类型
    search_query = build_product_search_query(order_info, last_msg)
    if not search_query:
        output = {
            "products": [],
            "selected_product_code": None,
            "step": "search_product_node",
        }
        trace_logger("node.search_product.skipped", **output)
        return output

    result = await asyncio.to_thread(
        search_product_tool.invoke,
        {
            "query": search_query,
            "top_k": 3,
            "threshold": None,
            "has_fault": bool(fault),
        },
    )
    data = result.get("data", {})
    products = data.get("products") or []
    top_product = get_selected_product(products, None, default_to_first=True)
    search_status = "success" if products else "no_match"
    if result.get("status") != "success":
        search_status = "error"

    # service_type 完全由 Top1 商品决定，匹配失败则置 null
    service_type = top_product.get("service_order_type") or None
    if service_type:
        emit_status("search_product_node", f"已确定服务类型：{service_type}")
    normalized_order_info = normalize_order_defaults(
        service_type=service_type,
        order_info=order_info,
        last_user_message=state.get("last_user_message", ""),
    )

    output = {
        "products": products,
        "selected_product_code": resolve_selected_code(
            products,
            state.get("selected_product_code"),
            default_to_first=False,
        ),
        "service_type": service_type,
        "order_info": normalized_order_info,
        "product_selection_rejected": False,
        "order_card_fields": [],
        "phase": PHASE_PRODUCT_SELECTION if products else PHASE_COLLECTING,
        "step": "search_product_node",
    }
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

    selected_product = get_selected_product(
        state.get("products") or [],
        state.get("selected_product_code"),
        default_to_first=False,
    )
    if (state.get("products") or []) and not selected_product:
        return {
            "effective_service_type": None,
            "coverage_result": {},
            "order_submit_route": None,
            "step": "coverage_node",
        }
    service_type = state.get("service_type") or selected_product.get("service_order_type")
    if not service_type:
        return {
            "effective_service_type": None,
            "coverage_result": {},
            "order_submit_route": None,
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
            "order_submit_route": resolve_order_submit_route(service_type),
            "step": "coverage_node",
        }

    emit_status("coverage_node", "正在校验维保卡范围...")
    coverage_result = await check_hosting_product_coverage(
        order_info=state.get("order_info") or {},
        matched_product=selected_product,
        user=user_from_runtime_config(),
    )
    coverage_data = coverage_result.get("data") or {}
    effective_service_type = coverage_data.get("effective_service_type") or service_type
    order_info = normalize_order_defaults(
        service_type=effective_service_type,
        order_info=state.get("order_info", {}),
        last_user_message=state.get("last_user_message", ""),
    )

    if effective_service_type != service_type:
        emit_status("coverage_node", "该商品不在维保范围内，将按单次维修继续下单。")
    else:
        emit_status("coverage_node", "该商品在维保范围内，可继续托管维修下单。")

    output = {
        "effective_service_type": effective_service_type,
        "coverage_result": coverage_data,
        "order_submit_route": resolve_order_submit_route(effective_service_type),
        "order_info": order_info,
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

    selected_product = get_selected_product(
        state.get("products") or [],
        state.get("selected_product_code"),
        default_to_first=False,
    )
    if not selected_product:
        return {
            "order_context": {},
            "order_card_fields": [],
            "step": "prepare_order_context_node",
        }

    service_type = get_effective_service_type(state)
    order_context = await load_order_context(user_from_runtime_config())

    order_card_fields = build_order_card_fields(
        service_type=service_type,
        order_info=state.get("order_info", {}),
        order_context=order_context,
    )
    output = {
        "order_context": order_context,
        "order_card_fields": order_card_fields,
        "phase": PHASE_PRE_ORDER,
        "step": "prepare_order_context_node",
    }
    trace_logger("node.prepare_order_context.output", service_type=service_type, **output)
    return output


async def validate_order_node(state: AgentState) -> dict[str, object]:
    """按订单类型检查缺失字段，并记录重试次数。"""

    products = state.get("products") or []
    selected_product = get_selected_product(products, state.get("selected_product_code"), default_to_first=False)
    if products and not selected_product:
        return {
            "missing_info": ["selected_product"],
            "retry_count": state.get("retry_count", 0),
            "phase": PHASE_PRODUCT_SELECTION,
            "step": "validate_order_node",
        }

    service_type = get_effective_service_type(state)
    order_info = normalize_order_defaults(
        service_type=service_type,
        order_info=state.get("order_info", {}),
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

    retry_count = state.get("retry_count", 0)
    if missing_info:
        retry_count += 1

    output = {
        "missing_info": missing_info,
        "order_info": order_info,
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
        "room_number": "请问您住哪个房间？",
        "product": "是哪样东西坏了？",
        "fault": "具体是什么故障呢？",
        "area": "请问是客房还是公区？",
        "expected_start_time": "还需补充：期待开工时间。请问具体什么时间？比如明天上午或3月20日",
        "goods_arrival_status": "请问货物是否到场？",
        "contacts": "请问联系人姓名是什么？",
        "phone": "请问联系电话是多少？",
    }
    return questions.get(field, f"请补充{field}。")


def message_chunk_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return ""


async def emit_token_text(text: str, step: str, chunk_size: int = 4, delay_seconds: float = 0.015) -> None:
    writer = get_optional_stream_writer()
    if not writer:
        return

    for index in range(0, len(text), chunk_size):
        token = text[index : index + chunk_size]
        if token:
            writer({"type": "token", "step": step, "content": token})
            await asyncio.sleep(delay_seconds)


async def stream_llm_text(messages: list[BaseMessage], step: str) -> str:
    parts: list[str] = []
    async for chunk in get_llm().astream(messages, config=get_llm_run_config()):
        token = message_chunk_to_text(getattr(chunk, "content", ""))
        if not token:
            continue
        parts.append(token)
        await emit_token_text(token, step=step, chunk_size=4, delay_seconds=0)
    return "".join(parts).strip()


async def build_missing_info_question(state: AgentState) -> str:
    missing_info = state.get("missing_info", [])
    if not missing_info:
        return build_missing_info_fallback_question(missing_info)
    if missing_info[0] == "expected_start_time":
        return build_missing_info_fallback_question(missing_info)
    if missing_info[0] == "goods_arrival_status":
        return build_missing_info_fallback_question(missing_info)

    prompt = render_prompt(
        "ask/missing_info.md",
        order_info=state.get("order_info", {}),
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
    if active_order and not missing_info and not state.get("order_info"):
        next_question = "请说房号和故障。"
    prompt = render_prompt(
        "ask/off_topic.md",
        last_user_message=get_last_human_message(state.get("messages", [])),
        active_order=active_order,
        status=state.get("phase") or PHASE_IDLE,
        order_info=state.get("order_info", {}) if active_order else {},
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
    selected_product = get_selected_product(products, state.get("selected_product_code"), default_to_first=False)
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
                "order_info": {},
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

    order_info = state.get("order_info", {})
    service_type = get_effective_service_type(state)
    selected_product = get_selected_product(
        state.get("products") or [],
        state.get("selected_product_code"),
        default_to_first=False,
    )

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
        "messages": [AIMessage(content=answer)],
        "step": "cancel_node",
        "intent": "cancel_order",
        "service_type": None,
        "effective_service_type": None,
        "coverage_result": {},
        "order_submit_route": None,
        "order_context": {},
        "order_card_fields": [],
        "phase": PHASE_CANCELLED,
        "order_info": {},
        "products": [],
        "selected_product_code": None,
        "missing_info": [],
        "submission": empty_submission(),
        "retry_count": 0,
        "off_topic_count": 0,
    }
    trace_logger(
        "node.cancel.output",
        answer=answer,
        previous_phase=state.get("phase"),
        previous_order_info=state.get("order_info", {}),
    )
    return output


def ensure_session_access(state: AgentState, user: UserContext) -> None:
    stored_user_id = state.get("user_id")
    if stored_user_id and stored_user_id != user.user_id:
        raise SessionAccessError("无权访问该会话")


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
    order_info = state.get("order_info", {})
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
    products = state.get("products") or []
    selected_product = get_selected_product(products, state.get("selected_product_code"), default_to_first=False)
    if products and not selected_product:
        return "ask_node"
    return "coverage_node"


def route_after_validation(state: AgentState) -> str:
    if state.get("missing_info"):
        return "ask_node"
    return "confirm_node"


def route_after_confirm(state: AgentState) -> str:
    order_info = state.get("order_info", {})
    if order_info.get("user_confirmed"):
        return "submit_node"
    return END


def build_graph(checkpointer: AsyncSqliteSaver | None = None):
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


def get_graph_config(user: UserContext, session_id: str) -> dict[str, object]:
    thread_id = build_thread_id(user.user_id, session_id)
    return get_llm_run_config(
        {
            "configurable": {
                "thread_id": thread_id,
                "user_context": user.to_config_dict(),
            },
            "run_name": "order_graph",
            "tags": [
                "hotel-ai-order",
                "order",
                settings.app_env,
            ],
            "metadata": {
                "session_id": session_id,
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
                "app_env": settings.app_env,
            },
        }
    )


def checkpoint_path() -> Path:
    db_path = Path(settings.sqlite_memory_path)
    if not db_path.is_absolute():
        db_path = PROMPTS_DIR.parent / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def message_to_item(message: BaseMessage) -> dict[str, str]:
    role_map = {
        "human": "human",
        "ai": "ai",
        "system": "system",
    }
    return {
        "role": role_map.get(message.type, message.type),
        "content": str(message.content),
    }


async def get_checkpoint_state(
    session_id: str,
    user: UserContext,
) -> AgentState:
    active_user = require_user(user)
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        snapshot = await graph.aget_state(get_graph_config(active_user, session_id))
        state = snapshot.values or {}
        if state:
            ensure_session_access(state, active_user)
        return state


async def get_checkpoint_messages(
    session_id: str,
    user: UserContext,
) -> list[dict[str, str]]:
    state = await get_checkpoint_state(session_id, user=user)
    return [message_to_item(message) for message in state.get("messages", [])]


async def clear_checkpoint_session(
    session_id: str,
    user: UserContext,
) -> None:
    active_user = require_user(user)
    thread_id = build_thread_id(active_user.user_id, session_id)
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
        await checkpointer.setup()
        await checkpointer.adelete_thread(thread_id)


def build_order_preview(state: dict[str, object]) -> dict[str, object] | None:
    from schemas.order_preview import build_order_preview_model

    order_info = state.get("order_info") or {}
    products = state.get("products") or []
    service_type = state.get("service_type")
    if not service_type and products:
        selected = get_selected_product(products, state.get("selected_product_code"), default_to_first=False)
        service_type = selected.get("service_order_type") or None

    enriched_state = dict(state)
    enriched_state["service_type"] = service_type
    enriched_state["service_type_display"] = format_service_type(service_type, order_info)
    effective_service_type = state.get("effective_service_type")
    if effective_service_type:
        enriched_state["effective_service_type_display"] = format_service_type(
            str(effective_service_type),
            order_info,
        )
    preview = build_order_preview_model(enriched_state)
    if preview is None:
        return None
    return preview.model_dump(mode="json")


async def select_product_in_session(
    session_id: str,
    product_code: str,
    user: UserContext,
) -> dict[str, object]:
    """在前端点选商品后，更新会话中的 selected_product_code 与 service_type。"""
    active_user = require_user(user)
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        config = get_graph_config(active_user, session_id)
        snapshot = await graph.aget_state(config)
        state = snapshot.values or {}
        if not state:
            raise SessionAccessError("会话不存在或尚未开始对话")
        ensure_session_access(state, active_user)

        products = state.get("products") or []
        selected = find_product_by_code(products, product_code)
        if not selected:
            raise ValueError(f"商品 {product_code} 不在当前检索结果中")

        service_type = selected.get("service_order_type") or state.get("service_type")
        order_info = normalize_order_defaults(
            service_type=service_type,
            order_info=state.get("order_info", {}),
            last_user_message=state.get("last_user_message", ""),
        )
        effective_service_type = service_type
        coverage_result: dict[str, object] = {}
        if service_type == "托管维修":
            result = await check_hosting_product_coverage(
                order_info=order_info,
                matched_product=selected,
                user=active_user,
            )
            coverage_result = result.get("data") or {}
            effective_service_type = str(coverage_result.get("effective_service_type") or service_type)
            order_info = normalize_order_defaults(
                service_type=effective_service_type,
                order_info=order_info,
                last_user_message=state.get("last_user_message", ""),
            )
        else:
            coverage_result = {
                "checked": False,
                "covered": None,
                "reason": "非托管维修商品，无需校验维保卡范围",
                "effective_service_type": service_type,
            }
        order_context = await load_order_context(active_user)
        order_card_fields = build_order_card_fields(
            service_type=effective_service_type,
            order_info=order_info,
            order_context=order_context,
        )
        missing_info = collect_missing_order_info(effective_service_type, order_info, order_card_fields)

        update = {
            "selected_product_code": product_code.strip(),
            "service_type": service_type,
            "effective_service_type": effective_service_type,
            "coverage_result": coverage_result,
            "order_submit_route": resolve_order_submit_route(effective_service_type),
            "order_info": order_info,
            "order_context": order_context,
            "order_card_fields": order_card_fields,
            "missing_info": missing_info,
            "phase": PHASE_PRE_ORDER,
            "submission": empty_submission(),
            "product_selection_rejected": False,
        }
        await graph.aupdate_state(config, update, as_node="search_product_node")

        merged_state = dict(state)
        merged_state.update(update)
        order_preview = build_order_preview(merged_state)
        if order_preview is None:
            raise ValueError("更新商品后无法生成订单预览")

        product_name = selected.get("service_product_name") or product_code
        repair_level = selected.get("repair_category") or selected.get("product_type") or selected.get("service_order_type") or "待确认"
        message = f"好的，已为您选择【{product_name}（{repair_level}）】，正在生成预下单卡片。"
        if missing_info:
            message = f"{message}\n{build_missing_info_fallback_question(missing_info)}"

        return {
            "session_id": session_id,
            "order_preview": order_preview,
            "message": message,
        }


async def update_order_info_in_session(
    session_id: str,
    updates: dict[str, object],
    user: UserContext,
) -> dict[str, object]:
    """前端编辑预下单卡片后，同步更新当前会话状态。"""

    active_user = require_user(user)
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        config = get_graph_config(active_user, session_id)
        snapshot = await graph.aget_state(config)
        state = snapshot.values or {}
        if not state:
            raise SessionAccessError("会话不存在或尚未开始对话")
        ensure_session_access(state, active_user)

        selected_product = get_selected_product(
            state.get("products") or [],
            state.get("selected_product_code"),
            default_to_first=False,
        )
        if not selected_product:
            raise ValueError("请先选择商品，再修改预下单信息")

        service_type = get_effective_service_type(state)
        order_info = normalize_order_card_update(
            order_info=state.get("order_info", {}),
            updates=updates,
            service_type=service_type,
        )
        order_info = normalize_order_defaults(
            service_type=service_type,
            order_info=order_info,
            last_user_message=state.get("last_user_message", ""),
        )
        order_context = state.get("order_context") or {}
        if not order_context:
            order_context = await load_order_context(active_user)

        order_card_fields = build_order_card_fields(
            service_type=service_type,
            order_info=order_info,
            order_context=order_context,
        )
        missing_info = collect_missing_order_info(service_type, order_info, order_card_fields)

        update = {
            "order_info": order_info,
            "order_context": order_context,
            "order_card_fields": order_card_fields,
            "missing_info": missing_info,
            "phase": PHASE_PRE_ORDER,
            "submission": empty_submission(),
        }
        await graph.aupdate_state(config, update, as_node="prepare_order_context_node")

        merged_state = dict(state)
        merged_state.update(update)
        order_preview = build_order_preview(merged_state)
        if order_preview is None:
            raise ValueError("更新下单信息后无法生成订单预览")

        return {
            "session_id": session_id,
            "order_preview": order_preview,
            "message": "已更新预下单信息。",
        }


async def confirm_order_in_session(
    session_id: str,
    user: UserContext,
) -> dict[str, object]:
    """前端点击确认按钮时直接提交当前预下单，避免再次依赖 LLM 判断“确认”。"""

    active_user = require_user(user)
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        config = get_graph_config(active_user, session_id)
        snapshot = await graph.aget_state(config)
        state = snapshot.values or {}
        if not state:
            raise SessionAccessError("会话不存在或尚未开始对话")
        ensure_session_access(state, active_user)

        selected_product = get_selected_product(
            state.get("products") or [],
            state.get("selected_product_code"),
            default_to_first=False,
        )
        if not selected_product:
            raise ValueError("请先选择商品，再确认下单")

        service_type = get_effective_service_type(state)
        order_info = normalize_order_defaults(
            service_type=service_type,
            order_info={
                **(state.get("order_info") or {}),
                "user_confirmed": True,
                "user_cancelled": False,
            },
            last_user_message=state.get("last_user_message", ""),
        )
        order_card_fields = state.get("order_card_fields") or []
        missing_info = collect_missing_order_info(service_type, order_info, order_card_fields)
        if missing_info:
            update = {
                "order_info": order_info,
                "missing_info": missing_info,
                "phase": PHASE_PRE_ORDER,
                "submission": empty_submission(),
            }
            await graph.aupdate_state(config, update, as_node="validate_order_node")
            merged_state = dict(state)
            merged_state.update(update)
            return {
                "session_id": session_id,
                "answer": build_missing_info_fallback_question(missing_info),
                "order_preview": build_order_preview(merged_state),
            }

        confirmed_state = dict(state)
        confirmed_state["order_info"] = order_info
        confirmed_state["missing_info"] = []
        submit_update = await submit_order_from_state(confirmed_state, active_user, emit=False)
        await graph.aupdate_state(config, submit_update, as_node="submit_node")

        merged_state = dict(confirmed_state)
        merged_state.update(submit_update)
        answer_messages = submit_update.get("messages") or []
        answer = str(answer_messages[-1].content) if answer_messages else "已处理确认下单请求。"
        await save_conversation_log(session_id, "human", "确认")
        await save_conversation_log(session_id, "ai", answer)
        return {
            "session_id": session_id,
            "answer": answer,
            "order_preview": build_order_preview(merged_state),
        }


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
    session_id: str | None,
    user: UserContext,
) -> AsyncIterator[dict[str, object]]:
    active_user = require_user(user)
    active_session_id = session_id or str(uuid4())

    trace_logger(
        "agent.stream.start",
        session_id=active_session_id,
        user_id=active_user.user_id,
        user_message=user_message,
    )
    yield {
        "type": "session",
        "session_id": active_session_id,
    }
    yield {
        "type": "status",
        "step": "intent_node",
        "message": NODE_STATUS_MESSAGES["intent_node"],
    }

    initial_state: AgentState = {
        "user_id": active_user.user_id,
        "messages": [HumanMessage(content=user_message)],
        "last_user_message": user_message,
    }

    try:
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
            await checkpointer.setup()
            graph = build_graph(checkpointer)
            config = get_graph_config(active_user, active_session_id)
            existing_snapshot = await graph.aget_state(config)
            if existing_snapshot.values:
                ensure_session_access(existing_snapshot.values, active_user)

            latest_state: dict[str, object] = dict(initial_state)
            emitted_token = False
            async for part in graph.astream(
                initial_state,
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

                        order_preview = build_order_preview(latest_state)
                        if order_preview:
                            yield {
                                "type": "preview",
                                "step": node_name,
                                "order_preview": order_preview,
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
                    if isinstance(data, dict) and data.get("type") in {"status", "token", "preview"}:
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

        trace_logger(
            "agent.stream.end",
            session_id=active_session_id,
            answer=answer,
            step=final_state.get("step"),
            intent=final_state.get("intent"),
            service_type=final_state.get("service_type"),
            order_info=final_state.get("order_info"),
            missing_info=final_state.get("missing_info"),
        )

        await save_conversation_log(active_session_id, "human", user_message)
        await save_conversation_log(active_session_id, "ai", str(answer))

        yield {
            "type": "final",
            "session_id": active_session_id,
            "answer": str(answer),
            "order_preview": build_order_preview(final_state),
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
    session_id: str | None,
    user: UserContext,
) -> dict[str, object]:
    active_user = require_user(user)
    active_session_id = session_id or str(uuid4())

    trace_logger(
        "agent.run.start",
        session_id=active_session_id,
        user_id=active_user.user_id,
        user_message=user_message,
    )

    initial_state: AgentState = {
        "user_id": active_user.user_id,
        "messages": [HumanMessage(content=user_message)],
        "last_user_message": user_message,
    }

    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        config = get_graph_config(active_user, active_session_id)
        existing_snapshot = await graph.aget_state(config)
        if existing_snapshot.values:
            ensure_session_access(existing_snapshot.values, active_user)
        result = await graph.ainvoke(
            initial_state,
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

    trace_logger(
        "agent.run.end",
        session_id=active_session_id,
        answer=answer,
        step=result.get("step"),
        intent=result.get("intent"),
        service_type=result.get("service_type"),
        order_info=result.get("order_info"),
        missing_info=result.get("missing_info"),
    )

    await save_conversation_log(active_session_id, "human", user_message)
    await save_conversation_log(active_session_id, "ai", answer)

    return {
        "session_id": active_session_id,
        "answer": answer,
        "order_preview": build_order_preview(result),
    }
