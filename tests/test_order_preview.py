"""order_preview 结构单元测试。"""

from graph.products import get_selected_product, resolve_selected_code
from schemas.order_preview import build_order_preview_model, build_product_section


def test_build_product_section_from_products_list():
    products = [
        {
            "service_product_code": "FWSP01537",
            "service_product_name": "门锁损坏（困客人）",
            "service_order_type": "托管维修",
            "score": 0.6756,
            "price": "48.08",
        },
        {
            "service_product_code": "FWSP01423",
            "service_product_name": "门锁(小修)",
            "service_order_type": "托管维修",
            "score": 0.6397,
            "price": "8.02",
        },
    ]

    section = build_product_section(
        products=products,
        selected_code="FWSP01537",
        search_status="success",
        search_query="门锁 打不开",
        search_feedback="已匹配到门锁损坏（困客人）",
    )

    assert section.status == "success"
    assert section.selected_code == "FWSP01537"
    assert len(section.items) == 2
    assert section.items[0].is_selected is True
    assert section.items[1].is_selected is False


def test_build_product_section_does_not_select_top1_without_user_choice():
    products = [
        {
            "service_product_code": "FWSP01537",
            "service_product_name": "门锁损坏（困客人）",
            "service_order_type": "托管维修",
        }
    ]

    section = build_product_section(
        products=products,
        selected_code=None,
        search_status="success",
        search_query="门锁 打不开",
        search_feedback=None,
    )

    assert section.selected_code is None
    assert section.items[0].is_selected is False


def test_build_order_preview_model_marks_product_selection_phase():
    preview = build_order_preview_model(
        {
            "phase": "product_selection",
            "order_info": {"room_number": "301", "product": "门锁", "fault": "打不开"},
            "products": [
                {
                    "service_product_code": "FWSP01537",
                    "service_product_name": "门锁损坏（困客人）",
                    "service_order_type": "托管维修",
                }
            ],
            "selected_product_code": None,
            "order_card_fields": [],
            "missing_info": [],
        }
    )

    assert preview is not None
    payload = preview.model_dump(mode="json")
    assert payload["phase"] == "product_selection"
    assert payload["products"]["selected_code"] is None
    assert payload["order_card"]["fields"] == []


def test_resolve_selected_code_defaults_to_top1():
    products = [{"service_product_code": "FWSP01537", "service_product_name": "A"}]
    assert resolve_selected_code(products, None) == "FWSP01537"
    assert get_selected_product(products, None)["service_product_name"] == "A"


def test_build_order_preview_model_uses_single_products_field():
    preview = build_order_preview_model(
        {
            "service_type": "托管维修",
            "service_type_display": "托管维修（客房）",
            "phase": "pre_order",
            "order_info": {"room_number": "301", "product": "门锁", "fault": "打不开"},
            "products": [
                {
                    "service_product_code": "FWSP01537",
                    "service_product_name": "门锁损坏（困客人）",
                    "service_order_type": "托管维修",
                }
            ],
            "selected_product_code": "FWSP01537",
            "missing_info": [],
        }
    )

    assert preview is not None
    payload = preview.model_dump(mode="json")
    assert payload["products"]["items"][0]["code"] == "FWSP01537"
    assert payload["products"]["status"] == "success"
    assert payload["products"]["query"] == "门锁 打不开"
    assert "门锁损坏" in (payload["products"]["feedback"] or "")


def test_build_order_preview_model_includes_effective_service_type_and_coverage():
    preview = build_order_preview_model(
        {
            "service_type": "托管维修",
            "effective_service_type": "单次维修服务",
            "phase": "pre_order",
            "order_info": {"room_number": "301", "product": "门锁", "fault": "打不开"},
            "products": [
                {
                    "service_product_code": "FWSP01537",
                    "service_product_name": "门锁损坏（困客人）",
                    "service_order_type": "托管维修",
                }
            ],
            "selected_product_code": "FWSP01537",
            "coverage_result": {
                "checked": True,
                "covered": False,
                "reason": "该商品不在当前维保卡维保范围内，只能按单次维修下单",
                "effective_service_type": "单次维修服务",
            },
            "missing_info": ["expected_start_time"],
        }
    )

    assert preview is not None
    payload = preview.model_dump(mode="json")
    assert payload["service_type"] == "托管维修"
    assert payload["effective_service_type"] == "单次维修服务"
    assert payload["coverage"]["checked"] is True
    assert payload["coverage"]["covered"] is False
    assert payload["missing_info"] == ["expected_start_time"]


def test_build_order_preview_model_warns_for_low_confidence_products():
    preview = build_order_preview_model(
        {
            "phase": "product_selection",
            "order_info": {"room_number": "301", "product": "吹风的东西", "fault": "不冷"},
            "products": [
                {
                    "service_product_code": "A",
                    "service_product_name": "空调(小修)",
                    "service_order_type": "单次维修服务",
                    "score": 0.38,
                }
            ],
            "selected_product_code": None,
        }
    )

    assert preview is not None
    payload = preview.model_dump(mode="json")
    assert payload["products"]["selected_code"] is None
    assert "置信度偏低" in payload["products"]["feedback"]


def test_build_order_preview_model_warns_for_ambiguous_products():
    preview = build_order_preview_model(
        {
            "phase": "product_selection",
            "order_info": {"room_number": "301", "product": "门锁", "fault": "打不开"},
            "products": [
                {
                    "service_product_code": "A",
                    "service_product_name": "门锁(小修)",
                    "service_order_type": "托管维修",
                    "score": 0.61,
                },
                {
                    "service_product_code": "B",
                    "service_product_name": "门锁损坏（困客人）",
                    "service_order_type": "托管维修",
                    "score": 0.58,
                },
            ],
            "selected_product_code": None,
        }
    )

    assert preview is not None
    payload = preview.model_dump(mode="json")
    assert "多个相近" in payload["products"]["feedback"]


def test_build_order_preview_model_ignores_last_order_outside_submitted_phase():
    preview = build_order_preview_model(
        {
            "phase": "idle",
            "order_info": {},
            "products": [],
            "submitted_order": {"order_no": "SO123"},
            "last_order": {"order_no": "SO123"},
        }
    )

    assert preview is None


def test_build_order_preview_model_keeps_last_order_for_submitted_phase():
    preview = build_order_preview_model(
        {
            "phase": "submitted",
            "order_info": {},
            "products": [],
            "last_order": {"order_no": "SO123"},
        }
    )

    assert preview is not None
    payload = preview.model_dump(mode="json")
    assert payload["phase"] == "submitted"
    assert payload["submitted_order"]["order_no"] == "SO123"
