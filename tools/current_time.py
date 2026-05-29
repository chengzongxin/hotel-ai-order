from datetime import UTC, datetime

from langchain_core.tools import tool


@tool
def current_time() -> str:
    """获取当前 UTC 时间。"""

    return datetime.now(UTC).isoformat()
