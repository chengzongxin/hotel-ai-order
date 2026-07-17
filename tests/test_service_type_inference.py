from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from graph.builder import intent_node, route_after_intent
from graph.text_parsing import detect_service_type, infer_service_type, parse_product_selection


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("帮我安装洗衣机", "单次安装"),
        ("给浴室安一个浴霸", "单次安装"),
        ("把电视装上", "单次安装"),
        ("测量一下窗帘尺寸", "单次测量"),
        ("量一下窗户", "单次测量"),
        ("先测量再安装", "单次安装"),
        ("不是安装，是测量", "单次测量"),
    ],
)
def test_detect_service_type_from_action_words(text, expected):
    assert detect_service_type(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "安排明天下午维修",
        "安全门坏了",
        "数量两个",
        "水流量太小",
        "这个设备重量不对",
        "西安天气怎么样",
    ],
)
def test_detect_service_type_ignores_non_action_words(text):
    assert detect_service_type(text) is None


def test_infer_service_type_defaults_to_managed_repair():
    assert infer_service_type("空调不制冷") == "托管维修"


def test_infer_service_type_preserves_current_type_when_supplementing_info():
    assert infer_service_type("明天下午", "单次安装") == "单次安装"


def test_product_selection_only_parses_explicit_numeric_selection():
    assert parse_product_selection("0") == 0
    assert parse_product_selection("这些都不是") is None


class _FakeStructuredLlm:
    def __init__(self, result):
        self.result = result

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages, config=None):
        return self.result


def _intent_result(**overrides):
    values = {
        "intent": "create_order",
        "room_number": None,
        "product": None,
        "fault": None,
        "area": None,
        "urgency": None,
        "expected_start_time": None,
        "goods_arrival_status": None,
        "contacts": None,
        "phone": None,
        "product_quantity": None,
        "managed_repair_scope": None,
        "user_confirmed": False,
        "user_cancelled": False,
        "product_selection_rejected": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_intent_node_sets_new_repair_order_to_managed_repair(monkeypatch):
    fake_llm = _FakeStructuredLlm(
        _intent_result(product="空调", fault="不制冷")
    )
    monkeypatch.setattr("graph.builder.get_llm", lambda: fake_llm)

    update = await intent_node(
        {"messages": [HumanMessage(content="空调不制冷")], "phase": "idle"}
    )

    assert update["service_type"] == "托管维修"


@pytest.mark.asyncio
async def test_intent_node_preserves_install_type_for_followup(monkeypatch):
    fake_llm = _FakeStructuredLlm(
        _intent_result(expected_start_time="明天下午")
    )
    monkeypatch.setattr("graph.builder.get_llm", lambda: fake_llm)

    update = await intent_node(
        {
            "messages": [HumanMessage(content="明天下午")],
            "phase": "collecting",
            "service_type": "单次安装",
            "order_info": {"product": "洗衣机"},
        }
    )

    assert update["service_type"] == "单次安装"


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["5个", "5个商品"])
async def test_intent_node_updates_selected_product_quantity(monkeypatch, message):
    fake_llm = _FakeStructuredLlm(
        _intent_result(intent="smalltalk", product_quantity=5)
    )
    monkeypatch.setattr("graph.builder.get_llm", lambda: fake_llm)

    update = await intent_node(
        {
            "messages": [HumanMessage(content=message)],
            "phase": "pre_order",
            "service_type": "单次维修服务",
            "products": [{"service_product_code": "AC001"}],
            "order": {
                "expected_start_time": "明天上午",
                "items": [
                    {
                        "id": "item-1",
                        "product_code": "AC001",
                        "product_name": "空调维修",
                        "service_type": "单次维修服务",
                        "quantity": 1,
                        "fault": "不制冷",
                        "product_snapshot": {"service_product_code": "AC001"},
                    }
                ],
            },
        }
    )

    assert update["order"]["items"][0]["quantity"] == 5
    assert update["intent"] == "create_order"


@pytest.mark.asyncio
async def test_intent_node_uses_llm_rejection_for_product_candidates(monkeypatch):
    fake_llm = _FakeStructuredLlm(
        _intent_result(intent="smalltalk", product_selection_rejected=True)
    )
    monkeypatch.setattr("graph.builder.get_llm", lambda: fake_llm)

    update = await intent_node(
        {
            "messages": [HumanMessage(content="这几项都不是我想要的，换一批吧")],
            "phase": "product_selection",
            "products": [
                {
                    "service_product_code": "AC001",
                    "service_product_name": "空调维修",
                }
            ],
            "order": {"items": []},
        }
    )

    assert update["product_selection_rejected"] is True
    assert route_after_intent({**update, "products": [{"service_product_code": "AC001"}]}) == "search_product_node"


@pytest.mark.asyncio
async def test_intent_node_preserves_new_product_request_when_replacing_selected_product(monkeypatch):
    fake_llm = _FakeStructuredLlm(
        _intent_result(product="门把手", fault="坏了", area="公区", managed_repair_scope="公区")
    )
    monkeypatch.setattr("graph.builder.get_llm", lambda: fake_llm)

    update = await intent_node(
        {
            "messages": [HumanMessage(content="大堂门把手坏了")],
            "phase": "pre_order",
            "service_type": "托管维修",
            "products": [{"service_product_code": "OLD001", "service_product_name": "淋浴龙头维修"}],
            "order": {
                "items": [
                    {
                        "id": "item-1",
                        "product_code": "OLD001",
                        "product_name": "淋浴龙头维修",
                        "service_type": "托管维修",
                        "quantity": 1,
                        "fault": "漏水",
                    }
                ]
            },
        }
    )

    assert update["product_change_requested"] is True
    assert update["product_request"]["product"] == "门把手"
    assert update["product_request"]["fault"] == "坏了"


@pytest.mark.asyncio
async def test_intent_node_clears_old_products_when_service_type_changes(monkeypatch):
    fake_llm = _FakeStructuredLlm(_intent_result(product="窗帘"))
    monkeypatch.setattr("graph.builder.get_llm", lambda: fake_llm)

    update = await intent_node(
        {
            "messages": [HumanMessage(content="不是安装，是测量窗帘")],
            "phase": "pre_order",
            "service_type": "单次安装",
            "order_info": {"product": "窗帘"},
            "products": [
                {
                    "service_product_code": "INSTALL",
                    "service_product_name": "窗帘安装",
                    "service_order_type": "单次安装",
                }
            ],
            "selected_product_code": "INSTALL",
            "effective_service_type": "单次安装",
        }
    )

    assert update["service_type"] == "单次测量"
    assert update["products"] == []
    assert update["order"]["items"] == []
    assert update["effective_service_type"] is None
