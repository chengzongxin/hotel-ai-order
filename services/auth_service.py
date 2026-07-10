"""用户登录态校验。"""

from __future__ import annotations

from typing import Any

import httpx

from config.settings import settings
from schemas.user import UserContext

JsonDict = dict[str, Any]


LOGIN_REQUIRED_MESSAGE = "请先登录后再使用下单助手。"


class LoginRequiredError(PermissionError):
    """当前请求没有有效登录态。"""


def _profile_headers(user: UserContext) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if user.access_token:
        headers["Authorization"] = f"Bearer {user.access_token}"
    if user.tenant_id:
        headers["tenant-id"] = user.tenant_id
    return headers


async def fetch_login_profile(user: UserContext) -> JsonDict:
    url = settings.login_profile_url.strip()
    if not url:
        raise LoginRequiredError(LOGIN_REQUIRED_MESSAGE)

    async with httpx.AsyncClient(timeout=settings.user_app_timeout_seconds, trust_env=False) as client:
        response = await client.post(url, headers=_profile_headers(user), json={})
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


async def ensure_user_logged_in(user: UserContext) -> JsonDict:
    try:
        data = await fetch_login_profile(user)
    except (httpx.HTTPError, ValueError) as exc:
        raise LoginRequiredError(LOGIN_REQUIRED_MESSAGE) from exc

    if data.get("code") != 200 or not isinstance(data.get("data"), dict):
        raise LoginRequiredError(str(data.get("msg") or LOGIN_REQUIRED_MESSAGE))
    return data["data"]
