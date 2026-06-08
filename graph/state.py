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

    # 当前登录用户 ID，用于会话隔离与越权校验。
    user_id: str

    # 当前识别到的用户意图，例如 create_order、confirm_order、cancel_order。
    intent: str | None

    # 服务类型，例如 单次安装、单次测量、单次维修服务、托管维修。
    service_type: str | None

    # 当前订单生命周期：idle、collecting、confirming、submitted、cancelled。
    status: str | None

    # 已从用户输入中提取出的结构化订单信息，例如 room_number、product、fault、
    # expected_start_time、goods_arrival_status、managed_repair_scope。
    order_info: dict[str, Any]

    # 最近一次已提交的订单，供用户追问“刚才那个单号”时使用。
    last_order: dict[str, Any]

    # 当前匹配到的真实商品，来自商品匹配工具。
    matched_product: dict[str, Any]

    # 按用户端 App 结构构造出的真实下单参数，以及真实接口返回结果。
    real_order_payload: dict[str, Any]
    real_order_result: dict[str, Any]
    real_order_missing_fields: list[str]

    # 商品候选列表，低置信度时可给前端或人工选择。
    product_candidates: list[dict[str, Any]]

    # 商品搜索状态：skipped、success、no_match、error。
    product_search_status: str | None

    # 本轮用于商品搜索的查询文本。
    product_search_query: str | None

    # 商品搜索成功后给用户看的反馈文案。
    product_search_feedback: str | None

    # 仍然缺失、需要继续追问用户的订单信息名。
    missing_info: list[str]

    # 当前流程步骤，例如 intent_node、validate_order_node、confirm_node。
    step: str

    # 当前步骤重试次数，适合控制重复追问或兜底策略。
    retry_count: int

    # 用户偏离当前任务的次数，适合做对话纠偏。
    off_topic_count: int

    # 压缩后的历史摘要，适合长对话时减少上下文长度。
    conversation_summary: str

    # 用户最近一轮输入，方便节点快速读取，不必总是解析 messages。
    last_user_message: str
