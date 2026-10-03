"""使用者管理與個人密碼變更測試 (Test User Management & Password Change API)."""

import pytest
from httpx import ASGITransport, AsyncClient

from omnirss.core.database import DatabaseManager, set_global_db_manager
from omnirss.core.security import PasswordHasher, TokenManager
from omnirss.main import app


@pytest.mark.asyncio
async def test_user_management_and_password_lifecycle(tmp_path):
    """測試使用者修改密碼、管理員 CRUD、403 權限隔離與級聯清理 (Test full user lifecycle)."""
    db_file = tmp_path / "test_users_api.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 建立初始超級管理員 (admin)
        setup_res = await client.post(
            "/api/auth/setup",
            json={"username": "superadmin", "password": "adminPassword123"},
        )
        assert setup_res.status_code == 200

        # 登入 admin
        login_res = await client.post(
            "/api/auth/login",
            json={"username": "superadmin", "password": "adminPassword123"},
        )
        assert login_res.status_code == 200
        admin_token = login_res.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 2. 測試管理員建立一般使用者 (alice)
        create_res = await client.post(
            "/api/users",
            headers=admin_headers,
            json={"username": "alice", "password": "alicePassword123", "is_admin": False},
        )
        assert create_res.status_code == 201
        alice_data = create_res.json()
        assert alice_data["username"] == "alice"
        assert alice_data["is_admin"] is False
        alice_id = alice_data["id"]

        # 驗證重複帳號名稱拋出 409
        dup_res = await client.post(
            "/api/users",
            headers=admin_headers,
            json={"username": "alice", "password": "otherPassword123", "is_admin": False},
        )
        assert dup_res.status_code == 409

        # 3. 測試 Alice 登入與權限隔離 (非管理員存取 /api/users 應被 403 攔截)
        alice_login = await client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "alicePassword123"},
        )
        assert alice_login.status_code == 200
        alice_token = alice_login.json()["access_token"]
        alice_headers = {"Authorization": f"Bearer {alice_token}"}

        # Alice 嘗試列出所有使用者 -> 403 Forbidden
        forbidden_res = await client.get("/api/users", headers=alice_headers)
        assert forbidden_res.status_code == 403

        # 4. 測試 Alice 修改自身密碼
        # (a) 舊密碼輸入錯誤
        wrong_old_res = await client.put(
            "/api/user/password",
            headers=alice_headers,
            json={"old_password": "wrongPassword", "new_password": "aliceNewPassword888"},
        )
        assert wrong_old_res.status_code == 400

        # (b) 正確舊密碼
        pw_change_res = await client.put(
            "/api/user/password",
            headers=alice_headers,
            json={"old_password": "alicePassword123", "new_password": "aliceNewPassword888"},
        )
        assert pw_change_res.status_code == 200

        # (c) 用新密碼登入驗證
        new_login = await client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "aliceNewPassword888"},
        )
        assert new_login.status_code == 200

        # 5. 管理員列表查看使用者
        list_res = await client.get("/api/users", headers=admin_headers)
        assert list_res.status_code == 200
        users_list = list_res.json()
        assert len(users_list) == 2
        usernames = [u["username"] for u in users_list]
        assert "superadmin" in usernames
        assert "alice" in usernames

        # 6. 管理員更新 Alice (升級為管理員並強制重設密碼)
        update_res = await client.put(
            f"/api/users/{alice_id}",
            headers=admin_headers,
            json={"is_admin": True, "new_password": "forcedReset999"},
        )
        assert update_res.status_code == 200
        assert update_res.json()["is_admin"] is True

        # 7. 管理員刪除測試
        # (a) 管理員試圖自刪 -> 400 防呆
        admin_me_res = await client.get("/api/auth/me", headers=admin_headers)
        admin_id = admin_me_res.json()["id"]
        self_del_res = await client.delete(f"/api/users/{admin_id}", headers=admin_headers)
        assert self_del_res.status_code == 400

        # (b) 管理員刪除 Alice -> 204 No Content
        del_alice_res = await client.delete(f"/api/users/{alice_id}", headers=admin_headers)
        assert del_alice_res.status_code == 204

        # (c) 驗證 Alice 帳號已被徹底清除
        list_after_del = await client.get("/api/users", headers=admin_headers)
        assert len(list_after_del.json()) == 1
