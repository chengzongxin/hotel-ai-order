"""真实下单共享工具：HTTP 客户端、文本清洗与通用辅助函数。"""

from __future__ import annotations

from typing import Any

import httpx

from config.settings import settings
from graph.streaming import run_traced_tool_call
from schemas.user import UserContext

JsonDict = dict[str, Any]

ADMIN_API_SPU_PAGE = "/admin-api/system/service-spu/page"
ADMIN_API_SPU_GET = "/admin-api/system/service-spu/get"
CREATE_MANAGED_REPAIR_ORDER = "/app-api/order/company-managed-repair-order/create"
CHECK_SINGLE_ORDER = "/app-api/order/publish-order/checkDouble"
CREATE_SINGLE_ORDER = "/app-api/order/publish-order/create"
HOSTING_CARD_GET = "/app-api/order/hosting-card/card"
USER_PROFILE_GET = "/app-api/system/profile/get"
MANAGED_REPAIR_GLOBAL_CONFIG = "/app-api/system/config/getManagedRepairGlobal"
MANAGED_REPAIR_AREA_TREE_LIST = "/app-api/system/managed-repair-order-homepage/area-tree-list"
SERVICE_SPU_CATEGORY_TYPE_LIST = "/app-api/system/service-spu-category/list-with-type"
SERVICE_SPU_TYPE_CATEGORY_LIST = "/app-api/system/service-spu/type-category-list"

DEFAULT_RESPONSE_TIME = 30
DEFAULT_RESPONSE_TIME_UNIT = "MINUTES"

PLACEHOLDER_MARKERS = ("你的", "租户ID", "your-", "replace")


def clean_text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


# 兼容旧模块内下划线命名
_clean_text = clean_text


def resolve_product_quantity(order_info: JsonDict) -> int:
    """商品数量来自预下单卡片；缺省时保持历史行为：1 件。"""

    value = order_info.get("product_quantity")
    if value in (None, ""):
        return 1
    try:
        quantity = int(str(value).strip())
    except (TypeError, ValueError):
        return 1
    return max(quantity, 1)


def _is_placeholder(value: str) -> bool:
    text = clean_text(value)
    return bool(text and any(marker in text for marker in PLACEHOLDER_MARKERS))


def has_login_config(user: UserContext) -> bool:
    return bool(
        user.access_token
        and user.tenant_id
        and not _is_placeholder(user.access_token)
        and not _is_placeholder(user.tenant_id)
    )


_has_login_config = has_login_config


INTERFACE_DISPLAY_NAMES = {
    ADMIN_API_SPU_PAGE: "查询 SPU 列表",
    ADMIN_API_SPU_GET: "查询 SPU 详情",
    CREATE_MANAGED_REPAIR_ORDER: "创建托管维修订单",
    CHECK_SINGLE_ORDER: "单次订单重复校验",
    CREATE_SINGLE_ORDER: "创建单次订单",
    HOSTING_CARD_GET: "查询维保卡",
    USER_PROFILE_GET: "查询用户资料",
    MANAGED_REPAIR_GLOBAL_CONFIG: "查询托管维修全局配置",
    MANAGED_REPAIR_AREA_TREE_LIST: "查询托管维修区域树",
    SERVICE_SPU_CATEGORY_TYPE_LIST: "查询单次订单分类",
    SERVICE_SPU_TYPE_CATEGORY_LIST: "查询单次订单商品",
}


def _interface_display_name(path: str, method: str) -> str:
    return INTERFACE_DISPLAY_NAMES.get(path, f"{method} {path}")


def _admin_headers(user: UserContext) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if user.tenant_id:
        headers["tenant-id"] = user.tenant_id
    if user.access_token:
        headers["Authorization"] = f"Bearer {user.access_token}"
    return headers


def _app_headers(user: UserContext) -> dict[str, str]:
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "type": user.app_type,
        "platform": user.platform,
    }
    if user.access_token:
        headers["Authorization"] = f"Bearer {user.access_token}"
    if user.tenant_id:
        headers["tenant-id"] = user.tenant_id
    if user.version:
        headers["version"] = user.version
    if user.channel:
        headers["channel"] = user.channel
    if user.device_id:
        headers["device-id"] = user.device_id
    if user.spirit:
        headers["spirit"] = user.spirit
    return headers


async def post_admin(path: str, payload: JsonDict, user: UserContext) -> JsonDict:
    async def request() -> JsonDict:
        url = settings.admin_api_base_url.rstrip("/") + path
        async with httpx.AsyncClient(timeout=settings.user_app_timeout_seconds, trust_env=False) as client:
            response = await client.post(url, headers=_admin_headers(user), json=payload)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    return await run_traced_tool_call(
        step="interface",
        kind="interface",
        name=f"POST {path}",
        display_name=_interface_display_name(path, "POST"),
        params={"method": "POST", "path": path, "payload": payload},
        action=request,
    )


async def post_app(path: str, payload: JsonDict, user: UserContext) -> JsonDict:
    async def request() -> JsonDict:
        url = settings.user_app_base_url.rstrip("/") + path
        async with httpx.AsyncClient(timeout=settings.user_app_timeout_seconds, trust_env=False) as client:
            response = await client.post(url, headers=_app_headers(user), json=payload)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    return await run_traced_tool_call(
        step="interface",
        kind="interface",
        name=f"POST {path}",
        display_name=_interface_display_name(path, "POST"),
        params={"method": "POST", "path": path, "payload": payload},
        action=request,
    )


_post_admin = post_admin
_post_app = post_app


async def get_admin(path: str, params: JsonDict, user: UserContext) -> JsonDict:
    async def request() -> JsonDict:
        url = settings.admin_api_base_url.rstrip("/") + path
        async with httpx.AsyncClient(timeout=settings.user_app_timeout_seconds, trust_env=False) as client:
            response = await client.get(url, headers=_admin_headers(user), params=params)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    return await run_traced_tool_call(
        step="interface",
        kind="interface",
        name=f"GET {path}",
        display_name=_interface_display_name(path, "GET"),
        params={"method": "GET", "path": path, "params": params},
        action=request,
    )


_get_admin = get_admin


async def fetch_app_data(path: str, user: UserContext, payload: JsonDict | None = None) -> JsonDict | None:
    if not has_login_config(user):
        return None
    try:
        data = await post_app(path, payload or {}, user)
    except httpx.HTTPError:
        return None
    if data.get("code") != 200:
        return None
    body = data.get("data")
    return body if isinstance(body, dict) else None


async def query_spu_by_name(name: str, user: UserContext) -> JsonDict | None:
    data = await post_admin(
        ADMIN_API_SPU_PAGE,
        {"pageNo": 1, "pageSize": 10, "name": name},
        user,
    )
    items: list[JsonDict] = (data.get("data") or {}).get("list") or []
    if not items:
        return None
    for item in items:
        if clean_text(item.get("name")) == name:
            return item
    return items[0]


def _response_data(data: JsonDict) -> JsonDict | None:
    body = data.get("data")
    return body if isinstance(body, dict) else None


async def query_spu_by_id(spu_id: int | str, user: UserContext) -> JsonDict | None:
    if spu_id in (None, ""):
        return None
    data = await get_admin(ADMIN_API_SPU_GET, {"id": spu_id}, user)
    if data.get("code") != 200:
        return None
    return _response_data(data)


async def query_spu_by_code(code: str, user: UserContext) -> JsonDict | None:
    """Reserved for the future exact-code query support.

    The backend does not fully support querying by service product code yet.
    Until it does, only accept responses whose code exactly matches the
    requested code, so an ignored filter cannot select the wrong product.
    """

    product_code = clean_text(code)
    if not product_code:
        return None
    data = await post_admin(
        ADMIN_API_SPU_PAGE,
        {"pageNo": 1, "pageSize": 10, "code": product_code},
        user,
    )
    items: list[JsonDict] = (data.get("data") or {}).get("list") or []
    for item in items:
        if clean_text(item.get("code")) != product_code:
            continue
        spu_id = item.get("id") or item.get("spuId")
        detail = await query_spu_by_id(spu_id, user) if spu_id else None
        return detail or item
    return None


def _pick_product_spu_id(product: JsonDict) -> object:
    for key in ("id", "spu_id", "spuId", "service_product_id", "serviceProductId"):
        value = product.get(key)
        if value not in (None, ""):
            return value
    return None


async def query_spu_detail(matched_product: JsonDict, user: UserContext) -> JsonDict | None:
    spu_id = _pick_product_spu_id(matched_product)
    if spu_id:
        try:
            detail = await query_spu_by_id(spu_id, user)
        except httpx.HTTPError:
            detail = None
        if detail:
            return detail

    product_code = clean_text(matched_product.get("service_product_code") or matched_product.get("code"))
    if product_code:
        try:
            detail = await query_spu_by_code(product_code, user)
        except httpx.HTTPError:
            detail = None
        if detail:
            return detail

    product_name = clean_text(matched_product.get("service_product_name") or matched_product.get("name"))
    if not product_name:
        return None
    spu = await query_spu_by_name(product_name, user)
    if not spu:
        return None
    spu_id = spu.get("id") or spu.get("spuId")
    if spu_id:
        detail = await query_spu_by_id(spu_id, user)
        if detail:
            return detail
    return spu


def extract_order_no(response: JsonDict) -> str | None:
    candidate_keys = ("orderNo", "order_no", "parentOrderNo", "parent_order_no")
    for key in candidate_keys:
        value = response.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = response.get("data")
    if isinstance(data, str) and data.strip():
        return data.strip()
    if isinstance(data, dict):
        for key in candidate_keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


_extract_order_no = extract_order_no


def first_present(*values: object) -> object:
    for value in values:
        if value not in (None, ""):
            return value
    return None


_first_present = first_present


def nested_dict(value: object) -> JsonDict:
    return value if isinstance(value, dict) else {}


_nested_dict = nested_dict
