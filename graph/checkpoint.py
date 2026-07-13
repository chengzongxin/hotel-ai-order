"""LangGraph SQLite checkpoint 读写与会话状态访问。"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import BaseMessage

from config.settings import settings
from graph.prompts import PROMPTS_DIR
from graph.state import AgentState
from memory.readable_sqlite_saver import ReadableAsyncSqliteSaver
from schemas.user import UserContext, build_thread_id, require_user
from services.session_access import ensure_session_access


def checkpoint_path() -> Path:
    db_path = Path(settings.sqlite_memory_path)
    if not db_path.is_absolute():
        db_path = PROMPTS_DIR.parent / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def message_to_item(message: BaseMessage) -> dict[str, str]:
    role_map = {
        "human": "human",
        "ai": "ai",
        "system": "system",
    }
    return {
        "role": role_map.get(message.type, message.type),
        "content": str(message.content),
    }


def get_graph_config(user: UserContext, session_id: str) -> dict[str, object]:
    from graph.llm import get_llm_run_config

    thread_id = build_thread_id(user.user_id, session_id)
    return get_llm_run_config(
        {
            "configurable": {
                "thread_id": thread_id,
                "user_context": user.to_config_dict(),
            },
            "run_name": "order_graph",
            "tags": [
                "hotel-ai-order",
                "order",
                settings.app_env,
            ],
            "metadata": {
                "session_id": session_id,
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
                "app_env": settings.app_env,
            },
        }
    )


async def get_checkpoint_state(
    session_id: str,
    user: UserContext,
) -> AgentState:
    from graph.builder import build_graph

    active_user = require_user(user)
    async with ReadableAsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        snapshot = await graph.aget_state(get_graph_config(active_user, session_id))
        state = snapshot.values or {}
        if state:
            ensure_session_access(state, active_user)
        return state


async def get_checkpoint_messages(
    session_id: str,
    user: UserContext,
) -> list[dict[str, str]]:
    state = await get_checkpoint_state(session_id, user=user)
    return [message_to_item(message) for message in state.get("messages", [])]


async def clear_checkpoint_session(
    session_id: str,
    user: UserContext,
) -> None:
    active_user = require_user(user)
    thread_id = build_thread_id(active_user.user_id, session_id)
    async with ReadableAsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
        await checkpointer.setup()
        await checkpointer.adelete_thread(thread_id)
