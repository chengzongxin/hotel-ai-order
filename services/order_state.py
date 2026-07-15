"""Order workflow transitions and development-time state invariants."""

from __future__ import annotations

from typing import Any

from graph.constants import PHASE_CANCELLED, PHASE_PRE_ORDER, PHASE_PRODUCT_SELECTION, PHASE_SUBMITTED

JsonDict = dict[str, Any]


def reset_product_state() -> JsonDict:
    return {
        "products": [],
        "effective_service_type": None,
        "coverage_result": {},
        "order_context": {},
        "order_card_fields": [],
        "missing_info": [],
        "product_selection_rejected": False,
        "product_change_requested": False,
    }


def reset_active_order_state() -> JsonDict:
    return {
        "service_type": None,
        "effective_service_type": None,
        "coverage_result": {},
        "order_context": {},
        "order_card_fields": [],
        "product_request": {},
        "order": {"items": []},
        "products": [],
        "missing_info": [],
        "product_selection_rejected": False,
        "product_change_requested": False,
    }


def assert_order_state_invariants(state: JsonDict) -> None:
    phase = state.get("phase")
    order = state.get("order") if isinstance(state.get("order"), dict) else {}
    items = [item for item in (order.get("items") or []) if isinstance(item, dict)]
    if phase == PHASE_PRODUCT_SELECTION and items:
        raise ValueError("product_selection 阶段不能存在已选订单商品")
    if phase == PHASE_PRE_ORDER and not items:
        raise ValueError("pre_order 阶段必须至少有一个订单商品")
    if items and state.get("product_request"):
        raise ValueError("商品选择后需求字段必须迁入 order.items，不能继续保留 product_request")
    if phase in {PHASE_SUBMITTED, PHASE_CANCELLED} and items:
        raise ValueError(f"{phase} 阶段不能保留活动订单商品")

    ids = [str(item.get("id") or "") for item in items]
    codes = [str(item.get("product_code") or "") for item in items]
    if any(not value for value in ids + codes):
        raise ValueError("订单商品必须包含稳定 ID 和商品编码")
    if len(ids) != len(set(ids)):
        raise ValueError("订单商品 ID 不能重复")
    if len(codes) != len(set(codes)):
        raise ValueError("同一商品应合并数量，不能产生重复明细")
    if any(int(item.get("quantity") or 0) < 1 for item in items):
        raise ValueError("订单商品数量必须大于 0")
