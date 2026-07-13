"""商品检索 query 构造逻辑测试。"""

from graph.products import build_product_search_query


def test_build_query_with_product_and_fault():
    query = build_product_search_query(
        {"product": "空调", "fault": "不制冷"},
        service_type="托管维修",
    )
    assert query == "空调 不制冷"


def test_build_query_adds_install_hint_without_fault():
    query = build_product_search_query(
        {"product": "洗衣机"},
        service_type="单次安装",
    )
    assert "洗衣机" in query
    assert "安装" in query


def test_build_query_keeps_install_hint_when_fault_present():
    query = build_product_search_query(
        {"product": "水龙头", "fault": "漏水"},
        service_type="单次安装",
    )
    assert query == "水龙头 漏水 安装"


def test_build_query_adds_measure_hint():
    query = build_product_search_query(
        {"product": "窗帘"},
        service_type="单次测量",
    )
    assert query == "窗帘 测量"
