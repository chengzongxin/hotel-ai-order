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


def get_effective_service_type(state: AgentState | dict[str, Any]) -> str | None:
    """返回最终用于校验和提交的服务类型。"""

    return state.get("effective_service_type") or state.get("service_type")


def format_service_type(service_type: str | None, order_info: dict[str, object]) -> str | None:
    return format_service_type_display(service_type, order_info)  # type: ignore[arg-type]


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
        "real_order_payload": {},
        "real_order_result": {},
        "real_order_missing_fields": [],
        "missing_info": [],
    }


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
    submitted_order: dict[str, object] = {}
    if is_submitted:
        order_id = str(submit_data.get("parent_order_no") or "")
        submitted_order = {
            "order_id": order_id,
            "service_type": format_service_type(state.get("service_type"), state.get("order_info", {})),
            "effective_service_type": format_service_type(get_effective_service_type(state), state.get("order_info", {})),
            **order_info,
            "product_code": selected_product.get("service_product_code"),
            "product_name": selected_product.get("service_product_name"),
            "product_order_type": selected_product.get("service_order_type"),
            "selected_product": selected_product,
            "real_order_payload": request_payload,
            "real_order_result": submit_data,
            "coverage_result": state.get("coverage_result") or {},
        }
        answer = render_prompt(
            "submit/submit.md",
            order_id=order_id,
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
        if not submit_data.get("submit_enabled"):
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
        "real_order_payload": request_payload,
        "real_order_result": submit_data,
        "real_order_missing_fields": missing_fields,
        "products": state.get("products") or [],
        "selected_product_code": state.get("selected_product_code"),
        "missing_info": missing_fields,
        "retry_count": 0 if is_submitted else state.get("retry_count", 0),
        "off_topic_count": 0,
    }
    if is_submitted:
        output.update(
            {
                "status": "submitted",
                "ui_phase": PHASE_SUBMITTED,
                "last_order": submitted_order,
                **clear_active_order_state(),
            }
        )
    else:
        output.update(
            {
                "status": "collecting" if missing_fields else "confirming",
                "ui_phase": PHASE_PRE_ORDER,
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
        real_order_missing_fields=missing_fields,
    )
    return output
