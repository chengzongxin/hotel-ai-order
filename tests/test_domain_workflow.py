import pytest

from domain.validation import missing_fields_for_order, validate_order_ready
from services.order_normalizer import normalize_order_defaults
from services.order_workflow import OrderWorkflowService
from tools.order_payload_managed import align_order_second_area_with_spu


def test_managed_repair_does_not_infer_second_area_before_product_scope():
    normalized = normalize_order_defaults(
        "托管维修",
        {"room_number": "301", "product": "空调", "fault": "不制冷"},
        "301房空调不制冷",
    )

    assert normalized["managed_repair_scope"] == "客房"
    assert normalized["area"] == "客房"
    assert "second_area" not in normalized


def test_managed_repair_infers_second_area_from_single_product_scope():
    normalized, area_match = align_order_second_area_with_spu(
        {"room_number": "1506", "product": "窗户", "fault": "关不上，有点漏风", "area": "客房", "managed_repair_scope": "客房"},
        {
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
            ]
        },
        source_text="1506 窗户关不上，有点漏风",
    )

    assert normalized["second_area"] == "客房区域"
    assert normalized["second_area_id"] == "1545054022"
    assert normalized["available_second_areas"] == ["客房区域", "洗衣房", "健身房"]
    assert [item["label"] for item in normalized["available_second_area_options"]] == [
        "客房区域（客房）",
        "洗衣房（公区）",
        "健身房（公区）",
    ]
    assert area_match["matched"] is True
    assert area_match["match_source"] == "single_option"


def test_managed_repair_matches_second_area_inside_product_scope_from_message():
    normalized = normalize_order_defaults(
        "托管维修",
        {"product": "灯", "fault": "不亮"},
        "电梯厅灯不亮",
    )

    assert normalized["managed_repair_scope"] == "公区"
    assert normalized["area"] == "公区"
    assert normalized["room_number"] == "/"

    aligned, area_match = align_order_second_area_with_spu(
        normalized,
        {
            "areaList": [
                {
                    "managedRepairAreaId": 1,
                    "managedRepairAreaName": "大堂",
                    "managedRepairAreaParentName": "公区",
                },
                {
                    "managedRepairAreaId": 2,
                    "managedRepairAreaName": "电梯",
                    "managedRepairAreaParentName": "公区",
                },
            ]
        },
        source_text="电梯厅灯不亮",
    )

    assert aligned["second_area"] == "电梯"
    assert aligned["second_area_id"] == "2"
    assert area_match["match_source"] == "source_text"


def test_validation_rules_delegate_service_required_fields():
    ready, missing = validate_order_ready(
        "单次维修服务",
        {"product": "空调", "fault": "不制冷"},
    )

    assert ready is False
    assert missing == ["expected_start_time"]
    assert missing_fields_for_order("单次测量", {"product": "窗帘"}) == ["expected_start_time"]


def test_order_workflow_service_uses_default_dependencies():
    service = OrderWorkflowService()

    update = service.match_products(
        state={
            "order_info": {"room_number": "301", "product": "门锁", "fault": "打不开"},
            "last_user_message": "301 门锁打不开",
        },
        products=[
            {
                "service_product_code": "A",
                "service_product_name": "门锁",
                "service_order_type": "托管维修",
            }
        ],
        service_type="托管维修",
    )

    assert update["phase"] == "product_selection"
    assert update["service_type"] == "托管维修"
    assert update["order_info"]["managed_repair_scope"] == "客房"


def test_order_workflow_uses_conversation_service_type_when_selecting_product():
    service = OrderWorkflowService()

    update = service.select_product_patch(
        state={
            "service_type": "单次安装",
            "order_info": {"product": "窗帘"},
        },
        selected_product={
            "service_product_code": "MEASURE",
            "service_product_name": "窗帘测量",
            "service_order_type": "单次测量",
        },
        product_code="MEASURE",
    )

    assert update["service_type"] == "单次安装"


@pytest.mark.asyncio
async def test_select_product_builds_second_area_dropdown_from_spu_detail():
    async def fake_load_order_context(user):
        return {"contacts": "张三", "phone": "13800000000"}

    async def fake_check_coverage(**kwargs):
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
                    ],
                },
            },
        }

    service = OrderWorkflowService(
        load_order_context=fake_load_order_context,
        check_hosting_product_coverage=fake_check_coverage,
    )

    update = await service.select_product(
        state={
            "service_type": "托管维修",
            "last_user_message": "1506 窗户关不上，有点漏风",
            "order_info": {
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
        },
        product_code="WINDOW_HINGE",
        user={},
    )

    second_area_field = next(field for field in update["order_card_fields"] if field["key"] == "second_area")
    assert update["order_info"]["second_area"] == "客房区域"
    assert second_area_field["input_type"] == "select"
    assert second_area_field["value"] == "1545054022"
    assert second_area_field["options"] == [
        {"label": "客房区域（客房）", "value": "1545054022"},
        {"label": "洗衣房（公区）", "value": "1545054019"},
    ]
    assert update["coverage_result"]["area_match"]["match_source"] == "single_option"
