import pytest

from schemas.user import UserContext
from services import auth_service
from services.auth_service import LoginRequiredError, ensure_user_logged_in


TEST_USER = UserContext(
    user_id="u1",
    tenant_id="2131",
    access_token="token",
)


@pytest.mark.asyncio
async def test_ensure_user_logged_in_returns_profile(monkeypatch):
    async def fake_fetch_login_profile(user):
        return {"code": 200, "data": {"userId": "QY1"}, "msg": ""}

    monkeypatch.setattr(auth_service, "fetch_login_profile", fake_fetch_login_profile)

    profile = await ensure_user_logged_in(TEST_USER)

    assert profile == {"userId": "QY1"}


@pytest.mark.asyncio
async def test_ensure_user_logged_in_rejects_invalid_profile(monkeypatch):
    async def fake_fetch_login_profile(user):
        return {"code": 401, "data": None, "msg": "token expired"}

    monkeypatch.setattr(auth_service, "fetch_login_profile", fake_fetch_login_profile)

    with pytest.raises(LoginRequiredError, match="token expired"):
        await ensure_user_logged_in(TEST_USER)
