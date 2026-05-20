from fastapi import APIRouter

from graph.builder import clear_checkpoint_session, get_checkpoint_messages, get_checkpoint_state, run_agent
from schemas.chat import ChatRequest, ChatResponse, HistoryResponse, MessageItem

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    result = await run_agent(
        user_message=request.message,
        session_id=request.session_id or request.conversation_id,
    )
    return ChatResponse(**result)


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
