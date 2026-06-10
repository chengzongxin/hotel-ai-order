from __future__ import annotations

from typing import Any

from schemas.user import UserContext
from tools.order_submit import fetch_hosting_card, query_spu_by_name
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

    for item in area_list:
        if not isinstance(item, dict):
            continue
        parent_name = _clean_text(item.get("managedRepairAreaParentName"))
        if parent_name and parent_name == area_scope:
            return item

    return area_list[0] if area_list and isinstance(area_list[0], dict) else {}


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
    covered: bool,
    reason: str,
    effective_service_type: str,
    hosting_card: JsonDict | None = None,
    spu_detail: JsonDict | None = None,
    second_area_id: int | None = None,
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
        "second_area_id": second_area_id,
    }


async def check_hosting_product_coverage(
    order_info: JsonDict,
    matched_product: JsonDict,
    user: UserContext,
) -> ToolResult:
    """检查托管维修商品是否在当前用户维保卡范围内。

    维保卡范围以后端返回的 scopeRepairSpuIdList 为准。命中时继续托管维修；
    未命中、无维保卡或查询失败时，保守降级为单次维修服务。
    """

    product_name = _clean_text(matched_product.get("service_product_name"))
    if not product_name:
        return error_response(
            error_code=ToolErrorCode.INVALID_INPUT,
            message="cannot check hosting coverage without matched product name",
            data=_build_result(
                checked=False,
                covered=False,
                reason="缺少匹配商品名称，无法校验维保范围",
                effective_service_type="单次维修服务",
            ),
        )

    hosting_card = await fetch_hosting_card(user)
    if not hosting_card:
        return success_response(
            data=_build_result(
                checked=True,
                covered=False,
                reason="当前用户没有可用维保卡，只能按单次维修下单",
                effective_service_type="单次维修服务",
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
            ),
            message="hosting card scope is empty",
        )

    try:
        spu = await query_spu_by_name(product_name, user)
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
            ),
            message="managed repair spu id is missing",
        )

    area_scope = _clean_text(order_info.get("managed_repair_scope") or order_info.get("area"))
    matched_area = _match_area_from_spu(spu, area_scope)
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
        ),
        message="hosting product is not covered",
    )
