"""订单提交与提交后状态清理逻辑。"""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import AIMessage

from graph.products import format_service_type_display
from services.order_items import (
    build_effective_order_info,
    build_order_state,
    get_order_common,
    get_order_items,
    product_from_order_item,
)
from services.order_state import assert_order_state_invariants, reset_active_order_state
from graph.prompts import render_prompt
from graph.state import AgentState
from graph.streaming import run_traced_tool_call
from schemas.user import UserContext
from tools.order_submit import submit_real_order
from utils.logger_handler import trace_logger

PHASE_PRE_ORDER = "pre_order"
PHASE_SUBMITTED = "submitted"

EmitTextChunk = Callable[[str, str], Awaitable[None]]

SUBMISSION_NOT_ATTEMPTED = "not_attempted"
SUBMISSION_SUCCEEDED = "succeeded"
SUBMISSION_FAILED = "failed"
SUBMISSION_DISABLED = "disabled"


def get_effective_service_type(state: AgentState | dict[str, Any]) -> str | None:
    """返回最终用于校验和提交的服务类型。"""

    return state.get("effective_service_type") or state.get("service_type")


def format_service_type(service_type: str | None, order_info: dict[str, object]) -> str | None:
    return format_service_type_display(service_type, order_info)  # type: ignore[arg-type]


def first_text(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def clear_active_order_state() -> dict[str, object]:
    """清空当前进行中的订单状态，保留 last_order 供后续追问使用。"""

    return reset_active_order_state()


def empty_submission() -> dict[str, object]:
    return {
        "attempted": False,
        "state": SUBMISSION_NOT_ATTEMPTED,
        "order_no": None,
        "failure_code": None,
        "failure_message": None,
        "missing_fields": [],
        "request_payload": {},
        "response_payload": {},
    }


def extract_upstream_error_message(submit_data: dict[str, Any]) -> str | None:
    """提取创建订单接口返回的原始错误信息，供用户直接查看。"""

    for key in ("create_response", "check_response"):
        response = submit_data.get(key)
        if not isinstance(response, dict):
            continue
        message = first_text(response.get("msg"), response.get("message"))
        code = response.get("code")
        failed = code not in (None, 0, "0", 200, "200") or response.get("success") is False
        if failed and message:
            return message
    return None


def build_submission_result(
    *,
    submit_result: dict[str, Any],
    request_payload: dict[str, Any],
    submit_data: dict[str, Any],
    missing_fields: list[str],
    order_no: str | None,
    is_submitted: bool,
) -> dict[str, object]:
    """把工具返回值归一化成前端可直接消费的提交状态。"""

    base: dict[str, object] = {
        "attempted": True,
        "state": SUBMISSION_SUCCEEDED if is_submitted else SUBMISSION_FAILED,
        "order_no": order_no if is_submitted else None,
        "failure_code": None,
        "failure_message": None,
        "missing_fields": missing_fields,
        "request_payload": request_payload,
        "response_payload": submit_data,
    }
    if is_submitted:
        base["request_payload"] = {}
        base["response_payload"] = {}
        return base

    upstream_error_message = extract_upstream_error_message(submit_data)
    if upstream_error_message:
        base.update(
            {
                "failure_code": "api_error",
                "failure_message": upstream_error_message,
            }
        )
    elif submit_data.get("submit_enabled") is False:
        base.update(
            {
                "state": SUBMISSION_DISABLED,
                "failure_code": "submit_disabled",
                "failure_message": "已生成真实下单参数，但当前未开启线上创建订单开关。",
            }
        )
    elif missing_fields:
        missing_text = "、".join(str(item) for item in missing_fields)
        base.update(
            {
                "failure_code": "missing_required_fields",
                "failure_message": f"真实下单参数仍缺少必填字段：{missing_text}。",
            }
        )
    elif submit_data.get("submit_enabled") is True and submit_data:
        base.update(
            {
                "failure_code": "order_no_missing",
                "failure_message": "已调用创建订单接口，但没有返回可识别的订单号。",
            }
        )
    elif submit_result.get("error_code"):
        base.update(
            {
                "failure_code": "api_error",
                "failure_message": str(submit_result.get("message") or "调用下单接口失败。"),
            }
        )
    else:
        base.update(
            {
                "failure_code": "order_no_missing",
                "failure_message": "已调用创建订单接口，但没有返回可识别的订单号。",
            }
        )
    return base


async def submit_order_from_state(
    state: AgentState,
    user: UserContext,
    *,
    emit: bool = True,
    emit_text_chunk: EmitTextChunk | None = None,
) -> dict[str, object]:
    """根据当前状态提交订单。"""

    assert_order_state_invariants(dict(state))
    order_items = get_order_items(state)
    if not order_items:
        raise ValueError("提交订单前必须至少选择一个商品")
    selected_product = product_from_order_item(order_items[0])
    order_info = build_effective_order_info(state)
    submit_params = {
        "order_info": order_info,
        "matched_product": selected_product,
        "order": build_order_state(get_order_common(state), order_items),
        "service_type": state.get("service_type"),
        "effective_service_type": get_effective_service_type(state),
        "coverage_result": state.get("coverage_result") or {},
        "submit": True,
    }
    submit_result = await run_traced_tool_call(
        step="submit_node",
        name="submit_real_order",
        display_name="创建订单",
        params=submit_params,
        action=lambda: submit_real_order(
            order_info=order_info,
            matched_product=selected_product,
            service_type=state.get("service_type"),
            effective_service_type=get_effective_service_type(state),
            coverage_result=state.get("coverage_result") or {},
            order_items=order_items,
            submit=True,
            user=user,
        ),
    )
    submit_data = submit_result.get("data", {})
    request_payload = submit_data.get("request_payload") or {}
    missing_fields = submit_data.get("missing_fields") or []
    is_submitted = bool(submit_data.get("submitted"))
    order_no = str(submit_data.get("parent_order_no") or "") if is_submitted else None
    submission = build_submission_result(
        submit_result=submit_result,
        request_payload=request_payload,
        submit_data=submit_data,
        missing_fields=missing_fields,
        order_no=order_no,
        is_submitted=is_submitted,
    )
    submitted_order: dict[str, object] = {}
    if is_submitted:
        submitted_order = {
            "order_no": order_no or "",
            "service_type": format_service_type(state.get("service_type"), order_info),
            "effective_service_type": format_service_type(get_effective_service_type(state), order_info),
            **order_info,
            "contacts": first_text(order_info.get("contacts"), submit_data.get("contacts"), request_payload.get("contacts")),
            "phone": first_text(order_info.get("phone"), submit_data.get("phone"), request_payload.get("phone")),
            "product_code": selected_product.get("service_product_code"),
            "product_name": selected_product.get("service_product_name"),
            "product_order_type": selected_product.get("service_order_type"),
            "coverage_result": state.get("coverage_result") or {},
            "items": [
                {
                    "id": str(item.get("id") or ""),
                    "code": str(item.get("product_code") or ""),
                    "name": str(item.get("product_name") or ""),
                    "service_type": str(item.get("service_type") or ""),
                    "quantity": max(int(item.get("quantity") or 1), 1),
                    "unit": item.get("unit"),
                    "price": item.get("price"),
                    "fault": item.get("fault"),
                    "coverage": item.get("coverage") or {},
                    "validation": item.get("validation") or {},
                    "can_edit": False,
                    "can_remove": False,
                }
                for item in order_items
            ],
        }
        answer = render_prompt(
            "submit/submit.md",
            order_id=order_no or "",
            service_type=format_service_type(get_effective_service_type(state), order_info),
            order_info=order_info,
            matched_product=selected_product,
        )
    else:
        # 订单接口已给出失败信息时，必须原样回复，避免通用话术掩盖业务原因。
        answer = str(submission.get("failure_message") or submit_result.get("message") or "调用下单接口失败。")
    if emit and emit_text_chunk:
        await emit_text_chunk(answer, "submit_node")

    output = {
        "messages": [AIMessage(content=answer)],
        "step": "submit_node",
        "submission": submission,
        "products": state.get("products") or [],
        "order": build_order_state(get_order_common(state), order_items),
        "missing_info": missing_fields,
        "retry_count": 0 if is_submitted else state.get("retry_count", 0),
        "off_topic_count": 0,
    }
    if is_submitted:
        output.update(
            {
                **clear_active_order_state(),
                "phase": PHASE_SUBMITTED,
                "last_order": submitted_order,
                "submission": submission,
            }
        )
    else:
        output.update(
            {
                "phase": PHASE_PRE_ORDER,
                "service_type": state.get("service_type"),
                "effective_service_type": state.get("effective_service_type"),
                "coverage_result": state.get("coverage_result") or {},
                "order_context": state.get("order_context") or {},
                "order_card_fields": state.get("order_card_fields") or [],
                "product_request": state.get("product_request") or {},
                "order": build_order_state(get_order_common(state), order_items),
            }
        )
    trace_logger(
        "node.submit.output",
        answer=answer,
        order_info=order_info,
        tool_status=submit_result.get("status"),
        real_submitted=submit_data.get("submitted"),
        submission=submission,
    )
    return output
