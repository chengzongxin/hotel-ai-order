import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import AliasChoices, BaseModel, Field

from config.logging import trace_event
from config.settings import settings
from graph.state import AgentState
from memory.postgres_log import save_conversation_log

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
MAX_RETRY_COUNT = 2

REQUIRED_FIELDS_BY_ORDER_TYPE: dict[str, list[str]] = {
    "repair_order": ["room_number", "product", "fault", "area"],
}

ACTIVE_ORDER_STATUSES = {"collecting", "confirming"}


class IntentResult(BaseModel):
    current_intent: str = Field(
        description="用户当前意图",
        validation_alias=AliasChoices("current_intent", "intent"),
    )
    current_order_type: str | None = Field(
        default=None,
        description="订单类型",
        validation_alias=AliasChoices("current_order_type", "order_type"),
    )


class ExtractedFieldsResult(BaseModel):
    room_number: str | None = None
    product: str | None = Field(
        default=None,
        validation_alias=AliasChoices("product", "item", "equipment"),
    )
    fault: str | None = Field(
        default=None,
        validation_alias=AliasChoices("fault", "fault_description", "problem"),
    )
    area: str | None = None
    urgency: str | None = None
    user_confirmed: bool = False


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
    return init_chat_model(
        model=settings.openai_model,
        model_provider="openai",
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        temperature=settings.openai_temperature,
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


def has_active_order(state: AgentState) -> bool:
    return state.get("order_status") in ACTIVE_ORDER_STATUSES


def get_extractor_history(state: AgentState) -> str:
    """提交后的新报修默认只看最新输入，避免已提交订单被重新抽取。"""

    if state.get("last_submitted_order") and not state.get("extracted_fields"):
        return f"human: {get_last_human_message(state.get('messages', []))}"
    return format_messages(state.get("messages", []))


async def intent_node(state: AgentState) -> dict[str, str | None]:
    """识别用户当前维修意图和订单类型。"""

    trace_event(
        "node.intent.input",
        last_user_message=get_last_human_message(state["messages"]),
        message_count=len(state["messages"]),
    )
    llm = get_llm().with_structured_output(IntentResult)
    result = await llm.ainvoke(
        [
            SystemMessage(
                content=render_prompt(
                    "router/maintenance_intent_router.md",
                    conversation_history=format_messages(state["messages"]),
                    last_user_message=get_last_human_message(state["messages"]),
                )
            ),
        ]
    )

    current_order_type = result.current_order_type or (
        "repair_order" if result.current_intent in {"create_repair_order", "confirm_repair_order"} else None
    )
    if result.current_intent in {"smalltalk", "unknown"} and has_active_order(state):
        current_order_type = state.get("current_order_type")

    order_status = state.get("order_status")
    if result.current_intent in {"create_repair_order", "confirm_repair_order"}:
        order_status = "collecting"
    elif result.current_intent in {"smalltalk", "unknown"} and not has_active_order(state):
        order_status = state.get("order_status") or "idle"

    output = {
        "current_intent": result.current_intent,
        "current_order_type": current_order_type,
        "order_status": order_status,
        "current_step": "intent_node",
        "last_user_message": get_last_human_message(state["messages"]),
    }
    trace_event("node.intent.output", **output)
    return output


async def extractor_node(state: AgentState) -> dict[str, object]:
    """从多轮对话中提取维修下单需要的结构化字段。"""

    trace_event(
        "node.extractor.input",
        current_intent=state.get("current_intent"),
        current_order_type=state.get("current_order_type"),
        last_user_message=get_last_human_message(state["messages"]),
    )
    llm = get_llm().with_structured_output(ExtractedFieldsResult)
    result = await llm.ainvoke(
        [
            SystemMessage(
                content=render_prompt(
                    "extractor/maintenance_order_extractor.md",
                    conversation_history=get_extractor_history(state),
                    user_input=get_last_human_message(state["messages"]),
                    order_status=state.get("order_status") or "idle",
                    last_submitted_order=state.get("last_submitted_order", {}),
                )
            ),
        ]
    )

    fields = result.model_dump()
    output = {
        "extracted_fields": fields,
        "current_step": "extractor_node",
    }
    trace_event("node.extractor.output", **output)
    return output


async def missing_field_node(state: AgentState) -> dict[str, object]:
    """根据维修订单类型检查缺失字段，并记录重试次数。"""

    order_type = state.get("current_order_type")
    required_fields = REQUIRED_FIELDS_BY_ORDER_TYPE.get(order_type or "", [])
    extracted_fields = state.get("extracted_fields", {})
    missing_fields = [
        field
        for field in required_fields
        if not extracted_fields.get(field)
    ]

    retry_count = state.get("retry_count", 0)
    if missing_fields:
        retry_count += 1

    output = {
        "missing_fields": missing_fields,
        "retry_count": retry_count,
        "order_status": "collecting" if missing_fields else "confirming",
        "current_step": "missing_field_node",
    }
    trace_event(
        "node.missing_field.output",
        current_order_type=order_type,
        extracted_fields=extracted_fields,
        **output,
    )
    return output


def build_missing_field_fallback_question(missing_fields: list[str]) -> str:
    if not missing_fields:
        return "请确认是否提交维修单？"

    field = missing_fields[0]
    questions = {
        "room_number": "请问您住哪个房间？",
        "product": "是哪样东西坏了？",
        "fault": "具体是什么故障呢？",
        "area": "是在房间哪里呢？",
        "urgency": "这个情况着急吗？",
    }
    return questions.get(field, f"请补充{field}。")


async def build_missing_field_question(state: AgentState) -> str:
    missing_fields = state.get("missing_fields", [])
    if not missing_fields:
        return build_missing_field_fallback_question(missing_fields)

    prompt = render_prompt(
        "ask/maintenance_minimal_question.md",
        extracted_fields=state.get("extracted_fields", {}),
        missing_fields=missing_fields,
        asked_questions=get_asked_questions(state.get("messages", [])),
        last_user_message=get_last_human_message(state.get("messages", [])),
    )
    response = await get_llm().ainvoke([SystemMessage(content=prompt)])
    question = str(response.content).strip()
    return question or build_missing_field_fallback_question(missing_fields)


async def build_topic_boundary_response(state: AgentState) -> str:
    missing_fields = state.get("missing_fields", [])
    active_order = has_active_order(state)
    next_question = build_missing_field_fallback_question(missing_fields) if active_order else ""
    if active_order and not missing_fields and not state.get("extracted_fields"):
        next_question = "请说房号和故障。"
    prompt = render_prompt(
        "safety/topic_boundary_redirect.md",
        last_user_message=get_last_human_message(state.get("messages", [])),
        active_order=active_order,
        order_status=state.get("order_status") or "idle",
        extracted_fields=state.get("extracted_fields", {}) if active_order else {},
        last_submitted_order=state.get("last_submitted_order", {}),
        missing_fields=missing_fields,
        next_question=next_question,
        deviation_count=state.get("deviation_count", 0) + 1,
        current_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    response = await get_llm().ainvoke([SystemMessage(content=prompt)])
    answer = str(response.content).strip()
    return answer or render_prompt(
        "ask/maintenance_unknown_intent.md",
        next_question=next_question or "如果需要继续报修，请告诉我房号和故障。",
    )


async def ask_user_node(state: AgentState) -> dict[str, object]:
    """返回追问，让本轮语音对话自然结束。"""

    missing_fields = state.get("missing_fields", [])
    retry_count = state.get("retry_count", 0)
    deviation_count = state.get("deviation_count", 0)
    is_topic_deviation = state.get("current_intent") in {"unknown", "smalltalk"}

    if is_topic_deviation:
        question = await build_topic_boundary_response(state)
        deviation_count += 1
    elif retry_count > MAX_RETRY_COUNT:
        question = render_prompt(
            "ask/maintenance_retry_missing_fields.md",
            missing_fields=", ".join(missing_fields),
        )
    else:
        question = await build_missing_field_question(state)

    trace_event(
        "node.ask_user.output",
        question=question,
        missing_fields=missing_fields,
        retry_count=retry_count,
        deviation_count=deviation_count,
        current_intent=state.get("current_intent"),
    )

    output = {
        "messages": [AIMessage(content=question)],
        "current_step": "ask_user_node",
        "order_status": state.get("order_status") or "idle",
        "deviation_count": deviation_count,
    }
    if is_topic_deviation and not has_active_order(state):
        output.update(
            {
                "current_order_type": None,
                "extracted_fields": {},
                "missing_fields": [],
                "retry_count": 0,
            }
        )
    return output


async def confirm_node(state: AgentState) -> dict[str, object]:
    """让用户确认维修订单信息。"""

    extracted_fields = state.get("extracted_fields", {})
    order_type = state.get("current_order_type")

    if extracted_fields.get("user_confirmed"):
        trace_event("node.confirm.skip", reason="user_confirmed")
        return {
            "current_step": "confirm_node",
        }

    confirmation_text = render_prompt(
        "confirm/maintenance_order_confirm.md",
        order_type=order_type,
        room_number=extracted_fields.get("room_number"),
        product=extracted_fields.get("product"),
        fault=extracted_fields.get("fault"),
        area=extracted_fields.get("area"),
        urgency=extracted_fields.get("urgency") or "medium",
    )

    trace_event(
        "node.confirm.output",
        confirmation_text=confirmation_text,
        extracted_fields=extracted_fields,
    )

    return {
        "messages": [AIMessage(content=confirmation_text)],
        "current_step": "confirm_node",
        "order_status": "confirming",
    }


async def submit_order_node(state: AgentState) -> dict[str, object]:
    """提交订单。

    真实项目中这里通常会调用维修工单系统 API。
    当前骨架先返回一个稳定的订单号，方便本地直接运行和测试流程。
    """

    order_id = f"ORDER-{uuid4().hex[:8].upper()}"
    submitted_order = {
        "order_id": order_id,
        "order_type": state.get("current_order_type"),
        **state.get("extracted_fields", {}),
    }
    answer = render_prompt(
        "confirm/maintenance_order_submitted.md",
        order_id=order_id,
        order_type=state.get("current_order_type"),
        extracted_fields=state.get("extracted_fields", {}),
    )

    output = {
        "messages": [AIMessage(content=answer)],
        "current_step": "submit_order_node",
        "order_status": "submitted",
        "last_submitted_order": submitted_order,
        "current_order_type": None,
        "extracted_fields": {},
        "missing_fields": [],
        "retry_count": 0,
        "deviation_count": 0,
    }
    trace_event(
        "node.submit_order.output",
        answer=answer,
        extracted_fields=state.get("extracted_fields", {}),
    )
    return output


def route_after_intent(state: AgentState) -> str:
    intent = state.get("current_intent")
    if intent in {"create_repair_order", "confirm_repair_order", "create_order", "confirm_order"}:
        return "extractor_node"
    return "ask_user_node"


def route_after_missing_field_check(state: AgentState) -> str:
    if state.get("missing_fields"):
        return "ask_user_node"
    return "confirm_node"


def route_after_confirm(state: AgentState) -> str:
    extracted_fields = state.get("extracted_fields", {})
    if extracted_fields.get("user_confirmed"):
        return "submit_order_node"
    return END


def build_graph(checkpointer: AsyncSqliteSaver | None = None):
    graph = StateGraph(AgentState)
    graph.add_node("intent_node", intent_node)
    graph.add_node("extractor_node", extractor_node)
    graph.add_node("missing_field_node", missing_field_node)
    graph.add_node("ask_user_node", ask_user_node)
    graph.add_node("confirm_node", confirm_node)
    graph.add_node("submit_order_node", submit_order_node)

    graph.add_edge(START, "intent_node")
    graph.add_conditional_edges(
        "intent_node",
        route_after_intent,
        {
            "extractor_node": "extractor_node",
            "ask_user_node": "ask_user_node",
        },
    )
    graph.add_edge("extractor_node", "missing_field_node")
    graph.add_conditional_edges(
        "missing_field_node",
        route_after_missing_field_check,
        {
            "ask_user_node": "ask_user_node",
            "confirm_node": "confirm_node",
        },
    )
    graph.add_conditional_edges(
        "confirm_node",
        route_after_confirm,
        {
            "submit_order_node": "submit_order_node",
            END: END,
        },
    )
    graph.add_edge("ask_user_node", END)
    graph.add_edge("submit_order_node", END)

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
        "run_name": "repair_order_graph",
        "tags": [
            "hotel-ai-order",
            "repair-order",
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


async def run_agent(
    user_message: str,
    session_id: str | None,
) -> dict[str, str]:
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
                as_node="ask_user_node",
            )

    trace_event(
        "agent.run.end",
        session_id=active_session_id,
        answer=answer,
        current_step=result.get("current_step"),
        current_intent=result.get("current_intent"),
        current_order_type=result.get("current_order_type"),
        extracted_fields=result.get("extracted_fields"),
        missing_fields=result.get("missing_fields"),
    )

    await save_conversation_log(active_session_id, "human", user_message)
    await save_conversation_log(active_session_id, "ai", answer)

    return {
        "session_id": active_session_id,
        "conversation_id": active_session_id,
        "answer": answer,
    }
