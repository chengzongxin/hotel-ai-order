"""真实下单参数构造的回归测试。"""

import pytest

from schemas.user import UserContext
from tools.order_submit_managed import submit_managed_repair_order
from tools.order_submit_single import submit_single_order


@pytest.mark.asyncio
async def test_single_order_payload_uses_edited_contacts_and_phone(monkeypatch, trace_step):
    async def fake_query_category_context(**kwargs):
        return {"category_id": 10, "category_code": "CAT", "category_name": "门窗", "type_id": 20, "type_code": "TYPE"}

    async def fake_query_app_spu(**kwargs):
        return {}

    monkeypatch.setattr("tools.order_submit.query_single_order_category_context", fake_query_category_context)
    monkeypatch.setattr("tools.order_submit.query_single_order_app_spu", fake_query_app_spu)

    order_info = {
        "product": "窗把手",
        "fault": "损坏",
        "expected_start_time": "明天上午",
        "product_quantity": 4,
        "contacts": "新联系人",
        "phone": "13900001111",
    }
    matched_product = {
        "service_product_code": "A",
        "service_product_name": "塑钢窗把手(小修)",
        "service_order_type": "单次维修服务",
        "category": "门窗",
    }
    spu = {
        "id": 1,
        "code": "A",
        "name": "塑钢窗把手(小修)",
        "price": 0,
    }
    order_context = {
        "selected_address": {
            "address": "旧地址",
            "province": "广东省",
            "city": "深圳市",
            "provinceCode": "440000",
            "cityCode": "440300",
            "houseNumber": "301",
        },
        "contacts": "旧联系人",
        "phone": "13800000000",
        "hosting_card": {},
        "hosting_card_error": None,
        "user_profile": {},
        "global_config": {},
    }
    trace_step(
        "submit_single_order input",
        order_info=order_info,
        matched_product=matched_product,
        order_context=order_context,
    )

    result = await submit_single_order(
        order_info=order_info,
        matched_product=matched_product,
        spu=spu,
        order_context=order_context,
        submit=False,
        user=UserContext(user_id="u1", tenant_id="t1", access_token="token"),
        service_type="单次维修服务",
    )

    payload = result["data"]["request_payload"]
    trace_step("submit_single_order output", result=result, request_payload=payload)
    assert payload["contacts"] == "新联系人"
    assert payload["phone"] == "13900001111"
    order_goods = payload["categorySaveReqVOS"][0]["goodsSaveReqVOList"][0]
    assert order_goods["num"] == 4
    assert order_goods["quantity"] == "4"


@pytest.mark.asyncio
async def test_managed_order_payload_uses_edited_contacts_and_phone(trace_step):
    order_info = {
        "managed_repair_scope": "客房",
        "area": "客房",
        "room_number": "301",
        "product": "门锁",
        "fault": "打不开",
        "product_quantity": 2,
        "contacts": "新联系人",
        "phone": "13900001111",
    }
    matched_product = {
        "service_product_code": "B",
        "service_product_name": "门锁损坏",
        "service_order_type": "托管维修",
    }
    spu = {
        "id": 2,
        "code": "B",
        "name": "门锁损坏",
        "typeId": 9,
        "areaList": [{"managedRepairAreaParentName": "客房", "managedRepairAreaId": 11, "managedRepairAreaName": "客房"}],
        "faultPhenomenonList": [],
    }
    order_context = {
        "selected_address": {
            "address": "旧地址",
            "hotelName": "测试酒店",
            "province": "广东省",
            "city": "深圳市",
            "provinceCode": "440000",
            "cityCode": "440300",
            "comboCardId": 123,
            "houseNumber": "301",
        },
        "contacts": "旧联系人",
        "phone": "13800000000",
        "area_tree": [],
        "global_config": {},
        "hosting_card": {},
        "hosting_card_error": None,
        "user_profile": {},
    }
    trace_step(
        "submit_managed_repair_order input",
        order_info=order_info,
        matched_product=matched_product,
        order_context=order_context,
    )

    result = await submit_managed_repair_order(
        order_info=order_info,
        matched_product=matched_product,
        spu=spu,
        order_context=order_context,
        submit=False,
        user=UserContext(user_id="u1", tenant_id="t1", access_token="token"),
        service_type="托管维修",
    )

    payload = result["data"]["request_payload"]
    trace_step("submit_managed_repair_order output", result=result, request_payload=payload)
    assert payload["contacts"] == "新联系人"
    assert payload["phone"] == "13900001111"
    order_spu = payload["orderDetailList"][0]["orderSpuList"][0]
    assert order_spu["num"] == 2
