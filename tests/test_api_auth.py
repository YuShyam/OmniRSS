"""身分認證 API 測試套件 (Auth API Integration Tests).

Tests setup, login, me, and key rotation endpoints.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from omnirss.core.database import DatabaseManager, set_global_db_manager
from omnirss.main import app


@pytest.mark.asyncio
async def test_auth_login_and_me(tmp_path):
    """測試登入流程與個人資料取得 (Test login and me endpoints)."""
    db_file = tmp_path / "test_auth_api.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. 首次設定管理員
        setup_res = await ac.post("/api/auth/setup", json={"username": "superadmin", "password": "password123"})
        assert setup_res.status_code == 200
        data = setup_res.json()
        assert data["username"] == "superadmin"
        assert data["is_admin"] is True

        # 2. 登入獲取 Token
        login_res = await ac.post("/api/auth/login", json={"username": "superadmin", "password": "password123"})
        assert login_res.status_code == 200
        token_data = login_res.json()
        token = token_data["access_token"]
        assert token is not None

        # 3. 攜帶 Token 查詢 /api/auth/me
        headers = {"Authorization": f"Bearer {token}"}
        me_res = await ac.get("/api/auth/me", headers=headers)
        assert me_res.status_code == 200
        me_data = me_res.json()
        assert me_data["username"] == "superadmin"
        assert me_data["is_admin"] is True

        # 4. 重新產生 API Key
        key_res = await ac.post("/api/auth/regenerate-key", headers=headers)
        assert key_res.status_code == 200
        assert "api_key" in key_res.json()

        # 5. 測試使用者設定讀取與更新 (GET/PUT /api/user/settings)
        settings_res = await ac.get("/api/user/settings", headers=headers)
        assert settings_res.status_code == 200
        assert "settings" in settings_res.json()

        update_settings = await ac.put(
            "/api/user/settings",
            json={"settings": {"theme": "midnight", "retentionDays": 90, "fontSize": "large"}},
            headers=headers,
        )
        assert update_settings.status_code == 200
        saved_settings = update_settings.json()["settings"]
        assert saved_settings["theme"] == "midnight"
        assert saved_settings["retentionDays"] == 90
        assert saved_settings["fontSize"] == "large"

        # 再次查詢確認持久化
        check_settings = await ac.get("/api/user/settings", headers=headers)
        assert check_settings.status_code == 200
        assert check_settings.json()["settings"]["theme"] == "midnight"

        # 6. 登出清除 Session Cookie
        logout_res = await ac.post("/api/auth/logout")
        assert logout_res.status_code == 200

        # 7. 測試未帶 Token 請求應回傳 401
        unauth_res = await ac.get("/api/auth/me")
        assert unauth_res.status_code == 401

