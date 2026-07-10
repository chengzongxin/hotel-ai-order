"""Backfill readable ``state_json`` values for legacy LangGraph checkpoints."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from graph.checkpoint import checkpoint_path
from memory.readable_sqlite_saver import ReadableAsyncSqliteSaver


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill checkpoints.state_json from canonical checkpoint BLOBs.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite path; defaults to SQLITE_MEMORY_PATH.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Rows committed per batch (default: 25).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum rows to backfill; omit to process every missing row.",
    )
    return parser.parse_args()


async def run() -> None:
    args = parse_args()
    db_path = (args.db or checkpoint_path()).resolve()

    async with ReadableAsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        updated = await saver.abackfill_state_json(
            batch_size=args.batch_size,
            limit=args.limit,
        )

    print(f"Backfilled {updated} checkpoint row(s) in {db_path}")


if __name__ == "__main__":
    asyncio.run(run())
