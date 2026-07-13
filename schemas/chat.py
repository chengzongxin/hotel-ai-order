from pydantic import BaseModel, Field

from schemas.order_preview import OrderPreview


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户本轮输入")
    session_id: str | None = Field(
        default=None,
        description="会话 ID；必须由前端生成并传入",
    )


class ChatResponse(BaseModel):
    """一轮对话或订单命令完成后的统一响应。"""

    session_id: str = Field(
        description="本次响应所属的会话 ID；后续查询历史和执行订单命令时继续使用。",
        examples=["01JZ8Y4Q2R6V8P3M5N7K9H1T0A"],
    )
    answer: str = Field(
        description="面向用户的自然语言回复；确定性命令也会返回对应结果说明。",
        examples=["已为你匹配到以下服务商品，请选择。"],
    )
    order_preview: OrderPreview | None = Field(
        default=None,
        description="当前客户端工作流快照；没有活跃订单且无最近订单时可能为 null。",
    )


class MessageItem(BaseModel):
    """会话历史中的一条可展示消息。"""

    role: str = Field(
        description="消息角色，当前主要为 user 或 assistant。",
        examples=["user"],
    )
    content: str = Field(description="消息正文。", examples=["301 房间门锁打不开"])


class HistoryResponse(BaseModel):
    """会话历史及其最新工作流状态。"""

    session_id: str = Field(description="当前查询的会话 ID。")
    messages: list[MessageItem] = Field(
        description="按时间正序排列、可恢复到聊天界面的历史消息。"
    )
    conversation_summary: str = Field(
        description="长对话压缩后的服务端摘要；无摘要时为空字符串。"
    )
    order_preview: OrderPreview | None = Field(
        default=None,
        description="从最新 checkpoint 投影得到的客户端工作流快照。",
    )


class SelectProductRequest(BaseModel):
    product_code: str = Field(
        ...,
        min_length=1,
        description="要选择的商品编码，对应 order_preview.products.items[].code",
        examples=["FWSP01537"],
    )


class SelectProductResponse(BaseModel):
    """选择商品后返回的最新工作流状态。"""

    session_id: str = Field(description="商品选择所属的会话 ID。")
    order_preview: OrderPreview = Field(description="选择商品后重新计算的客户端工作流快照。")
    message: str = Field(..., description="面向用户的商品选择结果说明。")


class UpdateOrderInfoRequest(BaseModel):
    updates: dict[str, object] = Field(
        ...,
        description="要更新的预下单字段，key 对应 order_preview.form.fields[].key",
        examples=[{"contacts": "李四", "phone": "13600000000"}],
    )


class UpdateOrderInfoResponse(BaseModel):
    """修改预下单字段后返回的最新工作流状态。"""

    session_id: str = Field(description="订单信息更新所属的会话 ID。")
    order_preview: OrderPreview = Field(description="字段更新并重新校验后的客户端工作流快照。")
    message: str = Field(..., description="面向用户的字段更新结果说明。")
