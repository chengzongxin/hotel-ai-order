"""订单提交与提交后状态清理逻辑。"""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import AIMessage

from graph.products import format_service_type_display, get_selected_product
from graph.prompts import render_prompt
from graph.state import AgentState
from schemas.user import UserContext
from tools.order_submit import submit_real_order
from utils.logger_handler import trace_logger

PHASE_PRE_ORDER = "pre_order"
PHASE_SUBMITTED = "submitted"

EmitTokenText = Callable[..., Awaitable[None]]

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

    return {
        "service_type": None,
        "effective_service_type": None,
        "coverage_result": {},
        "order_submit_route": None,
        "order_context": {},
        "order_card_fields": [],
        "order_info": {},
        "products": [],
        "selected_product_code": None,
        "missing_info": [],
    }


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
        return base

    if submit_data.get("submit_enabled") is False:
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
    emit_token_text: EmitTokenText | None = None,
) -> dict[str, object]:
    """根据当前状态提交订单。"""

    selected_product = get_selected_product(
        state.get("products") or [],
        state.get("selected_product_code"),
        default_to_first=False,
    )
    order_info = state.get("order_info", {})
    submit_result = await submit_real_order(
        order_info=order_info,
        matched_product=selected_product,
        service_type=state.get("service_type"),
        effective_service_type=get_effective_service_type(state),
        coverage_result=state.get("coverage_result") or {},
        submit=True,
        user=user,
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
            "service_type": format_service_type(state.get("service_type"), state.get("order_info", {})),
            "effective_service_type": format_service_type(get_effective_service_type(state), state.get("order_info", {})),
            **order_info,
            "contacts": first_text(order_info.get("contacts"), submit_data.get("contacts"), request_payload.get("contacts")),
            "phone": first_text(order_info.get("phone"), submit_data.get("phone"), request_payload.get("phone")),
            "product_code": selected_product.get("service_product_code"),
            "product_name": selected_product.get("service_product_name"),
            "product_order_type": selected_product.get("service_order_type"),
            "selected_product": selected_product,
            "request_payload": request_payload,
            "response_payload": submit_data,
            "coverage_result": state.get("coverage_result") or {},
        }
        answer = render_prompt(
            "submit/submit.md",
            order_id=order_no or "",
            service_type=format_service_type(get_effective_service_type(state), state.get("order_info", {})),
            order_info=order_info,
            matched_product=selected_product,
        )
    else:
        missing_text = "、".join(str(item) for item in missing_fields)
        diagnostics = submit_data.get("diagnostics") or {}
        address_diagnostics = diagnostics.get("default_address") if isinstance(diagnostics, dict) else {}
        address_hint = ""
        address_api_code = address_diagnostics.get("address_api_code") if isinstance(address_diagnostics, dict) else None
        if address_api_code and address_api_code != 200:
            address_hint = (
                "\n默认地址补齐失败："
                f"地址接口返回 {address_api_code}"
                f"（{address_diagnostics.get('address_api_message') or '无错误信息'}）。"
                "请更新用户端登录 token，或确认维保卡接口可返回酒店地址与联系人信息。"
            )
        if submit_data.get("submit_enabled") is False:
            lead = "已根据用户端 App 的下单逻辑生成真实下单参数，但当前关闭了线上创建订单开关。"
        elif missing_fields:
            lead = "已根据用户端 App 的下单逻辑生成真实下单参数，但仍有必填参数缺失，暂未提交。"
        else:
            lead = "已调用创建订单接口，但没有返回可识别的订单号，暂未标记为下单成功。"
        missing_line = f"还需补齐：{missing_text}。" if missing_text else "订单参数已补齐，请确认接口返回或稍后重试。"
        answer = (
            f"{lead}\n"
            f"原因：{submit_result.get('message')}。\n"
            f"{missing_line}"
            f"{address_hint}"
        )
    if emit and emit_token_text:
        await emit_token_text(answer, step="submit_node")

    output = {
        "messages": [AIMessage(content=answer)],
        "step": "submit_node",
        "submission": submission,
        "products": state.get("products") or [],
        "selected_product_code": state.get("selected_product_code"),
        "missing_info": missing_fields,
        "retry_count": 0 if is_submitted else state.get("retry_count", 0),
        "off_topic_count": 0,
    }
    if is_submitted:
        output.update(
            {
                "phase": PHASE_SUBMITTED,
                "last_order": submitted_order,
                "submitted_order": submitted_order,
                **clear_active_order_state(),
            }
        )
        output["submission"] = submission
        output["phase"] = PHASE_SUBMITTED
        output["last_order"] = submitted_order
        output["submitted_order"] = submitted_order
    else:
        output.update(
            {
                "phase": PHASE_PRE_ORDER,
                "service_type": state.get("service_type"),
                "effective_service_type": state.get("effective_service_type"),
                "coverage_result": state.get("coverage_result") or {},
                "order_submit_route": state.get("order_submit_route"),
                "order_context": state.get("order_context") or {},
                "order_card_fields": state.get("order_card_fields") or [],
                "order_info": order_info,
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
