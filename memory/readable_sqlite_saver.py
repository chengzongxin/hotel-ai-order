"""LangGraph SQLite saver with a human-readable state projection.

LangGraph keeps the canonical checkpoint in its serialized BLOB column.  This
subclass adds a nullable ``state_json`` column to the same row and stores the
checkpoint's ``channel_values`` there for inspection with ordinary SQLite
tools.  The JSON projection is never used to restore graph state.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


STATE_JSON_COLUMN = "state_json"


def _json_default(value: Any) -> Any:
    """Convert common state objects into inspection-friendly JSON values."""

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except (TypeError, ValueError):
            return model_dump()

    if isinstance(value, set | frozenset):
        return list(value)

    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()

    return str(value)


def checkpoint_state_to_json(checkpoint: Checkpoint) -> str:
    """Serialize the checkpoint's AgentState channels as compact UTF-8 JSON."""

    return json.dumps(
        checkpoint.get("channel_values", {}),
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default,
    )


class ReadableAsyncSqliteSaver(AsyncSqliteSaver):
    """Persist canonical checkpoints plus a readable JSON projection."""

    async def setup(self) -> None:
        await super().setup()

        if getattr(self, "_readable_schema_ready", False):
            return

        async with self.lock:
            if getattr(self, "_readable_schema_ready", False):
                return

            async with self.conn.execute("PRAGMA table_info(checkpoints)") as cursor:
                columns = {str(row[1]) for row in await cursor.fetchall()}

            if STATE_JSON_COLUMN not in columns:
                try:
                    await self.conn.execute(
                        f"ALTER TABLE checkpoints ADD COLUMN {STATE_JSON_COLUMN} TEXT"
                    )
                    await self.conn.commit()
                except sqlite3.OperationalError as exc:
                    # Different saver instances can race during the first startup.
                    # SQLite serializes the DDL, so the second one only needs to
                    # tolerate the column having been created by the first.
                    if "duplicate column name" not in str(exc).lower():
                        raise

            self._readable_schema_ready = True

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Store the BLOB and readable state JSON in the same transaction."""

        await self.setup()
        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        checkpoint_ns = str(configurable.get("checkpoint_ns", ""))
        checkpoint_id = str(checkpoint["id"])
        parent_checkpoint_id = configurable.get("checkpoint_id")

        type_, serialized_checkpoint = self.serde.dumps_typed(checkpoint)
        serialized_metadata = json.dumps(
            get_checkpoint_metadata(config, metadata),
            ensure_ascii=False,
        ).encode("utf-8", "ignore")
        state_json = checkpoint_state_to_json(checkpoint)

        async with (
            self.lock,
            self.conn.execute(
                """
                INSERT OR REPLACE INTO checkpoints (
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                    parent_checkpoint_id,
                    type,
                    checkpoint,
                    metadata,
                    state_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                    parent_checkpoint_id,
                    type_,
                    serialized_checkpoint,
                    serialized_metadata,
                    state_json,
                ),
            ),
        ):
            await self.conn.commit()

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def abackfill_state_json(
        self,
        *,
        batch_size: int = 25,
        limit: int | None = None,
    ) -> int:
        """Populate ``state_json`` for legacy checkpoint rows in batches.

        This is intentionally opt-in because a full backfill can substantially
        increase database size and hold write locks while each batch commits.
        """

        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        if limit is not None and limit < 0:
            raise ValueError("limit must be zero or greater")

        await self.setup()
        updated_count = 0

        while limit is None or updated_count < limit:
            current_batch_size = batch_size
            if limit is not None:
                current_batch_size = min(batch_size, limit - updated_count)
            if current_batch_size == 0:
                break

            async with self.lock:
                async with self.conn.execute(
                    """
                    SELECT
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id,
                        type,
                        checkpoint
                    FROM checkpoints
                    WHERE state_json IS NULL
                    ORDER BY checkpoint_id
                    LIMIT ?
                    """,
                    (current_batch_size,),
                ) as cursor:
                    rows = await cursor.fetchall()

            if not rows:
                break

            updates: list[tuple[str, str, str, str]] = []
            for thread_id, checkpoint_ns, checkpoint_id, type_, checkpoint_blob in rows:
                checkpoint = self.serde.loads_typed((str(type_), bytes(checkpoint_blob)))
                updates.append(
                    (
                        checkpoint_state_to_json(checkpoint),
                        str(thread_id),
                        str(checkpoint_ns),
                        str(checkpoint_id),
                    )
                )

            async with self.lock:
                await self.conn.executemany(
                    """
                    UPDATE checkpoints
                    SET state_json = ?
                    WHERE thread_id = ?
                      AND checkpoint_ns = ?
                      AND checkpoint_id = ?
                      AND state_json IS NULL
                    """,
                    updates,
                )
                await self.conn.commit()

            updated_count += len(updates)

        return updated_count
