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

    # 最终用于字段校验和真实提交的服务类型；托管维修范围外会降级为单次维修服务。
    effective_service_type: str | None

    # 托管维修商品是否在当前用户维保卡范围内的校验结果。
    coverage_result: dict[str, Any]

    # 真实提交路由，例如 managed_repair、single_repair、single_install、single_measure。
    order_submit_route: str | None

    # 下单卡片默认值，来自用户登录态、维保卡、地址、商品接口等。
    order_context: dict[str, Any]

    # 下单卡片字段列表，由后端按当前订单类型生成，前端直接渲染。
    order_card_fields: list[dict[str, Any]]

    # 订单主流程阶段，同时决定前端展示哪类主卡片。
    phase: str | None

    # 用户选择“以上都不符合”后，用于触发重新描述和重新检索。
    product_selection_rejected: bool

    # 已从用户输入中提取出的结构化订单信息，例如 room_number、product、fault、
    # expected_start_time、goods_arrival_status、managed_repair_scope。
    order_info: dict[str, Any]

    # 最近一次已提交的订单，供成功卡片和用户追问“刚才那个单号”时使用。
    last_order: dict[str, Any]
    submitted_order: dict[str, Any]

    # 商品检索结果（按相似度排序）。
    products: list[dict[str, Any]]

    # 当前选中的商品编码；未指定时默认取 products[0]。
    selected_product_code: str | None

    # 真实提交动作状态，包括请求参数、接口返回、失败原因和订单号。
    submission: dict[str, Any]

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
