from __future__ import annotations

from typing import Any

from config.settings import settings
from schemas.user import UserContext
from tools.protocol import ToolErrorCode, ToolResult, error_response, success_response

JsonDict = dict[str, Any]


async def submit_managed_repair_order(
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
    """托管维修真实下单流程。"""

    from tools.order_submit import (
        CREATE_MANAGED_REPAIR_ORDER,
        _clean_text,
        _extract_order_no,
        _post_app,
        build_managed_repair_order_payload,
    )

    contacts = _clean_text(order_info.get("contacts")) or order_context["contacts"]
    phone = _clean_text(order_info.get("phone")) or order_context["phone"]
    payload, missing_fields = build_managed_repair_order_payload(
        order_info=order_info,
        spu=spu,
        selected_address=order_context["selected_address"],
        contacts=contacts,
        phone=phone,
        area_tree=order_context["area_tree"],
        global_config=order_context["global_config"],
        ide_name=user.ide_name,
    )
    data: JsonDict = {
        "request_payload": payload,
        "missing_fields": missing_fields,
        "submit_enabled": settings.user_app_submit_enabled,
        "submitted": False,
        "parent_order_no": None,
        "service_type": service_type,
        "effective_service_type": "托管维修",
        "order_submit_route": "managed_repair",
        "coverage_result": coverage_result or {},
        "spu_detail": spu,
        "spu_query_error": spu_query_error,
        "hosting_card": order_context["hosting_card"],
        "hosting_card_error": order_context["hosting_card_error"],
        "selected_address": order_context["selected_address"],
        "user_profile": order_context["user_profile"],
        "global_config": order_context["global_config"],
    }

    if not submit or not settings.user_app_submit_enabled:
        return success_response(data=data, message="built managed repair payload; real submit is disabled")
    if missing_fields:
        return error_response(
            error_code=ToolErrorCode.INVALID_INPUT,
            message=f"cannot submit managed repair order, missing fields: {', '.join(missing_fields)}",
            data=data,
        )

    response_data = await _post_app(CREATE_MANAGED_REPAIR_ORDER, payload, user)
    data["create_response"] = response_data
    data["parent_order_no"] = _extract_order_no(response_data)
    data["submitted"] = bool(data["parent_order_no"])
    if data["submitted"]:
        return success_response(data=data, message="managed repair order submitted")
    return error_response(
        error_code=ToolErrorCode.UPSTREAM_ERROR,
        message="managed repair order api returned no order number",
        data=data,
    )
