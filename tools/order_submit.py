from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from config.settings import settings
from graph.expected_time import parse_expected_time_to_range
from tools.protocol import ToolErrorCode, ToolResult, error_response, success_response

JsonDict = dict[str, Any]

SERVICE_SPU_LIST_PATH = "/app-api/system/service-spu/list"
SERVICE_SPU_TYPE_CATEGORY_LIST_PATH = "/app-api/system/service-spu/type-category-list"
ADDRESS_PAGE_PATH = "/app-api/system/address/page"
CHECK_DOUBLE_PATH = "/app-api/order/publish-order/checkDouble"
CREATE_ORDER_PATH = "/app-api/order/publish-order/create"

SERVICE_TYPE_NAME_MAP = {
    "单次测量": "测量",
    "单次安装": "安装",
    "单次维修服务": "维修",
}

GOODS_ARRIVAL_MAP = {
    "未到场": 0,
    "已到场": 1,
    "已到物流站": 2,
}

PLACEHOLDER_MARKERS = ("你的", "租户ID", "your-", "replace")


class SubmitOrderInput(BaseModel):
    order_info: JsonDict = Field(..., description="对话抽取出的订单信息")
    matched_product: JsonDict = Field(..., description="商品匹配工具返回的标准商品")
    submit: bool = Field(default=False, description="是否真实调用用户端创建订单接口")


class AddressLoadResult(BaseModel):
    address: JsonDict
    diagnostics: JsonDict


def _clean_text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


def _is_placeholder(value: str) -> bool:
    text = _clean_text(value)
    return bool(text and any(marker in text for marker in PLACEHOLDER_MARKERS))


def _has_user_app_login_config() -> bool:
    return bool(
        settings.user_app_access_token
        and settings.user_app_tenant_id
        and not _is_placeholder(settings.user_app_access_token)
        and not _is_placeholder(settings.user_app_tenant_id)
    )


def _to_price_cent(value: object) -> int:
    try:
        return int(round(float(str(value).strip()) * 100))
    except (TypeError, ValueError):
        return 0


def _default_quantity(product: JsonDict) -> int:
    limit_start = product.get("limitBuyStart")
    limit_end = product.get("limitBuyEnd")
    if isinstance(limit_start, (int, float)) and limit_start > 0:
        return int(limit_start)
    if isinstance(limit_end, (int, float)) and 0 < limit_end <= 1:
        return int(limit_end)
    return 1


def _headers() -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "type": settings.user_app_type,
        "platform": settings.user_app_platform,
    }
    if settings.user_app_access_token:
        headers["Authorization"] = f"Bearer {settings.user_app_access_token}"
    if settings.user_app_tenant_id:
        headers["tenant-id"] = settings.user_app_tenant_id
    if settings.user_app_version:
        headers["version"] = settings.user_app_version
    if settings.user_app_channel:
        headers["channel"] = settings.user_app_channel
    if settings.user_app_device_id:
        headers["device-id"] = settings.user_app_device_id
    if settings.user_app_spirit:
        headers["spirit"] = settings.user_app_spirit
    return headers


async def _post(path: str, payload: JsonDict | None = None) -> JsonDict:
    url = settings.user_app_base_url.rstrip("/") + path
    async with httpx.AsyncClient(timeout=settings.user_app_timeout_seconds) as client:
        response = await client.post(url, headers=_headers(), json=payload or {})
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        return data
    return {"code": None, "data": data, "msg": "unexpected response type"}


async def _load_spu_tree() -> list[JsonDict]:
    if not _has_user_app_login_config():
        return []
    data = await _post(SERVICE_SPU_LIST_PATH)
    items = data.get("data")
    return items if isinstance(items, list) else []


async def _load_default_address() -> JsonDict:
    """读取 App 地址列表中的默认地址。

    用户端下单页会优先回填已有地址；AI 对话里如果没说联系人、电话、省市区，
    这里也按同样思路用用户默认地址补齐。
    """

    if not _has_user_app_login_config():
        return {}
    data = await _post(ADDRESS_PAGE_PATH, {"pageNo": 1, "pageSize": 100})
    page_data = data.get("data") if isinstance(data.get("data"), dict) else {}
    addresses = page_data.get("list")
    if not isinstance(addresses, list) or not addresses:
        return {}
    default_address = next((item for item in addresses if item.get("isDefault") is True), None)
    if default_address is None:
        default_address = next((item for item in addresses if item.get("sort") == 0), None)
    return default_address if isinstance(default_address, dict) else addresses[0]


def _settings_default_address() -> JsonDict:
    """从 .env 读取兜底地址，字段名对齐用户端 AddressRespVO。"""

    address = {
        "nickName": settings.user_app_default_contacts,
        "phone": settings.user_app_default_phone,
        "province": settings.user_app_default_province,
        "city": settings.user_app_default_city,
        "area": settings.user_app_default_area,
        "address": settings.user_app_default_address,
        "simpleAddress": settings.user_app_default_simple_address or settings.user_app_default_address,
        "houseNumber": settings.user_app_default_house_number,
        "ideName": settings.user_app_default_ide_name,
        "provinceCode": settings.user_app_default_province_code,
        "cityCode": settings.user_app_default_city_code,
        "areaCode": settings.user_app_default_area_code,
        "lon": settings.user_app_default_lon,
        "lat": settings.user_app_default_lat,
    }
    return {key: value for key, value in address.items() if value not in (None, "")}


def _extract_parent_order_no(response: JsonDict) -> str | None:
    """从创建订单接口响应中提取订单号。

    App 侧目前按 data.parentOrderNo 读取，但不同环境的后端可能返回
    data.orderNo、data.parent_order_no，甚至直接把订单号作为 data 字符串。
    这里集中兼容，避免真实创建成功后被误判为失败。
    """

    candidate_keys = ("parentOrderNo", "parent_order_no", "orderNo", "order_no")
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
        nested_data = data.get("data")
        if isinstance(nested_data, dict):
            for key in candidate_keys:
                value = nested_data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


async def _load_default_address_with_diagnostics() -> AddressLoadResult:
    """加载默认地址，并返回脱敏诊断信息。

    诊断信息只描述状态和字段是否存在，不包含手机号、联系人、详细地址等隐私数据。
    """

    diagnostics: JsonDict = {
        "source": None,
        "address_api_code": None,
        "address_api_message": None,
        "address_count": 0,
        "env_default_configured": bool(_settings_default_address()),
    }
    env_address = _settings_default_address()

    if not _has_user_app_login_config():
        diagnostics["source"] = "env" if env_address else None
        diagnostics["address_api_message"] = "user app login config is missing"
        return AddressLoadResult(address=env_address, diagnostics=diagnostics)

    try:
        data = await _post(ADDRESS_PAGE_PATH, {"pageNo": 1, "pageSize": 100})
    except Exception as exc:
        diagnostics["source"] = "env" if env_address else None
        diagnostics["address_api_message"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return AddressLoadResult(address=env_address, diagnostics=diagnostics)

    diagnostics["address_api_code"] = data.get("code")
    diagnostics["address_api_message"] = data.get("msg")
    page_data = data.get("data") if isinstance(data.get("data"), dict) else {}
    addresses = page_data.get("list")
    if not isinstance(addresses, list) or not addresses:
        diagnostics["source"] = "env" if env_address else None
        return AddressLoadResult(address=env_address, diagnostics=diagnostics)

    diagnostics["address_count"] = len(addresses)
    default_address = next((item for item in addresses if item.get("isDefault") is True), None)
    if default_address is None:
        default_address = next((item for item in addresses if item.get("sort") == 0), None)
    if default_address is None:
        default_address = addresses[0]
    diagnostics["source"] = "address_api"
    return AddressLoadResult(
        address=default_address if isinstance(default_address, dict) else env_address,
        diagnostics=diagnostics,
    )


def _merge_default_address(order_info: JsonDict, address: JsonDict) -> JsonDict:
    if not address:
        return dict(order_info)

    merged = dict(order_info)
    field_map = {
        "contacts": "nickName",
        "phone": "phone",
        "province": "province",
        "city": "city",
        "area": "area",
        "district": "area",
        "address": "address",
        "simple_address": "simpleAddress",
        "room_number": "houseNumber",
        "ide_name": "ideName",
        "province_code": "provinceCode",
        "city_code": "cityCode",
        "area_code": "areaCode",
        "lon": "lon",
        "lat": "lat",
    }
    for target_key, source_key in field_map.items():
        if not merged.get(target_key) and address.get(source_key) not in (None, ""):
            merged[target_key] = address[source_key]
    return merged


def _service_type_matches(service_type: JsonDict, matched_product: JsonDict) -> bool:
    expected_name = SERVICE_TYPE_NAME_MAP.get(_clean_text(matched_product.get("service_order_type")))
    if not expected_name:
        return True
    return _clean_text(service_type.get("typeName")) == expected_name


def _product_name_matches(candidate_name: object, matched_name: str) -> bool:
    name = _clean_text(candidate_name)
    return bool(name and matched_name and (name == matched_name or name in matched_name or matched_name in name))


def _find_product_in_tree(spu_tree: list[JsonDict], matched_product: JsonDict) -> JsonDict | None:
    product_code = _clean_text(matched_product.get("service_product_code"))
    product_name = _clean_text(matched_product.get("service_product_name"))
    for service_type in spu_tree:
        if not _service_type_matches(service_type, matched_product):
            continue
        for first_category in service_type.get("firstCategoryList") or []:
            for second_category in first_category.get("secondCategoryList") or []:
                for product in second_category.get("serviceSpuRespAppVOList") or []:
                    if product.get("code") == product_code or _product_name_matches(product.get("name"), product_name):
                        return {
                            "service_type": service_type,
                            "first_category": first_category,
                            "second_category": second_category,
                            "product": product,
                        }
    return None


async def _load_spu_detail_list(
    first_category_id: object,
    service_type_id: object,
    order_info: JsonDict,
) -> list[JsonDict]:
    if not _has_user_app_login_config() or not first_category_id or not service_type_id:
        return []

    payload: JsonDict = {
        "firstCategoryId": first_category_id,
        "serviceSpuTypeId": service_type_id,
    }
    optional_field_map = {
        "province": "province",
        "city": "city",
        "area": "area",
        "provinceCode": "province_code",
        "cityCode": "city_code",
        "areaCode": "area_code",
    }
    for api_key, info_key in optional_field_map.items():
        value = order_info.get(info_key)
        if value:
            payload[api_key] = value

    data = await _post(SERVICE_SPU_TYPE_CATEGORY_LIST_PATH, payload)
    items = data.get("data")
    return items if isinstance(items, list) else []


def _find_product_in_detail_list(
    detail_list: list[JsonDict],
    matched_product: JsonDict,
    tree_product: JsonDict | None,
) -> JsonDict | None:
    product_code = _clean_text(matched_product.get("service_product_code"))
    product_name = _clean_text(matched_product.get("service_product_name"))
    tree_product_id = tree_product.get("id") if tree_product else None

    for second_category in detail_list:
        for product in second_category.get("itemRespVOList") or []:
            if (
                (product_code and product.get("code") == product_code)
                or (tree_product_id and product.get("id") == tree_product_id)
                or _product_name_matches(product.get("name"), product_name)
            ):
                return {
                    "second_category": second_category,
                    "product": product,
                }
    return None


async def _resolve_product_context(order_info: JsonDict, matched_product: JsonDict) -> JsonDict | None:
    try:
        tree_context = _find_product_in_tree(await _load_spu_tree(), matched_product)
    except Exception:
        tree_context = None
    if tree_context is None:
        return None

    service_type = tree_context["service_type"]
    first_category = tree_context["first_category"]
    tree_product = tree_context["product"]
    try:
        detail_list = await _load_spu_detail_list(
            first_category_id=first_category.get("firstCategoryId"),
            service_type_id=service_type.get("typeId"),
            order_info=order_info,
        )
        detail_context = _find_product_in_detail_list(detail_list, matched_product, tree_product)
    except Exception:
        detail_context = None

    if detail_context:
        return {
            **tree_context,
            "second_category": detail_context["second_category"],
            "product": detail_context["product"],
        }
    return tree_context


def _fallback_product_context(matched_product: JsonDict) -> JsonDict:
    service_type_name = SERVICE_TYPE_NAME_MAP.get(_clean_text(matched_product.get("service_order_type")), "")
    related_category = _clean_text(matched_product.get("related_category"))
    erp_code, _, erp_name = related_category.partition("-")
    category_parts = [part for part in _clean_text(matched_product.get("category")).split("/") if part]
    price = _to_price_cent(matched_product.get("price"))
    return {
        "service_type": {
            "typeId": None,
            "typeCode": "",
            "typeName": service_type_name,
        },
        "first_category": {
            "firstCategoryId": None,
            "firstCategoryCode": "",
            "firstCategoryName": category_parts[0] if category_parts else "",
        },
        "second_category": {
            "secondCategoryId": None,
            "secondCategoryCode": erp_code,
            "secondCategoryName": erp_name or (category_parts[-1] if category_parts else ""),
        },
        "product": {
            "id": None,
            "code": matched_product.get("service_product_code"),
            "name": matched_product.get("service_product_name"),
            "icon": "",
            "price": price,
            "userPrice": price,
            "discount": None,
            "calculationMethod": 1,
            "serviceMeasureUnitDO": {
                "name": matched_product.get("unit") or "个",
                "type": "0",
            },
        },
    }


async def build_real_order_payload(order_info: JsonDict, matched_product: JsonDict) -> tuple[JsonDict, list[str]]:
    address_result = await _load_default_address_with_diagnostics()
    normalized_order_info = _merge_default_address(order_info, address_result.address)

    missing: list[str] = []
    product_context = await _resolve_product_context(normalized_order_info, matched_product)

    if product_context is None:
        product_context = _fallback_product_context(matched_product)
        missing.extend(["spuTypeId", "spuCategoryId", "goodsId"])
        if not _has_user_app_login_config():
            missing.extend(["USER_APP_ACCESS_TOKEN", "USER_APP_TENANT_ID"])

    service_type = product_context["service_type"]
    first_category = product_context["first_category"]
    second_category = product_context["second_category"]
    product = product_context["product"]
    unit = product.get("serviceMeasureUnitDO") or {}
    quantity = _default_quantity(product)
    work_start_time, work_end_time = parse_expected_time_to_range(
        normalized_order_info.get("expected_start_time")
    )

    goods_item = {
        "templateCode": product.get("code") or matched_product.get("service_product_code"),
        "templateName": product.get("name") or matched_product.get("service_product_name"),
        "num": quantity,
        "unit": unit.get("name") or matched_product.get("unit") or "个",
        "templatePhoto": product.get("icon") or "",
        "serviceMeasureUnitDO": unit or None,
        "quantity": str(quantity),
        "unitType": str(unit.get("type") or "0"),
        "erpCodeId": second_category.get("secondCategoryId"),
        "erpCode": second_category.get("secondCategoryCode") or "",
        "erpName": second_category.get("secondCategoryName") or "",
        "goodsId": product.get("id"),
        "price": product.get("price") or _to_price_cent(matched_product.get("price")),
        "actualPrice": product.get("price") or _to_price_cent(matched_product.get("price")),
        "userPrice": product.get("userPrice"),
        "discount": product.get("discount"),
        "provinceCode": product.get("provinceCode"),
        "province": product.get("province"),
        "cityCode": product.get("cityCode"),
        "city": product.get("city"),
        "areaCode": product.get("areaCode"),
        "area": product.get("area"),
        "calculationMethod": product.get("calculationMethod") or 1,
        "limitBuyType": product.get("limitBuyType"),
        "limitBuyStart": product.get("limitBuyStart"),
        "limitBuyEnd": product.get("limitBuyEnd"),
        "efficiency": product.get("efficiency"),
        "stackPrice": product.get("stackPrice"),
        "isStackDiscount": product.get("isStackDiscount"),
        "discountType": 0,
    }

    category_item = {
        "sId": f"ai_group_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "spuTypeId": service_type.get("typeId"),
        "spuTypeCode": service_type.get("typeCode") or "",
        "spuTypeName": service_type.get("typeName") or SERVICE_TYPE_NAME_MAP.get(_clean_text(matched_product.get("service_order_type")), ""),
        "spuCategoryId": first_category.get("firstCategoryId"),
        "spuCategoryCode": first_category.get("firstCategoryCode") or "",
        "spuCategoryName": first_category.get("firstCategoryName") or "",
        "installationRequirement": [],
        "isArrive": GOODS_ARRIVAL_MAP.get(_clean_text(normalized_order_info.get("goods_arrival_status")), 3),
        "goodsSaveReqVOList": [goods_item],
        "fileList": "",
        "workStartTime": work_start_time,
        "workEndTime": work_end_time,
        "roomNum": _clean_text(normalized_order_info.get("room_number")),
        "remark": _clean_text(normalized_order_info.get("fault") or normalized_order_info.get("remark")),
    }

    payload = {
        "projectNo": None,
        "attributeName": None,
        "projectName": None,
        "province": _clean_text(normalized_order_info.get("province")),
        "city": _clean_text(normalized_order_info.get("city")),
        "contacts": _clean_text(normalized_order_info.get("contacts")),
        "area": _clean_text(normalized_order_info.get("district") or normalized_order_info.get("area")),
        "lon": normalized_order_info.get("lon"),
        "lat": normalized_order_info.get("lat"),
        "areaCode": _clean_text(normalized_order_info.get("area_code")),
        "provinceCode": _clean_text(normalized_order_info.get("province_code")),
        "cityCode": _clean_text(normalized_order_info.get("city_code")),
        "photo": "",
        "phone": _clean_text(normalized_order_info.get("phone")),
        "address": _clean_text(normalized_order_info.get("address")),
        "simpleAddress": _clean_text(normalized_order_info.get("simple_address") or normalized_order_info.get("address")),
        "houseNumber": _clean_text(normalized_order_info.get("room_number")),
        "ideName": _clean_text(normalized_order_info.get("ide_name")),
        "workerName": "",
        "specialReq": _clean_text(normalized_order_info.get("fault")),
        "fileList": "",
        "categorySaveReqVOS": [category_item],
    }
    payload_diagnostics = {
        "default_address": address_result.diagnostics,
    }
    if _clean_text(matched_product.get("service_order_type")) == "单次维修服务":
        payload["emergencyFlag"] = 1 if _clean_text(normalized_order_info.get("urgency")) in {"紧急", "high"} else 0
        payload["nightEmergencyPrice"] = 0

    for field in ("contacts", "phone", "province", "city", "address", "simpleAddress"):
        if not payload.get(field):
            missing.append(field)
    if not payload["categorySaveReqVOS"][0].get("workStartTime"):
        missing.append("workStartTime")

    payload["_diagnostics"] = payload_diagnostics
    return payload, sorted(set(missing))


async def submit_real_order(order_info: JsonDict, matched_product: JsonDict, submit: bool) -> ToolResult:
    payload, missing_fields = await build_real_order_payload(order_info, matched_product)
    diagnostics = payload.pop("_diagnostics", {})
    data: JsonDict = {
        "request_payload": payload,
        "missing_fields": missing_fields,
        "submit_enabled": settings.user_app_submit_enabled,
        "submitted": False,
        "parent_order_no": None,
        "diagnostics": diagnostics,
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
    if not _has_user_app_login_config():
        return error_response(
            error_code=ToolErrorCode.INVALID_INPUT,
            message="cannot submit order, USER_APP_ACCESS_TOKEN or USER_APP_TENANT_ID is not configured",
            data=data,
        )

    try:
        check_result = await _post(CHECK_DOUBLE_PATH, payload)
        data["check_double_response"] = check_result
        create_result = await _post(CREATE_ORDER_PATH, payload)
        data["create_order_response"] = create_result
        parent_order_no = _extract_parent_order_no(create_result)
        data["parent_order_no"] = parent_order_no
        data["submitted"] = create_result.get("code") == 200 and bool(parent_order_no)
    except httpx.HTTPError as exc:
        return error_response(
            error_code=ToolErrorCode.UPSTREAM_ERROR,
            message=f"user app order api request failed: {exc}",
            data=data,
        )

    if not data["submitted"]:
        create_result = data.get("create_order_response") or {}
        if isinstance(create_result, dict):
            create_code = create_result.get("code")
            create_message = create_result.get("msg") or create_result.get("message") or "no message"
            message = f"user app order api returned code={create_code}, msg={create_message}, but no order number was found"
        else:
            message = "user app order api did not return a valid order response"
        return error_response(
            error_code=ToolErrorCode.UPSTREAM_ERROR,
            message=message,
            data=data,
        )
    return success_response(data=data, message="order submitted")


@tool(args_schema=SubmitOrderInput)
async def submit_real_order_tool(order_info: JsonDict, matched_product: JsonDict, submit: bool = False) -> ToolResult:
    """按用户端 App 的下单结构构造参数，并在启用配置后调用真实下单接口。"""

    return await submit_real_order(order_info=order_info, matched_product=matched_product, submit=submit)
