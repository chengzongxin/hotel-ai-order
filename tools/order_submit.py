"""真实下单统一入口：按服务类型分发到托管或单次订单模块。"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from schemas.user import UserContext, user_from_runtime_config
from tools.order_context import load_managed_repair_order_context
from tools.order_payload_managed import build_managed_repair_order_payload
from tools.order_payload_single import (
    build_single_order_payload,
    query_single_order_app_spu,
    query_single_order_category_context,
)
from tools.order_submit_common import (
    CHECK_SINGLE_ORDER,
    CREATE_MANAGED_REPAIR_ORDER,
    CREATE_SINGLE_ORDER,
    HOSTING_CARD_GET,
    JsonDict,
    clean_text,
    extract_order_no,
    first_present,
    has_login_config,
    nested_dict,
    post_app,
    post_admin,
    query_spu_detail,
    query_spu_by_name,
    resolve_product_quantity,
)
from tools.protocol import ToolResult

# 兼容旧 import 路径（facade re-export）
_clean_text = clean_text
_post_app = post_app
_post_admin = post_admin
_has_login_config = has_login_config
_extract_order_no = extract_order_no
_first_present = first_present
_nested_dict = nested_dict


class SubmitOrderInput(BaseModel):
    order_info: JsonDict = Field(..., description="对话抽取出的订单信息")
    matched_product: JsonDict = Field(..., description="商品匹配工具返回的标准商品")
    service_type: str | None = Field(default=None, description="商品库匹配出的原始服务类型")
    effective_service_type: str | None = Field(default=None, description="最终用于提交的服务类型")
    coverage_result: JsonDict = Field(default_factory=dict, description="托管维修维保范围校验结果")
    submit: bool = Field(default=False, description="是否真实调用创建订单接口")


async def submit_real_order(
    order_info: JsonDict,
    matched_product: JsonDict,
    submit: bool,
    user: UserContext,
    service_type: str | None = None,
    effective_service_type: str | None = None,
    coverage_result: JsonDict | None = None,
) -> ToolResult:
    active_user = user
    order_context = await load_managed_repair_order_context(active_user)
    final_service_type = effective_service_type or service_type or matched_product.get("service_order_type")

    spu: JsonDict = {}
    spu_query_error: str | None = None
    try:
        result = await query_spu_detail(matched_product, active_user)
        if result:
            spu = result
    except Exception as exc:
        spu_query_error = f"{type(exc).__name__}: {exc}"

    if final_service_type == "托管维修":
        from tools.order_submit_managed import submit_managed_repair_order

        return await submit_managed_repair_order(
            order_info=order_info,
            matched_product=matched_product,
            spu=spu,
            order_context=order_context,
            submit=submit,
            user=active_user,
            service_type=service_type,
            coverage_result=coverage_result,
            spu_query_error=spu_query_error,
        )

    from tools.order_submit_single import submit_single_order

    return await submit_single_order(
        order_info=order_info,
        matched_product=matched_product,
        spu=spu,
        order_context=order_context,
        submit=submit,
        user=active_user,
        service_type=final_service_type,
        coverage_result=coverage_result,
        spu_query_error=spu_query_error,
    )


@tool(args_schema=SubmitOrderInput)
async def submit_real_order_tool(
    order_info: JsonDict,
    matched_product: JsonDict,
    service_type: str | None = None,
    effective_service_type: str | None = None,
    coverage_result: JsonDict | None = None,
    submit: bool = False,
) -> ToolResult:
    """查询商品详情并构造下单参数，在启用配置后调用真实下单接口。"""
    return await submit_real_order(
        order_info=order_info,
        matched_product=matched_product,
        service_type=service_type,
        effective_service_type=effective_service_type,
        coverage_result=coverage_result or {},
        submit=submit,
        user=user_from_runtime_config(),
    )


__all__ = [
    "CHECK_SINGLE_ORDER",
    "CREATE_MANAGED_REPAIR_ORDER",
    "CREATE_SINGLE_ORDER",
    "HOSTING_CARD_GET",
    "SubmitOrderInput",
    "build_managed_repair_order_payload",
    "build_single_order_payload",
    "load_managed_repair_order_context",
    "query_spu_detail",
    "query_single_order_app_spu",
    "query_single_order_category_context",
    "query_spu_by_name",
    "resolve_product_quantity",
    "submit_real_order",
    "submit_real_order_tool",
]
