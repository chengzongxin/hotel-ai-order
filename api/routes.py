import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from api.deps import get_current_user
from graph.builder import (
    build_order_preview,
    clear_checkpoint_session,
    confirm_order_in_session,
    get_checkpoint_messages,
    get_checkpoint_state,
    run_agent,
    select_product_in_session,
    stream_agent_events,
    update_order_info_in_session,
)
from rag.spu_loader import SpuExcelLoader
from schemas.chat import (
    ChatRequest,
    ChatResponse,
    HistoryResponse,
    MessageItem,
    SelectProductRequest,
    SelectProductResponse,
    UpdateOrderInfoRequest,
    UpdateOrderInfoResponse,
)
from schemas.product import (
    ProductItem,
    ProductListResponse,
    ProductSearchRequest,
    ProductSearchResponse,
    ProductSearchResult,
)
from schemas.user import SessionAccessError, UserContext
from tools.product_search import search_product_tool

router = APIRouter(tags=["chat"])


def _session_access_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="无权访问该会话",
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: UserContext = Depends(get_current_user),
) -> ChatResponse:
    try:
        result = await run_agent(
            user_message=request.message,
            session_id=request.session_id,
            user=user,
        )
    except SessionAccessError as exc:
        raise _session_access_error() from exc
    return ChatResponse(**result)


@router.post("/chat/stream")
async def stream_chat(
    request: ChatRequest,
    user: UserContext = Depends(get_current_user),
) -> StreamingResponse:
    """流式对话，响应为 NDJSON（每行一个 JSON 事件）。

    事件类型：session / status / preview / token / final / error。
    字段定义见 `docs/api_order_preview.md`。
    """
    async def event_lines() -> AsyncIterator[str]:
        try:
            async for event in stream_agent_events(
                user_message=request.message,
                session_id=request.session_id,
                user=user,
            ):
                yield json.dumps(event, ensure_ascii=False, default=str) + "\n"
        except SessionAccessError as exc:
            yield json.dumps(
                {"type": "error", "message": str(exc)},
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(
        event_lines(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/{session_id}/select-product", response_model=SelectProductResponse)
async def select_product(
    session_id: str,
    request: SelectProductRequest,
    user: UserContext = Depends(get_current_user),
) -> SelectProductResponse:
    """前端点选商品卡片后调用，更新当前会话的选中商品。"""
    try:
        result = await select_product_in_session(
            session_id=session_id,
            product_code=request.product_code,
            user=user,
        )
    except SessionAccessError as exc:
        raise _session_access_error() from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SelectProductResponse(**result)


@router.patch("/chat/{session_id}/order-info", response_model=UpdateOrderInfoResponse)
async def update_order_info(
    session_id: str,
    request: UpdateOrderInfoRequest,
    user: UserContext = Depends(get_current_user),
) -> UpdateOrderInfoResponse:
    """前端编辑预下单卡片字段后调用，更新当前会话的订单信息。"""
    try:
        result = await update_order_info_in_session(
            session_id=session_id,
            updates=request.updates,
            user=user,
        )
    except SessionAccessError as exc:
        raise _session_access_error() from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UpdateOrderInfoResponse(**result)


@router.post("/chat/{session_id}/confirm", response_model=ChatResponse)
async def confirm_order(
    session_id: str,
    user: UserContext = Depends(get_current_user),
) -> ChatResponse:
    """前端确认按钮的确定性提交接口，不再依赖 LLM 重新识别“确认”。"""
    try:
        result = await confirm_order_in_session(session_id=session_id, user=user)
    except SessionAccessError as exc:
        raise _session_access_error() from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ChatResponse(**result)


@router.get("/chat/{session_id}/history", response_model=HistoryResponse)
async def get_history(
    session_id: str,
    user: UserContext = Depends(get_current_user),
) -> HistoryResponse:
    try:
        messages = await get_checkpoint_messages(session_id, user=user)
        state = await get_checkpoint_state(session_id, user=user)
    except SessionAccessError as exc:
        raise _session_access_error() from exc
    return HistoryResponse(
        session_id=session_id,
        messages=[MessageItem(role=item["role"], content=item["content"]) for item in messages],
        conversation_summary=state.get("conversation_summary", ""),
        order_preview=build_order_preview(state),
    )


@router.delete("/chat/{session_id}", status_code=204)
async def clear_history(
    session_id: str,
    user: UserContext = Depends(get_current_user),
) -> None:
    try:
        await get_checkpoint_state(session_id, user=user)
    except SessionAccessError as exc:
        raise _session_access_error() from exc
    await clear_checkpoint_session(session_id, user=user)


@router.get("/products", response_model=ProductListResponse, tags=["products"])
async def list_products(
    service_type: str | None = Query(default=None, description="按服务类型筛选"),
) -> ProductListResponse:
    records = SpuExcelLoader().load()
    if service_type:
        records = [r for r in records if r.service_order_type == service_type]
    items = [
        ProductItem(
            service_product_code=r.service_product_code,
            service_product_name=r.service_product_name,
            product_type=r.product_type,
            category=r.category,
            service_order_type=r.service_order_type,
            unit=r.unit,
            price=r.price,
            price_status=r.price_status,
            related_category=r.related_category,
            related_area=r.related_area,
            fault_phenomenon=r.fault_phenomenon,
            remark=r.remark,
        )
        for r in records
    ]
    return ProductListResponse(total=len(items), items=items)


@router.post("/products/search", response_model=ProductSearchResponse, tags=["products"])
async def search_products(request: ProductSearchRequest) -> ProductSearchResponse:
    result = await asyncio.to_thread(
        search_product_tool.invoke,
        {"query": request.query, "top_k": request.top_k, "threshold": request.threshold},
    )
    data = result.get("data", {})
    products = data.get("products") or []
    mapped_products = [
        ProductSearchResult(
            score=r["score"],
            service_product_code=r["service_product_code"],
            service_product_name=r["service_product_name"],
            service_order_type=r["service_order_type"],
            product_type=r["product_type"],
            related_area=r["related_area"],
            fault_phenomenon=r["fault_phenomenon"],
            price=r["price"],
            unit=r["unit"],
        )
        for r in products
    ]
    return ProductSearchResponse(
        query=data.get("query", request.query),
        count=len(mapped_products),
        products=mapped_products,
    )
