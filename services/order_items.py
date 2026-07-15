"""Order item helpers shared by workflow, API commands and submission."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from domain.validation import missing_fields_for_order

JsonDict = dict[str, Any]

PRODUCT_REQUEST_KEYS = {
    "room_number", "product", "fault", "area", "second_area", "second_area_id",
    "managed_repair_scope", "available_second_areas",
    "available_second_area_options", "second_area_needs_confirmation",
}
ORDER_COMMON_KEYS = {
    "room_number", "area", "second_area", "second_area_id", "managed_repair_scope",
    "available_second_areas", "available_second_area_options", "second_area_needs_confirmation",
    "urgency", "expected_start_time", "goods_arrival_status", "contacts", "phone",
    "contact_name", "contact_phone", "remark", "special_requirement", "total_fee",
    "user_confirmed", "user_cancelled", "address", "house_number", "ide_name",
}


def build_order_item(
    product: JsonDict,
    order_info: JsonDict,
    *,
    quantity: int | None = None,
    item_id: str | None = None,
) -> JsonDict:
    resolved_quantity = quantity or order_info.get("product_quantity") or 1
    return {
        "id": item_id or str(uuid4()),
        "product_code": str(product.get("service_product_code") or product.get("code") or ""),
        "product_name": str(product.get("service_product_name") or product.get("name") or ""),
        "service_type": str(product.get("service_order_type") or product.get("service_type") or ""),
        "quantity": max(int(resolved_quantity), 1),
        "unit": product.get("unit"),
        "price": product.get("price"),
        "fault": order_info.get("fault") or product.get("fault_phenomenon"),
        "product_snapshot": dict(product),
        "coverage": {},
        "validation": {"valid": True, "missing_fields": []},
    }


def get_order_items(state: JsonDict) -> list[JsonDict]:
    order = state.get("order") if isinstance(state.get("order"), dict) else {}
    return [dict(item) for item in (order.get("items") or []) if isinstance(item, dict)]


def get_order_common(state: JsonDict) -> JsonDict:
    order = dict(state.get("order") or {})
    order.pop("items", None)
    return order


def build_order_state(common_info: JsonDict, items: list[JsonDict]) -> JsonDict:
    return {**dict(common_info), "items": [dict(item) for item in items]}


def get_primary_order_item(state: JsonDict) -> JsonDict | None:
    items = get_order_items(state)
    return items[0] if items else None


def get_primary_order_product(state: JsonDict) -> JsonDict:
    item = get_primary_order_item(state) or {}
    product = item.get("product_snapshot")
    return dict(product) if isinstance(product, dict) else {}


def build_effective_order_info(state: JsonDict) -> JsonDict:
    """Build the validation/payload view; persisted item fields win over extraction hints."""

    info = {
        **dict(state.get("product_request") or {}),
        **get_order_common(state),
    }
    item = get_primary_order_item(state)
    if not item:
        return info
    info.update({
        "product": item.get("product_name"),
        "fault": item.get("fault"),
        "product_quantity": item.get("quantity") or 1,
    })
    return {key: value for key, value in info.items() if value is not None}


def build_order_info_for_item(common_info: JsonDict, item: JsonDict) -> JsonDict:
    info = dict(common_info)
    info.update({
        "product": item.get("product_name"), "fault": item.get("fault"),
        "product_quantity": item.get("quantity") or 1,
    })
    return {key: value for key, value in info.items() if value is not None}


def strip_item_fields(order_info: JsonDict) -> JsonDict:
    return {key: value for key, value in order_info.items() if key in ORDER_COMMON_KEYS}


def extract_product_request(order_info: JsonDict) -> JsonDict:
    return {key: value for key, value in order_info.items() if key in PRODUCT_REQUEST_KEYS}


def split_order_info(order_info: JsonDict, *, keep_product_request: bool) -> JsonDict:
    return {
        "product_request": extract_product_request(order_info) if keep_product_request else {},
        "order": build_order_state(strip_item_fields(order_info), []),
    }


def sync_primary_item_from_order_info(items: list[JsonDict], order_info: JsonDict) -> list[JsonDict]:
    result = [dict(item) for item in items]
    if not result:
        return result
    primary = result[0]
    mapping = {"fault": "fault"}
    for source, target in mapping.items():
        if source in order_info:
            primary[target] = order_info.get(source)
    if "product_quantity" in order_info:
        primary["quantity"] = max(int(order_info.get("product_quantity") or 1), 1)
    return result


def validate_order_items(service_type: str | None, common_info: JsonDict, items: list[JsonDict]) -> tuple[list[JsonDict], list[str]]:
    validated: list[JsonDict] = []
    all_missing: list[str] = []
    for raw in items:
        item = dict(raw)
        missing = [
            field for field in missing_fields_for_order(service_type, build_order_info_for_item(common_info, item), [])
            if field in {"product", "fault"}
        ]
        item["validation"] = {"valid": not missing, "missing_fields": missing}
        validated.append(item)
        for field in missing:
            qualified = f"items.{item.get('id')}.{field}"
            if qualified not in all_missing:
                all_missing.append(qualified)
    return validated, all_missing


def find_order_item(items: list[JsonDict], item_id: str) -> JsonDict | None:
    return next((item for item in items if str(item.get("id")) == item_id), None)


def add_or_merge_order_item(
    items: list[JsonDict],
    product: JsonDict,
    order_info: JsonDict,
    quantity: int,
) -> list[JsonDict]:
    code = str(product.get("service_product_code") or "")
    result = [dict(item) for item in items]
    for item in result:
        if str(item.get("product_code") or "") == code:
            item["quantity"] = max(int(item.get("quantity") or 1) + quantity, 1)
            return result
    result.append(build_order_item(product, order_info, quantity=quantity))
    return result
