"""Project internal AgentState into the stable client workflow contract."""

from typing import Any

from graph.order_fields import build_order_card_fields
from graph.products import (
    derive_product_section_fields,
)
from graph.text_parsing import format_service_type
from schemas.order_preview import (
    ClientOrder,
    OrderForm,
    OrderFormField,
    OrderCommon,
    OrderItem,
    OrderPhase,
    OrderPreview,
    ProductRequest,
    ProductOption,
    SubmissionSection,
    SubmissionState,
    SubmittedOrder,
)
from tools.order_payload_managed import align_order_second_area_with_spu
from services.order_items import build_effective_order_info, get_order_common, get_order_items


def product_raw_to_option(
    raw: dict[str, Any],
    *,
    rank: int,
) -> ProductOption:
    code = str(raw.get("service_product_code") or "")
    return ProductOption(
        code=code,
        name=str(raw.get("service_product_name") or ""),
        service_type=str(raw.get("service_order_type") or raw.get("product_type") or ""),
        category=raw.get("category"),
        unit=raw.get("unit"),
        price=raw.get("price"),
        price_status=raw.get("price_status"),
        repair_category=raw.get("repair_category"),
        fault_phenomenon=raw.get("fault_phenomenon"),
        related_area=raw.get("related_area"),
        remark=raw.get("remark"),
        score=raw.get("score"),
        rank=rank,
        is_recommended=rank == 1,
    )


def build_product_options(
    *,
    products: list[dict[str, Any]],
    search_status: str | None,
    search_query: str | None,
    search_feedback: str | None,
    selection_rejected: bool = False,
) -> list[ProductOption]:
    del search_status, search_query, search_feedback, selection_rejected
    return [
            product_raw_to_option(raw, rank=index)
            for index, raw in enumerate(products, start=1)
            if raw.get("service_product_code")
        ]


def _infer_phase(state: dict[str, Any]) -> str:
    phase = state.get("phase")
    if phase:
        return str(getattr(phase, "value", phase))

    products = state.get("products") or []
    submitted = state.get("last_order") or {}
    submission_state = (state.get("submission") or {}).get("state")
    if submitted.get("order_no") or submission_state == SubmissionState.SUCCEEDED:
        return OrderPhase.SUBMITTED.value
    if state.get("product_selection_rejected"):
        return OrderPhase.COLLECTING.value
    if get_order_items(state) and state.get("order_card_fields"):
        return OrderPhase.PRE_ORDER.value
    if products:
        return OrderPhase.PRODUCT_SELECTION.value
    if state.get("product_request") or state.get("order"):
        return OrderPhase.COLLECTING.value
    return OrderPhase.IDLE.value


def _has_client_data(
    state: dict[str, Any],
    *,
    phase: str,
    submitted_order: dict[str, Any] | None,
) -> bool:
    submission_state = str((state.get("submission") or {}).get("state") or "")
    return any(
        (
            state.get("product_request"),
            state.get("order"),
            state.get("products"),
            state.get("coverage_result"),
            state.get("order_card_fields"),
            get_order_items(state),
            submitted_order,
            phase == OrderPhase.CANCELLED.value,
            submission_state
            and submission_state != SubmissionState.NOT_ATTEMPTED.value,
        )
    )


def _actions(
    *,
    phase: str,
    products: list[dict[str, Any]],
    order_items: list[dict[str, Any]],
    selection_rejected: bool,
    missing_fields: list[str],
    submission_state: str,
) -> list[str]:
    busy = submission_state == SubmissionState.SUBMITTING.value
    submitted = submission_state == SubmissionState.SUCCEEDED.value
    active = phase in {
        OrderPhase.COLLECTING.value,
        OrderPhase.PRODUCT_SELECTION.value,
        OrderPhase.PRE_ORDER.value,
    }
    selecting = (
        phase == OrderPhase.PRODUCT_SELECTION.value
        and bool(products)
        and not selection_rejected
        and not busy
    )
    editing = (
        phase == OrderPhase.PRE_ORDER.value
        and bool(order_items)
        and not busy
        and not submitted
    )
    ready = editing and not missing_fields
    can_submit = ready and submission_state != SubmissionState.DISABLED.value
    actions: list[str] = []
    if selecting:
        actions.extend(("select_product", "reject_products"))
    if editing:
        actions.extend(("update_order", "add_item", "update_item"))
    if editing and len(order_items) > 1:
        actions.append("remove_item")
    if can_submit:
        actions.append("confirm_order")
    if active and not busy:
        actions.append("cancel_order")
    if ready and submission_state == SubmissionState.FAILED.value:
        actions.append("retry_submission")
    return actions


def _project_order_item(raw: dict[str, Any], *, editable: bool, removable: bool) -> OrderItem:
    return OrderItem(
        id=str(raw.get("id") or ""),
        code=str(raw.get("product_code") or ""),
        name=str(raw.get("product_name") or ""),
        service_type=str(raw.get("service_type") or ""),
        quantity=max(int(raw.get("quantity") or 1), 1),
        unit=raw.get("unit"),
        price=raw.get("price"),
        category=raw.get("category"),
        repair_category=raw.get("repair_category"),
        related_category=raw.get("related_category"),
        related_area=raw.get("related_area"),
        fault_phenomenon=raw.get("fault_phenomenon"),
        remark=raw.get("remark"),
        fault=raw.get("fault"),
        coverage=raw.get("coverage") or {},
        errors=list((raw.get("validation") or {}).get("missing_fields") or []),
        can_edit=editable,
        can_remove=removable,
    )


def build_order_preview_model(state: dict[str, Any]) -> OrderPreview | None:
    """Project internal state into the typed client workflow model."""

    projected_state = dict(state)
    order_info = build_effective_order_info(state)
    products = list(state.get("products") or [])
    order_items = get_order_items(state)
    phase = _infer_phase(state)
    submission_raw = state.get("submission") or {}
    submission_state = str(
        submission_raw.get("state") or SubmissionState.NOT_ATTEMPTED.value
    )

    submitted_candidate = state.get("last_order") or None
    submitted_order_raw = (
        submitted_candidate
        if phase == OrderPhase.SUBMITTED.value
        and isinstance(submitted_candidate, dict)
        and submitted_candidate.get("order_no")
        else None
    )
    if not _has_client_data(
        state,
        phase=phase,
        submitted_order=submitted_order_raw,
    ):
        return None

    service_type = state.get("service_type")
    effective_service_type = state.get("effective_service_type") or service_type
    coverage_result = state.get("coverage_result") or {}
    form_fields = list(state.get("order_card_fields") or [])

    spu_detail = (
        coverage_result.get("spu_detail")
        if isinstance(coverage_result, dict)
        and isinstance(coverage_result.get("spu_detail"), dict)
        else {}
    )
    if effective_service_type == "托管维修" and spu_detail:
        order_info, area_match = align_order_second_area_with_spu(
            order_info,
            spu_detail,
            source_text=str(state.get("last_user_message") or ""),
        )
        coverage_result = {**coverage_result, "area_match": area_match}
        second_area_field = next(
            (
                field
                for field in form_fields
                if isinstance(field, dict) and field.get("key") == "second_area"
            ),
            {},
        )
        if second_area_field.get("input_type") != "select" or not second_area_field.get("options"):
            form_fields = build_order_card_fields(
                service_type=effective_service_type,
                order_info=order_info,
                order_context=(
                    state.get("order_context")
                    if isinstance(state.get("order_context"), dict)
                    else {}
                ),
            )

    projected_state.update({"coverage_result": coverage_result, "service_type": service_type})
    search_status, search_query, search_feedback = derive_product_section_fields(
        projected_state
    )
    product_options = build_product_options(
        products=products,
        search_status=search_status,
        search_query=search_query,
        search_feedback=search_feedback,
        selection_rejected=bool(state.get("product_selection_rejected")),
    )
    missing_fields = list(state.get("missing_info") or [])
    for item in order_items:
        validation = item.get("validation") if isinstance(item.get("validation"), dict) else {}
        for field in validation.get("missing_fields") or []:
            qualified = f"items.{item.get('id')}.{field}"
            if qualified not in missing_fields:
                missing_fields.append(qualified)
    item_editable = phase == OrderPhase.PRE_ORDER.value and submission_state not in {
        SubmissionState.SUBMITTING.value,
        SubmissionState.SUCCEEDED.value,
    }
    projected_items = [
            _project_order_item(item, editable=item_editable, removable=item_editable and len(order_items) > 1)
            for item in order_items
        ]

    service_type_display = state.get("service_type_display") or format_service_type(
        service_type,
        order_info,
    )
    effective_service_type_display = (
        state.get("effective_service_type_display")
        or format_service_type(effective_service_type, order_info)
        or service_type_display
    )
    preview = OrderPreview(
        phase=phase,
        service_type=service_type,
        service_type_display=service_type_display,
        effective_service_type=effective_service_type,
        effective_service_type_display=effective_service_type_display,
        product_request=ProductRequest.model_validate(state.get("product_request") or {}),
        order=ClientOrder(
            **OrderCommon.model_validate(get_order_common(state)).model_dump(),
            items=projected_items,
        ),
        products=product_options,
        form=OrderForm(
            fields=[
                OrderFormField.model_validate(field)
                for field in form_fields
                if isinstance(field, dict)
            ]
        ),
        errors=missing_fields,
        actions=_actions(
            phase=phase,
            products=products,
            order_items=order_items,
            selection_rejected=bool(state.get("product_selection_rejected")),
            missing_fields=missing_fields,
            submission_state=submission_state,
        ),
        submission=SubmissionSection(
            state=submission_state,
            order_no=submission_raw.get("order_no"),
            message=submission_raw.get("failure_message"),
        ),
        submitted_order=(
            SubmittedOrder.model_validate(submitted_order_raw)
            if submitted_order_raw
            else None
        ),
    )
    return preview


def build_order_preview(state: dict[str, Any]) -> dict[str, Any] | None:
    """Serialize the client workflow model for API and streaming responses."""

    preview = build_order_preview_model(state)
    return preview.model_dump(mode="json") if preview else None
