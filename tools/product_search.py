from langchain_core.tools import tool
from pydantic import BaseModel, Field

from rag.product_store import get_product_store
from tools.protocol import ToolErrorCode, ToolResult, error_response, success_response


class ProductSearchInput(BaseModel):
    query: str = Field(..., min_length=1, description="向量检索用的查询词，例如：门锁 坏了")
    top_k: int = Field(default=5, ge=1, le=20, description="返回候选数量")
    threshold: float | None = Field(default=None, ge=0, le=1, description="相似度分数阈值")
    service_type: str | None = Field(default=None, description="只召回指定服务订单类型的商品")


@tool(args_schema=ProductSearchInput)
def search_product_tool(
    query: str,
    top_k: int = 5,
    threshold: float | None = None,
    service_type: str | None = None,
) -> ToolResult:
    """在商品库中向量检索最匹配的可下单商品，返回商品编码和订单类型等标准下单参数。"""
    try:
        store = get_product_store()
        products = store.search(
            query=query,
            top_k=top_k,
            threshold=threshold,
            service_type=service_type,
        )
    except (FileNotFoundError, ValueError) as exc:
        return error_response(
            error_code=ToolErrorCode.INVALID_INPUT,
            message=str(exc),
            data={"query": query, "service_type": service_type},
        )
    except Exception as exc:
        return error_response(
            error_code=ToolErrorCode.UPSTREAM_ERROR,
            message=f"product search failed: {exc}",
            data={"query": query, "service_type": service_type},
        )

    return success_response(
        data={
            "query": query,
            "service_type": service_type,
            "products": products,
            "count": len(products),
        }
    )
