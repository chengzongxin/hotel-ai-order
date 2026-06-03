from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户本轮输入")
    session_id: str | None = Field(
        default=None,
        description="会话 ID；优先使用该字段恢复上下文",
    )
    conversation_id: str | None = Field(
        default=None,
        description="兼容旧字段；不传时服务端会自动生成 session_id",
    )


class ChatResponse(BaseModel):
    session_id: str
    conversation_id: str
    answer: str
    order_preview: dict[str, Any] | None = None


class MessageItem(BaseModel):
    role: str
    content: str


class HistoryResponse(BaseModel):
    session_id: str
    conversation_id: str
    messages: list[MessageItem]
    conversation_summary: str
    order_preview: dict[str, Any] | None = None
