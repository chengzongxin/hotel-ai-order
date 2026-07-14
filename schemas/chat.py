from typing import Literal

from pydantic import BaseModel, Field

from schemas.order_preview import OrderPreview


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户本轮输入")
    session_id: str | None = Field(
        default=None,
        description="会话 ID；必须由前端生成并传入",
    )


class ConversationMessage(BaseModel):
    """只面向客户端的消息；不包含 LangChain system/tool 等内部消息。"""

    id: str = Field(description="消息稳定 ID；前端据此追加或更新消息。")
    role: Literal["human", "ai"] = Field(
        description="客户端消息角色：human 表示用户，ai 表示助手。",
    )
    content: str = Field(description="消息正文。", examples=["301 房间门锁打不开"])
    order_preview: OrderPreview | None = Field(
        default=None,
        description="该轮结束后的订单工作流快照；human 消息固定为 null。",
    )


class ConversationResponse(BaseModel):
    """聊天、历史和确定性命令共用的客户端消息响应。"""

    session_id: str = Field(description="响应所属的会话 ID。")
    conversation_messages: list[ConversationMessage] = Field(
        description="本次新增或更新的客户端消息；History 接口返回全部消息。",
    )


class SelectProductRequest(BaseModel):
    product_code: str = Field(
        ...,
        min_length=1,
        description="要选择的商品编码，对应 order_preview.products.items[].code",
        examples=["FWSP01537"],
    )


class UpdateOrderInfoRequest(BaseModel):
    updates: dict[str, object] = Field(
        ...,
        description="要更新的预下单字段，key 对应 order_preview.form.fields[].key",
        examples=[{"contacts": "李四", "phone": "13600000000"}],
    )


class AddOrderItemRequest(BaseModel):
    product_code: str = Field(min_length=1, description="要加入预下单的标准商品编码。")
    quantity: int = Field(default=1, ge=1, description="加入数量，最小为 1。")


class UpdateOrderItemRequest(BaseModel):
    quantity: int | None = Field(default=None, ge=1, description="修改后的商品数量。")
    fault: str | None = Field(default=None, description="该商品的故障或服务说明。")
