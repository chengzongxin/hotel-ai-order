"""Conversation ownership checks shared by graph and command services."""

from collections.abc import Mapping
from typing import Any

from schemas.user import SessionAccessError, UserContext


def ensure_session_access(state: Mapping[str, Any], user: UserContext) -> None:
    stored_user_id = state.get("user_id")
    if stored_user_id and stored_user_id != user.user_id:
        raise SessionAccessError("无权访问该会话")
