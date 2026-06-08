from uuid import uuid4

from sqlalchemy import insert
from sqlalchemy.exc import SQLAlchemyError

from config.settings import settings
from config.database import conversation_logs, engine


async def save_conversation_log(session_id: str, role: str, content: str) -> None:
    if not settings.postgres_enabled:
        return

    try:
        async with engine.begin() as conn:
            await conn.execute(
                insert(conversation_logs).values(
                    id=str(uuid4()),
                    session_id=session_id,
                    role=role,
                    content=content,
                )
            )
    except SQLAlchemyError:
        # PostgreSQL 日志不能影响主对话流程；生产环境可接入结构化日志或告警。
        return
