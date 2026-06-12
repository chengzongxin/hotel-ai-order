from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrderPhase(str, Enum):
    """订单主流程阶段，同时决定前端展示哪类主卡片。"""

    IDLE = "idle"
    COLLECTING = "collecting"
    PRODUCT_SELECTION = "product_selection"
    PRE_ORDER = "pre_order"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"


class SubmissionState(str, Enum):
    """真实提交动作的状态。"""

    NOT_ATTEMPTED = "not_attempted"
    SUBMITTING = "submitting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DISABLED = "disabled"


class SubmissionFailureCode(str, Enum):
    """提交失败原因，供前端选择文案和后续排查。"""

    SUBMIT_DISABLED = "submit_disabled"
    MISSING_REQUIRED_FIELDS = "missing_required_fields"
    ORDER_NO_MISSING = "order_no_missing"
    API_ERROR = "api_error"
    UNKNOWN = "unknown"


class UrgencyLevel(str, Enum):
    """紧急程度。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ProductSearchStatus(str, Enum):
    """商品检索状态。"""

    SKIPPED = "skipped"
    SUCCESS = "success"
    NO_MATCH = "no_match"
    ERROR = "error"


class OrderInfo(BaseModel):
    """用户已描述、可被确认/提交的订单信息。"""

    model_config = ConfigDict(extra="allow")

    room_number: str | None = Field(default=None, description="房号；公区维修时可能为 /")
    product: str | None = Field(default=None, description="用户描述的商品/设备")
    fault: str | None = Field(default=None, description="故障现象")
    area: str | None = Field(default=None, description="区域，如 客房、公区")
    managed_repair_scope: str | None = Field(default=None, description="托管维修范围：客房 / 公区")
    urgency: UrgencyLevel | str | None = Field(default=None, description="紧急程度")
    expected_start_time: str | None = Field(default=None, description="期待开工时间")
    goods_arrival_status: str | None = Field(default=None, description="货物是否到场")
    product_quantity: int | None = Field(default=None, ge=1, description="商品数量")
    user_confirmed: bool = Field(default=False, description="用户是否已确认下单")
    user_cancelled: bool = Field(default=False, description="用户是否已取消当前预下单")


class ProductOption(BaseModel):
    """单个可下单商品，供前端卡片展示与选择。"""

    code: str = Field(..., description="商品编码，如 FWSP01537", examples=["FWSP01537"])
    name: str = Field(..., description="商品名称", examples=["门锁损坏（困客人）"])
    service_type: str = Field(..., description="服务类型", examples=["托管维修"])
    category: str | None = Field(default=None, description="商品分类")
    unit: str | None = Field(default=None, description="计价单位")
    price: str | None = Field(default=None, description="参考价格")
    price_status: str | None = Field(default=None, description="价格状态")
    repair_category: str | None = Field(default=None, description="维修等级，如 小修/中修/大修")
    fault_phenomenon: str | None = Field(default=None, description="标准故障现象描述")
    related_area: str | None = Field(default=None, description="适用区域")
    remark: str | None = Field(default=None, description="服务说明")
    score: float | None = Field(default=None, ge=0.0, le=1.0, description="与检索 query 的相似度")
    rank: int = Field(..., ge=1, description="推荐排序，1 为最高")
    is_recommended: bool = Field(default=False, description="是否为系统默认推荐（Top1）")
    is_selected: bool = Field(default=False, description="当前是否已被选中")


class ProductSection(BaseModel):
    """商品匹配结果区块。"""

    status: ProductSearchStatus | str | None = Field(
        default=None,
        description="检索状态：skipped / success / no_match / error",
    )
    query: str | None = Field(default=None, description="本轮检索使用的 query")
    feedback: str | None = Field(default=None, description="面向用户的匹配说明文案")
    selected_code: str | None = Field(default=None, description="当前选中的商品编码")
    selection_rejected: bool = Field(default=False, description="用户是否选择了以上都不符合")
    items: list[ProductOption] = Field(default_factory=list, description="全部候选商品，按 rank 排序")


class OrderCardField(BaseModel):
    """预下单卡片字段，前端直接按列表渲染。"""

    key: str = Field(..., description="字段 key")
    label: str = Field(..., description="展示标签")
    value: Any = Field(default=None, description="展示值")
    required: bool = Field(default=False, description="是否必填")
    source: str = Field(default="system", description="字段来源：user / system / product")
    editable: bool = Field(default=True, description="前端是否可编辑")
    input_type: str = Field(default="text", description="输入类型：text / textarea / select / datetime / number")
    options: list[dict[str, str]] = Field(default_factory=list, description="可选项，仅 select 使用")


class OrderCardSection(BaseModel):
    """预下单卡片配置。"""

    card_type: str | None = Field(default=None, description="卡片类型")
    title: str | None = Field(default=None, description="卡片标题")
    fields: list[OrderCardField] = Field(default_factory=list, description="卡片字段")


class CoverageSection(BaseModel):
    """托管维修维保范围校验结果。"""

    checked: bool = Field(default=False, description="是否已校验维保范围")
    covered: bool | None = Field(default=None, description="是否在当前维保卡范围内；非托管维修为 null")
    reason: str | None = Field(default=None, description="范围校验或降级原因")
    effective_service_type: str | None = Field(default=None, description="校验后的最终下单服务类型")
    hosting_card_status: int | str | None = Field(default=None, description="维保卡状态")
    hosting_card_id: int | str | None = Field(default=None, description="维保卡 ID")
    hosting_card_name: str | None = Field(default=None, description="维保套餐名称")
    spu_id: int | str | None = Field(default=None, description="托管维修 SPU ID")
    spu_name: str | None = Field(default=None, description="托管维修 SPU 名称")
    second_area_id: int | str | None = Field(default=None, description="托管维修二级区域 ID")


class SubmissionSection(BaseModel):
    """真实下单动作的结构化结果。"""

    attempted: bool = Field(default=False, description="是否已经尝试过真实提交")
    state: SubmissionState | str = Field(default=SubmissionState.NOT_ATTEMPTED, description="提交动作状态")
    order_no: str | None = Field(default=None, description="真实订单号")
    failure_code: SubmissionFailureCode | str | None = Field(default=None, description="失败类型")
    failure_message: str | None = Field(default=None, description="面向前端展示的失败说明")
    missing_fields: list[str] = Field(default_factory=list, description="仍缺失的下单字段")
    request_payload: dict[str, Any] = Field(default_factory=dict, description="构造出的真实下单参数")
    response_payload: dict[str, Any] = Field(default_factory=dict, description="真实下单接口返回")


class SubmittedOrder(BaseModel):
    """提交成功后的订单快照，供成功卡片与历史追问使用。"""

    model_config = ConfigDict(extra="allow")

    order_no: str
    service_type: str | None = None
    effective_service_type: str | None = None
    product_code: str | None = None
    product_name: str | None = None
    product_order_type: str | None = None
    room_number: str | None = None
    product: str | None = None
    fault: str | None = None
    area: str | None = None
    managed_repair_scope: str | None = None
    urgency: UrgencyLevel | str | None = None
    expected_start_time: str | None = None
    goods_arrival_status: str | None = None
    product_quantity: int | None = None
    contacts: str | None = None
    phone: str | None = None


class OrderPreview(BaseModel):
    """对话过程中的订单预览，供前端侧边栏/卡片渲染。"""

    phase: OrderPhase | str = Field(default=OrderPhase.IDLE, description="订单主流程阶段")
    service_type: str | None = Field(default=None, description="服务类型")
    service_type_display: str | None = Field(
        default=None,
        description="展示用服务类型，如 托管维修（客房）",
    )
    effective_service_type: str | None = Field(default=None, description="最终用于校验和提交的服务类型")
    effective_service_type_display: str | None = Field(
        default=None,
        description="展示用最终服务类型，如 单次维修服务",
    )
    order_info: OrderInfo = Field(default_factory=OrderInfo, description="已收集的订单信息")
    products: ProductSection = Field(default_factory=ProductSection, description="商品匹配与选择")
    order_card: OrderCardSection = Field(default_factory=OrderCardSection, description="预下单卡片字段配置")
    coverage: CoverageSection = Field(default_factory=CoverageSection, description="托管维修维保范围校验结果")
    missing_info: list[str] = Field(default_factory=list, description="仍需用户补充的字段名")
    submission: SubmissionSection = Field(default_factory=SubmissionSection, description="提交阶段数据")
    submitted_order: SubmittedOrder | None = Field(default=None, description="提交成功后的订单快照")


def product_raw_to_option(
    raw: dict[str, Any],
    *,
    rank: int,
    selected_code: str | None,
) -> ProductOption:
    """将商品库原始字段映射为 API 对外结构。"""
    code = str(raw.get("service_product_code") or "")
    return ProductOption(
        code=code,
        name=str(raw.get("service_product_name") or ""),
        service_type=str(raw.get("service_order_type") or raw.get("product_type") or ""),
        category=raw.get("category"),
        unit=raw.get("unit"),
        price=raw.get("price"),
        price_status=raw.get("price_status"),
        repair_category=raw.get("repair_category"),
        fault_phenomenon=raw.get("fault_phenomenon"),
        related_area=raw.get("related_area"),
        remark=raw.get("remark"),
        score=raw.get("score"),
        rank=rank,
        is_recommended=rank == 1,
        is_selected=bool(code and code == selected_code),
    )


def build_product_section(
    *,
    products: list[dict[str, Any]],
    selected_code: str | None,
    search_status: str | None,
    search_query: str | None,
    search_feedback: str | None,
    selection_rejected: bool = False,
) -> ProductSection:
    """将状态机中的商品列表映射为 API 对外结构。"""
    from graph.products import resolve_selected_code

    resolved_code = resolve_selected_code(products, selected_code, default_to_first=False)

    items = [
        product_raw_to_option(raw, rank=index, selected_code=resolved_code)
        for index, raw in enumerate(products, start=1)
        if raw.get("service_product_code")
    ]

    return ProductSection(
        status=search_status,
        query=search_query,
        feedback=search_feedback,
        selected_code=resolved_code,
        selection_rejected=selection_rejected,
        items=items,
    )


def build_order_preview_model(state: dict[str, Any]) -> OrderPreview | None:
    """从 LangGraph state 构造结构化 OrderPreview。"""
    from graph.products import derive_product_section_fields, get_selected_product

    order_info_raw = state.get("order_info") or {}
    products = state.get("products") or []
    selected_code = state.get("selected_product_code")
    submission_raw = state.get("submission") or {}
    phase = state.get("phase")
    submission_state = submission_raw.get("state")
    request_payload = submission_raw.get("request_payload") or {}
    response_payload = submission_raw.get("response_payload") or {}
    submitted_order_candidate = state.get("submitted_order") or state.get("last_order") or None
    has_submitted_snapshot = (
        isinstance(submitted_order_candidate, dict)
        and bool(submitted_order_candidate.get("order_no"))
    )
    if not phase:
        if has_submitted_snapshot or submission_state == SubmissionState.SUCCEEDED:
            phase = OrderPhase.SUBMITTED
        elif state.get("product_selection_rejected"):
            phase = OrderPhase.COLLECTING
        elif selected_code and state.get("order_card_fields"):
            phase = OrderPhase.PRE_ORDER
        elif products:
            phase = OrderPhase.PRODUCT_SELECTION
        elif order_info_raw:
            phase = OrderPhase.COLLECTING
        else:
            phase = OrderPhase.IDLE
    is_submitted_preview = phase == OrderPhase.SUBMITTED or phase == OrderPhase.SUBMITTED.value
    submitted_order_raw = submitted_order_candidate if is_submitted_preview else None
    coverage_result = state.get("coverage_result") or {}

    if (
        not order_info_raw
        and not products
        and not request_payload
        and not response_payload
        and not submitted_order_raw
        and not coverage_result
        and not state.get("order_card_fields")
    ):
        return None

    search_status, search_query, search_feedback = derive_product_section_fields(state)
    service_type = state.get("service_type")
    if not service_type and products:
        selected = get_selected_product(products, selected_code, default_to_first=False)
        service_type = selected.get("service_order_type") or None

    submission = SubmissionSection.model_validate(submission_raw)
    submitted_order = None
    if isinstance(submitted_order_raw, dict) and submitted_order_raw.get("order_no"):
        submitted_order = SubmittedOrder.model_validate(submitted_order_raw)

    return OrderPreview(
        phase=phase,
        service_type=service_type,
        service_type_display=state.get("service_type_display"),
        effective_service_type=state.get("effective_service_type") or service_type,
        effective_service_type_display=state.get("effective_service_type_display") or state.get("service_type_display"),
        order_info=OrderInfo.model_validate(order_info_raw),
        products=build_product_section(
            products=products,
            selected_code=selected_code,
            search_status=search_status,
            search_query=search_query,
            search_feedback=search_feedback,
            selection_rejected=bool(state.get("product_selection_rejected")),
        ),
        order_card=OrderCardSection(
            card_type=state.get("order_submit_route"),
            title=state.get("effective_service_type_display") or state.get("service_type_display"),
            fields=[
                OrderCardField.model_validate(field)
                for field in (state.get("order_card_fields") or [])
                if isinstance(field, dict)
            ],
        ),
        coverage=CoverageSection.model_validate(coverage_result),
        missing_info=state.get("missing_info") or [],
        submission=submission,
        submitted_order=submitted_order,
    )
