from typing import Any

import pytest

from api.routes import get_history
from graph.state import upsert_conversation_messages
from schemas.chat import ConversationResponse
from schemas.user import UserContext
from services.conversation_service import (
    build_conversation_turn,
    update_active_conversation_preview,
)


def workflow_state(*, phase: str = "product_selection") -> dict[str, Any]:
    return {
        "phase": phase,
        "product_request": {
            "room_number": "1208",
            "product": "空调",
            "fault": "不制冷",
        },
        "products": [
            {
                "service_product_code": "AC001",
                "service_product_name": "空调维修",
                "service_order_type": "托管维修",
            }
        ],
        "product_search_status": "success",
        "missing_info": [],
    }


def test_build_conversation_turn_attaches_preview_only_to_ai_message() -> None:
    messages = build_conversation_turn(
        human_content="1208空调不制冷",
        ai_content="请选择服务商品。",
        state=workflow_state(),
    )

    assert [message["role"] for message in messages] == ["human", "ai"]
    assert messages[0]["order_preview"] is None
    assert messages[1]["order_preview"]["phase"] == "product_selection"
    assert messages[0]["id"] != messages[1]["id"]


def test_upsert_conversation_messages_replaces_same_message_id() -> None:
    original = [{"id": "m1", "role": "ai", "content": "确认信息", "order_preview": {"phase": "pre_order"}}]
    updated = [{"id": "m1", "role": "ai", "content": "确认信息", "order_preview": {"phase": "submitted"}}]

    result = upsert_conversation_messages(original, updated)

    assert len(result) == 1
    assert result[0]["order_preview"]["phase"] == "submitted"


def test_form_edit_updates_latest_workflow_message_without_appending() -> None:
    messages = build_conversation_turn(
        human_content="选择空调维修",
        ai_content="请确认预下单信息。",
        state=workflow_state(phase="pre_order"),
    )
    active_id = messages[-1]["id"]
    updated_state = {
        **workflow_state(phase="pre_order"),
        "order": {"items": [{"id": "item-1", "product_code": "AC001", "product_name": "空调维修", "service_type": "托管维修", "quantity": 1, "room_number": "1208", "fault": "不制冷", "area": "客房", "product_snapshot": {"service_product_code": "AC001", "service_product_name": "空调维修", "service_order_type": "托管维修"}}]},
        "order_card_fields": [
            {
                "key": "contacts",
                "label": "联系人",
                "value": "李四",
                "source": "user",
                "input_type": "text",
            }
        ],
    }

    updated = update_active_conversation_preview(
        messages=messages,
        state=updated_state,
        fallback_content="已更新预下单信息。",
    )

    assert updated["id"] == active_id
    assert updated["content"] == "请确认预下单信息。"
    assert "value" not in updated["order_preview"]["form"]["fields"][0]
    assert updated["order_preview"]["order"]["contacts"] is None


@pytest.mark.asyncio
async def test_history_returns_only_client_conversation_messages(monkeypatch) -> None:
    conversation_messages = build_conversation_turn(
        human_content="1208空调不制冷",
        ai_content="请选择服务商品。",
        state=workflow_state(),
    )

    async def fake_get_checkpoint_state(session_id: str, user: UserContext):
        return {
            "messages": ["internal LangChain messages are not public"],
            "conversation_messages": conversation_messages,
        }

    monkeypatch.setattr("api.routes.get_checkpoint_state", fake_get_checkpoint_state)
    response = await get_history("session-1", user=UserContext(user_id="u1"))
    payload = ConversationResponse.model_validate(response).model_dump(mode="json")

    assert set(payload) == {"session_id", "conversation_messages"}
    assert payload["conversation_messages"] == conversation_messages
