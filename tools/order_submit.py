from __future__ import annotations

import asyncio
from typing import Any

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from config.settings import settings
from graph.expected_time import parse_expected_time_to_range
from schemas.user import UserContext, user_from_runtime_config
from tools.protocol import ToolErrorCode, ToolResult, error_response, success_response

JsonDict = dict[str, Any]

ADMIN_API_SPU_PAGE = "/admin-api/system/service-spu/page"
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


class SubmitOrderInput(BaseModel):
    order_info: JsonDict = Field(..., description="对话抽取出的订单信息")
    matched_product: JsonDict = Field(..., description="商品匹配工具返回的标准商品")
    service_type: str | None = Field(default=None, description="商品库匹配出的原始服务类型")
    effective_service_type: str | None = Field(default=None, description="最终用于提交的服务类型")
    coverage_result: JsonDict = Field(default_factory=dict, description="托管维修维保范围校验结果")
    submit: bool = Field(default=False, description="是否真实调用创建订单接口")


def _clean_text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


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


def _first_present(*values: object) -> object:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _nested_dict(value: object) -> JsonDict:
    return value if isinstance(value, dict) else {}


def resolve_single_order_spu_type(service_type: str | None) -> str:
    if service_type == "单次安装":
        return "安装"
    if service_type == "单次测量":
        return "测量"
    return "维修"


def resolve_goods_arrival_status(value: object, service_type: str | None) -> int:
    if service_type != "单次安装":
        return 3
    mapping = {
        "未到场": 0,
        "已到场": 1,
        "已到物流站": 2,
    }
    return mapping.get(_clean_text(value), 3)


async def query_single_order_category_context(
    category_name: str,
    service_type: str | None,
    user: UserContext,
) -> JsonDict:
    """按 App 类目列表补齐普通订单所需的 category/type ID。"""

    if not category_name:
        return {}
    data = await _post_app(SERVICE_SPU_CATEGORY_TYPE_LIST, {}, user)
    if data.get("code") != 200:
        return {}

    categories = data.get("data") or []
    if not isinstance(categories, list):
        return {}

    spu_type_name = resolve_single_order_spu_type(service_type)
    normalized_category_name = _clean_text(category_name)
    matched_category: JsonDict | None = None
    for item in categories:
        if not isinstance(item, dict):
            continue
        names = [
            _clean_text(item.get("erpName")),
            _clean_text(item.get("name")),
            _clean_text(item.get("categoryName")),
        ]
        if normalized_category_name in names or any(
            name and (normalized_category_name in name or name in normalized_category_name)
            for name in names
        ):
            matched_category = item
            break

    if not matched_category:
        return {}

    type_list = matched_category.get("typeRespAppVOS") or []
    matched_type: JsonDict = {}
    if isinstance(type_list, list):
        for item in type_list:
            if not isinstance(item, dict):
                continue
            if _clean_text(item.get("serviceTypeName")) == spu_type_name:
                matched_type = item
                break

    return {
        "category_id": matched_category.get("id"),
        "category_code": matched_category.get("erpCode") or matched_category.get("code"),
        "category_name": matched_category.get("erpName") or matched_category.get("name"),
        "type_id": matched_type.get("id"),
        "type_code": matched_type.get("serviceTypeCode") or matched_type.get("code"),
        "type_name": matched_type.get("serviceTypeName") or spu_type_name,
    }


async def query_single_order_app_spu(
    *,
    product_name: str,
    product_code: str,
    category_context: JsonDict,
    selected_address: JsonDict,
    user: UserContext,
) -> JsonDict:
    """按 App 商品列表接口获取普通下单可用的商品结构。"""

    category_id = category_context.get("category_id")
    type_id = category_context.get("type_id")
    if not category_id or not type_id:
        return {}

    payload: JsonDict = {
        "firstCategoryId": category_id,
        "serviceSpuTypeId": type_id,
    }
    for source_key, target_key in [
        ("province", "province"),
        ("city", "city"),
        ("area", "area"),
        ("provinceCode", "provinceCode"),
        ("cityCode", "cityCode"),
        ("areaCode", "areaCode"),
    ]:
        value = selected_address.get(source_key)
        if value not in (None, ""):
            payload[target_key] = value

    data = await _post_app(SERVICE_SPU_TYPE_CATEGORY_LIST, payload, user)
    if data.get("code") != 200:
        return {}

    groups = data.get("data") or []
    if not isinstance(groups, list):
        return {}

    normalized_code = _clean_text(product_code)
    normalized_name = _clean_text(product_name)
    fallback: JsonDict = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        items = group.get("itemRespVOList") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            enriched = {
                **item,
                "categoryId": _first_present(item.get("categoryId"), group.get("secondCategoryId")),
                "categoryCode": _first_present(item.get("categoryCode"), group.get("secondCategoryCode")),
                "categoryName": _first_present(item.get("categoryName"), group.get("secondCategoryName")),
            }
            item_code = _clean_text(item.get("code"))
            item_name = _clean_text(item.get("name"))
            if normalized_code and item_code == normalized_code:
                return enriched
            if normalized_name and item_name == normalized_name:
                return enriched
            if normalized_name and not fallback and (normalized_name in item_name or item_name in normalized_name):
                fallback = enriched

    return fallback


def build_single_order_payload(
    order_info: JsonDict,
    spu: JsonDict,
    matched_product: JsonDict,
    category_context: JsonDict,
    selected_address: JsonDict,
    contacts: str,
    phone: str,
    service_type: str | None,
    ide_name: str = "",
) -> tuple[JsonDict, list[str]]:
    """按 App 普通订单 OrderSaveReqVO 结构构造单次安装/测量/维修参数。"""

    spu_type_name = resolve_single_order_spu_type(service_type)
    work_start_time, work_end_time = parse_expected_time_to_range(order_info.get("expected_start_time"))
    hotel_address = _clean_text(selected_address.get("address"))
    room_num = _clean_text(order_info.get("room_number"))
    category = _nested_dict(spu.get("category"))
    spu_type = _nested_dict(spu.get("type") or spu.get("serviceSpuType"))
    unit = _nested_dict(spu.get("serviceMeasureUnitDO") or spu.get("measureUnit"))

    category_id = _first_present(
        spu.get("firstCategoryId"),
        spu.get("spuCategoryId"),
        category_context.get("category_id"),
        category.get("id"),
        spu.get("spuCategoryId"),
    )
    category_code = _clean_text(
        _first_present(
            spu.get("categoryCode"),
            spu.get("spuCategoryCode"),
            category_context.get("category_code"),
            category.get("erpCode"),
            category.get("code"),
        )
    )
    category_name = _clean_text(
        _first_present(
            spu.get("categoryName"),
            spu.get("spuCategoryName"),
            category_context.get("category_name"),
            category.get("erpName"),
            category.get("name"),
            matched_product.get("category"),
            matched_product.get("related_category"),
        )
    )
    type_id = _first_present(
        spu.get("typeId"),
        spu.get("serviceSpuTypeId"),
        spu.get("spuTypeId"),
        spu_type.get("id"),
        category_context.get("type_id"),
    )
    type_code = _clean_text(
        _first_present(
            spu.get("typeCode"),
            spu.get("serviceSpuTypeCode"),
            spu.get("spuTypeCode"),
            spu_type.get("serviceTypeCode"),
            spu_type.get("code"),
            category_context.get("type_code"),
        )
    )
    unit_name = _clean_text(_first_present(spu.get("measureUnitName"), unit.get("name")), "个")
    unit_type = _first_present(spu.get("measureUnitType"), unit.get("type"), "0")
    product_quantity = resolve_product_quantity(order_info)

    order_goods: JsonDict = {
        "goodsId": spu.get("id"),
        "goodsNo": _clean_text(spu.get("code")),
        "templateCode": _clean_text(spu.get("code")),
        "templateName": _clean_text(spu.get("name")) or _clean_text(order_info.get("product")),
        "num": product_quantity,
        "unit": unit_name,
        "templatePhoto": _clean_text(spu.get("icon")),
        "unitType": str(unit_type),
        "quantity": str(product_quantity),
        "erpCodeId": _first_present(spu.get("categoryId"), spu.get("erpCodeId"), category_id),
        "erpCode": _clean_text(_first_present(spu.get("categoryCode"), spu.get("erpCode"), category_code)),
        "erpName": _clean_text(_first_present(spu.get("categoryName"), spu.get("erpName"), category_name)),
        "price": spu.get("discountPrice") or spu.get("price") or 0,
    }
    for key in [
        "actualPrice",
        "userPrice",
        "discount",
        "provinceCode",
        "province",
        "cityCode",
        "city",
        "areaCode",
        "area",
        "calculationMethod",
        "limitBuyType",
        "limitBuyStart",
        "limitBuyEnd",
        "efficiency",
        "stackPrice",
        "isStackDiscount",
    ]:
        if key in spu and spu.get(key) is not None:
            order_goods[key] = spu.get(key)
    order_goods["discountType"] = 0

    category_payload: JsonDict = {
        "sId": "ai_order_group_1",
        "spuTypeId": type_id,
        "spuTypeCode": type_code,
        "spuTypeName": spu_type_name,
        "spuCategoryId": category_id,
        "spuCategoryCode": category_code,
        "spuCategoryName": category_name,
        "isArrive": resolve_goods_arrival_status(order_info.get("goods_arrival_status"), service_type),
        "goodsSaveReqVOList": [order_goods],
        "workStartTime": work_start_time,
        "workEndTime": work_end_time,
        "roomNum": room_num,
        "imageList": "",
        "remark": _clean_text(order_info.get("remark") or order_info.get("fault")),
    }

    payload: JsonDict = {
        "projectNo": None,
        "attributeName": None,
        "projectName": None,
        "province": _clean_text(selected_address.get("province")),
        "city": _clean_text(selected_address.get("city")),
        "area": _clean_text(selected_address.get("area")) or None,
        "provinceCode": _clean_text(selected_address.get("provinceCode")) or None,
        "cityCode": _clean_text(selected_address.get("cityCode")) or None,
        "areaCode": _clean_text(selected_address.get("areaCode")) or None,
        "contacts": contacts,
        "phone": phone,
        "lon": selected_address.get("lon"),
        "lat": selected_address.get("lat"),
        "address": hotel_address,
        "simpleAddress": _clean_text(selected_address.get("simpleAddress")) or None,
        "houseNumber": _clean_text(order_info.get("house_number")) or _clean_text(selected_address.get("houseNumber")) or room_num,
        "ideName": _clean_text(order_info.get("ide_name")) or ide_name or _clean_text(selected_address.get("ideName")),
        "workerName": None,
        "specialReq": _clean_text(order_info.get("special_requirement") or order_info.get("remark") or order_info.get("fault")) or None,
        "fileList": "",
        "photo": "",
        "categorySaveReqVOS": [category_payload],
    }

    if service_type == "单次维修服务":
        urgency = _clean_text(order_info.get("urgency"))
        payload["emergencyFlag"] = 1 if urgency in {"urgent", "紧急"} else 0
        payload["nightEmergencyPrice"] = 0

    missing: list[str] = []
    for field, value in [
        ("contacts", contacts),
        ("phone", phone),
        ("address", hotel_address),
        ("province", payload["province"]),
        ("city", payload["city"]),
        ("provinceCode", payload["provinceCode"]),
        ("cityCode", payload["cityCode"]),
        ("spuTypeId", category_payload["spuTypeId"]),
        ("spuCategoryId", category_payload["spuCategoryId"]),
        ("goodsId", order_goods["goodsId"]),
        ("workStartTime", category_payload["workStartTime"]),
        ("workEndTime", category_payload["workEndTime"]),
    ]:
        if value in (None, ""):
            missing.append(field)
    if not selected_address:
        missing.append("address_context")
    return payload, sorted(set(missing))


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
    product_quantity = resolve_product_quantity(order_info)

    order_spu: JsonDict = {
        "spuId": spu.get("id"),
        "secondAreaId": second_area_id,
        "secondAreaName": second_area_name,
        "templateCode": _clean_text(spu.get("code")),
        "templateName": _clean_text(spu.get("name")),
        "templatePhoto": _clean_text(spu.get("icon")),
        "num": product_quantity,
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
    service_type: str | None = None,
    effective_service_type: str | None = None,
    coverage_result: JsonDict | None = None,
) -> ToolResult:
    active_user = user
    order_context = await load_managed_repair_order_context(active_user)
    final_service_type = effective_service_type or service_type or matched_product.get("service_order_type")

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

    if final_service_type == "托管维修":
        from tools.order_submit_managed import submit_managed_repair_order

        return await submit_managed_repair_order(
            order_info=order_info,
            matched_product=matched_product,
            spu=spu,
            order_context=order_context,
            submit=submit,
            user=active_user,
            service_type=service_type,
            coverage_result=coverage_result,
            spu_query_error=spu_query_error,
        )

    from tools.order_submit_single import submit_single_order

    return await submit_single_order(
        order_info=order_info,
        matched_product=matched_product,
        spu=spu,
        order_context=order_context,
        submit=submit,
        user=active_user,
        service_type=final_service_type,
        coverage_result=coverage_result,
        spu_query_error=spu_query_error,
    )

@tool(args_schema=SubmitOrderInput)
async def submit_real_order_tool(
    order_info: JsonDict,
    matched_product: JsonDict,
    service_type: str | None = None,
    effective_service_type: str | None = None,
    coverage_result: JsonDict | None = None,
    submit: bool = False,
) -> ToolResult:
    """查询商品详情并构造下单参数，在启用配置后调用真实下单接口。"""
    return await submit_real_order(
        order_info=order_info,
        matched_product=matched_product,
        service_type=service_type,
        effective_service_type=effective_service_type,
        coverage_result=coverage_result or {},
        submit=submit,
        user=user_from_runtime_config(),
    )
