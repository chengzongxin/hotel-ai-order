"""Project internal AgentState into the stable client workflow contract."""

from typing import Any

from graph.order_fields import build_order_card_fields
from graph.products import (
    derive_product_section_fields,
    get_selected_product,
    resolve_selected_code,
)
from graph.text_parsing import format_service_type
from schemas.order_preview import (
    CoverageSection,
    OrderForm,
    OrderFormField,
    OrderInfo,
    OrderPhase,
    OrderPreview,
    ProductOption,
    ProductSection,
    SubmissionSection,
    SubmissionState,
    SubmittedOrder,
    WorkflowCapabilities,
    WorkflowValidation,
)
from tools.order_payload_managed import align_order_second_area_with_spu


def product_raw_to_option(
    raw: dict[str, Any],
    *,
    rank: int,
    selected_code: str | None,
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
        is_selected=bool(code and code == selected_code),
    )


def build_product_section(
    *,
    products: list[dict[str, Any]],
    selected_code: str | None,
    search_status: str | None,
    search_query: str | None,
    search_feedback: str | None,
    selection_rejected: bool = False,
) -> ProductSection:
    resolved_code = resolve_selected_code(
        products,
        selected_code,
        default_to_first=False,
    )
    return ProductSection(
        status=search_status,
        query=search_query,
        feedback=search_feedback,
        selected_code=resolved_code,
        selection_rejected=selection_rejected,
        items=[
            product_raw_to_option(raw, rank=index, selected_code=resolved_code)
            for index, raw in enumerate(products, start=1)
            if raw.get("service_product_code")
        ],
    )


def _infer_phase(state: dict[str, Any]) -> str:
    phase = state.get("phase")
    if phase:
        return str(getattr(phase, "value", phase))

    products = state.get("products") or []
    submitted = state.get("submitted_order") or state.get("last_order") or {}
    submission_state = (state.get("submission") or {}).get("state")
    if submitted.get("order_no") or submission_state == SubmissionState.SUCCEEDED:
        return OrderPhase.SUBMITTED.value
    if state.get("product_selection_rejected"):
        return OrderPhase.COLLECTING.value
    if state.get("selected_product_code") and state.get("order_card_fields"):
        return OrderPhase.PRE_ORDER.value
    if products:
        return OrderPhase.PRODUCT_SELECTION.value
    if state.get("order_info"):
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
            state.get("order_info"),
            state.get("products"),
            state.get("coverage_result"),
            state.get("order_card_fields"),
            submitted_order,
            phase == OrderPhase.CANCELLED.value,
            submission_state
            and submission_state != SubmissionState.NOT_ATTEMPTED.value,
        )
    )


def _capabilities(
    *,
    phase: str,
    products: list[dict[str, Any]],
    selected_code: str | None,
    selection_rejected: bool,
    missing_fields: list[str],
    submission_state: str,
) -> WorkflowCapabilities:
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
        and bool(selected_code)
        and not busy
        and not submitted
    )
    ready = editing and not missing_fields
    can_submit = ready and submission_state != SubmissionState.DISABLED.value
    return WorkflowCapabilities(
        select_product=selecting,
        reject_products=selecting,
        update_order=editing,
        confirm_order=can_submit,
        cancel_order=active and not busy,
        retry_submission=ready and submission_state == SubmissionState.FAILED.value,
    )


def build_order_preview_model(state: dict[str, Any]) -> OrderPreview | None:
    """Project internal state into the typed client workflow model."""

    projected_state = dict(state)
    order_info = dict(state.get("order_info") or {})
    products = list(state.get("products") or [])
    selected_code = state.get("selected_product_code")
    phase = _infer_phase(state)
    submission_raw = state.get("submission") or {}
    submission_state = str(
        submission_raw.get("state") or SubmissionState.NOT_ATTEMPTED.value
    )

    submitted_candidate = state.get("submitted_order") or state.get("last_order") or None
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

    projected_state.update(
        {
            "order_info": order_info,
            "coverage_result": coverage_result,
            "service_type": service_type,
        }
    )
    search_status, search_query, search_feedback = derive_product_section_fields(
        projected_state
    )
    products_section = build_product_section(
        products=products,
        selected_code=selected_code,
        search_status=search_status,
        search_query=search_query,
        search_feedback=search_feedback,
        selection_rejected=bool(state.get("product_selection_rejected")),
    )
    missing_fields = list(state.get("missing_info") or [])
    selected_code = products_section.selected_code
    validation_ready = (
        phase == OrderPhase.PRE_ORDER.value
        and bool(selected_code)
        and not missing_fields
    )

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
        order_info=OrderInfo.model_validate(order_info),
        products=products_section,
        form=OrderForm(
            fields=[
                OrderFormField.model_validate(field)
                for field in form_fields
                if isinstance(field, dict)
            ]
        ),
        validation=WorkflowValidation(
            ready=validation_ready,
            missing_fields=missing_fields,
        ),
        capabilities=_capabilities(
            phase=phase,
            products=products,
            selected_code=selected_code,
            selection_rejected=bool(state.get("product_selection_rejected")),
            missing_fields=missing_fields,
            submission_state=submission_state,
        ),
        coverage=CoverageSection.model_validate(coverage_result),
        submission=SubmissionSection.model_validate(submission_raw),
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
