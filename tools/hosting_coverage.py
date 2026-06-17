from __future__ import annotations

from typing import Any

from schemas.user import UserContext
from tools.hosting_card import fetch_hosting_card_with_diagnostics
from tools.order_payload_managed import (
    align_order_second_area_with_spu,
    match_area_from_spu,
)
from tools.order_submit_common import query_spu_detail
from tools.protocol import ToolErrorCode, ToolResult, error_response, success_response

JsonDict = dict[str, Any]

HOSTING_CARD_ACTIVE_STATUS = 1


def _clean_text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


def _to_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _pick_spu_id(spu: JsonDict) -> int | None:
    return _to_int(spu.get("id") or spu.get("spuId"))


def _match_area_from_spu(spu: JsonDict, area_scope: str) -> JsonDict:
    area_list = spu.get("areaList") or []
    if not isinstance(area_list, list):
        return {}
    return match_area_from_spu(area_list, area_scope)


def _is_scope_match(scope_item: JsonDict, spu_id: int, second_area_id: int | None) -> bool:
    scope_spu_id = _to_int(scope_item.get("scopeRepairSpuId"))
    if scope_spu_id != spu_id:
        return False

    scope_second_area_id = _to_int(scope_item.get("secondAreaId"))
    if second_area_id is None or scope_second_area_id is None:
        return True
    return scope_second_area_id == second_area_id


def _build_result(
    *,
    checked: bool,
    covered: bool | None,
    reason: str,
    effective_service_type: str,
    hosting_card: JsonDict | None = None,
    spu_detail: JsonDict | None = None,
    second_area_id: int | None = None,
    interface_response: JsonDict | None = None,
) -> JsonDict:
    return {
        "checked": checked,
        "covered": covered,
        "reason": reason,
        "effective_service_type": effective_service_type,
        "hosting_card_status": hosting_card.get("status") if hosting_card else None,
        "hosting_card_id": hosting_card.get("id") if hosting_card else None,
        "hosting_card_name": hosting_card.get("comboName") if hosting_card else None,
        "spu_id": _pick_spu_id(spu_detail or {}),
        "spu_name": (spu_detail or {}).get("name"),
        "spu_detail": spu_detail or {},
        "second_area_id": second_area_id,
        "interface_response": interface_response or {},
    }


async def check_hosting_product_coverage(
    order_info: JsonDict,
    matched_product: JsonDict,
    user: UserContext,
    spu_detail: JsonDict | None = None,
    last_user_message: str = "",
) -> ToolResult:
    """检查托管维修商品是否在当前用户维保卡范围内。

    维保卡范围以后端返回的 scopeRepairSpuIdList 为准。命中时继续托管维修；
    未命中、无维保卡或查询失败时，保守降级为单次维修服务。
    """

    if not _clean_text(matched_product.get("service_product_name") or matched_product.get("service_product_code")):
        return error_response(
            error_code=ToolErrorCode.INVALID_INPUT,
            message="cannot check hosting coverage without matched product",
            data=_build_result(
                checked=False,
                covered=False,
                reason="缺少匹配商品，无法校验维保范围",
                effective_service_type="单次维修服务",
            ),
        )

    hosting_card, interface_response = await fetch_hosting_card_with_diagnostics(user)
    if not hosting_card:
        return success_response(
            data=_build_result(
                checked=True,
                covered=False,
                reason="当前用户没有可用维保卡，只能按单次维修下单",
                effective_service_type="单次维修服务",
                interface_response=interface_response,
            ),
            message="hosting card not found",
        )

    if _to_int(hosting_card.get("status")) != HOSTING_CARD_ACTIVE_STATUS:
        return success_response(
            data=_build_result(
                checked=True,
                covered=False,
                reason="当前维保卡未生效，只能按单次维修下单",
                effective_service_type="单次维修服务",
                hosting_card=hosting_card,
                interface_response=interface_response,
            ),
            message="hosting card is not active",
        )

    scope_list = hosting_card.get("scopeRepairSpuIdList") or []
    if not isinstance(scope_list, list) or not scope_list:
        return success_response(
            data=_build_result(
                checked=True,
                covered=False,
                reason="当前维保卡没有返回维保商品范围，只能按单次维修下单",
                effective_service_type="单次维修服务",
                hosting_card=hosting_card,
                interface_response=interface_response,
            ),
            message="hosting card scope is empty",
        )

    spu = spu_detail if isinstance(spu_detail, dict) else None
    if not spu:
        try:
            spu = await query_spu_detail(matched_product, user)
        except Exception as exc:
            return error_response(
                error_code=ToolErrorCode.UPSTREAM_ERROR,
                message=f"query managed repair spu failed: {exc}",
                data=_build_result(
                    checked=True,
                    covered=False,
                    reason="查询托管维修商品详情失败，只能按单次维修下单",
                    effective_service_type="单次维修服务",
                    hosting_card=hosting_card,
                    interface_response=interface_response,
                ),
            )

    if not spu:
        return success_response(
            data=_build_result(
                checked=True,
                covered=False,
                reason="未查询到托管维修商品详情，只能按单次维修下单",
                effective_service_type="单次维修服务",
                hosting_card=hosting_card,
                interface_response=interface_response,
            ),
            message="managed repair spu not found",
        )

    spu_id = _pick_spu_id(spu)
    if spu_id is None:
        return success_response(
            data=_build_result(
                checked=True,
                covered=False,
                reason="托管维修商品缺少 SPU ID，只能按单次维修下单",
                effective_service_type="单次维修服务",
                hosting_card=hosting_card,
                spu_detail=spu,
                interface_response=interface_response,
            ),
            message="managed repair spu id is missing",
        )

    aligned_order_info, area_match = align_order_second_area_with_spu(
        order_info,
        spu,
        source_text=last_user_message,
    )
    if area_match.get("checked") and area_match.get("matched") is False:
        data = _build_result(
            checked=False,
            covered=None,
            reason="二级区域待确认，暂不校验维保范围",
            effective_service_type="托管维修",
            hosting_card=hosting_card,
            spu_detail=spu,
            interface_response=interface_response,
        )
        data["area_match"] = area_match
        return success_response(data=data, message="managed repair second area needs confirmation")

    area_scope = _clean_text(aligned_order_info.get("managed_repair_scope") or aligned_order_info.get("area"))
    second_area = _clean_text(aligned_order_info.get("second_area"))
    second_area_id_value = _clean_text(aligned_order_info.get("second_area_id"))
    area_list = spu.get("areaList") or []
    matched_area = match_area_from_spu(area_list, area_scope, second_area, second_area_id_value) if isinstance(area_list, list) else {}
    second_area_id = _to_int(matched_area.get("managedRepairAreaId"))

    covered = any(
        _is_scope_match(item, spu_id, second_area_id)
        for item in scope_list
        if isinstance(item, dict)
    )
    if covered:
        return success_response(
            data=_build_result(
                checked=True,
                covered=True,
                reason="该商品在当前维保卡维保范围内，可下托管维修单",
                effective_service_type="托管维修",
                hosting_card=hosting_card,
                spu_detail=spu,
                second_area_id=second_area_id,
                interface_response=interface_response,
            ),
            message="hosting product is covered",
        )

    return success_response(
        data=_build_result(
            checked=True,
            covered=False,
            reason="该商品不在当前维保卡维保范围内，只能按单次维修下单",
            effective_service_type="单次维修服务",
            hosting_card=hosting_card,
            spu_detail=spu,
            second_area_id=second_area_id,
            interface_response=interface_response,
        ),
        message="hosting product is not covered",
    )
