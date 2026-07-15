"""order_preview 结构单元测试。"""

from services.workflow_projection import build_order_preview_model, build_product_options


def test_build_product_options_from_products_list():
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

    options = build_product_options(
        products=products,
        search_status="success",
        search_query="门锁 打不开",
        search_feedback="已匹配到门锁损坏（困客人）",
    )

    assert len(options) == 2
    assert options[0].code == "FWSP01537"


def test_build_product_options_do_not_add_selection_state():
    products = [
        {
            "service_product_code": "FWSP01537",
            "service_product_name": "门锁损坏（困客人）",
            "service_order_type": "托管维修",
        }
    ]

    options = build_product_options(
        products=products,
        search_status="success",
        search_query="门锁 打不开",
        search_feedback=None,
    )
    assert options[0].is_recommended is True
    assert not hasattr(options[0], "is_selected")



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
    assert payload["products"][0]["code"] == "FWSP01537"
    assert payload["form"]["fields"] == []
    assert "select_product" in payload["actions"]


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
            "order": {"items": [{"id": "item-1", "product_code": "FWSP01537", "product_name": "门锁损坏（困客人）", "service_type": "托管维修", "quantity": 1, "fault": "打不开", "room_number": "301", "area": "客房", "product_snapshot": {"service_product_code": "FWSP01537", "service_product_name": "门锁损坏（困客人）", "service_order_type": "托管维修"}}]},
            "missing_info": [],
        }
    )

    assert preview is not None
    payload = preview.model_dump(mode="json")
    assert payload["products"][0]["code"] == "FWSP01537"
    assert payload["order"]["items"][0]["code"] == "FWSP01537"


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
    assert "coverage" not in payload
    assert payload["errors"] == ["expected_start_time"]
    assert "confirm_order" not in payload["actions"]


def test_build_order_preview_model_includes_second_area_match_feedback():
    preview = build_order_preview_model(
        {
            "service_type": "托管维修",
            "effective_service_type": "托管维修",
            "phase": "pre_order",
            "order_info": {
                "room_number": "301",
                "product": "壁纸",
                "fault": "破损",
                "area": "客房",
                "managed_repair_scope": "客房",
                "second_area": "客房区域",
                "available_second_areas": ["客房区域"],
            },
            "products": [
                {
                    "service_product_code": "FWSP01643",
                    "service_product_name": "壁纸/墙布(≤3平米小修)",
                    "service_order_type": "托管维修",
                }
            ],
            "selected_product_code": "FWSP01643",
            "order": {"room_number": "301", "area": "客房", "second_area": "客房区域", "managed_repair_scope": "客房", "items": [{"id": "item-1", "product_code": "FWSP01643", "product_name": "壁纸/墙布(≤3平米小修)", "service_type": "托管维修", "quantity": 1, "fault": "破损", "product_snapshot": {"service_product_code": "FWSP01643", "service_product_name": "壁纸/墙布(≤3平米小修)", "service_order_type": "托管维修"}}]},
            "coverage_result": {
                "checked": True,
                "covered": True,
                "reason": "该商品在当前维保卡维保范围内，可下托管维修单",
                "effective_service_type": "托管维修",
                "area_match": {
                    "checked": True,
                    "matched": True,
                    "inferred_second_area": "客房区域",
                    "matched_second_area": "客房区域",
                    "matched_first_area": "客房",
                    "available_second_areas": ["客房区域"],
                },
            },
        }
    )

    assert preview is not None
    payload = preview.model_dump(mode="json")
    assert "coverage" not in payload
    assert payload["order"]["second_area"] == "客房区域"


def test_build_order_preview_model_warns_unmatched_second_area():
    preview = build_order_preview_model(
        {
            "service_type": "托管维修",
            "effective_service_type": "托管维修",
            "phase": "pre_order",
            "order_info": {
                "room_number": "301",
                "product": "壁纸",
                "fault": "破损",
                "area": "客房",
                "managed_repair_scope": "客房",
                "available_second_areas": ["客房区域"],
            },
            "products": [
                {
                    "service_product_code": "FWSP01643",
                    "service_product_name": "壁纸/墙布(≤3平米小修)",
                    "service_order_type": "托管维修",
                }
            ],
            "selected_product_code": "FWSP01643",
            "order": {"items": [{"id": "item-1", "product_code": "FWSP01643", "product_name": "壁纸/墙布(≤3平米小修)", "service_type": "托管维修", "quantity": 1, "fault": "破损", "room_number": "301", "area": "客房", "managed_repair_scope": "客房", "product_snapshot": {"service_product_code": "FWSP01643", "service_product_name": "壁纸/墙布(≤3平米小修)", "service_order_type": "托管维修"}}]},
            "coverage_result": {
                "checked": False,
                "covered": None,
                "reason": "二级区域待确认，暂不校验维保范围",
                "effective_service_type": "托管维修",
                "area_match": {
                    "checked": True,
                    "matched": False,
                    "inferred_second_area": "客房设备",
                    "matched_second_area": None,
                    "matched_first_area": None,
                    "available_second_areas": ["客房区域"],
                },
            },
            "order_card_fields": [
                {
                    "key": "second_area",
                    "label": "二级区域",
                    "value": None,
                    "required": True,
                    "source": "user",
                    "editable": True,
                    "input_type": "select",
                    "options": [{"label": "客房区域", "value": "客房区域"}],
                }
            ],
            "missing_info": ["second_area"],
        }
    )

    assert preview is not None
    payload = preview.model_dump(mode="json")
    assert payload["errors"] == ["second_area"]
    assert payload["form"]["fields"][0]["key"] == "second_area"
    assert payload["form"]["fields"][0]["options"] == [{"label": "客房区域", "value": "客房区域"}]


def test_build_order_preview_model_warns_for_low_confidence_products():
    preview = build_order_preview_model(
        {
            "phase": "product_selection",
            "product_request": {"room_number": "301", "product": "吹风的东西", "fault": "不冷"},
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
    assert payload["products"][0]["score"] == 0.38


def test_build_order_preview_model_warns_for_ambiguous_products():
    preview = build_order_preview_model(
        {
            "phase": "product_selection",
            "product_request": {"room_number": "301", "product": "门锁", "fault": "打不开"},
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
    assert [item["code"] for item in payload["products"]] == ["A", "B"]


def test_build_order_preview_model_ignores_last_order_outside_submitted_phase():
    preview = build_order_preview_model(
        {
            "phase": "idle",
            "order_info": {},
            "products": [],
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


def test_ready_preview_exposes_capabilities_without_internal_payloads():
    preview = build_order_preview_model(
        {
            "phase": "pre_order",
            "service_type": "单次维修服务",
            "order_info": {
                "room_number": "301",
                "product": "门锁",
                "fault": "打不开",
                "user_confirmed": False,
            },
            "products": [
                {
                    "service_product_code": "LOCK_REPAIR",
                    "service_product_name": "门锁维修",
                    "service_order_type": "单次维修服务",
                }
            ],
            "selected_product_code": "LOCK_REPAIR",
            "order": {"items": [{"id": "item-1", "product_code": "LOCK_REPAIR", "product_name": "门锁维修", "service_type": "单次维修服务", "quantity": 1, "fault": "打不开", "room_number": "301", "product_snapshot": {"service_product_code": "LOCK_REPAIR", "service_product_name": "门锁维修", "service_order_type": "单次维修服务"}}]},
            "order_card_fields": [
                {
                    "key": "room_number",
                    "label": "房号",
                    "value": "301",
                    "required": True,
                }
            ],
            "missing_info": [],
            "submission": {
                "state": "not_attempted",
                "request_payload": {"accessToken": "secret"},
                "response_payload": {"debug": True},
            },
        }
    )

    assert preview is not None
    payload = preview.model_dump(mode="json")
    assert payload["errors"] == []
    assert "update_order" in payload["actions"]
    assert "confirm_order" in payload["actions"]
    assert "cancel_order" in payload["actions"]
    assert "request_payload" not in payload["submission"]
    assert "response_payload" not in payload["submission"]
    assert "order_info" not in payload
    assert payload["product_request"]["product"] is None
    assert payload["order"]["user_confirmed"] is False
