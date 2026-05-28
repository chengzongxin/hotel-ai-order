from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from rag.product_store import get_product_store
from tools.protocol import ToolErrorCode, ToolResult, error_response, success_response


class ProductMatchInput(BaseModel):
    query: str = Field(..., min_length=1, description="用户完整维修、安装、测量或托管服务描述")
    product: str | None = Field(default=None, description="已抽取出的商品或设备")
    fault: str | None = Field(default=None, description="已抽取出的故障现象")
    area: str | None = Field(default=None, description="已抽取出的区域")
    service_type_hint: str | None = Field(
        default=None,
        description="服务类型提示，例如 单次维修服务、单次安装、单次测量、托管维修",
    )
    top_k: int = Field(default=5, ge=1, le=20, description="返回候选数量")
    threshold: float | None = Field(default=None, ge=0, le=1, description="相似度分数阈值")


@tool(args_schema=ProductMatchInput)
def match_product_tool(
    query: str,
    product: str | None = None,
    fault: str | None = None,
    area: str | None = None,
    service_type_hint: str | None = None,
    top_k: int = 5,
    threshold: float | None = None,
) -> ToolResult:
    """匹配可下单商品，返回商品编码和订单类型等标准下单参数。"""

    search_query = " ".join(v for v in [product, fault] if v) or query
    try:
        store = get_product_store()
        candidates = store.search(query=search_query, top_k=top_k, threshold=threshold)
    except (FileNotFoundError, ValueError) as exc:
        return error_response(
            error_code=ToolErrorCode.INVALID_INPUT,
            message=str(exc),
            data={"query": search_query},
        )
    except Exception as exc:
        return error_response(
            error_code=ToolErrorCode.UPSTREAM_ERROR,
            message=f"product match failed: {exc}",
            data={"query": search_query},
        )

    best_match: dict[str, Any] | None = candidates[0] if candidates else None
    return success_response(
        data={
            "query": search_query,
            "service_type_hint": service_type_hint,
            "best_match": best_match,
            "candidates": candidates,
            "count": len(candidates),
        }
    )
