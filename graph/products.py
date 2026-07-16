from typing import Any

VALID_MANAGED_REPAIR_SCOPES = {"客房", "公区"}
LOW_CONFIDENCE_SCORE = 0.45
AMBIGUOUS_SCORE_DELTA = 0.05


def find_product_by_code(
    products: list[dict[str, Any]],
    product_code: str,
) -> dict[str, Any] | None:
    normalized_code = product_code.strip()
    if not normalized_code:
        return None
    for product in products:
        if str(product.get("service_product_code") or "").strip() == normalized_code:
            return product
    return None


def format_service_type_display(
    service_type: str | None,
    order_info: dict[str, Any],
) -> str | None:
    if service_type != "托管维修":
        return service_type
    scope = order_info.get("managed_repair_scope")
    if scope in VALID_MANAGED_REPAIR_SCOPES:
        return f"托管维修（{scope}）"
    return service_type


def build_product_search_query(
    order_info: dict[str, Any],
    service_type: str | None = None,
) -> str:
    product = order_info.get("product")
    fault = order_info.get("fault")
    service_hint = {
        "单次安装": "安装",
        "单次测量": "测量",
    }.get(service_type or "")
    return " ".join(
        str(value)
        for value in [product, fault, service_hint]
        if value
    )


def infer_product_search_status(
    products: list[dict[str, Any]],
    search_query: str,
) -> str:
    if products:
        return "success"
    if not search_query:
        return "skipped"
    return "no_match"


def build_product_search_feedback(
    order_info: dict[str, Any],
    selected_product: dict[str, Any],
    service_type: str | None,
    coverage_result: dict[str, Any] | None = None,
) -> str | None:
    product_name = selected_product.get("service_product_name")
    if not product_name:
        return None

    described_issue = order_info.get("fault") or order_info.get("product") or "需求"
    service_type_text = format_service_type_display(service_type, order_info) or "待确认"
    feedback = (
        f"根据您描述的【{described_issue}】，已为您匹配到【{product_name}】，"
        f"服务类型为【{service_type_text}】。"
    )
    area_feedback = build_second_area_match_feedback(order_info, coverage_result or {})
    if area_feedback:
        feedback = f"{feedback}\n{area_feedback}"
    return feedback


def build_second_area_match_feedback(
    order_info: dict[str, Any],
    coverage_result: dict[str, Any],
) -> str | None:
    area_match = coverage_result.get("area_match") if isinstance(coverage_result, dict) else None
    if not isinstance(area_match, dict) or not area_match.get("checked"):
        return None

    inferred = area_match.get("inferred_second_area") or order_info.get("second_area")
    matched = area_match.get("matched_second_area") or order_info.get("second_area")
    options = [
        str(item)
        for item in (area_match.get("available_second_areas") or order_info.get("available_second_areas") or [])
        if item
    ]
    options_text = "、".join(options)

    if area_match.get("matched") is True:
        match_source = area_match.get("match_source")
        if match_source == "single_option" and matched:
            return f"区域匹配：该商品在当前区域下仅绑定【{matched}】，已自动选择；如不对，可在预下单卡片修改。"
        if match_source == "source_text" and matched:
            return f"区域匹配：已根据您的描述和商品绑定区域匹配为【{matched}】；如不对，可在预下单卡片修改。"
        if inferred and matched and inferred != matched:
            return f"区域匹配：系统初步识别的二级区域【{inferred}】已按商品绑定区域归一为【{matched}】；如不对，可在预下单卡片修改。"
        if matched:
            return f"区域匹配：当前二级区域为【{matched}】，已匹配该商品绑定区域；如不对，可在预下单卡片修改。"
        return None

    if area_match.get("matched") is False:
        if inferred and options_text:
            return f"区域待确认：系统初步识别的二级区域【{inferred}】不在该商品绑定区域内，可选【{options_text}】，请补充或在卡片中修改。"
        if options_text:
            return f"区域待确认：该商品绑定的二级区域为【{options_text}】，请补充或在卡片中选择。"
        if inferred:
            return f"区域待确认：系统初步识别的二级区域【{inferred}】未匹配到该商品绑定区域，请补充确认。"

    if options_text:
        return f"区域提示：该商品绑定的二级区域为【{options_text}】，请确认是否正确。"
    return None


def _score(product: dict[str, Any]) -> float | None:
    value = product.get("score")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_product_selection_feedback(products: list[dict[str, Any]], search_query: str) -> str | None:
    """给前端展示商品候选的选择原因。

    商品推荐阶段默认不自动选 Top1；当分数偏低或候选接近时，文案会提醒用户确认，
    避免低置信匹配直接进入下单。
    """

    if not search_query:
        return None
    if not products:
        return "暂时没有匹配到可下单商品，请换一种说法描述商品和故障。"

    top_score = _score(products[0])
    second_score = _score(products[1]) if len(products) > 1 else None
    if top_score is not None and top_score < LOW_CONFIDENCE_SCORE:
        return "匹配置信度偏低，请从下方候选中选择最接近的服务商品；如果都不符合，请选择“以上都不符合”。"
    if top_score is not None and second_score is not None and abs(top_score - second_score) <= AMBIGUOUS_SCORE_DELTA:
        return "找到多个相近服务商品，请先确认要下单的具体商品。"
    return "已找到可下单的服务商品，请先选择一个商品后再生成预下单卡片。"


def derive_product_section_fields(state: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """从 state 推导 API products 区块的 status / query / feedback。"""
    products = state.get("products") or []
    from services.order_items import build_effective_order_info, product_from_order_item

    order_info = build_effective_order_info(state)
    search_query = build_product_search_query(order_info, state.get("service_type"))
    status = infer_product_search_status(products, search_query)

    first_item = next((item for item in ((state.get("order") or {}).get("items") or []) if isinstance(item, dict)), {})
    selected = product_from_order_item(first_item)
    service_type = state.get("service_type")
    feedback = (
        build_product_search_feedback(order_info, selected, service_type, state.get("coverage_result") or {})
        if selected
        else build_product_selection_feedback(products, search_query)
    )
    return status, search_query or None, feedback
