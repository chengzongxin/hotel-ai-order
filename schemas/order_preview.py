"""面向客户端的工作流状态契约。

LangGraph ``AgentState`` 是后端运行时细节；本模块只定义允许通过 API 暴露、
并供前端渲染当前订单流程的业务数据。
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrderPhase(str, Enum):
    """订单主流程阶段；前端可据此选择页面区域或卡片。"""

    IDLE = "idle"
    COLLECTING = "collecting"
    PRODUCT_SELECTION = "product_selection"
    PRE_ORDER = "pre_order"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"


class SubmissionState(str, Enum):
    """真实下单动作状态，与订单主流程 phase 分开表达。"""

    NOT_ATTEMPTED = "not_attempted"
    SUBMITTING = "submitting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DISABLED = "disabled"


class SubmissionFailureCode(str, Enum):
    """可供前端分类展示和埋点的提交失败原因。"""

    SUBMIT_DISABLED = "submit_disabled"
    MISSING_REQUIRED_FIELDS = "missing_required_fields"
    ORDER_NO_MISSING = "order_no_missing"
    API_ERROR = "api_error"
    UNKNOWN = "unknown"


class UrgencyLevel(str, Enum):
    """订单紧急程度。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ProductSearchStatus(str, Enum):
    """本轮标准商品检索结果状态。"""

    SKIPPED = "skipped"
    SUCCESS = "success"
    NO_MATCH = "no_match"
    ERROR = "error"


class OrderFieldSource(str, Enum):
    """预下单字段当前值的主要来源。"""

    USER = "user"
    SYSTEM = "system"
    PRODUCT = "product"


class OrderFieldInputType(str, Enum):
    """字段编辑语义；前端自行决定具体使用哪种组件。"""

    TEXT = "text"
    TEXTAREA = "textarea"
    SELECT = "select"
    DATETIME = "datetime"
    NUMBER = "number"


class OrderInfo(BaseModel):
    """从多轮对话中收集、且允许展示给当前用户的订单事实。"""

    room_number: str | None = Field(
        default=None,
        description="房号；公区维修通常使用 `/` 表示不适用具体房号。",
        examples=["301"],
    )
    product: str | None = Field(
        default=None,
        description="用户自然语言中描述的商品、设备或设施名称。",
        examples=["门锁"],
    )
    fault: str | None = Field(
        default=None,
        description="用户描述的故障现象或服务需求。",
        examples=["打不开"],
    )
    area: str | None = Field(
        default=None,
        description="一级区域，例如客房或公区。",
        examples=["客房"],
    )
    second_area: str | None = Field(
        default=None,
        description="二级区域，例如客房设备、大堂或卫生间区域。",
        examples=["客房设备"],
    )
    managed_repair_scope: str | None = Field(
        default=None,
        description="托管维修范围；当前主要为 `客房` 或 `公区`。",
        examples=["客房"],
    )
    urgency: UrgencyLevel | str | None = Field(
        default=None,
        description="紧急程度：low、medium、high 或 urgent。",
        examples=["medium"],
    )
    expected_start_time: str | None = Field(
        default=None,
        description="用户期望的开工时间，可包含自然语言或规范化时间文本。",
        examples=["明天上午"],
    )
    goods_arrival_status: str | None = Field(
        default=None,
        description="安装类订单的货物到场状态。",
        examples=["已到场"],
    )
    product_quantity: int | None = Field(
        default=None,
        ge=1,
        description="下单商品数量，最小为 1。",
        examples=[1],
    )


class ProductOption(BaseModel):
    """一个可由用户选择的标准服务商品。"""

    code: str = Field(description="标准服务商品编码，用于选择和真实下单。", examples=["FWSP01537"])
    name: str = Field(description="标准服务商品名称。", examples=["门锁损坏（困客人）"])
    service_type: str = Field(description="该商品对应的服务订单类型。", examples=["托管维修"])
    category: str | None = Field(default=None, description="商品所属分类。")
    unit: str | None = Field(default=None, description="商品计价单位。", examples=["次"])
    price: str | None = Field(default=None, description="商品参考价格；字符串可保留上游展示格式。", examples=["48.08"])
    price_status: str | None = Field(default=None, description="价格状态或价格展示说明。")
    repair_category: str | None = Field(default=None, description="维修等级，例如小修、中修或大修。", examples=["小修"])
    fault_phenomenon: str | None = Field(default=None, description="商品绑定的标准故障现象。")
    related_area: str | None = Field(default=None, description="商品适用的区域说明。")
    remark: str | None = Field(default=None, description="商品服务说明或备注。")
    score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="商品与本轮检索条件的融合匹配分数，范围 0～1。",
        examples=[0.6756],
    )
    rank: int = Field(description="候选商品排序，从 1 开始。", ge=1, examples=[1])
    is_recommended: bool = Field(default=False, description="是否为当前候选列表的第一推荐项。")
    is_selected: bool = Field(default=False, description="用户当前是否已经选中该商品。")


class ProductSection(BaseModel):
    """本轮商品检索、候选与选中状态。"""

    status: ProductSearchStatus | str | None = Field(
        default=None,
        description="检索状态：skipped、success、no_match 或 error。",
    )
    query: str | None = Field(default=None, description="后端实际用于商品检索的查询文本。", examples=["门锁 打不开"])
    feedback: str | None = Field(default=None, description="解释匹配结果或引导用户选择的提示文案。")
    selected_code: str | None = Field(default=None, description="用户当前选中的标准商品编码；未选择时为 null。")
    selection_rejected: bool = Field(default=False, description="用户是否明确选择了“以上都不符合”。")
    items: list[ProductOption] = Field(default_factory=list, description="按 rank 升序排列的商品候选列表。")


class OrderFormOption(BaseModel):
    """枚举型预下单字段的一个可选项。"""

    label: str = Field(description="展示给用户的选项名称。", examples=["客房区域（客房）"])
    value: str = Field(description="更新订单字段时提交给后端的选项值。", examples=["1545054022"])


class OrderFormField(BaseModel):
    """预下单字段的业务元数据；前端决定具体组件和布局。"""

    key: str = Field(description="字段稳定标识；更新订单信息时作为 updates 的 key。", examples=["expected_time"])
    label: str = Field(description="面向用户的字段名称。", examples=["期望开工/完工时间"])
    value: Any = Field(default=None, description="当前字段值；类型由 input_type 和业务字段决定。")
    required: bool = Field(default=False, description="该字段在当前服务类型下是否必填。")
    source: OrderFieldSource = Field(default=OrderFieldSource.SYSTEM, description="当前值来源：user、system 或 product。")
    editable: bool = Field(default=True, description="后端是否允许用户通过确定性接口修改该字段。")
    input_type: OrderFieldInputType = Field(
        default=OrderFieldInputType.TEXT,
        description="字段编辑语义：text、textarea、select、datetime 或 number；不绑定具体前端组件。",
    )
    options: list[OrderFormOption] = Field(
        default_factory=list,
        description="input_type 为 select 时可用的选项；其他类型通常为空数组。",
    )
    hint: str | None = Field(default=None, description="字段补充说明或输入提示。")


class OrderForm(BaseModel):
    """当前服务类型对应的预下单业务字段集合。"""

    fields: list[OrderFormField] = Field(default_factory=list, description="前端按顺序渲染的预下单字段。")


class CoverageSection(BaseModel):
    """托管维修维保范围校验摘要。"""

    checked: bool = Field(default=False, description="是否已经执行维保范围校验。")
    covered: bool | None = Field(default=None, description="是否在维保范围内；未校验或不适用时为 null。")
    reason: str | None = Field(default=None, description="校验结果、降级原因或待补充信息说明。")
    effective_service_type: str | None = Field(default=None, description="范围校验后最终采用的服务类型。")
    hosting_card_name: str | None = Field(default=None, description="命中的维保卡或维保套餐名称。")


class WorkflowValidation(BaseModel):
    """当前订单数据完整性校验结果。"""

    ready: bool = Field(
        default=False,
        description="订单业务数据是否完整；不等同于按钮当前是否可点击，操作权限以 capabilities 为准。",
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        description="仍需补充的业务字段 key；为空表示数据完整。",
        examples=[["expected_start_time"]],
    )


class WorkflowCapabilities(BaseModel):
    """后端当前接受的确定性业务命令。

    前端决定在哪里、以什么组件展示这些操作；后端收到命令后仍会再次校验。
    """

    select_product: bool = Field(default=False, description="当前是否允许选择一个商品候选。")
    reject_products: bool = Field(default=False, description="当前是否允许拒绝全部商品候选。")
    update_order: bool = Field(default=False, description="当前是否允许修改预下单字段。")
    confirm_order: bool = Field(default=False, description="当前是否允许确认并提交订单。")
    cancel_order: bool = Field(default=False, description="当前是否允许取消进行中的订单。")
    retry_submission: bool = Field(default=False, description="上次提交失败后，当前是否满足再次提交条件。")


class SubmissionSection(BaseModel):
    """真实下单动作的客户端安全摘要。"""

    state: SubmissionState | str = Field(
        default=SubmissionState.NOT_ATTEMPTED,
        description="提交状态：not_attempted、submitting、succeeded、failed 或 disabled。",
    )
    order_no: str | None = Field(default=None, description="提交成功后返回的真实订单号。", examples=["SO202607130001"])
    failure_code: SubmissionFailureCode | str | None = Field(default=None, description="提交失败分类码，供前端选择提示和埋点。")
    failure_message: str | None = Field(default=None, description="已经脱敏、可展示给用户的提交失败说明。")
    missing_fields: list[str] = Field(default_factory=list, description="真实下单接口仍缺失的参数或业务字段名称。")


class SubmittedOrder(BaseModel):
    """提交成功后用于成功卡片和历史恢复的订单快照。"""

    order_no: str = Field(description="真实订单号。", examples=["SO202607130001"])
    service_type: str | None = Field(default=None, description="对话关键词确定的原始服务类型。")
    effective_service_type: str | None = Field(default=None, description="最终提交采用的服务类型。")
    product_code: str | None = Field(default=None, description="已下单的标准服务商品编码。")
    product_name: str | None = Field(default=None, description="已下单的标准服务商品名称。")
    product_order_type: str | None = Field(default=None, description="标准商品记录中的订单类型。")
    room_number: str | None = Field(default=None, description="订单房号；公区订单可能为 `/`。")
    product: str | None = Field(default=None, description="用户原始描述的商品或设备。")
    fault: str | None = Field(default=None, description="用户原始描述的故障或需求。")
    area: str | None = Field(default=None, description="订单一级区域。")
    second_area: str | None = Field(default=None, description="订单二级区域。")
    managed_repair_scope: str | None = Field(default=None, description="托管维修范围。")
    urgency: UrgencyLevel | str | None = Field(default=None, description="订单紧急程度。")
    expected_start_time: str | None = Field(default=None, description="期望开工时间。")
    goods_arrival_status: str | None = Field(default=None, description="货物到场状态。")
    product_quantity: int | None = Field(default=None, description="下单商品数量。")
    contacts: str | None = Field(default=None, description="订单联系人。")
    phone: str | None = Field(default=None, description="订单联系电话。")


class OrderPreview(BaseModel):
    """从内部 AgentState 投影得到的客户端工作流快照。"""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "schema_version": 1,
                    "phase": "pre_order",
                    "service_type": "托管维修",
                    "service_type_display": "托管维修（客房）",
                    "effective_service_type": "托管维修",
                    "effective_service_type_display": "托管维修（客房）",
                    "order_info": {
                        "room_number": "301",
                        "product": "门锁",
                        "fault": "打不开",
                        "area": "客房",
                        "urgency": "medium",
                    },
                    "products": {
                        "status": "success",
                        "query": "门锁 打不开",
                        "selected_code": "FWSP01537",
                        "selection_rejected": False,
                        "items": [],
                    },
                    "form": {"fields": []},
                    "validation": {"ready": True, "missing_fields": []},
                    "capabilities": {
                        "select_product": False,
                        "reject_products": False,
                        "update_order": True,
                        "confirm_order": True,
                        "cancel_order": True,
                        "retry_submission": False,
                    },
                    "coverage": {"checked": True, "covered": True},
                    "submission": {"state": "not_attempted", "missing_fields": []},
                    "submitted_order": None,
                }
            ]
        }
    )

    schema_version: int = Field(default=1, description="客户端状态契约版本；用于兼容未来字段演进。", examples=[1])
    phase: OrderPhase | str = Field(default=OrderPhase.IDLE, description="订单主流程阶段；前端可据此选择展示区域。")
    service_type: str | None = Field(default=None, description="由当前订单对话关键词确定的原始服务类型。")
    service_type_display: str | None = Field(default=None, description="原始服务类型的用户展示文案。")
    effective_service_type: str | None = Field(default=None, description="维保校验后最终用于字段校验和提交的服务类型。")
    effective_service_type_display: str | None = Field(default=None, description="最终服务类型的用户展示文案。")
    order_info: OrderInfo = Field(default_factory=OrderInfo, description="当前已收集的订单事实。")
    products: ProductSection = Field(default_factory=ProductSection, description="商品检索、候选及选中状态。")
    form: OrderForm = Field(default_factory=OrderForm, description="当前预下单业务字段；前端决定具体组件。")
    validation: WorkflowValidation = Field(default_factory=WorkflowValidation, description="订单数据完整性校验结果。")
    capabilities: WorkflowCapabilities = Field(default_factory=WorkflowCapabilities, description="后端当前允许执行的确定性命令。")
    coverage: CoverageSection = Field(
        default_factory=CoverageSection,
        description="当前所选商品的托管维修维保范围校验摘要。",
    )
    submission: SubmissionSection = Field(default_factory=SubmissionSection, description="真实下单动作状态和安全错误摘要。")
    submitted_order: SubmittedOrder | None = Field(default=None, description="提交成功后的订单快照；未成功时为 null。")
