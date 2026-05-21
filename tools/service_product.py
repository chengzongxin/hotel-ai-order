from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from rag.service_product_retriever import get_service_product_retriever
from tools.protocol import ToolErrorCode, ToolResult, error_response, success_response


class ServiceProductRecallInput(BaseModel):
    query: str = Field(..., min_length=1, description="用户完整维修、安装、测量或托管服务描述")
    product: str | None = Field(default=None, description="已抽取出的商品或设备")
    fault: str | None = Field(default=None, description="已抽取出的故障现象")
    area: str | None = Field(default=None, description="已抽取出的区域")
    service_type_hint: str | None = Field(
        default=None,
        description="服务类型提示，例如 单次维修服务、单次安装、单次测量、托管维修",
    )
    top_k: int = Field(default=5, ge=1, le=20, description="返回候选数量")
    threshold: float | None = Field(default=None, ge=0, le=1, description="最终融合分数阈值")


@tool(args_schema=ServiceProductRecallInput)
def recall_service_product_tool(
    query: str,
    product: str | None = None,
    fault: str | None = None,
    area: str | None = None,
    service_type_hint: str | None = None,
    top_k: int = 5,
    threshold: float | None = None,
) -> ToolResult:
    """召回可下单服务商品，返回服务商品编码和服务类型等标准下单参数。"""

    inferred_hint: str | None = None
    try:
        retriever = get_service_product_retriever()
        inferred_hint = service_type_hint or retriever.infer_service_type_hint(
            " ".join(value for value in [query, product, fault, area] if value)
        )
        candidates = retriever.search(
            query=query,
            product=product,
            fault=fault,
            area=area,
            service_type_hint=inferred_hint,
            top_k=top_k,
            threshold=threshold,
        )
    except (FileNotFoundError, ValueError) as exc:
        return error_response(
            error_code=ToolErrorCode.INVALID_INPUT,
            message=str(exc),
            data={
                "query": query,
                "service_type_hint": inferred_hint,
            },
        )
    except Exception as exc:
        return error_response(
            error_code=ToolErrorCode.UPSTREAM_ERROR,
            message=f"service product recall failed: {exc}",
            data={
                "query": query,
                "service_type_hint": inferred_hint,
            },
        )

    best_match: dict[str, Any] | None = candidates[0] if candidates else None
    return success_response(
        data={
            "query": query,
            "service_type_hint": inferred_hint,
            "best_match": best_match,
            "candidates": candidates,
            "count": len(candidates),
        }
    )
