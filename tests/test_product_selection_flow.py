"""商品推荐与选择流程的稳定自动化测试。

这些测试直接调用后端流程节点，不依赖前端页面、真实 LLM 或真实商品库。
重点验证业务状态是否正确变化，而不是固定 AI 自然语言文案。
"""

from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from graph.builder import (
    ask_node,
    coverage_node,
    prepare_order_context_node,
    route_after_search_product,
    search_product_node,
    validate_order_node,
)
from schemas.user import UserContext
from services.workflow_projection import build_order_preview


def product(
    code: str,
    name: str,
    service_type: str,
    *,
    repair_category: str | None = None,
    fault_phenomenon: str | None = None,
) -> dict[str, Any]:
    """构造一条最小可用的商品检索结果。"""
    return {
        "service_product_code": code,
        "service_product_name": name,
        "service_order_type": service_type,
        "repair_category": repair_category,
        "fault_phenomenon": fault_phenomenon,
    }


@pytest.mark.asyncio
async def test_prepare_and_validate_nodes_use_persisted_order_items(monkeypatch):
    selected = product("A", "空调维修", "单次维修服务")
    state = {
        "phase": "pre_order",
        "service_type": "单次维修服务",
        "effective_service_type": "单次维修服务",
        "order": {"expected_start_time": "明天上午", "items": [{
            "id": "item-1", "product_code": "A", "product_name": "空调维修",
            "service_type": "单次维修服务", "quantity": 1, "fault": "不制冷",
            "room_number": "1208", "product_snapshot": selected,
        }]},
        "order_card_fields": [],
    }

    class FakeWorkflow:
        async def prepare_pre_order(self, **kwargs):
            return {"order_context": {}, "order_card_fields": [], "missing_info": [], "phase": "pre_order"}

    async def invoke_action(**kwargs):
        return await kwargs["action"]()

    monkeypatch.setattr("graph.builder.get_order_workflow_service", lambda: FakeWorkflow())
    monkeypatch.setattr("graph.builder.run_traced_tool_call", invoke_action)
    monkeypatch.setattr("graph.builder.user_from_runtime_config", lambda: UserContext(user_id="u1"))

    prepared = await prepare_order_context_node(state)
    validated = await validate_order_node({**state, **prepared})

    assert prepared["phase"] == "pre_order"
    assert validated["order"]["items"][0]["product_code"] == "A"


async def mock_product_search(monkeypatch: pytest.MonkeyPatch, products: list[dict[str, Any]]) -> None:
    """把商品检索替换为固定结果，避免测试受真实商品库影响。"""

    async def fake_to_thread(func, args):
        return {
            "status": "success",
            "data": {
                "products": products,
                "query": args["query"],
                "count": len(products),
            },
        }

    monkeypatch.setattr("graph.builder.asyncio.to_thread", fake_to_thread)


def merge_state(state: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    return {**state, **update}


def preview(state: dict[str, Any]) -> dict[str, Any]:
    data = build_order_preview(state)
    assert data is not None
    return data


@pytest.mark.asyncio
async def test_first_turn_recommends_products_then_selects_first(monkeypatch, trace_step):
    products = [
        product("FAUCET_SMALL", "淋浴龙头/花洒(小修)", "托管维修", repair_category="小修"),
        product("FAUCET_MEDIUM", "淋浴龙头/花洒(中修)", "托管维修", repair_category="中修"),
        product("FAUCET_LARGE", "淋浴龙头/花洒(大修)", "托管维修", repair_category="大修"),
    ]
    await mock_product_search(monkeypatch, products)

    state = {
        "intent": "create_order",
        "last_user_message": "201房间淋浴龙头漏水",
        "messages": [HumanMessage(content="201房间淋浴龙头漏水")],
        "product_request": {"room_number": "201", "product": "淋浴龙头", "fault": "漏水"},
    }
    trace_step("search_product_node input: first turn", state=state, mocked_products=products)

    search_update = await search_product_node(state)
    trace_step("search_product_node output: recommendations", update=search_update)
    state = merge_state(state, search_update)
    first_preview = preview(state)
    trace_step("order_preview after recommendations", preview=first_preview)

    assert first_preview["phase"] == "product_selection"
    assert first_preview["order"]["items"] == []
    assert [item["code"] for item in first_preview["products"]] == [
        "FAUCET_SMALL",
        "FAUCET_MEDIUM",
        "FAUCET_LARGE",
    ]
    assert route_after_search_product(state) == "ask_node"

    state = merge_state(
        state,
        {
            "intent": "confirm_order",
            "last_user_message": "第一个",
            "messages": [HumanMessage(content="第一个")],
        },
    )
    trace_step("search_product_node input: select first product", state=state)
    select_update = await search_product_node(state)
    trace_step("search_product_node output: selected product", update=select_update)
    state = merge_state(state, select_update)
    selected_preview = preview(state)
    trace_step("order_preview after selection", preview=selected_preview)

    assert selected_preview["phase"] == "pre_order"
    assert selected_preview["order"]["items"][0]["code"] == "FAUCET_SMALL"
    assert state["order"]["items"][0]["product_code"] == "FAUCET_SMALL"


@pytest.mark.asyncio
async def test_reject_products_then_describe_more_and_recommend_again(monkeypatch, trace_step):
    initial_products = [
        product("AC_CLEAN", "空调(小修)", "托管维修", repair_category="小修"),
        product("AC_FLUORIDE", "空调(中修)", "托管维修", repair_category="中修"),
        product("AC_COMPRESSOR", "空调(大修)", "托管维修", repair_category="大修"),
    ]
    await mock_product_search(monkeypatch, initial_products)

    state = {
        "intent": "create_order",
        "last_user_message": "201房间空调有异响",
        "messages": [HumanMessage(content="201房间空调有异响")],
        "product_request": {"room_number": "201", "product": "空调", "fault": "异响"},
    }
    trace_step("search_product_node input: initial products", state=state, mocked_products=initial_products)
    initial_update = await search_product_node(state)
    trace_step("search_product_node output: initial products", update=initial_update)
    state = merge_state(state, initial_update)

    state = merge_state(
        state,
        {
            "intent": "confirm_order",
            "last_user_message": "0",
            "messages": [HumanMessage(content="0")],
        },
    )
    trace_step("search_product_node input: reject products", state=state)
    reject_update = await search_product_node(state)
    trace_step("search_product_node output: rejected products", update=reject_update)
    state = merge_state(state, reject_update)
    rejected_preview = preview(state)
    trace_step("order_preview after rejection", preview=rejected_preview)

    assert rejected_preview["phase"] == "collecting"
    assert rejected_preview["phase"] == "collecting"
    assert rejected_preview["products"] == []
    assert route_after_search_product(state) == "ask_node"

    async def fake_emit_token_text(*args, **kwargs):
        return None

    monkeypatch.setattr("graph.builder.emit_token_text", fake_emit_token_text)
    answer = await ask_node(state)
    trace_step("ask_node output after rejection", answer=answer)
    assert "再详细描述商品和故障现象" in answer["messages"][0].content

    refined_products = [
        product("AC_FAN_CLEAN", "空调(小修)", "托管维修", repair_category="小修", fault_phenomenon="风机清洁、轴承润滑"),
        product("AC_FOREIGN_BODY", "空调(小修)", "托管维修", repair_category="小修", fault_phenomenon="异物清除"),
        product("AC_MOTOR", "空调(中修)", "托管维修", repair_category="中修", fault_phenomenon="电机更换"),
    ]
    await mock_product_search(monkeypatch, refined_products)

    state = merge_state(
        state,
        {
            "intent": "create_order",
            "last_user_message": "就是开机后有吱吱的声音，像有什么东西卡住了",
            "messages": [HumanMessage(content="就是开机后有吱吱的声音，像有什么东西卡住了")],
            "order_info": {
                "room_number": "201",
                "product": "空调",
                "fault": "开机后有吱吱的声音，像有什么东西卡住了",
            },
        },
    )
    trace_step("search_product_node input: refined description", state=state, mocked_products=refined_products)
    refined_update = await search_product_node(state)
    trace_step("search_product_node output: refined products", update=refined_update)
    state = merge_state(state, refined_update)
    refined_preview = preview(state)
    trace_step("order_preview after refined search", preview=refined_preview)

    assert refined_preview["phase"] == "product_selection"
    assert [item["code"] for item in refined_preview["products"]] == [
        "AC_FAN_CLEAN",
        "AC_FOREIGN_BODY",
        "AC_MOTOR",
    ]


@pytest.mark.asyncio
async def test_no_product_match_asks_for_more_precise_product(monkeypatch, trace_step):
    await mock_product_search(monkeypatch, [])

    state = {
        "intent": "create_order",
        "last_user_message": "2301房间浴缸下水很慢",
        "messages": [HumanMessage(content="2301房间浴缸下水很慢")],
        "product_request": {"room_number": "2301", "product": "浴缸", "fault": "下水很慢", "area": "客房"},
    }

    search_update = await search_product_node(state)
    trace_step("search_product_node output: no product match", update=search_update)
    state = merge_state(state, search_update)
    no_match_preview = preview(state)

    assert no_match_preview["phase"] == "collecting"
    assert no_match_preview["products"] == []
    assert no_match_preview["errors"] == ["product_match"]
    assert route_after_search_product(state) == "ask_node"

    async def fake_emit_token_text(*args, **kwargs):
        return None

    monkeypatch.setattr("graph.builder.emit_token_text", fake_emit_token_text)
    answer = await ask_node(state)

    assert "商品库没检索到这个商品" in answer["messages"][0].content
    assert "精确" in answer["messages"][0].content


@pytest.mark.asyncio
async def test_managed_product_selection_keeps_hosting_coverage(monkeypatch, trace_step):
    products = [
        product("AC_MANAGED_MEDIUM", "空调(中修)", "托管维修", repair_category="中修"),
        product("AC_MANAGED_SMALL", "空调(小修)", "托管维修", repair_category="小修"),
        product("AC_MANAGED_LARGE", "空调(大修)", "托管维修", repair_category="大修"),
    ]
    await mock_product_search(monkeypatch, products)

    async def fake_check_hosting_product_coverage(**kwargs):
        return {
            "status": "success",
            "data": {
                "checked": True,
                "covered": True,
                "reason": "空调在托管范围内",
                "effective_service_type": "托管维修",
            },
        }

    monkeypatch.setattr("graph.builder.check_hosting_product_coverage", fake_check_hosting_product_coverage)
    monkeypatch.setattr(
        "graph.builder.user_from_runtime_config",
        lambda: UserContext(user_id="u1", tenant_id="t1", access_token="token"),
    )

    state = {
        "intent": "create_order",
        "last_user_message": "201房间空调不制冷",
        "messages": [HumanMessage(content="201房间空调不制冷")],
        "product_request": {"room_number": "201", "product": "空调", "fault": "不制冷"},
    }
    trace_step("search_product_node input: managed products", state=state, mocked_products=products)
    search_update = await search_product_node(state)
    trace_step("search_product_node output: managed products", update=search_update)
    state = merge_state(state, search_update)
    state = merge_state(
        state,
        {
            "intent": "confirm_order",
            "last_user_message": "第一个",
            "messages": [HumanMessage(content="第一个")],
        },
    )
    select_update = await search_product_node(state)
    trace_step("search_product_node output: managed selected product", update=select_update)
    state = merge_state(state, select_update)
    coverage_update = await coverage_node(state)
    trace_step("coverage_node output", update=coverage_update)
    state = merge_state(state, coverage_update)
    managed_preview = preview(state)
    trace_step("order_preview after coverage", preview=managed_preview)

    assert managed_preview["phase"] == "pre_order"
    assert managed_preview["service_type"] == "托管维修"
    assert managed_preview["effective_service_type"] == "托管维修"
    assert managed_preview["order"]["items"][0]["coverage"]["checked"] is True
    assert managed_preview["order"]["items"][0]["coverage"]["covered"] is True
    assert managed_preview["order"]["items"][0]["code"] == "AC_MANAGED_MEDIUM"


@pytest.mark.asyncio
async def test_coverage_node_clears_unmatched_second_area(monkeypatch, trace_step):
    products = [
        product("WALLPAPER_MANAGED", "壁纸/墙布(≤3平米小修)", "托管维修"),
    ]

    async def fake_check_hosting_product_coverage(**kwargs):
        return {
            "status": "success",
            "data": {
                "checked": False,
                "covered": None,
                "reason": "二级区域待确认，暂不校验维保范围",
                "effective_service_type": "托管维修",
                "spu_detail": {
                    "id": 1772,
                    "code": "FWSP01643",
                    "name": "壁纸/墙布(≤3平米小修)",
                    "areaList": [
                        {
                            "managedRepairAreaId": 1545054022,
                            "managedRepairAreaName": "客房区域",
                            "managedRepairAreaParentName": "客房",
                        },
                        {
                            "managedRepairAreaId": 1545054023,
                            "managedRepairAreaName": "卫生间区域",
                            "managedRepairAreaParentName": "客房",
                        },
                    ],
                },
            },
        }

    monkeypatch.setattr("graph.builder.check_hosting_product_coverage", fake_check_hosting_product_coverage)
    monkeypatch.setattr(
        "graph.builder.user_from_runtime_config",
        lambda: UserContext(user_id="u1", tenant_id="t1", access_token="token"),
    )

    state = {
        "service_type": "托管维修",
        "products": products,
        "selected_product_code": "WALLPAPER_MANAGED",
        "order": {"items": [{"id": "item-1", "product_code": "WALLPAPER_MANAGED", "product_name": "壁纸/墙布(≤3平米小修)", "service_type": "托管维修", "quantity": 1, "fault": "破损", "room_number": "201", "area": "客房", "managed_repair_scope": "客房", "product_snapshot": products[0]}]},
        "last_user_message": "201房间空调不制冷",
        "product_request": {
            "managed_repair_scope": "客房",
            "area": "客房",
            "room_number": "201",
            "second_area": "客房设备",
            "product": "壁纸",
            "fault": "破损",
        },
    }

    update = await coverage_node(state)
    trace_step("coverage_node output: unmatched second area", update=update)

    assert update["effective_service_type"] == "托管维修"
    assert "second_area" not in update["order"]
    assert update["order"]["items"][0]["coverage"]["area_match"]["matched"] is False
    assert update["order"]["available_second_areas"] == ["客房区域", "卫生间区域"]
    assert update["coverage_result"]["area_match"]["matched"] is False


@pytest.mark.asyncio
async def test_coverage_node_auto_selects_single_product_second_area(monkeypatch, trace_step):
    products = [
        product("WINDOW_HINGE", "窗户铰链(中修)", "托管维修"),
    ]

    async def fake_check_hosting_product_coverage(**kwargs):
        return {
            "status": "success",
            "data": {
                "checked": True,
                "covered": True,
                "reason": "该商品在当前维保卡维保范围内，可下托管维修单",
                "effective_service_type": "托管维修",
                "spu_detail": {
                    "id": 1772,
                    "code": "WINDOW_HINGE",
                    "name": "窗户铰链(中修)",
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
                        {
                            "managedRepairAreaId": 1545054017,
                            "managedRepairAreaName": "健身房",
                            "managedRepairAreaParentName": "公区",
                        }
                    ],
                },
            },
        }

    monkeypatch.setattr("graph.builder.check_hosting_product_coverage", fake_check_hosting_product_coverage)
    monkeypatch.setattr(
        "graph.builder.user_from_runtime_config",
        lambda: UserContext(user_id="u1", tenant_id="t1", access_token="token"),
    )

    state = {
        "service_type": "托管维修",
        "products": products,
        "selected_product_code": "WINDOW_HINGE",
        "order": {"room_number": "1506", "area": "客房", "managed_repair_scope": "客房", "items": [{"id": "item-1", "product_code": "WINDOW_HINGE", "product_name": "窗户铰链(中修)", "service_type": "托管维修", "quantity": 1, "fault": "关不上，有点漏风", "product_snapshot": products[0]}]},
        "last_user_message": "1506 窗户关不上，有点漏风",
        "order_info": {
            "managed_repair_scope": "客房",
            "area": "客房",
            "room_number": "1506",
            "product": "窗户",
            "fault": "关不上，有点漏风",
        },
    }

    update = await coverage_node(state)
    trace_step("coverage_node output: single second area", update=update)

    assert update["order"]["second_area"] == "客房区域"
    assert update["order"]["second_area_id"] == "1545054022"
    assert update["order"]["available_second_areas"] == ["客房区域", "洗衣房", "健身房"]
    assert [item["label"] for item in update["order"]["available_second_area_options"]] == [
        "客房区域（客房）",
        "洗衣房（公区）",
        "健身房（公区）",
    ]
    assert update["coverage_result"]["area_match"]["matched"] is True
    assert update["coverage_result"]["area_match"]["match_source"] == "single_option"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "order_info", "products", "expected_service_type", "expected_code"),
    [
        (
            "安装咖啡机",
            {"product": "咖啡机"},
            [
                product("COFFEE_INSTALL", "咖啡机(安装)", "单次安装"),
                product("COFFEE_INSTALL_DEBUG", "咖啡机(安装+调试)", "单次安装"),
            ],
            "单次安装",
            "COFFEE_INSTALL",
        ),
        (
            "量窗帘尺寸",
            {"product": "窗帘"},
            [
                product("CURTAIN_MEASURE", "窗帘(测量)", "单次测量"),
            ],
            "单次测量",
            "CURTAIN_MEASURE",
        ),
    ],
)
async def test_install_and_measure_flows_select_first_product(
    monkeypatch,
    trace_step,
    message,
    order_info,
    products,
    expected_service_type,
    expected_code,
):
    await mock_product_search(monkeypatch, products)

    state = {
        "intent": "create_order",
        "last_user_message": message,
        "messages": [HumanMessage(content=message)],
        "order_info": order_info,
    }
    trace_step("search_product_node input: install/measure", state=state, mocked_products=products)
    search_update = await search_product_node(state)
    trace_step("search_product_node output: install/measure products", update=search_update)
    state = merge_state(state, search_update)

    first_preview = preview(state)
    trace_step("order_preview before install/measure selection", preview=first_preview)
    assert first_preview["phase"] == "product_selection"
    assert first_preview["service_type"] == expected_service_type
    assert first_preview["order"]["items"] == []

    state = merge_state(
        state,
        {
            "intent": "confirm_order",
            "last_user_message": "第一个",
            "messages": [HumanMessage(content="第一个")],
        },
    )
    select_update = await search_product_node(state)
    trace_step("search_product_node output: install/measure selected", update=select_update)
    state = merge_state(state, select_update)
    coverage_update = await coverage_node(state)
    trace_step("coverage_node output: install/measure", update=coverage_update)
    state = merge_state(state, coverage_update)
    selected_preview = preview(state)
    trace_step("order_preview after install/measure selection", preview=selected_preview)

    assert selected_preview["phase"] == "pre_order"
    assert selected_preview["service_type"] == expected_service_type
    assert selected_preview["effective_service_type"] == expected_service_type
    assert selected_preview["order"]["items"][0]["code"] == expected_code
