import asyncio

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from tools.protocol import ToolResult, fallback_response, run_with_timeout, success_response

DEFAULT_TOOL_TIMEOUT_SECONDS = 3.0


class CheckPackageInput(BaseModel):
    room_number: str = Field(..., min_length=1, description="房号")
    product: str = Field(..., min_length=1, description="商品、设备或物品")


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
