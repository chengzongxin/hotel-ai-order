"""最新聊天主流程集成测试。

这些用例按当前产品逻辑重写：首轮命中商品后先进入 `product_selection`，
再通过文本选择或确定性接口进入 `pre_order`。测试重点是稳定状态字段，
不固定 LLM 的自然语言文案。
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

from graph.builder import (
    clear_checkpoint_session,
    confirm_order_in_session,
    run_agent,
    select_product_in_session,
    update_order_info_in_session,
)
from schemas.user import UserContext

pytestmark = pytest.mark.llm

DEFAULT_API_PARAMS = {
    # 与 frontend/src/utils/apiParams.ts 的开发默认值保持一致。
    "access_token": "replace-with-test-token",
    "user_id": "dev-user",
    "tenant_id": "2123",
    "platform": "ios",
    "app_type": "2",
    "device_id": "1234567890",
    "version": "1.1.2",
    "channel": "appstore",
    "spirit": "IDontKnowPasswordtoo/1708hxcchang",
}

TEST_USER = UserContext(
    user_id=os.getenv("TEST_USER_ID", DEFAULT_API_PARAMS["user_id"]),
    tenant_id=os.getenv("TEST_TENANT_ID", DEFAULT_API_PARAMS["tenant_id"]),
    access_token=os.getenv("TEST_ACCESS_TOKEN", DEFAULT_API_PARAMS["access_token"]),
    platform=os.getenv("TEST_PLATFORM", DEFAULT_API_PARAMS["platform"]),
    app_type=os.getenv("TEST_APP_TYPE", DEFAULT_API_PARAMS["app_type"]),
    device_id=os.getenv("TEST_DEVICE_ID", DEFAULT_API_PARAMS["device_id"]),
    version=os.getenv("TEST_APP_VERSION", DEFAULT_API_PARAMS["version"]),
    channel=os.getenv("TEST_APP_CHANNEL", DEFAULT_API_PARAMS["channel"]),
    spirit=os.getenv("TEST_APP_SPIRIT", DEFAULT_API_PARAMS["spirit"]),
)


def new_session() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


async def chat(session_id: str, message: str, trace_step=None) -> dict[str, Any]:
    result = await run_agent(user_message=message, session_id=session_id, user=TEST_USER)
    if trace_step:
        trace_step("chat turn", message=message, result=summarize_result(result))
    return result


async def clear_session(session_id: str) -> None:
    await clear_checkpoint_session(session_id, user=TEST_USER)


def preview(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("order_preview")
    assert isinstance(data, dict), f"expected order_preview, got: {result}"
    return data


def maybe_preview(result: dict[str, Any]) -> dict[str, Any] | None:
    data = result.get("order_preview")
    return data if isinstance(data, dict) else None


def info(result: dict[str, Any]) -> dict[str, Any]:
    return (maybe_preview(result) or {}).get("order_info") or {}


def phase(result: dict[str, Any]) -> str | None:
    return (maybe_preview(result) or {}).get("phase")


def missing(result: dict[str, Any]) -> list[str]:
    return (maybe_preview(result) or {}).get("missing_info") or []


def products(result: dict[str, Any]) -> list[dict[str, Any]]:
    section = (maybe_preview(result) or {}).get("products") or {}
    return section.get("items") or []


def selected_code(result: dict[str, Any]) -> str | None:
    section = (maybe_preview(result) or {}).get("products") or {}
    return section.get("selected_code")


def order_card_fields(result: dict[str, Any]) -> list[dict[str, Any]]:
    card = (maybe_preview(result) or {}).get("order_card") or {}
    return card.get("fields") or []


def product_codes(result: dict[str, Any]) -> list[str]:
    return [str(item.get("code")) for item in products(result) if item.get("code")]


def first_product_code(result: dict[str, Any]) -> str:
    codes = product_codes(result)
    assert codes, f"expected product candidates, got: {summarize_result(result)}"
    return codes[0]


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    data = maybe_preview(result)
    if not data:
        return {"answer": result.get("answer"), "order_preview": None}
    return {
        "answer": result.get("answer"),
        "phase": data.get("phase"),
        "order_info": data.get("order_info"),
        "service_type": data.get("service_type"),
        "effective_service_type": data.get("effective_service_type"),
        "missing_info": data.get("missing_info"),
        "selected_code": (data.get("products") or {}).get("selected_code"),
        "products": [
            {
                "code": item.get("code"),
                "name": item.get("name"),
                "service_type": item.get("service_type"),
                "score": item.get("score"),
            }
            for item in ((data.get("products") or {}).get("items") or [])
        ],
    }


async def select_first_product(session_id: str, first_result: dict[str, Any], trace_step=None) -> dict[str, Any]:
    code = first_product_code(first_result)
    result = await select_product_in_session(session_id=session_id, product_code=code, user=TEST_USER)
    if trace_step:
        trace_step("select first product", product_code=code, result=summarize_result(result))
    return result


def assert_product_selection(result: dict[str, Any]) -> None:
    assert phase(result) == "product_selection"
    assert products(result)
    assert selected_code(result) is None
    assert "选择" in str(result.get("answer", "")) or products(result)


class TestCurrentProductSelectionFlow:
    async def test_repair_first_turn_recommends_products(self, trace_step):
        sid = new_session()
        try:
            result = await chat(sid, "1208房间卧室空调不制冷，比较急。", trace_step)

            assert_product_selection(result)
            assert info(result).get("room_number") == "1208"
            assert info(result).get("product") == "空调"
            assert "制冷" in str(info(result).get("fault") or "")
            assert preview(result).get("service_type") in {"单次维修服务", "托管维修"}
        finally:
            await clear_session(sid)

    async def test_text_selection_moves_to_pre_order(self, trace_step):
        sid = new_session()
        try:
            first = await chat(sid, "816房间卫生间水龙头漏水。", trace_step)
            assert_product_selection(first)

            selected = await chat(sid, "第一个", trace_step)
            assert phase(selected) == "pre_order"
            assert selected_code(selected) == first_product_code(first)
            assert order_card_fields(selected)
            assert info(selected).get("room_number") == "816"
            assert info(selected).get("product")
        finally:
            await clear_session(sid)

    async def test_api_selection_moves_to_pre_order_and_builds_card(self, trace_step):
        sid = new_session()
        try:
            first = await chat(sid, "1208房间空调有问题。", trace_step)
            assert_product_selection(first)

            selected = await select_first_product(sid, first, trace_step)
            assert phase(selected) == "pre_order"
            assert selected_code(selected) == first_product_code(first)
            assert order_card_fields(selected)
            assert info(selected).get("room_number") == "1208"
            assert info(selected).get("product") == "空调"
        finally:
            await clear_session(sid)


class TestCurrentFieldValidationFlow:
    async def test_missing_room_or_time_is_checked_after_selection(self, trace_step):
        sid = new_session()
        try:
            first = await chat(sid, "卫生间水龙头漏水，麻烦来修一下。", trace_step)
            assert_product_selection(first)

            selected = await select_first_product(sid, first, trace_step)
            assert phase(selected) == "pre_order"
            assert missing(selected)

            # 最新流程中，必填项由“用户选中的商品服务类型”决定：
            # 托管维修通常追问房号；单次维修通常追问期望时间。
            assert set(missing(selected)) & {"room_number", "expected_start_time", "contacts", "phone"}
        finally:
            await clear_session(sid)

    async def test_update_order_info_recalculates_missing_fields(self, trace_step):
        sid = new_session()
        try:
            first = await chat(sid, "1208房间洗衣机需要安装。", trace_step)
            assert_product_selection(first)

            selected = await select_first_product(sid, first, trace_step)
            before_missing = set(missing(selected))
            assert phase(selected) == "pre_order"

            updated = await update_order_info_in_session(
                session_id=sid,
                updates={
                    "expected_time": "明天上午",
                    "goods_arrival_status": "已到场",
                    "contacts": "测试联系人",
                    "phone": "13600000000",
                },
                user=TEST_USER,
            )
            if trace_step:
                trace_step("update order info", before_missing=sorted(before_missing), result=summarize_result(updated))

            assert phase(updated) == "pre_order"
            assert "expected_start_time" not in missing(updated)
            assert "goods_arrival_status" not in missing(updated)
            assert info(updated).get("expected_start_time") == "明天上午"
            assert info(updated).get("goods_arrival_status") == "已到场"
        finally:
            await clear_session(sid)

    async def test_confirm_with_missing_fields_does_not_submit(self, trace_step):
        sid = new_session()
        try:
            first = await chat(sid, "1208房间洗衣机需要安装。", trace_step)
            assert_product_selection(first)
            selected = await select_first_product(sid, first, trace_step)

            result = await confirm_order_in_session(session_id=sid, user=TEST_USER)
            if trace_step:
                trace_step("confirm with missing fields", selected=summarize_result(selected), result=summarize_result(result))

            assert phase(result) == "pre_order"
            assert missing(result)
            submission = preview(result).get("submission") or {}
            assert submission.get("state") in {None, "not_attempted"}
        finally:
            await clear_session(sid)


class TestCurrentConversationControl:
    async def test_reject_products_returns_to_collecting(self, trace_step):
        sid = new_session()
        try:
            first = await chat(sid, "1208房间空调不制冷。", trace_step)
            assert_product_selection(first)

            rejected = await chat(sid, "以上都不符合", trace_step)
            assert phase(rejected) == "collecting"
            product_section = preview(rejected).get("products") or {}
            assert product_section.get("selection_rejected") is True
            assert product_section.get("items") == []
        finally:
            await clear_session(sid)

    async def test_cancel_active_order_clears_flow(self, trace_step):
        sid = new_session()
        try:
            first = await chat(sid, "1208房间空调不制冷。", trace_step)
            assert_product_selection(first)

            result = await chat(sid, "取消，不用了。", trace_step)
            # 取消后可以返回 cancelled/idle preview，也可以直接不返回 order_preview。
            assert maybe_preview(result) is None or phase(result) in {"cancelled", "idle"}
            assert products(result) == []
        finally:
            await clear_session(sid)

    async def test_smalltalk_does_not_create_order(self, trace_step):
        sid = new_session()
        try:
            result = await chat(sid, "你好，你是谁？", trace_step)
            data = maybe_preview(result)
            assert data is None or data.get("phase") in {None, "idle"}
            assert info(result) == {}
            assert result.get("answer")
        finally:
            await clear_session(sid)


class TestCurrentServiceTypeFlow:
    async def test_installation_query_recommends_install_products(self, trace_step):
        sid = new_session()
        try:
            result = await chat(sid, "1208房间洗衣机需要安装。", trace_step)
            assert_product_selection(result)

            names = " ".join(str(item.get("name") or "") for item in products(result))
            service_types = {item.get("service_type") for item in products(result)}
            assert "安装" in service_types or "安装" in names
        finally:
            await clear_session(sid)
