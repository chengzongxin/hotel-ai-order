from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from memory.readable_sqlite_saver import ReadableAsyncSqliteSaver


class ExampleState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    order_info: dict[str, Any]
    debug_context: dict[str, Any]
    step: str


def _checkpoint_columns(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        return [str(row[1]) for row in conn.execute("PRAGMA table_info(checkpoints)")]


async def test_setup_adds_state_json_to_existing_checkpoint_table(tmp_path: Path) -> None:
    db_path = tmp_path / "existing.sqlite3"

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        await saver.setup()

    assert "state_json" not in _checkpoint_columns(db_path)

    async with ReadableAsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        await saver.setup()
        await saver.setup()

    columns = _checkpoint_columns(db_path)
    assert columns.count("state_json") == 1


async def test_aput_stores_readable_state_json_next_to_blob(tmp_path: Path) -> None:
    db_path = tmp_path / "readable.sqlite3"

    def record_state(state: ExampleState) -> dict[str, Any]:
        return {
            "messages": [AIMessage(content="已收到")],
            "debug_context": {
                "recorded_at": datetime(2026, 7, 10, 3, 0, tzinfo=timezone.utc),
                "labels": {"checkpoint"},
            },
            "step": "record_state",
        }

    builder = StateGraph(ExampleState)
    builder.add_node("record_state", record_state)
    builder.add_edge(START, "record_state")
    builder.add_edge("record_state", END)

    async with ReadableAsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        graph = builder.compile(checkpointer=saver)
        await graph.ainvoke(
            {
                "messages": [HumanMessage(content="1208 房间空调不制冷")],
                "order_info": {"room_number": "1208", "fault": "空调不制冷"},
            },
            {"configurable": {"thread_id": "dev-user:test-session"}},
        )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT type, checkpoint, state_json
            FROM checkpoints
            WHERE state_json IS NOT NULL
            ORDER BY checkpoint_id DESC
            LIMIT 1
            """
        ).fetchone()
        room_number = conn.execute(
            """
            SELECT json_extract(state_json, '$.order_info.room_number')
            FROM checkpoints
            WHERE state_json IS NOT NULL
            ORDER BY checkpoint_id DESC
            LIMIT 1
            """
        ).fetchone()[0]

    assert row is not None
    checkpoint_type, checkpoint_blob, state_json = row
    assert checkpoint_type == "msgpack"
    assert isinstance(checkpoint_blob, bytes)
    assert checkpoint_blob
    assert room_number == "1208"

    readable_state = json.loads(state_json)
    assert readable_state["step"] == "record_state"
    assert readable_state["order_info"] == {
        "room_number": "1208",
        "fault": "空调不制冷",
    }
    assert readable_state["debug_context"] == {
        "recorded_at": "2026-07-10T03:00:00+00:00",
        "labels": ["checkpoint"],
    }
    assert [message["content"] for message in readable_state["messages"]] == [
        "1208 房间空调不制冷",
        "已收到",
    ]


async def test_backfill_decodes_legacy_checkpoint_blobs(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"

    builder = StateGraph(ExampleState)
    builder.add_node(
        "record_state",
        lambda state: {
            "step": "record_state",
            "order_info": {**state.get("order_info", {}), "status": "ready"},
        },
    )
    builder.add_edge(START, "record_state")
    builder.add_edge("record_state", END)

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        graph = builder.compile(checkpointer=saver)
        await graph.ainvoke(
            {"order_info": {"room_number": "0816"}},
            {"configurable": {"thread_id": "dev-user:legacy-session"}},
        )

    async with ReadableAsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        updated = await saver.abackfill_state_json(batch_size=1)

    with sqlite3.connect(db_path) as conn:
        missing_count = conn.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE state_json IS NULL"
        ).fetchone()[0]
        final_state_json = conn.execute(
            """
            SELECT state_json
            FROM checkpoints
            ORDER BY checkpoint_id DESC
            LIMIT 1
            """
        ).fetchone()[0]

    assert updated > 0
    assert missing_count == 0
    assert json.loads(final_state_json)["order_info"] == {
        "room_number": "0816",
        "status": "ready",
    }
