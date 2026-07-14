"""托管维修下单 payload 构造。"""

from __future__ import annotations

from typing import Any

from graph.text_parsing import infer_second_area
from tools.order_context import resolve_first_area, resolve_response_time
from tools.order_submit_common import JsonDict, clean_text, resolve_product_quantity


def match_fault_phenomenon(fault: str, fault_list: list[JsonDict]) -> JsonDict | None:
    if not fault_list:
        return None
    if not fault:
        return fault_list[0]
    fault_text = fault.strip()
    for item in fault_list:
        if clean_text(item.get("managedRepairFaultPhenomenonName")) == fault_text:
            return item
    for item in fault_list:
        name = clean_text(item.get("managedRepairFaultPhenomenonName"))
        if name and (fault_text in name or name in fault_text):
            return item
    return fault_list[0]


_match_fault_phenomenon = match_fault_phenomenon


def match_area_from_spu(
    area_list: list[JsonDict],
    area_scope: str,
    second_area: str = "",
    second_area_id: str = "",
) -> JsonDict:
    if not area_list:
        return {}

    scoped_items = [
        item
        for item in area_list
        if clean_text(item.get("managedRepairAreaParentName")) == area_scope
    ] or area_list

    if second_area_id:
        for item in scoped_items:
            item_id = clean_text(item.get("managedRepairAreaId"))
            if item_id and item_id == second_area_id:
                return item

    if second_area:
        for item in scoped_items:
            name = clean_text(item.get("managedRepairAreaName"))
            if name and (name == second_area or second_area in name or name in second_area):
                return item

    return scoped_items[0] if scoped_items else {}


def get_spu_area_list(spu: JsonDict | None) -> list[JsonDict]:
    if not isinstance(spu, dict):
        return []
    area_list = spu.get("areaList") or []
    return [item for item in area_list if isinstance(item, dict)] if isinstance(area_list, list) else []


def find_matching_second_area(
    area_list: list[JsonDict],
    area_scope: str = "",
    second_area: str = "",
    second_area_id: str = "",
) -> JsonDict:
    if not area_list or not (second_area or second_area_id):
        return {}
    scoped_items = [
        item
        for item in area_list
        if not area_scope or clean_text(item.get("managedRepairAreaParentName")) == area_scope
    ]
    if second_area_id:
        for item in scoped_items:
            item_id = clean_text(item.get("managedRepairAreaId"))
            if item_id and item_id == second_area_id:
                return item

    for item in scoped_items:
        name = clean_text(item.get("managedRepairAreaName"))
        if name and (name == second_area or second_area in name or name in second_area):
            return item
    return {}


def _scoped_area_items(area_list: list[JsonDict], area_scope: str = "") -> list[JsonDict]:
    scoped_items = [
        item
        for item in area_list
        if not area_scope or clean_text(item.get("managedRepairAreaParentName")) == area_scope
    ]
    if not scoped_items and area_scope:
        scoped_items = area_list
    return scoped_items


def infer_second_area_from_spu_scope(
    area_list: list[JsonDict],
    area_scope: str = "",
    source_text: str = "",
) -> tuple[JsonDict, str | None]:
    scoped_items = _scoped_area_items(area_list, area_scope)
    if not scoped_items:
        return {}, None

    text = clean_text(source_text)
    if text:
        for item in scoped_items:
            name = clean_text(item.get("managedRepairAreaName"))
            if name and name in text:
                return item, "source_text"

        inferred = infer_second_area(text, area_scope)
        if inferred:
            matched = find_matching_second_area(scoped_items, "", inferred)
            if matched:
                return matched, "source_text"

    if len(scoped_items) == 1:
        return scoped_items[0], "single_option"
    return {}, None


def list_spu_second_area_options(area_list: list[JsonDict], area_scope: str = "") -> list[str]:
    options: list[str] = []
    for item in area_list:
        if area_scope and clean_text(item.get("managedRepairAreaParentName")) != area_scope:
            continue
        name = clean_text(item.get("managedRepairAreaName"))
        if name and name not in options:
            options.append(name)
    if options or not area_scope:
        return options
    return list_spu_second_area_options(area_list)


def _second_area_option(item: JsonDict) -> JsonDict:
    second_area_id = clean_text(item.get("managedRepairAreaId"))
    second_area_name = clean_text(item.get("managedRepairAreaName"))
    first_area_name = clean_text(item.get("managedRepairAreaParentName"))
    label = second_area_name
    if first_area_name:
        label = f"{second_area_name}（{first_area_name}）"
    return {
        "label": label,
        "value": second_area_id or f"{first_area_name}|{second_area_name}",
        "second_area_id": second_area_id or None,
        "second_area": second_area_name or None,
        "first_area": first_area_name or None,
    }


def list_spu_second_area_option_details(area_list: list[JsonDict], area_scope: str = "") -> list[JsonDict]:
    scoped_items = _scoped_area_items(area_list, area_scope)

    options: list[JsonDict] = []
    seen_values: set[str] = set()
    for item in scoped_items:
        option = _second_area_option(item)
        if not option.get("second_area"):
            continue
        value = clean_text(option.get("value"))
        if value and value not in seen_values:
            options.append(option)
            seen_values.add(value)
    return options


def align_order_second_area_with_spu(
    order_info: JsonDict,
    spu: JsonDict | None,
    source_text: str = "",
) -> tuple[JsonDict, JsonDict]:
    """Infer/validate second area inside the selected product's areaList."""

    area_list = get_spu_area_list(spu)
    normalized = dict(order_info)
    area_scope = clean_text(normalized.get("managed_repair_scope") or normalized.get("area"))
    second_area = clean_text(normalized.get("second_area"))
    second_area_id = clean_text(normalized.get("second_area_id"))
    options = list_spu_second_area_options(area_list)
    option_details = list_spu_second_area_option_details(area_list)
    result: JsonDict = {
        "checked": bool(area_list),
        "matched": None,
        "inferred_second_area": second_area or None,
        "match_source": None,
        "matched_second_area": None,
        "matched_first_area": None,
        "available_second_areas": options,
        "available_second_area_options": option_details,
    }
    if not area_list:
        return normalized, result

    match_source: str | None = None
    matched_area = find_matching_second_area(area_list, area_scope, second_area, second_area_id)
    if matched_area:
        match_source = "selected" if second_area_id else "existing"
    else:
        infer_source = " ".join(
            str(value)
            for value in (
                source_text,
                normalized.get("product"),
                normalized.get("fault"),
            )
            if value
        )
        matched_area, match_source = infer_second_area_from_spu_scope(area_list, area_scope, infer_source)

    if matched_area:
        matched_second_area_id = clean_text(matched_area.get("managedRepairAreaId"))
        matched_second_area = clean_text(matched_area.get("managedRepairAreaName"))
        matched_first_area = clean_text(matched_area.get("managedRepairAreaParentName"))
        if matched_second_area_id:
            normalized["second_area_id"] = matched_second_area_id
        normalized["second_area"] = matched_second_area
        if matched_first_area:
            normalized["area"] = matched_first_area
            normalized["managed_repair_scope"] = matched_first_area
            if matched_first_area == "公区":
                normalized["room_number"] = "/"
        normalized.pop("second_area_needs_confirmation", None)
        if options:
            normalized["available_second_areas"] = options
        else:
            normalized.pop("available_second_areas", None)
        if option_details:
            normalized["available_second_area_options"] = option_details
        else:
            normalized.pop("available_second_area_options", None)
        result.update(
            {
                "matched": True,
                "matched_second_area_id": matched_second_area_id or None,
                "matched_second_area": matched_second_area or None,
                "matched_first_area": matched_first_area or None,
                "inferred_second_area": second_area or matched_second_area or None,
                "match_source": match_source,
            }
        )
        return normalized, result

    normalized.pop("second_area", None)
    normalized.pop("second_area_id", None)
    normalized["second_area_needs_confirmation"] = True
    normalized["available_second_areas"] = options
    normalized["available_second_area_options"] = option_details
    result["matched"] = False
    return normalized, result


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
    matched_fault = match_fault_phenomenon(clean_text(order_info.get("fault")), fault_list)
    spu_fault_list: list[JsonDict] = []
    if matched_fault:
        spu_fault_list = [{
            "faultPhenomenonId": matched_fault.get("managedRepairFaultPhenomenonId"),
            "faultPhenomenonName": matched_fault.get("managedRepairFaultPhenomenonName"),
            "commonRepairType": matched_fault.get("commonRepairType") or [],
        }]

    area_list = get_spu_area_list(spu)
    area_scope = clean_text(order_info.get("managed_repair_scope") or order_info.get("area"))
    second_area = clean_text(order_info.get("second_area"))
    second_area_id = clean_text(order_info.get("second_area_id"))
    room_num = clean_text(order_info.get("room_number"))
    urgency = clean_text(order_info.get("urgency"))
    emergency_flag = 1 if urgency in {"urgent", "紧急"} else 0

    matched_area = match_area_from_spu(area_list, area_scope, second_area, second_area_id) if area_scope else {}

    first_area_id, first_area_name = resolve_first_area(area_tree, area_scope)
    if first_area_id is None and area_scope:
        first_area_name = area_scope or None

    second_area_id = matched_area.get("managedRepairAreaId")
    second_area_name = clean_text(matched_area.get("managedRepairAreaName")) or None
    product_quantity = resolve_product_quantity(order_info)

    order_spu: JsonDict = {
        "spuId": spu.get("id"),
        "secondAreaId": second_area_id,
        "secondAreaName": second_area_name,
        "templateCode": clean_text(spu.get("code")),
        "templateName": clean_text(spu.get("name")),
        "templatePhoto": clean_text(spu.get("icon")),
        "num": product_quantity,
        "unit": clean_text(spu.get("measureUnitName"), "个"),
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
    hotel_address = clean_text(selected_address.get("address"))
    house_number = (
        clean_text(order_info.get("house_number"))
        or clean_text(selected_address.get("houseNumber"))
        or room_num
    )

    payload: JsonDict = {
        "contacts": contacts,
        "phone": phone,
        "ideName": clean_text(order_info.get("ide_name")) or ide_name or None,
        "lon": selected_address.get("lon"),
        "lat": selected_address.get("lat"),
        "province": clean_text(selected_address.get("province")),
        "city": clean_text(selected_address.get("city")),
        "area": clean_text(order_info.get("district")) or clean_text(selected_address.get("area")) or None,
        "provinceCode": clean_text(selected_address.get("provinceCode")) or None,
        "cityCode": clean_text(selected_address.get("cityCode")) or None,
        "areaCode": clean_text(selected_address.get("areaCode")) or None,
        "address": hotel_address,
        "hotelName": clean_text(selected_address.get("hotelName")),
        "houseNumber": house_number,
        "simpleAddress": clean_text(selected_address.get("simpleAddress")) or None,
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


def build_managed_repair_multi_payload(
    order_info: JsonDict,
    resolved_items: list[JsonDict],
    selected_address: JsonDict,
    contacts: str,
    phone: str,
    area_tree: list[JsonDict],
    global_config: JsonDict,
    ide_name: str = "",
) -> tuple[JsonDict, list[str]]:
    payload: JsonDict = {}
    details: list[JsonDict] = []
    detail_by_key: dict[tuple[Any, ...], JsonDict] = {}
    missing: list[str] = []
    for resolved in resolved_items:
        item = resolved.get("item") or {}
        item_info = {
            **order_info,
            "product_quantity": item.get("quantity") or 1,
            "fault": item.get("fault") or order_info.get("fault"),
            "area": item.get("area") or order_info.get("area"),
            "second_area": item.get("second_area") or order_info.get("second_area"),
            "second_area_id": item.get("second_area_id") or order_info.get("second_area_id"),
        }
        item_payload, item_missing = build_managed_repair_order_payload(
            order_info=item_info,
            spu=resolved.get("spu") or {},
            selected_address=selected_address,
            contacts=contacts,
            phone=phone,
            area_tree=area_tree,
            global_config=global_config,
            ide_name=ide_name,
        )
        if not payload:
            payload = item_payload
        for detail in item_payload.get("orderDetailList") or []:
            key = (
                detail.get("spuTypeId"),
                detail.get("firstAreaId"),
                detail.get("firstAreaName"),
                detail.get("roomNum"),
            )
            existing = detail_by_key.get(key)
            if existing is None:
                existing = {**detail, "orderSpuList": list(detail.get("orderSpuList") or [])}
                detail_by_key[key] = existing
                details.append(existing)
            else:
                existing["orderSpuList"].extend(detail.get("orderSpuList") or [])
        missing.extend(item_missing)
    payload["orderDetailList"] = details
    return payload, sorted(set(missing))
