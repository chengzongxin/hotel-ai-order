import json
import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from config.logging import trace_event
from config.settings import settings
from graph.agent_runtime import get_assist_agent
from graph.state import AgentState
from memory.postgres_log import save_conversation_log
from tools.product_match import match_product_tool

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
MAX_RETRY_COUNT = 2

REQUIRED_ORDER_INFO = ["room_number", "product", "fault", "area"]

ACTIVE_ORDER_STATUSES = {"collecting", "confirming"}
CANCEL_ORDER_KEYWORDS = ("取消", "不用了", "不提交", "先算了", "撤销", "放弃", "不要了")


class IntentResult(BaseModel):
    intent: str
    service_type: str | None = None
    room_number: str | None = None
    product: str | None = None
    fault: str | None = None
    area: str | None = None
    urgency: str | None = None
    user_confirmed: bool = False
    user_cancelled: bool = False


@lru_cache
def load_prompt(relative_path: str) -> str:
    return (PROMPTS_DIR / relative_path).read_text(encoding="utf-8")


def render_prompt(relative_path: str, **variables: object) -> str:
    prompt = load_prompt(relative_path)
    for key, value in variables.items():
        prompt = prompt.replace(f"{{{{{key}}}}}", to_prompt_text(value))
    return prompt


def to_prompt_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


@lru_cache
def get_llm() -> BaseChatModel:
    return ChatOpenAI(
        model=settings.openai_model,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        temperature=settings.openai_temperature,
        model_kwargs={"extra_body": {"enable_thinking": False}},
    )


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
    return state.get("status") in ACTIVE_ORDER_STATUSES


def is_cancel_request(text: str) -> bool:
    normalized_text = text.strip().lower()
    return any(keyword in normalized_text for keyword in CANCEL_ORDER_KEYWORDS)


def get_extractor_history(state: AgentState) -> str:
    """提交后的新订单默认只看最新输入，避免已提交订单被重新抽取。"""

    if state.get("last_order") and not state.get("order_info"):
        return f"human: {get_last_human_message(state.get('messages', []))}"
    return format_messages(state.get("messages", []))


async def intent_node(state: AgentState) -> dict[str, object]:
    """一次性完成意图识别和订单信息抽取。"""

    emit_status("intent_node", "正在理解您的需求...")
    trace_event(
        "node.intent.input",
        last_user_message=get_last_human_message(state["messages"]),
        message_count=len(state["messages"]),
        status=state.get("status"),
    )
    emit_status("intent_node", "正在识别意图并提取订单信息...")
    llm = get_llm().with_structured_output(IntentResult)
    result = await llm.ainvoke(
        [
            SystemMessage(
                content=render_prompt(
                    "router/order_intent.md",
                    conversation_history=get_extractor_history(state),
                    user_input=get_last_human_message(state["messages"]),
                    status=state.get("status") or "idle",
                    last_order=state.get("last_order", {}),
                )
            ),
        ]
    )

    last_user_message = get_last_human_message(state["messages"])
    user_cancelled = result.user_cancelled or (has_active_order(state) and is_cancel_request(last_user_message))
    intent = "cancel_order" if user_cancelled else result.intent
    emit_status("intent_node", f"已识别意图：{intent}")

    service_type = result.service_type or state.get("service_type")
    if service_type:
        emit_status("intent_node", f"已识别服务类型：{service_type}")

    status = state.get("status")
    if intent in {"create_order", "confirm_order"}:
        status = "collecting"
        emit_status("intent_node", "正在整理订单信息...")
    elif intent in {"smalltalk", "unknown"} and not has_active_order(state):
        status = state.get("status") or "idle"
        emit_status("intent_node", "正在准备辅助回复...")
    elif intent == "cancel_order":
        emit_status("intent_node", "已收到取消请求...")

    detected_fields = {
        "room_number": result.room_number,
        "product": result.product,
        "fault": result.fault,
        "area": result.area,
        "urgency": result.urgency,
        "user_confirmed": result.user_confirmed,
        "user_cancelled": user_cancelled,
    }
    existing_order_info = state.get("order_info", {}) if has_active_order(state) else {}
    if intent in {"smalltalk", "unknown", "cancel_order"}:
        order_info = existing_order_info if has_active_order(state) else {}
        if intent == "cancel_order":
            order_info = {**order_info, "user_confirmed": False, "user_cancelled": True}
    else:
        order_info = {
            **existing_order_info,
            **{
                key: value
                for key, value in detected_fields.items()
                if value is not None
            },
        }
        order_info["user_confirmed"] = result.user_confirmed
        order_info["user_cancelled"] = user_cancelled
    output: dict[str, object] = {
        "intent": intent,
        "service_type": service_type,
        "status": status,
        "order_info": order_info,
        "step": "intent_node",
        "last_user_message": last_user_message,
    }
    trace_event("node.intent.output", **output)
    if intent in {"create_order", "confirm_order"}:
        emit_status("intent_node", "已完成需求理解，准备匹配商品...")
    return output


async def match_product_node(state: AgentState) -> dict[str, object]:
    """根据已抽取的商品和问题，尽早匹配真实可下单商品。"""

    order_info = state.get("order_info", {})
    product = order_info.get("product")
    fault = order_info.get("fault")
    area = order_info.get("area")

    recall_query = " ".join(
        str(value)
        for value in [product, fault, area]
        if value
    )
    if not product and not fault:
        output = {
            "matched_product": {},
            "product_candidates": [],
            "product_match_status": "skipped",
            "product_match_query": recall_query,
            "step": "match_product_node",
        }
        trace_event("node.match_product.skipped", **output)
        return output

    result = await asyncio.to_thread(
        match_product_tool.invoke,
        {
            "query": recall_query,
            "product": product,
            "fault": fault,
            "area": area,
            "service_type_hint": state.get("service_type"),
            "top_k": 3,
            "threshold": None,
        },
    )
    data = result.get("data", {})
    candidates = data.get("candidates") or []
    best_match = data.get("best_match") or {}
    status = "success" if best_match else "no_match"
    if result.get("status") != "success":
        status = "error"

    output = {
        "matched_product": best_match,
        "product_candidates": candidates,
        "product_match_status": status,
        "product_match_query": recall_query,
        "service_type": best_match.get("service_order_type") or state.get("service_type"),
        "step": "match_product_node",
    }
    trace_event(
        "node.match_product.output",
        tool_status=result.get("status"),
        tool_error_code=result.get("error_code"),
        tool_message=result.get("message"),
        **output,
    )
    return output


async def validate_order_node(state: AgentState) -> dict[str, object]:
    """根据维修订单类型检查缺失字段，并记录重试次数。"""

    order_info = state.get("order_info", {})
    missing_info = [
        field
        for field in REQUIRED_ORDER_INFO
        if not order_info.get(field)
    ]

    retry_count = state.get("retry_count", 0)
    if missing_info:
        retry_count += 1

    output = {
        "missing_info": missing_info,
        "retry_count": retry_count,
        "status": "collecting" if missing_info else "confirming",
        "step": "validate_order_node",
    }
    trace_event(
        "node.validate_order.output",
        service_type=state.get("service_type"),
        order_info=order_info,
        **output,
    )
    return output


def build_missing_info_fallback_question(missing_info: list[str]) -> str:
    if not missing_info:
        return "请确认是否提交订单？"

    field = missing_info[0]
    questions = {
        "room_number": "请问您住哪个房间？",
        "product": "是哪样东西坏了？",
        "fault": "具体是什么故障呢？",
        "area": "是在房间哪里呢？",
        "urgency": "这个情况着急吗？",
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
    async for chunk in get_llm().astream(messages):
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

    prompt = render_prompt(
        "ask/ask_missing_info.md",
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
        "safety/off_topic_redirect.md",
        last_user_message=get_last_human_message(state.get("messages", [])),
        active_order=active_order,
        status=state.get("status") or "idle",
        order_info=state.get("order_info", {}) if active_order else {},
        last_order=state.get("last_order", {}),
        missing_info=missing_info,
        next_question=next_question,
        off_topic_count=state.get("off_topic_count", 0) + 1,
        current_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    answer = await stream_llm_text([SystemMessage(content=prompt)], step="ask_node")
    return answer or render_prompt(
        "ask/maintenance_unknown_intent.md",
        next_question=next_question or "如果需要继续报修，请告诉我房号和故障。",
    )


async def ask_node(state: AgentState) -> dict[str, object]:
    """返回追问，让本轮语音对话自然结束。"""

    missing_info = state.get("missing_info", [])
    retry_count = state.get("retry_count", 0)
    off_topic_count = state.get("off_topic_count", 0)
    is_topic_deviation = state.get("intent") in {"unknown", "smalltalk"}

    if is_topic_deviation:
        question = await build_topic_boundary_response(state)
        off_topic_count += 1
    elif retry_count > MAX_RETRY_COUNT:
        question = render_prompt(
            "ask/retry_missing_info.md",
            missing_info=", ".join(missing_info),
        )
        await emit_token_text(question, step="ask_node")
    else:
        question = await build_missing_info_question(state)

    trace_event(
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
        "status": state.get("status") or "idle",
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

    trace_event(
        "node.assist.input",
        message_count=len(state.get("messages", [])),
        intent=state.get("intent"),
        status=state.get("status"),
    )
    answer_parts: list[str] = []
    latest_messages: list[BaseMessage] = []
    async for part in get_assist_agent().astream(
        {"messages": state.get("messages", [])},
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

    trace_event(
        "node.assist.output",
        answer=str(answer),
        message_count=len(latest_messages),
    )
    return {
        "messages": [AIMessage(content=str(answer))],
        "step": "assist_node",
        "status": state.get("status") or "idle",
    }


async def confirm_node(state: AgentState) -> dict[str, object]:
    """让用户确认订单信息。"""

    order_info = state.get("order_info", {})
    service_type = state.get("service_type")
    matched_product = state.get("matched_product", {})

    if order_info.get("user_confirmed"):
        trace_event("node.confirm.skip", reason="user_confirmed")
        return {
            "step": "confirm_node",
        }

    confirmation_text = render_prompt(
        "confirm/order_confirm.md",
        service_type=service_type,
        room_number=order_info.get("room_number"),
        product=order_info.get("product"),
        fault=order_info.get("fault"),
        area=order_info.get("area"),
        urgency=order_info.get("urgency") or "medium",
        product_name=matched_product.get("service_product_name") or "未匹配到标准商品",
        product_code=matched_product.get("service_product_code") or "无",
    )
    await emit_token_text(confirmation_text, step="confirm_node")

    trace_event(
        "node.confirm.output",
        confirmation_text=confirmation_text,
        order_info=order_info,
    )

    return {
        "messages": [AIMessage(content=confirmation_text)],
        "step": "confirm_node",
        "status": "confirming",
    }


async def cancel_node(state: AgentState) -> dict[str, object]:
    """取消当前预下单，避免旧订单继续参与后续对话。"""

    answer = "已取消本次订单。"
    await emit_token_text(answer, step="cancel_node")
    output = {
        "messages": [AIMessage(content=answer)],
        "step": "cancel_node",
        "intent": "cancel_order",
        "service_type": None,
        "status": "cancelled",
        "order_info": {},
        "matched_product": {},
        "product_candidates": [],
        "product_match_status": None,
        "product_match_query": None,
        "missing_info": [],
        "retry_count": 0,
        "off_topic_count": 0,
    }
    trace_event(
        "node.cancel.output",
        answer=answer,
        previous_status=state.get("status"),
        previous_order_info=state.get("order_info", {}),
    )
    return output


async def submit_node(state: AgentState) -> dict[str, object]:
    """提交订单。

    真实项目中这里通常会调用下单系统 API。
    当前骨架先返回一个稳定的订单号，方便本地直接运行和测试流程。
    """

    order_id = f"ORDER-{uuid4().hex[:8].upper()}"
    matched_product = state.get("matched_product", {})
    submitted_order = {
        "order_id": order_id,
        "service_type": state.get("service_type"),
        **state.get("order_info", {}),
        "product_code": matched_product.get("service_product_code"),
        "product_name": matched_product.get("service_product_name"),
        "product_order_type": matched_product.get("service_order_type"),
        "matched_product": matched_product,
    }
    answer = render_prompt(
        "confirm/order_submitted.md",
        order_id=order_id,
        service_type=state.get("service_type"),
        order_info=state.get("order_info", {}),
        matched_product=matched_product,
    )
    await emit_token_text(answer, step="submit_node")

    output = {
        "messages": [AIMessage(content=answer)],
        "step": "submit_node",
        "status": "submitted",
        "last_order": submitted_order,
        "service_type": None,
        "order_info": {},
        "matched_product": {},
        "product_candidates": [],
        "product_match_status": None,
        "product_match_query": None,
        "missing_info": [],
        "retry_count": 0,
        "off_topic_count": 0,
    }
    trace_event(
        "node.submit.output",
        answer=answer,
        order_info=state.get("order_info", {}),
    )
    return output


def route_after_intent(state: AgentState) -> str:
    intent = state.get("intent")
    order_info = state.get("order_info", {})
    if intent == "cancel_order" or order_info.get("user_cancelled"):
        return "cancel_node"
    if intent in {"create_order", "confirm_order"}:
        return "match_product_node"
    if intent in {"smalltalk", "unknown"} and not has_active_order(state):
        return "assist_node"
    return "ask_node"


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
    graph.add_node("match_product_node", match_product_node)
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
            "match_product_node": "match_product_node",
            "assist_node": "assist_node",
            "ask_node": "ask_node",
        },
    )
    graph.add_edge("match_product_node", "validate_order_node")
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


def get_graph_config(session_id: str) -> dict[str, object]:
    return {
        "configurable": {"thread_id": session_id},
        "run_name": "order_graph",
        "tags": [
            "hotel-ai-order",
            "order",
            settings.app_env,
        ],
        "metadata": {
            "session_id": session_id,
            "app_env": settings.app_env,
        },
    }


def checkpoint_path() -> Path:
    db_path = Path(settings.sqlite_memory_path)
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


async def get_checkpoint_state(session_id: str) -> AgentState:
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        snapshot = await graph.aget_state(get_graph_config(session_id))
    return snapshot.values or {}


async def get_checkpoint_messages(session_id: str) -> list[dict[str, str]]:
    state = await get_checkpoint_state(session_id)
    return [message_to_item(message) for message in state.get("messages", [])]


async def clear_checkpoint_session(session_id: str) -> None:
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
        await checkpointer.setup()
        await checkpointer.adelete_thread(session_id)


def build_order_preview(state: dict[str, object]) -> dict[str, object] | None:
    order_info = state.get("order_info") or {}
    matched_product = state.get("matched_product") or {}
    candidates = state.get("product_candidates") or []
    if not order_info and not matched_product and not candidates:
        return None

    return {
        "service_type": state.get("service_type"),
        "status": state.get("status"),
        "order_info": order_info,
        "matched_product": matched_product,
        "product_candidates": candidates,
        "product_match_status": state.get("product_match_status"),
        "product_match_query": state.get("product_match_query"),
        "missing_info": state.get("missing_info") or [],
    }


NODE_STATUS_MESSAGES = {
    "intent_node": "正在理解您的需求并提取订单信息...",
    "match_product_node": "正在匹配可下单的标准商品...",
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
) -> AsyncIterator[dict[str, object]]:
    active_session_id = session_id or str(uuid4())

    trace_event(
        "agent.stream.start",
        session_id=active_session_id,
        user_message=user_message,
    )
    yield {
        "type": "session",
        "session_id": active_session_id,
        "conversation_id": active_session_id,
    }
    yield {
        "type": "status",
        "step": "intent_node",
        "message": NODE_STATUS_MESSAGES["intent_node"],
    }

    initial_state: AgentState = {
        "conversation_id": active_session_id,
        "messages": [HumanMessage(content=user_message)],
        "last_user_message": user_message,
    }

    try:
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
            await checkpointer.setup()
            graph = build_graph(checkpointer)
            config = get_graph_config(active_session_id)

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

        trace_event(
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
            "conversation_id": active_session_id,
            "answer": str(answer),
            "order_preview": build_order_preview(final_state),
        }
    except Exception as exc:
        trace_event(
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
) -> dict[str, object]:
    active_session_id = session_id or str(uuid4())

    trace_event(
        "agent.run.start",
        session_id=active_session_id,
        user_message=user_message,
    )

    initial_state: AgentState = {
        "conversation_id": active_session_id,
        "messages": [HumanMessage(content=user_message)],
        "last_user_message": user_message,
    }

    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        config = get_graph_config(active_session_id)
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

    trace_event(
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
        "conversation_id": active_session_id,
        "answer": answer,
        "order_preview": build_order_preview(result),
    }
