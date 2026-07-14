"""Build and update the client-visible conversation timeline."""

from typing import Any
from uuid import uuid4

from schemas.chat import ConversationMessage
from schemas.order_preview import OrderPreview
from services.workflow_projection import build_order_preview_model


def _serialize(message: ConversationMessage) -> dict[str, Any]:
    return message.model_dump(mode="json")


def build_conversation_turn(
    *,
    human_content: str,
    ai_content: str,
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    """Create the two client messages produced by a completed user turn."""

    preview = build_order_preview_model(state)
    return [
        _serialize(
            ConversationMessage(
                id=str(uuid4()),
                role="human",
                content=human_content,
                order_preview=None,
            )
        ),
        _serialize(
            ConversationMessage(
                id=str(uuid4()),
                role="ai",
                content=ai_content,
                order_preview=preview,
            )
        ),
    ]


def update_active_conversation_preview(
    *,
    messages: list[dict[str, Any]],
    state: dict[str, Any],
    fallback_content: str,
) -> dict[str, Any]:
    """Update the latest workflow-bearing AI message after a silent form edit."""

    preview = build_order_preview_model(state)
    for raw in reversed(messages):
        if raw.get("role") != "ai" or raw.get("order_preview") is None:
            continue
        current = ConversationMessage.model_validate(raw)
        return _serialize(
            current.model_copy(update={"order_preview": preview})
        )

    return _serialize(
        ConversationMessage(
            id=str(uuid4()),
            role="ai",
            content=fallback_content,
            order_preview=preview,
        )
    )


def validate_conversation_messages(
    messages: list[dict[str, Any]] | None,
) -> list[ConversationMessage]:
    """Validate checkpoint data before returning it through the public API."""

    return [ConversationMessage.model_validate(item) for item in messages or []]
