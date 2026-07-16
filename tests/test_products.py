"""商品状态辅助函数单元测试。"""

from graph.products import (
    derive_product_section_fields,
    find_product_by_code,
)
from graph.text_parsing import build_selected_product_text


def test_find_product_by_code():
    products = [
        {"service_product_code": "A", "service_product_name": "商品A"},
        {"service_product_code": "B", "service_product_name": "商品B"},
    ]
    assert find_product_by_code(products, "B")["service_product_name"] == "商品B"
    assert find_product_by_code(products, "X") is None


def test_derive_product_section_fields_from_products():
    status, query, feedback = derive_product_section_fields(
        {
            "product_request": {"product": "门锁", "fault": "打不开"},
            "products": [
                {
                    "service_product_code": "FWSP01537",
                    "service_product_name": "门锁损坏（困客人）",
                    "service_order_type": "托管维修",
                }
            ],
            "order": {"items": [{
                "product_code": "FWSP01537",
                "product_name": "门锁损坏（困客人）",
                "service_type": "托管维修",
                "fault": "打不开",
            }]},
            "service_type": "托管维修",
        }
    )
    assert status == "success"
    assert query == "门锁损坏（困客人） 打不开"
    assert feedback and "门锁损坏" in feedback


def test_selected_product_text_does_not_repeat_inconsistent_repair_category():
    text = build_selected_product_text(
        {"service_product_name": "门五金(小修)", "repair_category": "中修"}
    )
    assert text == "好的，已为您选择【门五金(小修)】，正在生成预下单卡片。"
