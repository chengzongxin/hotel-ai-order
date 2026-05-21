import asyncio
from uuid import uuid4

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from tools.protocol import (
    ToolErrorCode,
    ToolResult,
    error_response,
    fallback_response,
    run_with_timeout,
    success_response,
)

DEFAULT_TOOL_TIMEOUT_SECONDS = 3.0


class SearchProductInput(BaseModel):
    keyword: str = Field(..., min_length=1, description="商品、设备或物品关键词")
    area: str | None = Field(default=None, description="问题区域，例如卫生间、卧室、客厅")


class CreateOrderInput(BaseModel):
    room_number: str = Field(..., min_length=1, description="房号")
    product: str = Field(..., min_length=1, description="商品、设备或物品")
    fault: str = Field(..., min_length=1, description="问题描述")
    area: str | None = Field(default=None, description="问题区域")
    urgency: str | None = Field(default=None, description="紧急度：low、medium、high、urgent")
    service_product_code: str | None = Field(default=None, description="商品编码，来自商品匹配")
    service_product_name: str | None = Field(default=None, description="商品名称，来自商品匹配")
    service_order_type: str | None = Field(default=None, description="下单类型，例如单次维修服务、单次安装")


class CheckPackageInput(BaseModel):
    room_number: str = Field(..., min_length=1, description="房号")
    product: str = Field(..., min_length=1, description="商品、设备或物品")


async def _search_product(keyword: str, area: str | None) -> ToolResult:
    await asyncio.sleep(0)

    product_catalog = [
        {"product_id": "air_conditioner", "name": "空调", "areas": ["卧室", "客厅"]},
        {"product_id": "faucet", "name": "水龙头", "areas": ["卫生间", "厨房"]},
        {"product_id": "door_lock", "name": "门锁", "areas": ["房门", "卧室"]},
        {"product_id": "television", "name": "电视", "areas": ["卧室", "客厅"]},
    ]
    matched_products = [
        item
        for item in product_catalog
        if keyword in item["name"] or keyword in item["product_id"]
    ]

    if area:
        matched_products = [
            item
            for item in matched_products
            if area in item["areas"]
        ] or matched_products

    if not matched_products:
        return fallback_response(
            message="未找到精确匹配的商品，已使用人工兜底分类",
            fallback={
                "fallback_type": "manual_product_classification",
                "next_action": "ask_staff_to_classify_product",
            },
            data={"keyword": keyword, "area": area},
        )

    return success_response(data={"products": matched_products})


async def _create_order(payload: CreateOrderInput) -> ToolResult:
    await asyncio.sleep(0)

    if payload.urgency not in {None, "low", "medium", "high", "urgent"}:
        return error_response(
            error_code=ToolErrorCode.INVALID_INPUT,
            message="urgency must be one of low, medium, high, urgent, or null",
            data={"urgency": payload.urgency},
        )

    order_id = f"ORDER-{uuid4().hex[:10].upper()}"
    return success_response(
        message="order created",
        data={
            "order_id": order_id,
            "room_number": payload.room_number,
            "product": payload.product,
            "fault": payload.fault,
            "area": payload.area,
            "urgency": payload.urgency or "medium",
            "service_product_code": payload.service_product_code,
            "service_product_name": payload.service_product_name,
            "service_order_type": payload.service_order_type,
        },
    )


async def _check_package(room_number: str, product: str) -> ToolResult:
    await asyncio.sleep(0)

    covered_products = {"空调", "电视", "门锁"}
    is_covered = product in covered_products

    return success_response(
        data={
            "room_number": room_number,
            "product": product,
            "is_covered": is_covered,
            "package_name": "基础客房维修包" if is_covered else None,
        }
    )


@tool(args_schema=SearchProductInput)
async def search_product_tool(keyword: str, area: str | None = None) -> ToolResult:
    """查询商品或设备，返回标准 JSON。"""

    return await run_with_timeout(
        action=lambda: _search_product(keyword=keyword, area=area),
        timeout_seconds=DEFAULT_TOOL_TIMEOUT_SECONDS,
        fallback=lambda: fallback_response(
            message="商品查询超时，已转人工分类",
            fallback={
                "fallback_type": "manual_product_classification",
                "next_action": "ask_staff_to_classify_product",
            },
            data={"keyword": keyword, "area": area},
        ),
    )


@tool(args_schema=CreateOrderInput)
async def create_order_tool(
    room_number: str,
    product: str,
    fault: str,
    area: str | None = None,
    urgency: str | None = None,
    service_product_code: str | None = None,
    service_product_name: str | None = None,
    service_order_type: str | None = None,
) -> ToolResult:
    """创建维修工单，返回标准 JSON。"""

    payload = CreateOrderInput(
        room_number=room_number,
        product=product,
        fault=fault,
        area=area,
        urgency=urgency,
        service_product_code=service_product_code,
        service_product_name=service_product_name,
        service_order_type=service_order_type,
    )
    return await run_with_timeout(
        action=lambda: _create_order(payload),
        timeout_seconds=DEFAULT_TOOL_TIMEOUT_SECONDS,
        fallback=lambda: fallback_response(
            message="创建维修工单超时，已生成待人工处理任务",
            fallback={
                "fallback_type": "manual_order",
                "next_action": "staff_create_order_manually",
            },
            data=payload.model_dump(),
        ),
    )


@tool(args_schema=CheckPackageInput)
async def check_package_tool(room_number: str, product: str) -> ToolResult:
    """检查房间或商品是否在维修服务包内，返回标准 JSON。"""

    return await run_with_timeout(
        action=lambda: _check_package(room_number=room_number, product=product),
        timeout_seconds=DEFAULT_TOOL_TIMEOUT_SECONDS,
        fallback=lambda: fallback_response(
            message="服务包查询超时，默认允许继续报修",
            fallback={
                "fallback_type": "allow_order_without_package_check",
                "next_action": "create_order_then_verify_package",
            },
            data={"room_number": room_number, "product": product},
        ),
    )
