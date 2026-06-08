from __future__ import annotations

import asyncio
from typing import Any

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from config.settings import settings
from schemas.user import UserContext, user_from_runtime_config
from tools.protocol import ToolErrorCode, ToolResult, error_response, success_response

JsonDict = dict[str, Any]

ADMIN_API_SPU_PAGE = "/admin-api/system/service-spu/page"
CREATE_MANAGED_REPAIR_ORDER = "/app-api/order/company-managed-repair-order/create"
HOSTING_CARD_GET = "/app-api/order/hosting-card/card"
USER_PROFILE_GET = "/app-api/system/profile/get"
MANAGED_REPAIR_GLOBAL_CONFIG = "/app-api/system/config/getManagedRepairGlobal"
MANAGED_REPAIR_AREA_TREE_LIST = "/app-api/system/managed-repair-order-homepage/area-tree-list"

DEFAULT_RESPONSE_TIME = 30
DEFAULT_RESPONSE_TIME_UNIT = "MINUTES"

PLACEHOLDER_MARKERS = ("你的", "租户ID", "your-", "replace")


class SubmitOrderInput(BaseModel):
    order_info: JsonDict = Field(..., description="对话抽取出的订单信息")
    matched_product: JsonDict = Field(..., description="商品匹配工具返回的标准商品")
    submit: bool = Field(default=False, description="是否真实调用创建订单接口")


def _clean_text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


def _is_placeholder(value: str) -> bool:
    text = _clean_text(value)
    return bool(text and any(marker in text for marker in PLACEHOLDER_MARKERS))


def _has_login_config(user: UserContext) -> bool:
    return bool(
        user.access_token
        and user.tenant_id
        and not _is_placeholder(user.access_token)
        and not _is_placeholder(user.tenant_id)
    )


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


async def _post_admin(path: str, payload: JsonDict, user: UserContext) -> JsonDict:
    url = settings.admin_api_base_url.rstrip("/") + path
    async with httpx.AsyncClient(timeout=settings.user_app_timeout_seconds, trust_env=False) as client:
        response = await client.post(url, headers=_admin_headers(user), json=payload)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


async def _post_app(path: str, payload: JsonDict, user: UserContext) -> JsonDict:
    url = settings.user_app_base_url.rstrip("/") + path
    async with httpx.AsyncClient(timeout=settings.user_app_timeout_seconds, trust_env=False) as client:
        response = await client.post(url, headers=_app_headers(user), json=payload)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


async def _fetch_app_data(path: str, user: UserContext, payload: JsonDict | None = None) -> JsonDict | None:
    if not _has_login_config(user):
        return None
    try:
        data = await _post_app(path, payload or {}, user)
    except httpx.HTTPError:
        return None
    if data.get("code") != 200:
        return None
    body = data.get("data")
    return body if isinstance(body, dict) else None


async def query_spu_by_name(name: str, user: UserContext) -> JsonDict | None:
    data = await _post_admin(
        ADMIN_API_SPU_PAGE,
        {"pageNo": 1, "pageSize": 10, "name": name},
        user,
    )
    items: list[JsonDict] = (data.get("data") or {}).get("list") or []
    if not items:
        return None
    for item in items:
        if _clean_text(item.get("name")) == name:
            return item
    return items[0]


def _match_fault_phenomenon(fault: str, fault_list: list[JsonDict]) -> JsonDict | None:
    if not fault_list:
        return None
    if not fault:
        return fault_list[0]
    fault_text = fault.strip()
    for item in fault_list:
        if _clean_text(item.get("managedRepairFaultPhenomenonName")) == fault_text:
            return item
    for item in fault_list:
        name = _clean_text(item.get("managedRepairFaultPhenomenonName"))
        if name and (fault_text in name or name in fault_text):
            return item
    return fault_list[0]


async def fetch_hosting_card(user: UserContext) -> JsonDict | None:
    return await _fetch_app_data(HOSTING_CARD_GET, user)


async def fetch_user_profile(user: UserContext) -> JsonDict | None:
    return await _fetch_app_data(USER_PROFILE_GET, user)


async def fetch_managed_repair_global_config(user: UserContext) -> JsonDict | None:
    return await _fetch_app_data(MANAGED_REPAIR_GLOBAL_CONFIG, user)


async def fetch_managed_repair_area_tree(user: UserContext) -> list[JsonDict]:
    if not _has_login_config(user):
        return []
    try:
        data = await _post_app(MANAGED_REPAIR_AREA_TREE_LIST, {}, user)
    except httpx.HTTPError:
        return []
    if data.get("code") != 200:
        return []
    areas = data.get("data")
    return areas if isinstance(areas, list) else []


def hosting_card_to_selected_address(card: JsonDict) -> JsonDict:
    """对齐 App CreateHostingOrderStore.fetchHostingCard 构造的 selectedAddress。"""
    selected_address: JsonDict = {
        "province": card.get("province"),
        "city": card.get("city"),
        "area": card.get("area"),
        "provinceCode": card.get("provinceCode"),
        "cityCode": card.get("cityCode"),
        "areaCode": card.get("areaCode"),
        "address": card.get("address"),
        "simpleAddress": card.get("simpleAddress"),
        "houseNumber": card.get("houseNumber"),
        "lon": card.get("lon"),
        "lat": card.get("lat"),
        "hotelName": card.get("tenantName"),
        "comboCardId": card.get("id"),
        "contacts": card.get("contactName"),
        "phone": card.get("contactPhone"),
    }
    return {
        key: value
        for key, value in selected_address.items()
        if value not in (None, "")
    }


def user_profile_to_contacts(profile: JsonDict) -> JsonDict:
    contacts = (
        _clean_text(profile.get("realName"))
        or _clean_text(profile.get("nickname"))
        or _clean_text(profile.get("workerName"))
    )
    phone = _clean_text(profile.get("mobile"))
    return {key: value for key, value in {"contacts": contacts, "phone": phone}.items() if value}


def resolve_contacts(
    user: UserContext,
    user_profile: JsonDict | None,
    selected_address: JsonDict,
) -> tuple[str, str]:
    """联系人优先 userStore（profile 接口），其次网关 Header，最后维保卡。"""
    profile_contacts = user_profile_to_contacts(user_profile or {})
    contacts = (
        _clean_text(profile_contacts.get("contacts"))
        or _clean_text(user.contacts)
        or _clean_text(selected_address.get("contacts"))
    )
    phone = (
        _clean_text(profile_contacts.get("phone"))
        or _clean_text(user.phone)
        or _clean_text(selected_address.get("phone"))
    )
    return contacts, phone


def resolve_response_time(global_config: JsonDict | None, emergency_flag: int) -> tuple[int, str]:
    """对齐 App CreateHostingOrderStore.getResponseTimeForSubmit。"""
    if not global_config or global_config.get("responseTimeEnable") != 0:
        return DEFAULT_RESPONSE_TIME, DEFAULT_RESPONSE_TIME_UNIT
    if emergency_flag == 1:
        return (
            int(global_config.get("urgentBookTime") or 10),
            _clean_text(global_config.get("urgentBookTimeUnit"), DEFAULT_RESPONSE_TIME_UNIT),
        )
    return (
        int(global_config.get("commonBookTime") or 10),
        _clean_text(global_config.get("commonBookTimeUnit"), DEFAULT_RESPONSE_TIME_UNIT),
    )


def resolve_first_area(
    area_tree: list[JsonDict],
    area_scope: str,
) -> tuple[int | None, str | None]:
    if not area_scope:
        return None, None
    for area in area_tree:
        if _clean_text(area.get("name")) == area_scope:
            area_id = area.get("id")
            return (int(area_id) if area_id is not None else None, _clean_text(area.get("name")))
    return None, None


def _extract_order_no(response: JsonDict) -> str | None:
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


def build_managed_repair_order_payload(
    order_info: JsonDict,
    spu: JsonDict,
    selected_address: JsonDict,
    contacts: str,
    phone: str,
    area_tree: list[JsonDict],
    global_config: JsonDict | None,
    ide_name: str = "",
) -> tuple[JsonDict, list[str]]:
    fault_list: list[JsonDict] = spu.get("faultPhenomenonList") or []
    matched_fault = _match_fault_phenomenon(_clean_text(order_info.get("fault")), fault_list)
    spu_fault_list: list[JsonDict] = []
    if matched_fault:
        spu_fault_list = [{
            "faultPhenomenonId": matched_fault.get("managedRepairFaultPhenomenonId"),
            "faultPhenomenonName": matched_fault.get("managedRepairFaultPhenomenonName"),
            "commonRepairType": matched_fault.get("commonRepairType") or [],
        }]

    area_list: list[JsonDict] = spu.get("areaList") or []
    area_scope = _clean_text(order_info.get("managed_repair_scope") or order_info.get("area"))
    room_num = _clean_text(order_info.get("room_number"))
    urgency = _clean_text(order_info.get("urgency"))
    emergency_flag = 1 if urgency in {"urgent", "紧急"} else 0

    matched_area: JsonDict = {}
    if area_list and area_scope:
        for item in area_list:
            if _clean_text(item.get("managedRepairAreaParentName")) == area_scope:
                matched_area = item
                break
        if not matched_area:
            matched_area = area_list[0]

    first_area_id, first_area_name = resolve_first_area(area_tree, area_scope)
    if first_area_id is None and area_scope:
        first_area_name = area_scope or None

    second_area_id = matched_area.get("managedRepairAreaId")
    second_area_name = _clean_text(matched_area.get("managedRepairAreaName")) or None

    order_spu: JsonDict = {
        "spuId": spu.get("id"),
        "secondAreaId": second_area_id,
        "secondAreaName": second_area_name,
        "templateCode": _clean_text(spu.get("code")),
        "templateName": _clean_text(spu.get("name")),
        "templatePhoto": _clean_text(spu.get("icon")),
        "num": 1,
        "unit": _clean_text(spu.get("measureUnitName"), "个"),
        "unitType": "0",
        "spuFaultPhenomenonList": spu_fault_list,
    }

    order_detail: JsonDict = {
        "spuTypeId": spu.get("typeId"),
        "firstAreaId": first_area_id,
        "firstAreaName": first_area_name,
        "roomNum": room_num,
        "imageList": "",
        "orderSpuList": [order_spu],
    }

    response_time, response_time_unit = resolve_response_time(global_config, emergency_flag)
    hotel_address = _clean_text(selected_address.get("address"))
    house_number = (
        _clean_text(order_info.get("house_number"))
        or _clean_text(selected_address.get("houseNumber"))
        or room_num
    )

    payload: JsonDict = {
        "contacts": contacts,
        "phone": phone,
        "ideName": _clean_text(order_info.get("ide_name")) or ide_name or None,
        "lon": selected_address.get("lon"),
        "lat": selected_address.get("lat"),
        "province": _clean_text(selected_address.get("province")),
        "city": _clean_text(selected_address.get("city")),
        "area": _clean_text(order_info.get("district")) or _clean_text(selected_address.get("area")) or None,
        "provinceCode": _clean_text(selected_address.get("provinceCode")) or None,
        "cityCode": _clean_text(selected_address.get("cityCode")) or None,
        "areaCode": _clean_text(selected_address.get("areaCode")) or None,
        "address": hotel_address,
        "hotelName": _clean_text(selected_address.get("hotelName")),
        "houseNumber": house_number,
        "simpleAddress": _clean_text(selected_address.get("simpleAddress")) or None,
        "responseTime": response_time,
        "comboCardId": selected_address.get("comboCardId"),
        "responseTimeUnit": response_time_unit,
        "emergencyFlag": emergency_flag,
        "orderDetailList": [order_detail],
        "confirmDuplicateSubmit": True,
    }

    missing: list[str] = []
    for field, value in [
        ("contacts", contacts),
        ("phone", phone),
        ("address", hotel_address),
        ("province", payload["province"]),
        ("city", payload["city"]),
        ("provinceCode", payload["provinceCode"]),
        ("cityCode", payload["cityCode"]),
        ("hotelName", payload["hotelName"]),
        ("comboCardId", payload["comboCardId"]),
    ]:
        if value in (None, ""):
            missing.append(field)
    if not selected_address:
        missing.append("hosting_card")
    return payload, sorted(set(missing))


async def load_managed_repair_order_context(user: UserContext) -> JsonDict:
    hosting_card, user_profile, global_config, area_tree = await asyncio.gather(
        fetch_hosting_card(user),
        fetch_user_profile(user),
        fetch_managed_repair_global_config(user),
        fetch_managed_repair_area_tree(user),
    )

    selected_address = hosting_card_to_selected_address(hosting_card) if hosting_card else {}
    contacts, phone = resolve_contacts(user, user_profile, selected_address)

    return {
        "hosting_card": hosting_card,
        "user_profile": user_profile,
        "global_config": global_config,
        "area_tree": area_tree,
        "selected_address": selected_address,
        "contacts": contacts,
        "phone": phone,
        "hosting_card_error": None if hosting_card else "hosting card api returned empty data",
    }


async def submit_real_order(
    order_info: JsonDict,
    matched_product: JsonDict,
    submit: bool,
    user: UserContext,
) -> ToolResult:
    active_user = user
    order_context = await load_managed_repair_order_context(active_user)

    product_name = _clean_text(matched_product.get("service_product_name"))
    spu: JsonDict = {}
    spu_query_error: str | None = None
    if product_name:
        try:
            result = await query_spu_by_name(product_name, active_user)
            if result:
                spu = result
        except Exception as exc:
            spu_query_error = f"{type(exc).__name__}: {exc}"

    payload, missing_fields = build_managed_repair_order_payload(
        order_info=order_info,
        spu=spu,
        selected_address=order_context["selected_address"],
        contacts=order_context["contacts"],
        phone=order_context["phone"],
        area_tree=order_context["area_tree"],
        global_config=order_context["global_config"],
        ide_name=active_user.ide_name,
    )

    data: JsonDict = {
        "request_payload": payload,
        "missing_fields": missing_fields,
        "submit_enabled": settings.user_app_submit_enabled,
        "submitted": False,
        "parent_order_no": None,
        "spu_detail": spu,
        "spu_query_error": spu_query_error,
        "hosting_card": order_context["hosting_card"],
        "hosting_card_error": order_context["hosting_card_error"],
        "selected_address": order_context["selected_address"],
        "user_profile": order_context["user_profile"],
        "global_config": order_context["global_config"],
    }

    should_submit = submit and settings.user_app_submit_enabled
    if not should_submit:
        return success_response(
            data=data,
            message="built order payload; real submit is disabled",
        )

    if missing_fields:
        return error_response(
            error_code=ToolErrorCode.INVALID_INPUT,
            message=f"cannot submit order, missing fields: {', '.join(missing_fields)}",
            data=data,
        )
    if not _has_login_config(active_user):
        return error_response(
            error_code=ToolErrorCode.INVALID_INPUT,
            message="cannot submit order, user access token or tenant id is missing",
            data=data,
        )

    try:
        create_result = await _post_app(CREATE_MANAGED_REPAIR_ORDER, payload, active_user)
        data["create_order_response"] = create_result
        order_no = _extract_order_no(create_result)
        data["parent_order_no"] = order_no
        data["submitted"] = create_result.get("code") == 200 and bool(order_no)
    except httpx.HTTPError as exc:
        return error_response(
            error_code=ToolErrorCode.UPSTREAM_ERROR,
            message=f"order api request failed: {exc}",
            data=data,
        )

    if not data["submitted"]:
        create_result = data.get("create_order_response") or {}
        if isinstance(create_result, dict):
            code = create_result.get("code")
            msg = create_result.get("msg") or create_result.get("message") or "no message"
            message = f"order api returned code={code}, msg={msg}, but no order number was found"
        else:
            message = "order api did not return a valid response"
        return error_response(
            error_code=ToolErrorCode.UPSTREAM_ERROR,
            message=message,
            data=data,
        )

    return success_response(data=data, message="order submitted")


@tool(args_schema=SubmitOrderInput)
async def submit_real_order_tool(
    order_info: JsonDict,
    matched_product: JsonDict,
    submit: bool = False,
) -> ToolResult:
    """查询商品详情并构造托管维修下单参数，在启用配置后调用真实下单接口。"""
    return await submit_real_order(
        order_info=order_info,
        matched_product=matched_product,
        submit=submit,
        user=user_from_runtime_config(),
    )
