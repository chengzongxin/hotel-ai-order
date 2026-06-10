from __future__ import annotations

from typing import Any

from config.settings import settings
from schemas.user import UserContext
from tools.protocol import ToolErrorCode, ToolResult, error_response, success_response

JsonDict = dict[str, Any]


async def submit_single_order(
    *,
    order_info: JsonDict,
    matched_product: JsonDict,
    spu: JsonDict,
    order_context: JsonDict,
    submit: bool,
    user: UserContext,
    service_type: str | None,
    coverage_result: JsonDict | None = None,
    spu_query_error: str | None = None,
) -> ToolResult:
    """单次维修/安装/测量真实下单流程。"""

    from tools.order_submit import (
        CHECK_SINGLE_ORDER,
        CREATE_SINGLE_ORDER,
        _clean_text,
        _extract_order_no,
        _first_present,
        _post_app,
        build_single_order_payload,
        query_single_order_app_spu,
        query_single_order_category_context,
    )

    category_context: JsonDict = {}
    category_name = _clean_text(
        _first_present(
            spu.get("categoryName"),
            spu.get("erpName"),
            matched_product.get("category"),
            matched_product.get("related_category"),
        )
    )
    try:
        category_context = await query_single_order_category_context(
            category_name=category_name,
            service_type=service_type,
            user=user,
        )
    except Exception as exc:
        spu_query_error = "; ".join(
            item
            for item in [
                spu_query_error,
                f"category_context_query={type(exc).__name__}: {exc}",
            ]
            if item
        )

    app_spu: JsonDict = {}
    try:
        app_spu = await query_single_order_app_spu(
            product_name=_clean_text(matched_product.get("service_product_name")),
            product_code=_clean_text(matched_product.get("service_product_code")),
            category_context=category_context,
            selected_address=order_context["selected_address"],
            user=user,
        )
    except Exception as exc:
        spu_query_error = "; ".join(
            item
            for item in [
                spu_query_error,
                f"app_spu_query={type(exc).__name__}: {exc}",
            ]
            if item
        )
    single_order_spu = {**spu, **app_spu} if app_spu else spu
    contacts = _clean_text(order_info.get("contacts")) or order_context["contacts"]
    phone = _clean_text(order_info.get("phone")) or order_context["phone"]
    payload, missing_fields = build_single_order_payload(
        order_info=order_info,
        spu=single_order_spu,
        matched_product=matched_product,
        category_context=category_context,
        selected_address=order_context["selected_address"],
        contacts=contacts,
        phone=phone,
        service_type=service_type,
        ide_name=user.ide_name,
    )
    data: JsonDict = {
        "request_payload": payload,
        "missing_fields": missing_fields,
        "submit_enabled": settings.user_app_submit_enabled,
        "submitted": False,
        "parent_order_no": None,
        "service_type": matched_product.get("service_order_type"),
        "effective_service_type": service_type,
        "order_submit_route": "single_order",
        "coverage_result": coverage_result or {},
        "spu_detail": spu,
        "app_spu_detail": app_spu,
        "category_context": category_context,
        "spu_query_error": spu_query_error,
        "hosting_card": order_context["hosting_card"],
        "hosting_card_error": order_context["hosting_card_error"],
        "selected_address": order_context["selected_address"],
        "user_profile": order_context["user_profile"],
        "global_config": order_context["global_config"],
    }

    if not submit or not settings.user_app_submit_enabled:
        return success_response(data=data, message="built single order payload; real submit is disabled")
    if missing_fields:
        return error_response(
            error_code=ToolErrorCode.INVALID_INPUT,
            message=f"cannot submit single order, missing fields: {', '.join(missing_fields)}",
            data=data,
        )

    check_data = await _post_app(CHECK_SINGLE_ORDER, payload, user)
    data["check_response"] = check_data
    create_data = await _post_app(CREATE_SINGLE_ORDER, payload, user)
    data["create_response"] = create_data
    data["parent_order_no"] = _extract_order_no(create_data)
    data["submitted"] = bool(data["parent_order_no"])
    if data["submitted"]:
        return success_response(data=data, message="single order submitted")
    return error_response(
        error_code=ToolErrorCode.UPSTREAM_ERROR,
        message="single order api returned no order number",
        data=data,
    )
