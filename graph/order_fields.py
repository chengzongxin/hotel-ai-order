"""订单必填字段、预下单卡片字段与前端编辑归一化。"""

from typing import Any

DEFAULT_URGENCY = "medium"
DEFAULT_PRODUCT_QUANTITY = 1
VALID_GOODS_ARRIVAL_STATUSES = {"未到场", "已到场", "已到物流站"}
PUBLIC_AREA_KEYWORDS = (
    "公区",
    "公共区域",
    "大厅",
    "大堂",
    "接待区",
    "公区卫生间",
    "公共厕所",
    "布草间",
    "办公室",
    "洗衣房",
    "员工区",
    "走廊",
    "过道",
    "电梯",
    "电梯厅",
    "前台",
    "餐厅",
    "会议室",
    "楼梯间",
    "楼顶",
    "健身房",
    "停车场",
    "仓库",
    "设备间",
)

URGENCY_OPTIONS = [
    {"label": "普通", "value": "medium"},
    {"label": "紧急", "value": "urgent"},
    {"label": "较急", "value": "high"},
    {"label": "低优先级", "value": "low"},
]

GOODS_ARRIVAL_OPTIONS = [
    {"label": "未到场", "value": "未到场"},
    {"label": "已到场", "value": "已到场"},
    {"label": "已到物流站", "value": "已到物流站"},
]


def is_public_area_text(text: str | None) -> bool:
    if not text:
        return False
    return any(keyword in text for keyword in PUBLIC_AREA_KEYWORDS)


def normalize_goods_arrival_status(value: str | None) -> str | None:
    if not value:
        return None
    if value in VALID_GOODS_ARRIVAL_STATUSES:
        return value

    text = value.strip()
    if any(keyword in text for keyword in ("货没到", "还没到", "在路上")):
        return "未到场"
    if any(keyword in text for keyword in ("已经到了", "已到", "到了", "货到了", "到场")):
        return "已到场"
    if any(keyword in text for keyword in ("物流站", "快递站", "驿站")):
        return "已到物流站"
    return None


def get_required_order_fields(service_type: str | None, order_info: dict[str, object]) -> list[str]:
    if service_type == "托管维修":
        if order_info.get("managed_repair_scope") == "公区":
            return ["area", "product", "fault"]
        return ["area", "room_number", "product", "fault"]
    if service_type == "单次维修服务":
        return ["product", "fault", "expected_start_time"]
    if service_type == "单次安装":
        return ["product", "expected_start_time", "goods_arrival_status"]
    if service_type == "单次测量":
        return ["product", "expected_start_time"]
    return ["product", "fault"]


def _display_value(*values: object) -> object | None:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def normalize_product_quantity(value: object) -> int:
    """把卡片输入的商品数量归一化为正整数。"""

    if value in (None, ""):
        return DEFAULT_PRODUCT_QUANTITY
    try:
        quantity = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("商品数量必须是正整数") from exc
    if quantity < 1:
        raise ValueError("商品数量必须大于 0")
    return quantity


def build_order_card_fields(
    service_type: str | None,
    order_info: dict[str, object],
    order_context: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """按最终订单类型生成预下单卡片字段。"""

    context = order_context or {}
    selected_address = context.get("selected_address") if isinstance(context.get("selected_address"), dict) else {}
    contacts = _display_value(order_info.get("contacts"), order_info.get("contact_name"), context.get("contacts"))
    phone = _display_value(order_info.get("phone"), order_info.get("contact_phone"), context.get("phone"))
    remark = _display_value(order_info.get("remark"), order_info.get("fault"), "无")
    total_fee = _display_value(order_info.get("total_fee"), "¥0")
    expected_time = _display_value(order_info.get("expected_start_time"))
    product_quantity = normalize_product_quantity(order_info.get("product_quantity"))

    def field(
        key: str,
        label: str,
        value: object | None,
        *,
        required: bool = False,
        source: str = "system",
        editable: bool = True,
        input_type: str = "text",
        options: list[dict[str, str]] | None = None,
    ) -> dict[str, object]:
        return {
            "key": key,
            "label": label,
            "value": value,
            "required": required,
            "source": source,
            "editable": editable,
            "input_type": input_type,
            "options": options or [],
        }

    if service_type == "托管维修":
        area_room = _display_value(
            order_info.get("room_number"),
            order_info.get("area"),
            selected_address.get("houseNumber") if isinstance(selected_address, dict) else None,
        )
        return [
            field("area_room", "区域/房号", area_room, required=True, source="user"),
            field(
                "urgency",
                "紧急度",
                order_info.get("urgency") or DEFAULT_URGENCY,
                required=True,
                input_type="select",
                options=URGENCY_OPTIONS,
            ),
            field("remark", "备注", remark, source="user", input_type="textarea"),
            field("product_quantity", "商品数量", product_quantity, required=True, source="user", input_type="number"),
            field("contacts", "联系人", contacts, required=True),
            field("phone", "联系电话", phone, required=True),
            field("total_fee", "费用总计", total_fee, editable=False),
        ]

    common_single = [
        field("expected_time", "期望开工/完工时间", expected_time, required=True, source="user", input_type="text"),
    ]
    if service_type == "单次安装":
        common_single.append(
            field(
                "goods_arrival_status",
                "货物是否到场",
                _display_value(order_info.get("goods_arrival_status")),
                required=True,
                source="user",
                input_type="select",
                options=GOODS_ARRIVAL_OPTIONS,
            )
        )
    common_single.extend(
        [
            field("remark", "备注", remark, source="user", input_type="textarea"),
            field("product_quantity", "商品数量", product_quantity, required=True, source="user", input_type="number"),
            field("contacts", "联系人", contacts, required=True),
            field("phone", "联系电话", phone, required=True),
            field("total_fee", "费用总计", total_fee, editable=False),
        ]
    )
    return common_single


def get_missing_fields_from_card(card_fields: list[dict[str, object]]) -> list[str]:
    missing: list[str] = []
    key_map = {
        "area_room": "room_number",
        "expected_time": "expected_start_time",
        "product_quantity": "product_quantity",
        "contacts": "contacts",
        "phone": "phone",
    }
    for item in card_fields:
        if not item.get("required"):
            continue
        if item.get("value") not in (None, ""):
            continue
        missing.append(key_map.get(str(item.get("key")), str(item.get("key"))))
    return missing


def collect_missing_order_info(
    service_type: str | None,
    order_info: dict[str, object],
    order_card_fields: list[dict[str, object]] | None = None,
) -> list[str]:
    missing_info = [
        field
        for field in get_required_order_fields(service_type, order_info)
        if not order_info.get(field)
    ]
    for field in get_missing_fields_from_card(order_card_fields or []):
        if field not in missing_info:
            missing_info.append(field)
    return missing_info


def normalize_order_card_update(
    order_info: dict[str, object],
    updates: dict[str, object],
    service_type: str | None,
) -> dict[str, object]:
    """把前端可编辑卡片字段写回内部 order_info。"""

    normalized = dict(order_info)
    for key, raw_value in updates.items():
        value = str(raw_value).strip() if raw_value is not None else ""
        if key == "area_room":
            if service_type == "托管维修" and is_public_area_text(value):
                normalized["area"] = "公区"
                normalized["managed_repair_scope"] = "公区"
                normalized["room_number"] = "/"
            else:
                normalized["room_number"] = value
                if service_type == "托管维修":
                    normalized["area"] = "客房"
                    normalized["managed_repair_scope"] = "客房"
        elif key == "expected_time":
            normalized["expected_start_time"] = value
        elif key == "contacts":
            normalized["contacts"] = value
        elif key == "phone":
            normalized["phone"] = value
        elif key == "remark":
            normalized["remark"] = value
        elif key == "product_quantity":
            normalized["product_quantity"] = normalize_product_quantity(value)
        elif key == "urgency":
            urgency_alias = {
                "普通": "medium",
                "紧急": "urgent",
                "较急": "high",
                "低优先级": "low",
            }
            normalized["urgency"] = urgency_alias.get(value, value or DEFAULT_URGENCY)
        elif key == "goods_arrival_status":
            normalized_status = normalize_goods_arrival_status(value)
            normalized["goods_arrival_status"] = normalized_status or value
        elif key in {"room_number", "area", "fault", "product", "expected_start_time", "goods_arrival_status"}:
            normalized[key] = value
    return normalized
