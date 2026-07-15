"""多商品订单状态与 payload 聚合回归测试。"""

import pytest

from services.order_items import (
    add_or_merge_order_item,
    build_effective_order_info,
    build_order_item,
    get_order_items,
    strip_item_fields,
    sync_primary_item_from_order_info,
    validate_order_items,
)
from services.order_state import assert_order_state_invariants
from services.workflow_projection import build_order_preview_model
from tools.order_payload_managed import build_managed_repair_multi_payload
from tools.order_payload_single import build_single_order_multi_payload


def _product(code: str, name: str = "测试商品") -> dict:
    return {
        "service_product_code": code,
        "service_product_name": name,
        "service_order_type": "托管维修",
        "unit": "次",
        "price": "10.00",
        "category": "维修",
    }


def test_order_items_add_and_merge_quantity():
    first = build_order_item(_product("A"), {"fault": "损坏"}, quantity=2)
    items = add_or_merge_order_item([first], _product("A"), {}, 3)
    items = add_or_merge_order_item(items, _product("B", "第二件商品"), {}, 1)

    assert len(items) == 2
    assert items[0]["quantity"] == 5
    assert items[1]["product_code"] == "B"


def test_order_items_have_no_legacy_selected_product_fallback():
    state = {
        "products": [_product("A")],
        "selected_product_code": "A",
        "order_info": {"fault": "损坏"},
    }

    assert get_order_items(state) == []


def test_primary_item_is_the_only_source_for_product_fields():
    item = build_order_item(_product("A"), {"fault": "旧故障", "room_number": "1208"})
    updated = sync_primary_item_from_order_info([item], {"fault": "新故障", "room_number": "1306"})
    common = strip_item_fields({"fault": "新故障", "room_number": "1306", "contacts": "张三"})
    effective = build_effective_order_info({"order": {**common, "items": updated}})

    assert common == {"room_number": "1306", "contacts": "张三"}
    assert effective["fault"] == "新故障"
    assert effective["room_number"] == "1306"


def test_state_invariants_reject_pre_order_without_items_and_duplicate_products():
    with pytest.raises(ValueError, match="至少有一个"):
        assert_order_state_invariants({"phase": "pre_order", "order": {"items": []}})

    item = build_order_item(_product("A"), {})
    duplicate = build_order_item(_product("A"), {})
    with pytest.raises(ValueError, match="重复明细"):
        assert_order_state_invariants({"phase": "pre_order", "order": {"items": [item, duplicate]}})


def test_shared_second_area_is_not_reported_as_an_item_error():
    item = build_order_item(_product("A"), {"fault": "损坏"})

    validated, item_errors = validate_order_items(
        "托管维修",
        {"room_number": "1208", "area": "客房"},
        [item],
    )

    assert item_errors == []
    assert validated[0]["validation"] == {"valid": True, "missing_fields": []}


def test_preview_exposes_cart_and_item_capabilities():
    items = [
        build_order_item(_product("A"), {}, quantity=2),
        build_order_item(_product("B"), {}, quantity=1),
    ]
    preview = build_order_preview_model({
        "phase": "pre_order",
        "service_type": "托管维修",
        "effective_service_type": "托管维修",
        "order": {"items": items},
        "missing_info": [],
    })

    assert preview is not None
    assert sum(item.quantity for item in preview.order.items) == 3
    assert len(preview.order.items) == 2
    assert "add_item" in preview.actions
    assert "remove_item" in preview.actions
    assert "confirm_order" in preview.actions


def test_managed_multi_payload_contains_one_detail_per_item():
    spu = {
        "id": 1,
        "code": "A",
        "name": "维修商品",
        "price": 10,
        "faultPhenomenonList": [{"managedRepairFaultPhenomenonId": 1, "managedRepairFaultPhenomenonName": "损坏"}],
        "areaList": [{"managedRepairAreaId": 2, "managedRepairAreaName": "客房区域", "managedRepairAreaParentName": "客房"}],
    }
    resolved = [
        {"item": {"quantity": 2, "fault": "损坏"}, "product": _product("A"), "spu": spu},
        {"item": {"quantity": 3, "fault": "损坏"}, "product": _product("B"), "spu": {**spu, "id": 2, "code": "B"}},
    ]
    payload, _ = build_managed_repair_multi_payload(
        order_info={"room_number": "1208", "area": "客房", "fault": "损坏"},
        resolved_items=resolved,
        selected_address={"address": "测试酒店", "province": "广东", "city": "深圳", "provinceCode": "44", "cityCode": "4403", "hotelName": "测试酒店", "comboCardId": 1},
        contacts="张三",
        phone="13800000000",
        area_tree=[],
        global_config={},
    )

    assert len(payload["orderDetailList"]) == 1
    assert [item["num"] for item in payload["orderDetailList"][0]["orderSpuList"]] == [2, 3]


def test_single_multi_payload_contains_one_category_per_item():
    def resolved(code: str, quantity: int) -> dict:
        return {
            "item": {"quantity": quantity},
            "product": {**_product(code), "service_order_type": "单次安装"},
            "spu": {"id": quantity, "code": code, "name": code, "price": 10, "firstCategoryId": 1, "categoryCode": "CAT", "categoryName": "安装", "typeId": 2, "typeCode": "TYPE"},
            "category_context": {},
        }

    payload, _ = build_single_order_multi_payload(
        order_info={"room_number": "1208", "fault": "安装", "expected_start_time": "2026-07-15 10:00", "goods_arrival_status": "已到场"},
        resolved_items=[resolved("A", 2), resolved("B", 4)],
        selected_address={"address": "测试酒店", "province": "广东", "city": "深圳", "provinceCode": "44", "cityCode": "4403"},
        contacts="张三",
        phone="13800000000",
        service_type="单次安装",
    )

    assert len(payload["categorySaveReqVOS"]) == 1
    quantities = [item["num"] for item in payload["categorySaveReqVOS"][0]["goodsSaveReqVOList"]]
    assert quantities == [2, 4]
