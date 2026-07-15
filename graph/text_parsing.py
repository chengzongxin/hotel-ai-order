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


DEFAULT_SERVICE_TYPE = "托管维修"
VALID_SERVICE_TYPES = {"托管维修", "单次维修服务", "单次安装", "单次测量"}

# 单字“安”“量”也属于业务口语，但先屏蔽常见非动作词，避免把“安排明天”或
# “数量两个”误判成安装、测量订单。
_INSTALL_NON_ACTION_WORDS = (
    "安排",
    "安全",
    "安静",
    "安心",
    "安保",
    "安防",
    "安稳",
    "安置",
    "安慰",
    "安顿",
    "西安",
    "公安",
    "保安",
    "治安",
    "安检",
)
_MEASURE_NON_ACTION_WORDS = (
    "数量",
    "重量",
    "质量",
    "流量",
    "用量",
    "容量",
    "电量",
    "含量",
    "销量",
    "产量",
    "总量",
    "计量",
    "变量",
    "能量",
    "热量",
    "音量",
    "剂量",
    "量子",
)
_INSTALL_ACTION_PATTERN = re.compile(r"安装|加装|拆装|装上|装一下|安")
_MEASURE_ACTION_PATTERN = re.compile(r"测量|测尺寸|测一下|量尺|量房|量一下|量一量|量")


def _mask_non_action_words(text: str, words: tuple[str, ...]) -> str:
    """用等长空格屏蔽非动作词，保留关键词在原句中的位置。"""

    masked = text
    for word in words:
        masked = masked.replace(word, " " * len(word))
    return masked


def detect_service_type(text: str | None) -> str | None:
    """从当前用户输入识别明确服务类型；同句多类型时以最后出现的动作词为准。"""

    if not text:
        return None

    matches: list[tuple[int, str]] = []
    install_text = _mask_non_action_words(text, _INSTALL_NON_ACTION_WORDS)
    measure_text = _mask_non_action_words(text, _MEASURE_NON_ACTION_WORDS)
    matches.extend((match.start(), "单次安装") for match in _INSTALL_ACTION_PATTERN.finditer(install_text))
    matches.extend((match.start(), "单次测量") for match in _MEASURE_ACTION_PATTERN.finditer(measure_text))
    if not matches:
        return None
    return max(matches, key=lambda item: item[0])[1]


def infer_service_type(
    text: str | None,
    current_service_type: str | None = None,
) -> str:
    """明确关键词优先；补充信息沿用当前类型；新订单默认托管维修。"""

    detected = detect_service_type(text)
    if detected:
        return detected
    if current_service_type in VALID_SERVICE_TYPES:
        return current_service_type
    return DEFAULT_SERVICE_TYPE


def is_cancel_request(text: str) -> bool:
    normalized_text = text.strip().lower()
    return any(keyword in normalized_text for keyword in CANCEL_ORDER_KEYWORDS)


def parse_product_selection(text: str | None) -> int | None:
    """解析用户对候选商品的序号选择；0 表示“以上都不符合”。"""

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
        "第四": 4,
        "第四个": 4,
        "四": 4,
        "第五": 5,
        "第五个": 5,
        "五": 5,
        "第六": 6,
        "第六个": 6,
        "六": 6,
        "第七": 7,
        "第七个": 7,
        "七": 7,
        "第八": 8,
        "第八个": 8,
        "八": 8,
        "第九": 9,
        "第九个": 9,
        "九": 9,
        "第十": 10,
        "第十个": 10,
        "十": 10,
    }
    for selection in range(4, 11):
        mapping[str(selection)] = selection
        mapping[f"选{selection}"] = selection
        mapping[f"选择{selection}"] = selection
    if normalized in mapping:
        return mapping[normalized]
    match = re.fullmatch(r"(?:选|选择|第)?\s*(10|[1-9])\s*(?:个|项)?", normalized)
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
