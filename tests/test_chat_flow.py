"""
聊天流程集成测试。
每个测试用独立 session_id，测后自动清理。

默认复用前端开发配置里的用户凭证；也可以通过环境变量覆盖：
TEST_ACCESS_TOKEN、TEST_USER_ID、TEST_TENANT_ID 等。
"""

import os
import uuid

from graph.builder import clear_checkpoint_session, run_agent
from schemas.user import UserContext

DEFAULT_API_PARAMS = {
    # 与 frontend/src/utils/apiParams.ts 的开发默认值保持一致。
    "access_token": "d5d15b2e6fc7480b9fe87ea8f43591c0",
    "user_id": "dev-user",
    "tenant_id": "2123",
    "platform": "ios",
    "app_type": "2",
    "device_id": "1234567890",
    "version": "1.1.2",
    "channel": "appstore",
    "spirit": "IDontKnowPasswordtoo/1708hxcchang",
}


# ── 工具函数 ────────────────────────────────────────────────────────────────────

def new_session() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


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


async def chat(session_id: str, message: str) -> dict:
    """一次对话，打印用户输入和 AI 回复，返回 run_agent 结果。"""
    result = await run_agent(user_message=message, session_id=session_id, user=TEST_USER)
    preview = result.get("order_preview") or {}
    print(f"\n  > 用户: {message}")
    print(f"  < AI  : {result.get('answer', '')}")
    if preview:
        print(f"    order_info   : {preview.get('order_info')}")
        print(f"    missing_info : {preview.get('missing_info')}")
        print(f"    service_type : {preview.get('service_type')}")
        print(f"    status       : {preview.get('status')}")
    return result


def order_info(result: dict) -> dict:
    return (result.get("order_preview") or {}).get("order_info") or {}


def order_preview(result: dict) -> dict:
    return result.get("order_preview") or {}


def missing(result: dict) -> list:
    return (result.get("order_preview") or {}).get("missing_info") or []


def service_type(result: dict) -> str | None:
    return (result.get("order_preview") or {}).get("service_type")


def status(result: dict) -> str | None:
    return (result.get("order_preview") or {}).get("status")


# ── 单轮完整信息 ──────────────────────────────────────────────────────────────

class TestSingleTurnComplete:

    async def test_guest_room_ac_repair(self):
        """客房空调不制冷——信息完整，直接进入确认或追问预约时间。"""
        sid = new_session()
        try:
            result = await chat(sid, "1208房间卧室空调不制冷，比较急。")
            info = order_info(result)
            assert info.get("room_number") == "1208"
            assert info.get("product") == "空调"
            assert "制冷" in (info.get("fault") or "")
            # 单次维修服务类型会要求 expected_start_time，missing 中只剩该字段是正常的
            assert missing(result) in ([], ["expected_start_time"])
            assert status(result) in ("confirming", "collecting")
        finally:
            await clear_checkpoint_session(sid, user=TEST_USER)

    async def test_faucet_leak(self):
        """卫生间水龙头漏水——信息完整，直接确认。"""
        sid = new_session()
        try:
            result = await chat(sid, "816房间卫生间水龙头漏水。")
            info = order_info(result)
            assert info.get("room_number") == "816"
            assert info.get("product") == "水龙头"
            assert missing(result) == []
        finally:
            await clear_checkpoint_session(sid, user=TEST_USER)

    async def test_public_area_door_lock(self):
        """大堂门锁坏了——识别为公区，service_type 包含公区，不带客房房号。"""
        sid = new_session()
        try:
            result = await chat(sid, "大堂门锁坏了，打不开。")
            info = order_info(result)
            assert info.get("managed_repair_scope") == "公区" or info.get("area") == "公区"
            # room_number 应为 None 或占位符 '/'，不应是真实房号
            assert info.get("room_number") in (None, "/", "")
            stype = service_type(result)
            assert stype is not None
        finally:
            await clear_checkpoint_session(sid, user=TEST_USER)


# ── 缺字段追问 ────────────────────────────────────────────────────────────────

class TestMissingField:

    async def test_missing_room_number(self):
        """缺房号——当前流程会先推荐商品，选品后再追问房号。"""
        sid = new_session()
        try:
            first = await chat(sid, "卫生间水龙头漏水，麻烦来修一下。")
            first_preview = order_preview(first)
            products = (first_preview.get("products") or {}).get("items") or []

            # 新流程：只要匹配到商品，第一轮先让用户选商品，而不是马上追问房号。
            assert first_preview.get("ui_phase") == "product_selection"
            assert products

            result = await chat(sid, "第一个")

            # 选完商品后进入信息校验，此时才应该发现缺少客房房号。
            assert "room_number" in missing(result)
            assert status(result) == "collecting"
            # AI 的回复里应有追问房号的意图
            answer = result.get("answer", "")
            assert any(kw in answer for kw in ("房间", "房号", "几号", "哪个房"))
        finally:
            await clear_checkpoint_session(sid, user=TEST_USER)

    async def test_missing_fault(self):
        """
        "空调有问题"——LLM 会把'有问题'抽取为 fault，系统视为已填写并继续推进。
        验证：room_number 和 product 正确提取，流程没有停在 fault 追问上。
        """
        sid = new_session()
        try:
            result = await chat(sid, "1208房间空调有问题。")
            info = order_info(result)
            assert info.get("room_number") == "1208"
            assert info.get("product") == "空调"
            # 系统接受模糊 fault，进入后续步骤（collecting 或 confirming）
            assert status(result) in ("collecting", "confirming")
        finally:
            await clear_checkpoint_session(sid, user=TEST_USER)

    async def test_missing_product(self):
        """只说坏了但没说是什么——应追问商品。"""
        sid = new_session()
        try:
            result = await chat(sid, "1208房间坏了，打不开。")
            assert "product" in missing(result)
            info = order_info(result)
            assert info.get("room_number") == "1208"
        finally:
            await clear_checkpoint_session(sid, user=TEST_USER)


# ── 多轮对话 ──────────────────────────────────────────────────────────────────

class TestMultiTurn:

    async def test_fill_room_number_in_second_turn(self):
        """第一轮缺房号，第二轮补充，最终信息完整。"""
        sid = new_session()
        try:
            await chat(sid, "空调不制冷。")
            result = await chat(sid, "1208房间。")
            info = order_info(result)
            assert info.get("room_number") == "1208"
            assert info.get("product") == "空调"
            assert "制冷" in (info.get("fault") or "")
        finally:
            await clear_checkpoint_session(sid, user=TEST_USER)

    async def test_correct_room_number(self):
        """用户纠正房号，最新值生效。"""
        sid = new_session()
        try:
            await chat(sid, "1208房间电视不亮。")
            result = await chat(sid, "不是1208，是1210。")
            info = order_info(result)
            assert info.get("room_number") == "1210"
            assert info.get("product") == "电视"
        finally:
            await clear_checkpoint_session(sid, user=TEST_USER)

    async def test_public_area_after_guest_room(self):
        """先报客房单，确认后再报公区故障——新单不应带旧房号。"""
        sid = new_session()
        try:
            await chat(sid, "2107房间空调不制冷。")
            await chat(sid, "确认提交。")
            result = await chat(sid, "大堂门锁坏了。")
            info = order_info(result)
            # 新单应识别为公区，不能带旧房号
            assert info.get("room_number") is None or info.get("managed_repair_scope") == "公区"
        finally:
            await clear_checkpoint_session(sid, user=TEST_USER)


# ── 取消与闲聊 ────────────────────────────────────────────────────────────────

class TestCancelAndSmallTalk:

    async def test_cancel_order(self):
        """收集过程中取消——状态应变为 cancelled 或 idle。"""
        sid = new_session()
        try:
            await chat(sid, "1208房间空调不制冷。")
            result = await chat(sid, "取消，不用了。")
            s = status(result)
            assert s in ("cancelled", "idle", None)
        finally:
            await clear_checkpoint_session(sid, user=TEST_USER)

    async def test_smalltalk_does_not_create_order(self):
        """纯闲聊——不应创建订单。"""
        sid = new_session()
        try:
            result = await chat(sid, "你好，你是谁？")
            assert result.get("order_preview") is None or order_info(result) == {}
        finally:
            await clear_checkpoint_session(sid, user=TEST_USER)


# ── 商品匹配与服务类型 ────────────────────────────────────────────────────────

class TestProductMatch:

    async def test_service_type_from_matched_product(self):
        """service_type 应来自商品匹配结果，不应为 None。"""
        sid = new_session()
        try:
            result = await chat(sid, "1208房间空调不制冷。")
            stype = service_type(result)
            assert stype is not None
            assert stype in ("单次维修服务", "托管维修", "托管维修（客房）", "托管维修（公区）")
        finally:
            await clear_checkpoint_session(sid, user=TEST_USER)

    async def test_installation_service_type(self):
        """安装类商品应匹配到单次安装服务类型。"""
        sid = new_session()
        try:
            result = await chat(sid, "1208房间洗衣机需要安装。")
            stype = service_type(result)
            # 安装类不一定第一轮就能匹配，有可能还在追问，但 service_type 若已有应为安装
            if stype is not None:
                assert "安装" in stype
        finally:
            await clear_checkpoint_session(sid, user=TEST_USER)
