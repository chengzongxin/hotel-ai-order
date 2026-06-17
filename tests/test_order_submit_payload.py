"""真实下单参数构造的回归测试。"""

import pytest

from schemas.user import UserContext
from tools.order_submit_common import ADMIN_API_SPU_GET, query_spu_detail
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
async def test_query_spu_detail_uses_get_by_id(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_get_admin(path, params, user):
        calls.append((path, params))
        return {
            "code": 200,
            "data": {
                "id": 1772,
                "code": "FWSP01643",
                "name": "壁纸/墙布(≤3平米小修)",
                "areaList": [
                    {
                        "managedRepairAreaId": 1545054022,
                        "managedRepairAreaName": "客房区域",
                        "managedRepairAreaParentName": "客房",
                    }
                ],
            },
        }

    monkeypatch.setattr("tools.order_submit_common.get_admin", fake_get_admin)

    result = await query_spu_detail(
        {"id": 1772, "service_product_code": "FWSP01643", "service_product_name": "壁纸/墙布(≤3平米小修)"},
        UserContext(user_id="u1", tenant_id="t1", access_token="token"),
    )

    assert calls == [(ADMIN_API_SPU_GET, {"id": 1772})]
    assert result["code"] == "FWSP01643"
    assert result["areaList"][0]["managedRepairAreaName"] == "客房区域"


@pytest.mark.asyncio
async def test_query_spu_detail_reserves_exact_code_lookup(monkeypatch):
    post_calls: list[tuple[str, dict]] = []
    get_calls: list[tuple[str, dict]] = []

    async def fake_post_admin(path, payload, user):
        post_calls.append((path, payload))
        return {
            "code": 200,
            "data": {
                "list": [
                    {"id": 9999, "code": "OTHER", "name": "其他商品"},
                    {"id": 1772, "code": "FWSP01643", "name": "壁纸/墙布(≤3平米小修)"},
                ]
            },
        }

    async def fake_get_admin(path, params, user):
        get_calls.append((path, params))
        return {"code": 200, "data": {"id": 1772, "code": "FWSP01643", "areaList": []}}

    monkeypatch.setattr("tools.order_submit_common.post_admin", fake_post_admin)
    monkeypatch.setattr("tools.order_submit_common.get_admin", fake_get_admin)

    result = await query_spu_detail(
        {"service_product_code": "FWSP01643", "service_product_name": "壁纸/墙布(≤3平米小修)"},
        UserContext(user_id="u1", tenant_id="t1", access_token="token"),
    )

    assert post_calls[0][1]["code"] == "FWSP01643"
    assert get_calls == [(ADMIN_API_SPU_GET, {"id": 1772})]
    assert result["id"] == 1772


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


@pytest.mark.asyncio
async def test_managed_order_payload_matches_second_area(trace_step):
    order_info = {
        "managed_repair_scope": "公区",
        "area": "公区",
        "second_area": "电梯",
        "room_number": "/",
        "product": "灯",
        "fault": "不亮",
    }
    matched_product = {
        "service_product_code": "B",
        "service_product_name": "灯具维修",
        "service_order_type": "托管维修",
    }
    spu = {
        "id": 2,
        "code": "B",
        "name": "灯具维修",
        "typeId": 9,
        "areaList": [
            {"managedRepairAreaParentName": "公区", "managedRepairAreaId": 21, "managedRepairAreaName": "大堂"},
            {"managedRepairAreaParentName": "公区", "managedRepairAreaId": 22, "managedRepairAreaName": "电梯"},
        ],
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
            "houseNumber": "公区",
        },
        "contacts": "联系人",
        "phone": "13800000000",
        "area_tree": [],
        "global_config": {},
        "hosting_card": {},
        "hosting_card_error": None,
        "user_profile": {},
    }

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
    trace_step("submit_managed_repair_order second area output", result=result, request_payload=payload)
    order_spu = payload["orderDetailList"][0]["orderSpuList"][0]
    assert order_spu["secondAreaId"] == 22
    assert order_spu["secondAreaName"] == "电梯"
