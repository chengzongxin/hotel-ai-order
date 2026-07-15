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


class UrgencyLevel(str, Enum):
    """订单紧急程度。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


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


class ProductRequest(BaseModel):
    """商品选择前从自然语言中抽取的商品需求。"""

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
    second_area_id: str | None = Field(default=None, description="二级区域 ID。")
    available_second_areas: list[str] = Field(default_factory=list, description="可选二级区域名称。")
    available_second_area_options: list[dict[str, Any]] = Field(default_factory=list, description="结构化二级区域选项。")
    second_area_needs_confirmation: bool = Field(default=False, description="是否需要用户确认二级区域。")


class OrderCommon(BaseModel):
    """作用于整张订单的公共字段。"""

    room_number: str | None = Field(default=None, description="本订单所有商品共用的房号或位置。")
    area: str | None = Field(default=None, description="本订单所有商品共用的一级区域。")
    second_area: str | None = Field(default=None, description="本订单所有商品共用的二级区域。")
    second_area_id: str | None = Field(default=None, description="共用二级区域 ID。")
    managed_repair_scope: str | None = Field(default=None, description="共用托管维修范围。")
    available_second_areas: list[str] = Field(default_factory=list, description="可选二级区域。")
    available_second_area_options: list[dict[str, Any]] = Field(default_factory=list, description="结构化二级区域选项。")
    second_area_needs_confirmation: bool = Field(default=False, description="是否需要确认二级区域。")
    urgency: UrgencyLevel | str | None = Field(default=None, description="紧急程度。")
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
    contacts: str | None = Field(default=None, description="订单联系人。")
    phone: str | None = Field(default=None, description="订单联系电话。")
    remark: str | None = Field(default=None, description="订单备注。")
    special_requirement: str | None = Field(default=None, description="特殊要求。")
    total_fee: str | None = Field(default=None, description="订单总费用展示值。")
    user_confirmed: bool = Field(default=False, description="用户是否确认下单。")
    user_cancelled: bool = Field(default=False, description="用户是否取消下单。")


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


class OrderItem(BaseModel):
    """预下单中的一个已选商品明细。"""

    id: str = Field(description="订单商品明细稳定 ID，用于修改数量或删除。")
    code: str = Field(description="标准服务商品编码。")
    name: str = Field(description="标准服务商品名称。")
    service_type: str = Field(description="商品对应的服务订单类型。")
    quantity: int = Field(default=1, ge=1, description="该商品下单数量。")
    unit: str | None = Field(default=None, description="商品计量单位。")
    price: str | None = Field(default=None, description="商品参考单价。")
    fault: str | None = Field(default=None, description="该商品对应的故障或服务说明。")
    coverage: dict[str, Any] = Field(default_factory=dict, description="该商品的维保范围校验摘要。")
    errors: list[str] = Field(default_factory=list, description="该商品仍需补充的字段。")
    can_edit: bool = Field(default=True, description="当前是否允许修改该商品明细。")
    can_remove: bool = Field(default=True, description="当前是否允许删除该商品明细。")


class OrderFormOption(BaseModel):
    """枚举型预下单字段的一个可选项。"""

    label: str = Field(description="展示给用户的选项名称。", examples=["客房区域（客房）"])
    value: str = Field(description="更新订单字段时提交给后端的选项值。", examples=["1545054022"])


class OrderFormField(BaseModel):
    """预下单字段的业务元数据；前端决定具体组件和布局。"""

    key: str = Field(description="字段稳定标识；更新订单信息时作为 updates 的 key。", examples=["expected_time"])
    label: str = Field(description="面向用户的字段名称。", examples=["期望开工/完工时间"])
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


class SubmissionSection(BaseModel):
    """真实下单动作的客户端安全摘要。"""

    state: SubmissionState | str = Field(
        default=SubmissionState.NOT_ATTEMPTED,
        description="提交状态：not_attempted、submitting、succeeded、failed 或 disabled。",
    )
    order_no: str | None = Field(default=None, description="提交成功后返回的真实订单号。", examples=["SO202607130001"])
    message: str | None = Field(default=None, description="已经脱敏、可展示给用户的提交结果说明。")


class ClientOrder(OrderCommon):
    """客户端直接使用的订单；公共字段与商品明细归于一个对象。"""

    items: list[OrderItem] = Field(default_factory=list, description="最终要提交的商品明细。")


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
    items: list[OrderItem] = Field(default_factory=list, description="本次成功提交的商品明细。")


class OrderPreview(BaseModel):
    """从内部 AgentState 投影得到的客户端工作流快照。"""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "schema_version": 4,
                    "phase": "pre_order",
                    "service_type": "托管维修",
                    "service_type_display": "托管维修（客房）",
                    "effective_service_type": "托管维修",
                    "effective_service_type_display": "托管维修（客房）",
                    "product_request": {},
                    "order": {
                        "urgency": "medium",
                        "items": [],
                    },
                    "products": [],
                    "form": {"fields": []},
                    "errors": [],
                    "actions": ["update_order", "confirm_order", "cancel_order"],
                    "submission": {"state": "not_attempted", "order_no": None, "message": None},
                    "submitted_order": None,
                }
            ]
        }
    )

    schema_version: int = Field(default=4, description="客户端最小状态契约版本。", examples=[4])
    phase: OrderPhase | str = Field(default=OrderPhase.IDLE, description="订单主流程阶段；前端可据此选择展示区域。")
    service_type: str | None = Field(default=None, description="由当前订单对话关键词确定的原始服务类型。")
    service_type_display: str | None = Field(default=None, description="原始服务类型的用户展示文案。")
    effective_service_type: str | None = Field(default=None, description="维保校验后最终用于字段校验和提交的服务类型。")
    effective_service_type_display: str | None = Field(default=None, description="最终服务类型的用户展示文案。")
    product_request: ProductRequest = Field(default_factory=ProductRequest, description="商品选择前的自然语言需求。")
    order: ClientOrder = Field(default_factory=ClientOrder, description="订单公共字段和最终商品明细。")
    products: list[ProductOption] = Field(default_factory=list, description="当前可选择的商品候选。")
    form: OrderForm = Field(default_factory=OrderForm, description="当前预下单业务字段；前端决定具体组件。")
    errors: list[str] = Field(default_factory=list, description="当前订单仍需补充的字段路径。")
    actions: list[str] = Field(default_factory=list, description="当前允许执行的确定性操作。")
    submission: SubmissionSection = Field(default_factory=SubmissionSection, description="真实下单动作状态和安全错误摘要。")
    submitted_order: SubmittedOrder | None = Field(default=None, description="提交成功后的订单快照；未成功时为 null。")
