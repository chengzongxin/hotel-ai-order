"""Order item helpers shared by workflow, API commands and submission."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from graph.products import get_selected_product

JsonDict = dict[str, Any]


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
        "area": order_info.get("area"),
        "second_area": order_info.get("second_area"),
        "second_area_id": order_info.get("second_area_id"),
        "product_snapshot": dict(product),
    }


def get_order_items(state: JsonDict) -> list[JsonDict]:
    items = [dict(item) for item in (state.get("order_items") or []) if isinstance(item, dict)]
    if items:
        return items
    selected = get_selected_product(
        state.get("products") or [],
        state.get("selected_product_code"),
        default_to_first=False,
    )
    return [build_order_item(selected, state.get("order_info") or {})] if selected else []


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
