"""单次安装/测量/维修下单 payload 构造与 App SPU 查询。"""

from __future__ import annotations

from graph.expected_time import parse_expected_time_to_range
from schemas.user import UserContext
from tools.order_submit_common import (
    SERVICE_SPU_CATEGORY_TYPE_LIST,
    SERVICE_SPU_TYPE_CATEGORY_LIST,
    JsonDict,
    clean_text,
    first_present,
    nested_dict,
    post_app,
    resolve_product_quantity,
)


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
    return mapping.get(clean_text(value), 3)


async def query_single_order_category_context(
    category_name: str,
    service_type: str | None,
    user: UserContext,
) -> JsonDict:
    """按 App 类目列表补齐普通订单所需的 category/type ID。"""

    if not category_name:
        return {}
    data = await post_app(SERVICE_SPU_CATEGORY_TYPE_LIST, {}, user)
    if data.get("code") != 200:
        return {}

    categories = data.get("data") or []
    if not isinstance(categories, list):
        return {}

    spu_type_name = resolve_single_order_spu_type(service_type)
    normalized_category_name = clean_text(category_name)
    matched_category: JsonDict | None = None
    for item in categories:
        if not isinstance(item, dict):
            continue
        names = [
            clean_text(item.get("erpName")),
            clean_text(item.get("name")),
            clean_text(item.get("categoryName")),
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
            if clean_text(item.get("serviceTypeName")) == spu_type_name:
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

    data = await post_app(SERVICE_SPU_TYPE_CATEGORY_LIST, payload, user)
    if data.get("code") != 200:
        return {}

    groups = data.get("data") or []
    if not isinstance(groups, list):
        return {}

    normalized_code = clean_text(product_code)
    normalized_name = clean_text(product_name)
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
                "categoryId": first_present(item.get("categoryId"), group.get("secondCategoryId")),
                "categoryCode": first_present(item.get("categoryCode"), group.get("secondCategoryCode")),
                "categoryName": first_present(item.get("categoryName"), group.get("secondCategoryName")),
            }
            item_code = clean_text(item.get("code"))
            item_name = clean_text(item.get("name"))
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
    hotel_address = clean_text(selected_address.get("address"))
    room_num = clean_text(order_info.get("room_number"))
    category = nested_dict(spu.get("category"))
    spu_type = nested_dict(spu.get("type") or spu.get("serviceSpuType"))
    unit = nested_dict(spu.get("serviceMeasureUnitDO") or spu.get("measureUnit"))

    category_id = first_present(
        spu.get("firstCategoryId"),
        spu.get("spuCategoryId"),
        category_context.get("category_id"),
        category.get("id"),
        spu.get("spuCategoryId"),
    )
    category_code = clean_text(
        first_present(
            spu.get("categoryCode"),
            spu.get("spuCategoryCode"),
            category_context.get("category_code"),
            category.get("erpCode"),
            category.get("code"),
        )
    )
    category_name = clean_text(
        first_present(
            spu.get("categoryName"),
            spu.get("spuCategoryName"),
            category_context.get("category_name"),
            category.get("erpName"),
            category.get("name"),
            matched_product.get("category"),
            matched_product.get("related_category"),
        )
    )
    type_id = first_present(
        spu.get("typeId"),
        spu.get("serviceSpuTypeId"),
        spu.get("spuTypeId"),
        spu_type.get("id"),
        category_context.get("type_id"),
    )
    type_code = clean_text(
        first_present(
            spu.get("typeCode"),
            spu.get("serviceSpuTypeCode"),
            spu.get("spuTypeCode"),
            spu_type.get("serviceTypeCode"),
            spu_type.get("code"),
            category_context.get("type_code"),
        )
    )
    unit_name = clean_text(first_present(spu.get("measureUnitName"), unit.get("name")), "个")
    unit_type = first_present(spu.get("measureUnitType"), unit.get("type"), "0")
    product_quantity = resolve_product_quantity(order_info)

    order_goods: JsonDict = {
        "goodsId": spu.get("id"),
        "goodsNo": clean_text(spu.get("code")),
        "templateCode": clean_text(spu.get("code")),
        "templateName": clean_text(spu.get("name")) or clean_text(order_info.get("product")),
        "num": product_quantity,
        "unit": unit_name,
        "templatePhoto": clean_text(spu.get("icon")),
        "unitType": str(unit_type),
        "quantity": str(product_quantity),
        "erpCodeId": first_present(spu.get("categoryId"), spu.get("erpCodeId"), category_id),
        "erpCode": clean_text(first_present(spu.get("categoryCode"), spu.get("erpCode"), category_code)),
        "erpName": clean_text(first_present(spu.get("categoryName"), spu.get("erpName"), category_name)),
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
        "remark": clean_text(order_info.get("remark") or order_info.get("fault")),
    }

    payload: JsonDict = {
        "projectNo": None,
        "attributeName": None,
        "projectName": None,
        "province": clean_text(selected_address.get("province")),
        "city": clean_text(selected_address.get("city")),
        "area": clean_text(selected_address.get("area")) or None,
        "provinceCode": clean_text(selected_address.get("provinceCode")) or None,
        "cityCode": clean_text(selected_address.get("cityCode")) or None,
        "areaCode": clean_text(selected_address.get("areaCode")) or None,
        "contacts": contacts,
        "phone": phone,
        "lon": selected_address.get("lon"),
        "lat": selected_address.get("lat"),
        "address": hotel_address,
        "simpleAddress": clean_text(selected_address.get("simpleAddress")) or None,
        "houseNumber": clean_text(order_info.get("house_number")) or clean_text(selected_address.get("houseNumber")) or room_num,
        "ideName": clean_text(order_info.get("ide_name")) or ide_name or clean_text(selected_address.get("ideName")),
        "workerName": None,
        "specialReq": clean_text(order_info.get("special_requirement") or order_info.get("remark") or order_info.get("fault")) or None,
        "fileList": "",
        "photo": "",
        "categorySaveReqVOS": [category_payload],
    }

    if service_type == "单次维修服务":
        urgency = clean_text(order_info.get("urgency"))
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


def build_single_order_multi_payload(
    order_info: JsonDict,
    resolved_items: list[JsonDict],
    selected_address: JsonDict,
    contacts: str,
    phone: str,
    service_type: str | None,
    ide_name: str = "",
) -> tuple[JsonDict, list[str]]:
    payload: JsonDict = {}
    categories: list[JsonDict] = []
    category_by_key: dict[tuple[object, ...], JsonDict] = {}
    missing: list[str] = []
    for resolved in resolved_items:
        item = resolved.get("item") or {}
        item_info = {
            **order_info,
            "room_number": item.get("room_number") or order_info.get("room_number"),
            "product_quantity": item.get("quantity") or 1,
            "fault": item.get("fault") or order_info.get("fault"),
            "area": item.get("area") or order_info.get("area"),
            "second_area": item.get("second_area") or order_info.get("second_area"),
        }
        item_payload, item_missing = build_single_order_payload(
            order_info=item_info,
            spu=resolved.get("spu") or {},
            matched_product=resolved.get("product") or {},
            category_context=resolved.get("category_context") or {},
            selected_address=selected_address,
            contacts=contacts,
            phone=phone,
            service_type=service_type,
            ide_name=ide_name,
        )
        if not payload:
            payload = item_payload
        for category in item_payload.get("categorySaveReqVOS") or []:
            key = (
                category.get("spuTypeId"),
                category.get("spuCategoryId"),
                category.get("workStartTime"),
                category.get("workEndTime"),
                category.get("roomNum"),
                category.get("isArrive"),
            )
            existing = category_by_key.get(key)
            if existing is None:
                existing = {
                    **category,
                    "sId": f"ai_order_group_{len(categories) + 1}",
                    "goodsSaveReqVOList": list(category.get("goodsSaveReqVOList") or []),
                }
                category_by_key[key] = existing
                categories.append(existing)
            else:
                existing["goodsSaveReqVOList"].extend(category.get("goodsSaveReqVOList") or [])
        missing.extend(item_missing)
    payload["categorySaveReqVOS"] = categories
    return payload, sorted(set(missing))
