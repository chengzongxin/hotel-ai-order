from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from schemas.user import UserContext
from services.auth_service import LOGIN_REQUIRED_MESSAGE, LoginRequiredError, ensure_user_logged_in


async def get_current_user(
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    tenant_id: str = Header(default="", alias="tenant-id"),
    platform: str = Header(default="ios"),
    device_id: str = Header(default="", alias="device-id"),
    version: str = Header(default=""),
    channel: str = Header(default=""),
    spirit: str = Header(default=""),
    app_type: str = Header(default="2", alias="type"),
    x_user_phone: str | None = Header(default=None, alias="X-User-Phone"),
    x_user_contacts: str | None = Header(default=None, alias="X-User-Contacts"),
) -> UserContext:
    """从网关透传的 Header 构造用户上下文。

    酒店地址、经纬度、省市区等信息由维保卡接口获取，不在 Header 中配置。
    """
    if not authorization or not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少用户身份信息，请通过网关携带 Authorization 与 X-User-Id",
        )

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization 格式无效",
        )

    if not tenant_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 tenant-id",
        )

    return UserContext(
        user_id=x_user_id.strip(),
        tenant_id=tenant_id.strip(),
        access_token=token,
        app_type=app_type.strip() or "2",
        platform=platform.strip() or "ios",
        device_id=device_id.strip(),
        version=version.strip(),
        channel=channel.strip(),
        spirit=spirit.strip(),
        contacts=(x_user_contacts or "").strip(),
        phone=(x_user_phone or "").strip(),
    )


async def get_logged_in_user(
    user: UserContext = Depends(get_current_user),
) -> UserContext:
    try:
        await ensure_user_logged_in(user)
    except LoginRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc) or LOGIN_REQUIRED_MESSAGE,
        ) from exc
    return user
