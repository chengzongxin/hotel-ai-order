from pydantic import BaseModel, Field

from schemas.order_preview import OrderPreview


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户本轮输入")
    session_id: str | None = Field(
        default=None,
        description="会话 ID；不传时服务端会自动生成",
    )


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    order_preview: OrderPreview | None = None


class MessageItem(BaseModel):
    role: str
    content: str


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[MessageItem]
    conversation_summary: str
    order_preview: OrderPreview | None = None


class SelectProductRequest(BaseModel):
    product_code: str = Field(
        ...,
        min_length=1,
        description="要选择的商品编码，对应 order_preview.products.items[].code",
        examples=["FWSP01537"],
    )


class SelectProductResponse(BaseModel):
    session_id: str
    order_preview: OrderPreview
    message: str = Field(..., description="选择结果说明")


class UpdateOrderInfoRequest(BaseModel):
    updates: dict[str, object] = Field(
        ...,
        description="要更新的预下单字段，key 对应 order_preview.order_card.fields[].key",
        examples=[{"contacts": "李四", "phone": "13600000000"}],
    )


class UpdateOrderInfoResponse(BaseModel):
    session_id: str
    order_preview: OrderPreview
    message: str = Field(..., description="更新结果说明")
