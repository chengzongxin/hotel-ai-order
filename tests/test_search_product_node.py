"""search_product_node 选中商品保留逻辑测试。"""

import pytest

from graph.order_fields import build_order_card_fields

from graph.builder import (
    build_order_preview,
    build_missing_info_fallback_question,
    normalize_order_card_update,
    route_after_search_product,
    search_product_node,
    submit_node,
)
from schemas.user import UserContext


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
            "order_info": {"user_confirmed": True},
        }
    )

    assert calls == []
    assert result == {"step": "search_product_node"}


@pytest.mark.asyncio
async def test_search_product_node_preserves_selected_code(monkeypatch):
    tool_products = [
        {"service_product_code": "A", "service_product_name": "Top1", "service_order_type": "托管维修"},
        {"service_product_code": "B", "service_product_name": "Top2", "service_order_type": "托管维修"},
    ]

    async def fake_to_thread(func, arg):
        return {
            "status": "success",
            "data": {"products": tool_products, "query": arg["query"], "count": 2},
        }

    monkeypatch.setattr("graph.builder.asyncio.to_thread", fake_to_thread)

    result = await search_product_node(
        {
            "intent": "create_order",
            "order_info": {"product": "门锁", "fault": "打不开"},
            "last_user_message": "301 门锁打不开",
            "selected_product_code": "B",
        }
    )

    assert result["selected_product_code"] == "B"
    assert result["products"] == tool_products


def test_route_after_search_product_stops_at_product_selection():
    state = {
        "products": [{"service_product_code": "A", "service_product_name": "Top1"}],
        "selected_product_code": None,
        "product_selection_rejected": False,
    }

    assert route_after_search_product(state) == "ask_node"


def test_expected_start_time_missing_prompt_is_explicit():
    question = build_missing_info_fallback_question(["expected_start_time"])

    assert "还需补充：期待开工时间" in question
    assert "请问具体什么时间" in question


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

    async def fake_emit_token_text(*args, **kwargs):
        return None

    monkeypatch.setattr("graph.submission.submit_real_order", fake_submit_real_order)
    monkeypatch.setattr("graph.builder.emit_token_text", fake_emit_token_text)
    monkeypatch.setattr(
        "graph.builder.user_from_runtime_config",
        lambda: UserContext(user_id="u1", tenant_id="t1", access_token="token"),
    )

    state = {
        "service_type": "单次维修服务",
        "effective_service_type": "单次维修服务",
        "order_submit_route": "single_repair",
        "order_info": {"product": "门锁", "fault": "打不开", "expected_start_time": "明天上午"},
        "products": [{"service_product_code": "A", "service_product_name": "门锁", "service_order_type": "单次维修服务"}],
        "selected_product_code": "A",
        "order_card_fields": [{"key": "expected_time", "label": "期望时间", "value": "明天上午"}],
    }

    result = await submit_node(state)

    assert result["phase"] == "pre_order"
    assert result["submission"]["state"] == "disabled"
    assert result["submission"]["failure_code"] == "submit_disabled"
    assert result["order_info"] == state["order_info"]
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

    async def fake_emit_token_text(*args, **kwargs):
        return None

    monkeypatch.setattr("graph.submission.submit_real_order", fake_submit_real_order)
    monkeypatch.setattr("graph.builder.emit_token_text", fake_emit_token_text)
    monkeypatch.setattr(
        "graph.builder.user_from_runtime_config",
        lambda: UserContext(user_id="u1", tenant_id="t1", access_token="token"),
    )

    result = await submit_node(
        {
            "service_type": "单次维修服务",
            "effective_service_type": "单次维修服务",
            "order_info": {"product": "门锁", "fault": "打不开", "expected_start_time": "明天上午"},
            "products": [{"service_product_code": "A", "service_product_name": "门锁", "service_order_type": "单次维修服务"}],
            "selected_product_code": "A",
        }
    )

    assert result["phase"] == "submitted"
    assert result["submission"]["state"] == "succeeded"
    assert result["submission"]["order_no"] == "SO123"
    assert result["last_order"]["order_no"] == "SO123"
    assert result["submitted_order"]["order_no"] == "SO123"
    assert result["submitted_order"]["contacts"] == "默认联系人"
    assert result["submitted_order"]["phone"] == "13900001111"
    assert result["order_info"] == {}
    assert result["missing_info"] == []
    assert result["products"] == []
    assert result["selected_product_code"] is None
    preview = build_order_preview(result)
    assert preview is not None
    assert preview["phase"] == "submitted"
    assert preview["submission"]["state"] == "succeeded"
    assert preview["submitted_order"]["order_no"] == "SO123"
