from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


def upsert_conversation_messages(
    left: list[dict[str, Any]] | None,
    right: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Append new client messages and replace existing messages with the same ID."""

    merged = [dict(item) for item in (left or [])]
    positions = {
        str(item.get("id")): index
        for index, item in enumerate(merged)
        if item.get("id")
    }
    for incoming in right or []:
        item = dict(incoming)
        message_id = str(item.get("id") or "")
        if message_id and message_id in positions:
            merged[positions[message_id]] = item
            continue
        if message_id:
            positions[message_id] = len(merged)
        merged.append(item)
    return merged


OrderPhase = Literal["idle", "collecting", "product_selection", "pre_order", "submitted", "cancelled"]
SubmissionStatus = Literal["not_attempted", "submitting", "succeeded", "failed", "disabled"]


class OrderItemState(TypedDict, total=False):
    id: str
    product_code: str
    product_name: str
    service_type: str
    quantity: int
    fault: str | None
    unit: str | None
    price: str | None
    product_type: str | None
    category: str | None
    raw_service_type: str | None
    price_status: str | None
    shelf_status: str | None
    repair_category: str | None
    related_category: str | None
    related_area: str | None
    fault_phenomenon: str | None
    display_order: str | None
    remark: str | None
    coverage: dict[str, Any]
    validation: dict[str, Any]


class SubmissionState(TypedDict, total=False):
    attempted: bool
    state: SubmissionStatus
    order_no: str | None
    failure_code: str | None
    failure_message: str | None
    missing_fields: list[str]
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]


class ProductRequestState(TypedDict, total=False):
    room_number: str | None
    product: str | None
    fault: str | None
    area: str | None
    second_area: str | None
    second_area_id: str | None
    managed_repair_scope: str | None
    available_second_areas: list[str]
    available_second_area_options: list[dict[str, Any]]
    second_area_needs_confirmation: bool


class OrderCommonState(TypedDict, total=False):
    room_number: str | None
    area: str | None
    second_area: str | None
    second_area_id: str | None
    managed_repair_scope: str | None
    available_second_areas: list[str]
    available_second_area_options: list[dict[str, Any]]
    second_area_needs_confirmation: bool
    urgency: str | None
    expected_start_time: str | None
    goods_arrival_status: str | None
    contacts: str | None
    phone: str | None
    remark: str | None
    special_requirement: str | None
    total_fee: str | None
    user_confirmed: bool
    user_cancelled: bool


class OrderState(OrderCommonState, total=False):
    items: list[OrderItemState]


class AgentState(TypedDict, total=False):
    """LangGraph 运行时状态。

    这里使用 TypedDict 是为了让 State 既保持字典的轻量形式，
    又能清楚表达每个字段的含义和类型，方便后续扩展节点。
    """

    # LangGraph 会通过 add_messages 自动追加消息，而不是每次覆盖整个列表。
    messages: Annotated[list[BaseMessage], add_messages]

    # 只面向客户端的消息时间线。它与 LLM messages 分离，并携带每轮工作流快照。
    conversation_messages: Annotated[
        list[dict[str, Any]],
        upsert_conversation_messages,
    ]

    # 当前登录用户 ID，用于会话隔离与越权校验。
    user_id: str

    # 当前识别到的用户意图，例如 create_order、confirm_order、cancel_order。
    intent: str | None

    # 由当前订单对话关键词确定的服务类型，例如 单次安装、单次测量、托管维修。
    service_type: str | None

    # 最终用于字段校验和真实提交的服务类型；托管维修范围外会降级为单次维修服务。
    effective_service_type: str | None

    # 托管维修商品是否在当前用户维保卡范围内的校验结果。
    coverage_result: dict[str, Any]

    # 下单卡片默认值，来自用户登录态、维保卡、地址、商品接口等。
    order_context: dict[str, Any]

    # 下单卡片字段列表，由后端按当前订单类型生成，前端直接渲染。
    order_card_fields: list[dict[str, Any]]

    # 订单主流程阶段，同时决定前端展示哪类主卡片。
    phase: OrderPhase | None

    # 用户选择“以上都不符合”后，用于触发重新描述和重新检索。
    product_selection_rejected: bool

    # 用户在预下单阶段明确更换商品描述时，触发重新检索并重建商品明细。
    product_change_requested: bool

    # 商品选择前的自然语言需求；选择后商品级字段迁入 order.items。
    product_request: ProductRequestState

    # 与客户端一致的订单对象：公共字段和最终商品明细。
    order: OrderState

    # 最近一次已提交的订单，供成功卡片和用户追问“刚才那个单号”时使用。
    last_order: dict[str, Any]

    # 商品检索结果（按相似度排序）。
    products: list[dict[str, Any]]

    # 真实提交动作状态，包括请求参数、接口返回、失败原因和订单号。
    submission: SubmissionState

    # 仍然缺失、需要继续追问用户的订单信息名。
    missing_info: list[str]

    # 当前流程步骤，例如 intent_node、validate_order_node、confirm_node。
    step: str

    # 当前步骤重试次数，适合控制重复追问或兜底策略。
    retry_count: int

    # 用户偏离当前任务的次数，适合做对话纠偏。
    off_topic_count: int

    # 用户最近一轮输入，方便节点快速读取，不必总是解析 messages。
    last_user_message: str
