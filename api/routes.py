import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from graph.builder import (
    clear_checkpoint_session,
    get_checkpoint_messages,
    get_checkpoint_state,
    run_agent,
    stream_agent_events,
)
from rag.product_store import get_product_store
from rag.spu_loader import SpuExcelLoader
from schemas.chat import ChatRequest, ChatResponse, HistoryResponse, MessageItem
from schemas.product import (
    ProductItem,
    ProductListResponse,
    ProductSearchRequest,
    ProductSearchResponse,
    ProductSearchResult,
)

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    result = await run_agent(
        user_message=request.message,
        session_id=request.session_id or request.conversation_id,
    )
    return ChatResponse(**result)


@router.post("/chat/stream")
async def stream_chat(request: ChatRequest) -> StreamingResponse:
    async def event_lines() -> AsyncIterator[str]:
        async for event in stream_agent_events(
            user_message=request.message,
            session_id=request.session_id or request.conversation_id,
        ):
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(
        event_lines(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/{session_id}/history", response_model=HistoryResponse)
async def get_history(session_id: str) -> HistoryResponse:
    messages = await get_checkpoint_messages(session_id)
    state = await get_checkpoint_state(session_id)
    return HistoryResponse(
        session_id=session_id,
        conversation_id=session_id,
        messages=[MessageItem(role=item["role"], content=item["content"]) for item in messages],
        conversation_summary=state.get("conversation_summary", ""),
    )


@router.delete("/chat/{session_id}", status_code=204)
async def clear_history(session_id: str) -> None:
    await clear_checkpoint_session(session_id)


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
    search_query = " ".join(
        v for v in [request.query, request.product, request.fault, request.area] if v
    )
    store = get_product_store()
    raw_results = store.search(query=search_query, top_k=request.top_k, threshold=request.threshold)
    results = [
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
        for r in raw_results
    ]
    return ProductSearchResponse(query=search_query, count=len(results), results=results)
