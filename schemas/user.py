from __future__ import annotations

from pydantic import BaseModel, Field


class UserContext(BaseModel):
    """网关鉴权后透传的用户上下文，供对话与下单使用。"""

    user_id: str = Field(..., min_length=1, description="网关校验后注入的用户 ID")
    tenant_id: str = ""
    access_token: str = Field(default="", repr=False)
    app_type: str = "2"
    platform: str = "ios"
    device_id: str = ""
    version: str = ""
    channel: str = ""
    spirit: str = ""

    contacts: str = ""
    phone: str = ""
    ide_name: str = ""

    def to_config_dict(self) -> dict[str, object]:
        return self.model_dump()

    @classmethod
    def from_config_dict(cls, data: dict[str, object] | None) -> UserContext | None:
        if not data:
            return None
        return cls.model_validate(data)


def build_thread_id(user_id: str, session_id: str) -> str:
    return f"{user_id}:{session_id}"


def require_user(user: UserContext | None) -> UserContext:
    if user is None:
        raise MissingUserContextError("缺少用户上下文，请通过已鉴权的 API 请求携带用户 Header")
    return user


def user_from_runtime_config() -> UserContext:
    """从 LangGraph 运行时 configurable 读取当前请求的用户上下文。"""
    from langgraph.config import get_config

    config = get_config() or {}
    configurable = config.get("configurable", {})
    user_data = configurable.get("user_context") if isinstance(configurable, dict) else None
    if isinstance(user_data, dict):
        return UserContext.model_validate(user_data)
    raise MissingUserContextError("LangGraph 运行时缺少 user_context")


class MissingUserContextError(RuntimeError):
    """调用链中未注入用户上下文。"""


class SessionAccessError(PermissionError):
    """当前用户无权访问目标会话。"""
