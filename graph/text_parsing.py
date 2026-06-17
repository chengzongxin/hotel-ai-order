"""文本解析：商品选择、房号、公区/客房判断等。"""

from __future__ import annotations

import re

from graph.constants import (
    CANCEL_ORDER_KEYWORDS,
    GUEST_ROOM_KEYWORDS,
    GUEST_SECOND_AREA_KEYWORDS,
    PRODUCT_NONE_SELECTIONS,
    PUBLIC_AREA_KEYWORDS,
    PUBLIC_SECOND_AREA_KEYWORDS,
)


def is_cancel_request(text: str) -> bool:
    normalized_text = text.strip().lower()
    return any(keyword in normalized_text for keyword in CANCEL_ORDER_KEYWORDS)


def parse_product_selection(text: str | None) -> int | None:
    """解析用户对 Top3 商品的选择；0 表示“以上都不符合”。"""

    if not text:
        return None
    normalized = text.strip().lower()
    if normalized in PRODUCT_NONE_SELECTIONS or "以上都不符合" in normalized:
        return 0

    mapping = {
        "第一": 1,
        "第一个": 1,
        "1": 1,
        "选1": 1,
        "选择1": 1,
        "一": 1,
        "第二": 2,
        "第二个": 2,
        "2": 2,
        "选2": 2,
        "选择2": 2,
        "二": 2,
        "第三": 3,
        "第三个": 3,
        "3": 3,
        "选3": 3,
        "选择3": 3,
        "三": 3,
    }
    if normalized in mapping:
        return mapping[normalized]
    match = re.search(r"(?:选|选择|第)?\s*([123])\s*(?:个|项)?", normalized)
    if match:
        return int(match.group(1))
    return None


def build_product_recommendation_text(products: list[dict[str, object]]) -> str:
    if products:
        return "好的，根据您的描述，为您推荐以下服务商品，请在下方卡片中选择您要下单的商品。"
    return "请先选择要下单的服务商品。"


def build_selected_product_text(selected_product: dict[str, object]) -> str:
    name = selected_product.get("service_product_name") or "该商品"
    repair_level = (
        selected_product.get("repair_category")
        or selected_product.get("product_type")
        or selected_product.get("service_order_type")
        or "待确认"
    )
    return f"好的，已为您选择【{name}（{repair_level}）】，正在生成预下单卡片。"


def is_public_area_text(text: str | None) -> bool:
    if not text:
        return False
    return any(keyword in text for keyword in PUBLIC_AREA_KEYWORDS)


def is_guest_room_text(text: str | None) -> bool:
    if not text:
        return False
    return any(keyword in text for keyword in GUEST_ROOM_KEYWORDS)


def infer_second_area(text: str | None, first_area: str | None = None) -> str | None:
    if not text:
        return None

    def match(mapping: dict[str, tuple[str, ...]]) -> str | None:
        for second_area, keywords in mapping.items():
            if any(keyword in text for keyword in keywords):
                return second_area
        return None

    if first_area == "公区":
        return match(PUBLIC_SECOND_AREA_KEYWORDS)
    if first_area == "客房":
        return match(GUEST_SECOND_AREA_KEYWORDS)
    return match(PUBLIC_SECOND_AREA_KEYWORDS) or match(GUEST_SECOND_AREA_KEYWORDS)


def extract_room_number(text: str | None) -> str | None:
    if not text:
        return None
    patterns = (
        r"([A-Za-z]栋\s*\d{2,5})",
        r"(\d{2,5})\s*(?:房间|房|号)",
        r"房间\s*(\d{2,5})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).replace(" ", "")
    return None


def format_service_type(service_type: str | None, order_info: dict[str, object]) -> str | None:
    from graph.products import format_service_type_display

    return format_service_type_display(service_type, order_info)  # type: ignore[arg-type]


def format_urgency(value: object) -> str:
    labels = {
        "low": "低优先级",
        "medium": "普通",
        "high": "较急",
        "urgent": "紧急",
    }
    return labels.get(str(value), str(value or "普通"))
