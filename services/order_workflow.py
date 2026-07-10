"""Reusable order workflow operations.

This service keeps deterministic order transitions out of LangGraph nodes and
HTTP handlers. Nodes still orchestrate external I/O; the service returns
LangGraph-compatible state patches.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from domain.events import (
    OrderCardUpdated,
    ProductMatched,
    ProductSelected,
    event_to_state_patch,
)
from domain.validation import missing_fields_for_order
from graph.order_fields import build_order_card_fields, normalize_order_card_update
from graph.products import find_product_by_code, get_selected_product, resolve_selected_code
from graph.submission import empty_submission
from graph.constants import PHASE_COLLECTING, PHASE_PRE_ORDER, PHASE_PRODUCT_SELECTION
from schemas.user import UserContext
from services.order_context_service import load_order_context
from services.order_normalizer import normalize_order_defaults
from services.order_routing import resolve_order_submit_route
from tools.hosting_coverage import check_hosting_product_coverage
from tools.order_payload_managed import align_order_second_area_with_spu

JsonDict = dict[str, Any]
NormalizeOrderDefaults = Callable[[str | None, JsonDict, str], JsonDict]
LoadOrderContext = Callable[[UserContext], Awaitable[JsonDict]]
CheckCoverage = Callable[..., Awaitable[JsonDict]]
ResolveSubmitRoute = Callable[[str | None], str | None]


@dataclass
class OrderWorkflowService:
    normalize_order_defaults: NormalizeOrderDefaults = normalize_order_defaults
    load_order_context: LoadOrderContext = load_order_context
    check_hosting_product_coverage: CheckCoverage = check_hosting_product_coverage
    resolve_order_submit_route: ResolveSubmitRoute = resolve_order_submit_route

    def match_products(
        self,
        *,
        state: JsonDict,
        products: list[JsonDict],
        service_type: str | None,
    ) -> JsonDict:
        selected_code = resolve_selected_code(
            products,
            state.get("selected_product_code"),
            default_to_first=False,
        )
        order_info = self.normalize_order_defaults(
            service_type,
            state.get("order_info") or {},
            str(state.get("last_user_message") or ""),
        )
        patch = {
            "products": products,
            "selected_product_code": selected_code,
            "service_type": service_type,
            "order_info": order_info,
            "product_selection_rejected": False,
            "missing_info": [] if products else ["product_match"],
            "order_card_fields": [],
            "phase": PHASE_PRODUCT_SELECTION if products else PHASE_COLLECTING,
            "step": "search_product_node",
        }
        if not products:
            patch.update(
                {
                    "effective_service_type": None,
                    "coverage_result": {},
                    "order_submit_route": None,
                }
            )
        return event_to_state_patch(ProductMatched(payload=patch))

    def reject_products(self) -> JsonDict:
        patch = {
            "products": [],
            "selected_product_code": None,
            "service_type": None,
            "effective_service_type": None,
            "coverage_result": {},
            "order_submit_route": None,
            "order_card_fields": [],
            "product_selection_rejected": True,
            "missing_info": [],
            "phase": PHASE_COLLECTING,
            "step": "search_product_node",
        }
        return event_to_state_patch(ProductMatched(payload=patch))

    def select_existing_product_by_rank(
        self,
        *,
        state: JsonDict,
        selection: int,
    ) -> JsonDict:
        products = state.get("products") or []
        selected = products[int(selection) - 1] if len(products) >= int(selection) else {}
        if not selected:
            return {"step": "search_product_node"}
        return self.select_product_patch(
            state=state,
            selected_product=selected,
            product_code=str(selected.get("service_product_code") or ""),
        )

    def select_product_patch(
        self,
        *,
        state: JsonDict,
        selected_product: JsonDict,
        product_code: str,
    ) -> JsonDict:
        service_type = selected_product.get("service_order_type") or state.get("service_type")
        order_info = self.normalize_order_defaults(
            service_type,
            state.get("order_info") or {},
            str(state.get("last_user_message") or ""),
        )
        patch: JsonDict = {
            "selected_product_code": product_code.strip(),
            "service_type": service_type,
            "order_info": order_info,
            "product_selection_rejected": False,
            "phase": PHASE_PRE_ORDER,
            "step": "search_product_node",
        }
        return event_to_state_patch(ProductSelected(payload=patch))

    async def select_product(
        self,
        *,
        state: JsonDict,
        product_code: str,
        user: UserContext,
    ) -> JsonDict:
        products = state.get("products") or []
        selected = find_product_by_code(products, product_code)
        if not selected:
            raise ValueError(f"商品 {product_code} 不在当前检索结果中")

        service_type = selected.get("service_order_type") or state.get("service_type")
        order_info = self.normalize_order_defaults(
            service_type,
            state.get("order_info") or {},
            str(state.get("last_user_message") or ""),
        )
        effective_service_type = service_type
        if service_type == "托管维修":
            coverage_result = await self.check_hosting_product_coverage(
                order_info=order_info,
                matched_product=selected,
                user=user,
                last_user_message=str(state.get("last_user_message") or ""),
            )
            coverage_data = coverage_result.get("data") or {}
            effective_service_type = str(coverage_data.get("effective_service_type") or service_type)
            order_info = self.normalize_order_defaults(
                effective_service_type,
                order_info,
                str(state.get("last_user_message") or ""),
            )
            spu_detail = coverage_data.get("spu_detail") if isinstance(coverage_data.get("spu_detail"), dict) else {}
            if effective_service_type == "托管维修" and spu_detail:
                order_info, area_match = align_order_second_area_with_spu(
                    order_info,
                    spu_detail,
                    source_text=str(state.get("last_user_message") or ""),
                )
                coverage_data = {**coverage_data, "area_match": area_match}
        else:
            coverage_data = {
                "checked": False,
                "covered": None,
                "reason": "非托管维修商品，无需校验维保卡范围",
                "effective_service_type": service_type,
            }

        pre_order_patch = await self.prepare_pre_order(
            state={**state, "order_info": order_info},
            service_type=effective_service_type,
            user=user,
        )
        patch = {
            **pre_order_patch,
            "selected_product_code": product_code.strip(),
            "service_type": service_type,
            "effective_service_type": effective_service_type,
            "coverage_result": coverage_data,
            "order_submit_route": self.resolve_order_submit_route(effective_service_type),
            "order_info": order_info,
            "submission": empty_submission(),
            "product_selection_rejected": False,
            "phase": PHASE_PRE_ORDER,
            "step": "search_product_node",
        }
        return event_to_state_patch(ProductSelected(payload=patch))

    async def prepare_pre_order(
        self,
        *,
        state: JsonDict,
        service_type: str | None,
        user: UserContext,
    ) -> JsonDict:
        order_context = state.get("order_context") or await self.load_order_context(user)
        order_info = state.get("order_info") or {}
        order_card_fields = build_order_card_fields(
            service_type=service_type,
            order_info=order_info,
            order_context=order_context,
        )
        missing_info = missing_fields_for_order(service_type, order_info, order_card_fields)
        return {
            "order_context": order_context,
            "order_card_fields": order_card_fields,
            "missing_info": missing_info,
            "phase": PHASE_PRE_ORDER,
        }

    async def update_order_card(
        self,
        *,
        state: JsonDict,
        updates: JsonDict,
        service_type: str | None,
        user: UserContext,
    ) -> JsonDict:
        selected_product = get_selected_product(
            state.get("products") or [],
            state.get("selected_product_code"),
            default_to_first=False,
        )
        if not selected_product:
            raise ValueError("请先选择商品，再修改预下单信息")

        order_info = normalize_order_card_update(
            order_info=state.get("order_info") or {},
            updates=updates,
            service_type=service_type,
        )
        order_info = self.normalize_order_defaults(
            service_type,
            order_info,
            str(state.get("last_user_message") or ""),
        )
        pre_order_patch = await self.prepare_pre_order(
            state={**state, "order_info": order_info},
            service_type=service_type,
            user=user,
        )
        patch = {
            **pre_order_patch,
            "order_info": order_info,
            "submission": empty_submission(),
            "phase": PHASE_PRE_ORDER,
            "step": "prepare_order_context_node",
        }
        return event_to_state_patch(OrderCardUpdated(payload=patch))

    def validate(
        self,
        *,
        service_type: str | None,
        order_info: JsonDict,
        order_card_fields: list[JsonDict],
    ) -> list[str]:
        return missing_fields_for_order(service_type, order_info, order_card_fields)
