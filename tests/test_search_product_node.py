"""search_product_node 选中商品保留逻辑测试。"""

import pytest

from graph.order_fields import build_order_card_fields
from graph.order_fields import collect_missing_order_info

from graph.builder import (
    ask_node,
    build_missing_info_fallback_question,
    build_order_resume_question,
    is_product_change_requested,
    normalize_order_card_update,
    route_after_search_product,
    search_product_node,
    submit_node,
)
from langchain_core.messages import HumanMessage
from schemas.user import UserContext
from services.workflow_projection import build_order_preview


def test_history_derived_product_does_not_replace_selected_item_when_filling_area():
    assert is_product_change_requested(
        last_user_message="客房",
        detected_product_name="门合页",
        current_product_names={"门五金(小修)"},
    ) is False


def test_explicit_new_product_still_replaces_selected_item():
    assert is_product_change_requested(
        last_user_message="改成报修空调不制冷",
        detected_product_name="空调",
        current_product_names={"门五金(小修)"},
    ) is True


@pytest.mark.asyncio
async def test_search_product_node_skips_research_on_confirm(monkeypatch):
    calls: list[dict] = []

    def fake_invoke(args):
        calls.append(args)
        return {"status": "success", "data": {"products": [], "query": args["query"], "count": 0}}

    monkeypatch.setattr(
        "graph.builder.asyncio.to_thread",
        lambda func, args: fake_invoke(args),
    )

    result = await search_product_node(
        {
            "intent": "confirm_order",
            "products": [{"service_product_code": "FWSP01537", "service_product_name": "门锁"}],
            "selected_product_code": "FWSP01537",
            "order": {"user_confirmed": True, "items": [{"id": "item-1", "product_code": "FWSP01537", "product_name": "门锁", "service_type": "托管维修", "quantity": 1, "product_snapshot": {"service_product_code": "FWSP01537", "service_product_name": "门锁", "service_order_type": "托管维修"}}]},
        }
    )

    assert calls == []
    assert result == {"step": "search_product_node"}


@pytest.mark.asyncio
async def test_search_product_node_skips_research_when_supplementing_info_after_selection(monkeypatch):
    calls: list[dict] = []

    async def fake_to_thread(func, args):
        calls.append(args)
        return {"status": "success", "data": {"products": [], "query": args["query"], "count": 0}}

    monkeypatch.setattr("graph.builder.asyncio.to_thread", fake_to_thread)

    state = {
        "intent": "create_order",
        "products": [
            {
                "service_product_code": "DOOR_HARDWARE",
                "service_product_name": "门五金(中修)",
                "service_order_type": "单次安装",
            }
        ],
        "selected_product_code": "DOOR_HARDWARE",
        "order": {"items": [{"id": "item-1", "product_code": "DOOR_HARDWARE", "product_name": "门五金(中修)", "service_type": "单次安装", "quantity": 1, "area": "公区", "managed_repair_scope": "公区", "fault": "需要维修", "product_snapshot": {"service_product_code": "DOOR_HARDWARE", "service_product_name": "门五金(中修)", "service_order_type": "单次安装"}}]},
        "missing_info": ["second_area"],
        "order_info": {
            "area": "公区",
            "managed_repair_scope": "公区",
            "product": "消防门",
            "fault": "需要维修",
        },
        "last_user_message": "走廊",
    }

    result = await search_product_node(state)

    assert calls == []
    assert result == {"step": "search_product_node"}
    assert route_after_search_product({**state, **result}) == "coverage_node"


@pytest.mark.asyncio
async def test_fresh_product_search_has_no_selected_order_item(monkeypatch):
    tool_products = [
        {"service_product_code": "A", "service_product_name": "Top1", "service_order_type": "托管维修"},
        {"service_product_code": "B", "service_product_name": "Top2", "service_order_type": "托管维修"},
    ]

    calls = []

    async def fake_to_thread(func, arg):
        calls.append(arg)
        return {
            "status": "success",
            "data": {"products": tool_products, "query": arg["query"], "count": 2},
        }

    monkeypatch.setattr("graph.builder.asyncio.to_thread", fake_to_thread)

    result = await search_product_node(
        {
            "intent": "create_order",
                "product_request": {"product": "门锁", "fault": "打不开"},
            "last_user_message": "301 门锁打不开",
        }
    )

    assert result["order"]["items"] == []
    assert result["products"] == tool_products
    assert result["service_type"] == "托管维修"
    assert calls[0]["service_type"] == "托管维修"


def test_route_after_search_product_stops_at_product_selection():
    state = {
        "products": [{"service_product_code": "A", "service_product_name": "Top1"}],
        "selected_product_code": None,
        "product_selection_rejected": False,
    }

    assert route_after_search_product(state) == "ask_node"


def test_route_after_search_product_never_runs_coverage_without_selected_product():
    assert route_after_search_product(
        {"products": [], "order": {"items": []}, "missing_info": ["product_match"]}
    ) == "ask_node"


def test_off_topic_resume_question_uses_product_selection_phase_even_without_missing_info():
    question = build_order_resume_question(
        {
            "phase": "product_selection",
            "products": [{"service_product_code": "AC001"}],
            "order": {"items": []},
            "missing_info": [],
        }
    )

    assert question == "请在下方卡片中选择您要下单的服务商品。"


def test_off_topic_resume_question_only_confirms_complete_pre_order():
    question = build_order_resume_question(
        {
            "phase": "pre_order",
            "products": [{"service_product_code": "AC001"}],
            "order": {
                "items": [
                    {
                        "id": "item-1",
                        "product_code": "AC001",
                        "product_name": "空调维修",
                        "product_snapshot": {"service_product_code": "AC001"},
                    }
                ]
            },
            "missing_info": [],
        }
    )

    assert question == "请确认是否提交订单？"


@pytest.mark.asyncio
async def test_ask_node_handles_off_topic_before_repeating_product_recommendation(monkeypatch):
    async def fake_topic_boundary_response(state):
        return "暂时查不了实时天气。咱们继续下单，请在下方卡片中选择合适的服务商品。"

    monkeypatch.setattr(
        "graph.builder.build_topic_boundary_response",
        fake_topic_boundary_response,
    )
    result = await ask_node(
        {
            "intent": "smalltalk",
            "phase": "product_selection",
            "messages": [HumanMessage(content="今天天气怎么样？")],
            "products": [
                {
                    "service_product_code": "AC001",
                    "service_product_name": "空调维修",
                    "service_order_type": "托管维修",
                }
            ],
            "order": {"items": []},
            "missing_info": [],
            "off_topic_count": 0,
        }
    )

    assert result["messages"][0].content.startswith("暂时查不了实时天气")
    assert "选择合适的服务商品" in result["messages"][0].content
    assert result["off_topic_count"] == 1


def test_expected_start_time_missing_prompt_is_explicit():
    question = build_missing_info_fallback_question(["expected_start_time"])

    assert "还需补充：期待开工时间" in question
    assert "请问具体什么时间" in question


def test_managed_repair_missing_second_area_prompt():
    missing = collect_missing_order_info(
        "托管维修",
        {"managed_repair_scope": "公区", "area": "公区", "product": "灯", "fault": "不亮"},
    )

    assert missing == ["second_area"]
    assert build_missing_info_fallback_question(missing) == "请问具体在哪个区域？"


def test_normalize_order_card_update_maps_editable_fields():
    order_info = {"product": "门锁", "fault": "打不开"}

    updated = normalize_order_card_update(
        order_info=order_info,
        updates={
            "area_room": "301",
            "urgency": "紧急",
            "remark": "晚上不要打扰住客",
            "product_quantity": "3",
            "contacts": "李四",
            "phone": "13600000000",
        },
        service_type="托管维修",
    )

    assert updated["room_number"] == "301"
    assert updated["managed_repair_scope"] == "客房"
    assert updated["urgency"] == "urgent"
    assert updated["remark"] == "晚上不要打扰住客"
    assert updated["product_quantity"] == 3
    assert updated["contacts"] == "李四"
    assert updated["phone"] == "13600000000"


def test_order_card_includes_editable_product_quantity():
    fields = build_order_card_fields(
        service_type="单次维修服务",
        order_info={"expected_start_time": "明天上午", "product_quantity": 2},
        order_context={"contacts": "张三", "phone": "13800000000"},
    )

    quantity_field = next(field for field in fields if field["key"] == "product_quantity")
    assert quantity_field["label"] == "商品数量"
    assert quantity_field["value"] == 2
    assert quantity_field["editable"] is True
    assert quantity_field["input_type"] == "number"


def test_managed_order_card_uses_structured_second_area_options():
    fields = build_order_card_fields(
        service_type="托管维修",
        order_info={
            "managed_repair_scope": "客房",
            "area": "客房",
            "room_number": "301",
            "second_area_id": "1545054022",
            "second_area": "客房区域",
            "available_second_area_options": [
                {
                    "label": "客房区域（客房）",
                    "value": "1545054022",
                    "second_area_id": "1545054022",
                    "second_area": "客房区域",
                    "first_area": "客房",
                },
                {
                    "label": "洗衣房（公区）",
                    "value": "1545054019",
                    "second_area_id": "1545054019",
                    "second_area": "洗衣房",
                    "first_area": "公区",
                },
            ],
        },
        order_context={"contacts": "张三", "phone": "13800000000"},
    )

    second_area_field = next(field for field in fields if field["key"] == "second_area")
    assert second_area_field["input_type"] == "select"
    assert second_area_field["value"] == "1545054022"
    assert second_area_field["options"] == [
        {"label": "客房区域（客房）", "value": "1545054022"},
        {"label": "洗衣房（公区）", "value": "1545054019"},
    ]
    assert second_area_field["hint"] == "该商品可选二级区域：客房区域（客房）、洗衣房（公区）"


def test_order_preview_rebuilds_stale_second_area_text_field_from_spu_detail():
    preview = build_order_preview(
        {
            "phase": "pre_order",
            "service_type": "托管维修",
            "effective_service_type": "托管维修",
            "last_user_message": "1506 窗户关不上，有点漏风",
            "product_request": {
                "managed_repair_scope": "客房",
                "area": "客房",
                "room_number": "1506",
                "product": "窗户",
                "fault": "关不上，有点漏风",
            },
            "products": [
                {
                    "service_product_code": "WINDOW_HINGE",
                    "service_product_name": "窗户铰链(中修)",
                    "service_order_type": "托管维修",
                }
            ],
            "selected_product_code": "WINDOW_HINGE",
            "coverage_result": {
                "checked": True,
                "covered": True,
                "reason": "该商品在当前维保卡维保范围内，可下托管维修单",
                "effective_service_type": "托管维修",
                "spu_detail": {
                    "areaList": [
                        {
                            "managedRepairAreaId": 1545054022,
                            "managedRepairAreaName": "客房区域",
                            "managedRepairAreaParentName": "客房",
                        },
                        {
                            "managedRepairAreaId": 1545054019,
                            "managedRepairAreaName": "洗衣房",
                            "managedRepairAreaParentName": "公区",
                        },
                    ],
                },
            },
            "order_context": {"contacts": "张三", "phone": "13800000000"},
            "order_card_fields": [
                {
                    "key": "second_area",
                    "label": "二级区域",
                    "value": None,
                    "required": True,
                    "editable": True,
                    "input_type": "text",
                    "options": [],
                }
            ],
        }
    )

    assert preview is not None
    second_area_field = next(field for field in preview["form"]["fields"] if field["key"] == "second_area")
    assert second_area_field["input_type"] == "select"
    assert "value" not in second_area_field
    assert second_area_field["options"] == [
        {"label": "客房区域（客房）", "value": "1545054022"},
    ]


def test_normalize_order_card_update_maps_second_area_option_parent():
    updated = normalize_order_card_update(
        order_info={
            "managed_repair_scope": "客房",
            "area": "客房",
            "room_number": "301",
            "second_area": "客房区域",
            "available_second_area_options": [
                {
                    "label": "洗衣房（公区）",
                    "value": "1545054019",
                    "second_area_id": "1545054019",
                    "second_area": "洗衣房",
                    "first_area": "公区",
                }
            ],
        },
        updates={"second_area": "1545054019"},
        service_type="托管维修",
    )

    assert updated["second_area_id"] == "1545054019"
    assert updated["second_area"] == "洗衣房"
    assert updated["managed_repair_scope"] == "公区"
    assert updated["area"] == "公区"
    assert updated["room_number"] == "/"


@pytest.mark.asyncio
async def test_submit_node_keeps_pre_order_when_real_submit_disabled(monkeypatch):
    async def fake_submit_real_order(**kwargs):
        return {
            "status": "success",
            "message": "built single order payload; real submit is disabled",
            "data": {
                "request_payload": {"serviceProductCode": "A"},
                "missing_fields": [],
                "submit_enabled": False,
                "submitted": False,
                "parent_order_no": None,
            },
        }

    async def fake_emit_text_chunk(*args, **kwargs):
        return None

    monkeypatch.setattr("graph.submission.submit_real_order", fake_submit_real_order)
    monkeypatch.setattr("graph.builder.emit_text_chunk", fake_emit_text_chunk)
    monkeypatch.setattr(
        "graph.builder.user_from_runtime_config",
        lambda: UserContext(user_id="u1", tenant_id="t1", access_token="token"),
    )

    state = {
        "service_type": "单次维修服务",
        "effective_service_type": "单次维修服务",
        "order": {"expected_start_time": "明天上午", "items": [{"id": "item-1", "product_code": "A", "product_name": "门锁", "service_type": "单次维修服务", "quantity": 1, "fault": "打不开", "product_snapshot": {"service_product_code": "A", "service_product_name": "门锁", "service_order_type": "单次维修服务"}}]},
        "products": [{"service_product_code": "A", "service_product_name": "门锁", "service_order_type": "单次维修服务"}],
        "selected_product_code": "A",
        "order_card_fields": [{"key": "expected_time", "label": "期望时间", "value": "明天上午"}],
    }

    result = await submit_node(state)

    assert result["phase"] == "pre_order"
    assert result["submission"]["state"] == "disabled"
    assert result["submission"]["failure_code"] == "submit_disabled"
    assert result["order"] == state["order"]
    assert result["order_card_fields"] == state["order_card_fields"]
    assert result["missing_info"] == []
    assert "last_order" not in result


@pytest.mark.asyncio
async def test_submit_node_marks_submitted_only_after_real_success(monkeypatch):
    async def fake_submit_real_order(**kwargs):
        return {
            "status": "success",
            "message": "single order submitted",
            "data": {
                "request_payload": {
                    "serviceProductCode": "A",
                    "contacts": "默认联系人",
                    "phone": "13900001111",
                },
                "missing_fields": [],
                "submit_enabled": True,
                "submitted": True,
                "parent_order_no": "SO123",
            },
        }

    async def fake_emit_text_chunk(*args, **kwargs):
        return None

    monkeypatch.setattr("graph.submission.submit_real_order", fake_submit_real_order)
    monkeypatch.setattr("graph.builder.emit_text_chunk", fake_emit_text_chunk)
    monkeypatch.setattr(
        "graph.builder.user_from_runtime_config",
        lambda: UserContext(user_id="u1", tenant_id="t1", access_token="token"),
    )

    result = await submit_node(
        {
            "service_type": "单次维修服务",
            "effective_service_type": "单次维修服务",
            "order": {"expected_start_time": "明天上午", "items": [{"id": "item-1", "product_code": "A", "product_name": "门锁", "service_type": "单次维修服务", "quantity": 1, "fault": "打不开", "product_snapshot": {"service_product_code": "A", "service_product_name": "门锁", "service_order_type": "单次维修服务"}}]},
            "products": [{"service_product_code": "A", "service_product_name": "门锁", "service_order_type": "单次维修服务"}],
            "selected_product_code": "A",
        }
    )

    assert result["phase"] == "submitted"
    assert result["submission"]["state"] == "succeeded"
    assert result["submission"]["order_no"] == "SO123"
    assert result["last_order"]["order_no"] == "SO123"
    assert result["last_order"]["contacts"] == "默认联系人"
    assert result["last_order"]["phone"] == "13900001111"
    assert result["product_request"] == {}
    assert result["order"] == {"items": []}
    assert result["missing_info"] == []
    assert result["products"] == []
    assert result["order"] == {"items": []}
    preview = build_order_preview(result)
    assert preview is not None
    assert preview["phase"] == "submitted"
    assert preview["submission"]["state"] == "succeeded"
    assert preview["submitted_order"]["order_no"] == "SO123"


@pytest.mark.asyncio
async def test_submit_node_returns_upstream_api_error_message_verbatim(monkeypatch):
    async def fake_submit_real_order(**kwargs):
        return {
            "status": "error",
            "error_code": "UPSTREAM_ERROR",
            "message": "managed repair order api returned no order number",
            "data": {
                "request_payload": {"serviceProductCode": "A"},
                "missing_fields": [],
                "submit_enabled": True,
                "submitted": False,
                "parent_order_no": None,
                "create_response": {"code": -1, "data": None, "msg": "套餐卡已失效"},
            },
        }

    async def fake_emit_text_chunk(*args, **kwargs):
        return None

    monkeypatch.setattr("graph.submission.submit_real_order", fake_submit_real_order)
    monkeypatch.setattr("graph.builder.emit_text_chunk", fake_emit_text_chunk)
    monkeypatch.setattr(
        "graph.builder.user_from_runtime_config",
        lambda: UserContext(user_id="u1", tenant_id="t1", access_token="token"),
    )

    result = await submit_node(
        {
            "service_type": "托管维修",
            "effective_service_type": "托管维修",
            "order": {
                "items": [
                    {
                        "id": "item-1",
                        "product_code": "A",
                        "product_name": "门锁",
                        "service_type": "托管维修",
                        "quantity": 1,
                        "fault": "打不开",
                    }
                ]
            },
        }
    )

    assert result["submission"]["failure_code"] == "api_error"
    assert result["submission"]["failure_message"] == "套餐卡已失效"
    assert result["messages"][0].content == "套餐卡已失效"
