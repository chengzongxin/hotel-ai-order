from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """LangGraph 运行时状态。

    这里使用 TypedDict 是为了让 State 既保持字典的轻量形式，
    又能清楚表达每个字段的含义和类型，方便后续扩展节点。
    """

    # LangGraph 会通过 add_messages 自动追加消息，而不是每次覆盖整个列表。
    messages: Annotated[list[BaseMessage], add_messages]

    # 当前会话 ID，供 Redis Memory 和 PostgreSQL 日志使用。
    conversation_id: str

    # 当前识别到的用户意图，例如 order_food、modify_order、cancel_order。
    current_intent: str | None

    # 当前订单类型，例如 room_service、restaurant、takeaway。
    current_order_type: str | None

    # 当前订单生命周期：idle、collecting、confirming、submitted、cancelled。
    order_status: str | None

    # 已从用户输入中提取出的结构化字段，例如 room_number、items、delivery_time。
    extracted_fields: dict[str, Any]

    # 最近一次已提交的订单，供用户追问“刚才那个单号”时使用。
    last_submitted_order: dict[str, Any]

    # 当前匹配到的真实服务商品，来自服务商品 RAG 召回。
    matched_service_product: dict[str, Any]

    # 服务商品候选列表，低置信度时可给前端或人工选择。
    service_product_candidates: list[dict[str, Any]]

    # 服务商品召回状态：skipped、success、no_match、error。
    service_product_recall_status: str | None

    # 本轮用于服务商品召回的查询文本。
    service_product_recall_query: str | None

    # 仍然缺失、需要继续追问用户的字段名。
    missing_fields: list[str]

    # 当前流程步骤，例如 intent_detection、field_extraction、confirmation。
    current_step: str

    # 当前步骤重试次数，适合控制重复追问或兜底策略。
    retry_count: int

    # 用户偏离当前任务的次数，适合做对话纠偏。
    deviation_count: int

    # 压缩后的历史摘要，适合长对话时减少上下文长度。
    conversation_summary: str

    # 用户最近一轮输入，方便节点快速读取，不必总是解析 messages。
    last_user_message: str
