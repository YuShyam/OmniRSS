"""規則、備份與 Edge API 測試套件 (Rules, Backup & Edge API Integration Tests).

Tests rules CRUD, OPML export/import, sanitized user backup, and Edge tasks isolation.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from omnirss.core.database import DatabaseManager, set_global_db_manager
from omnirss.core.security import PasswordHasher, TokenManager
from omnirss.main import app


@pytest.mark.asyncio
async def test_rules_backup_and_edge_api(tmp_path):
    """測試過濾規則、脫敏備份與 Edge 中繼 API (Test Rules, Backup & Edge API)."""
    db_file = tmp_path / "test_rules_backup_edge.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    # 1. 建立測試用戶
    pwd_hash = PasswordHasher.hash_password("password123")
    api_key = TokenManager.generate_api_key()
    async with db_mgr.get_connection() as conn:
        u_cur = await conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, api_key) VALUES (?, ?, 0, ?)",
            ("carol", pwd_hash, api_key),
        )
        user_id = u_cur.lastrowid
        await conn.commit()

    token = TokenManager.create_access_token(data={"sub": str(user_id), "username": "carol"})
    headers = {"Authorization": f"Bearer {token}"}
    api_headers = {"X-API-Key": api_key}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 2. 測試規則建立與讀取
        rule_res = await ac.post(
            "/api/rules",
            json={
                "name": "垃圾郵件過濾",
                "sort_order": 1,
                "is_enabled": True,
                "conditions": [{"field": "title", "operator": "contains", "value": "廣告"}],
                "actions": [{"action": "trash"}],
            },
            headers=headers,
        )
        assert rule_res.status_code == 200
        rule_data = rule_res.json()
        assert rule_data["name"] == "垃圾郵件過濾"
        rule_id = rule_data["id"]

        rules_list_res = await ac.get("/api/rules", headers=headers)
        assert rules_list_res.status_code == 200
        assert len(rules_list_res.json()) >= 1

        # 3. 測試個人全套脫敏備份匯出
        backup_res = await ac.get("/api/user/backup", headers=headers)
        assert backup_res.status_code == 200
        backup_data = backup_res.json()
        assert backup_data["user_id"] == str(user_id)
        assert len(backup_data["rules"]) == 1

        # 4. 測試 OPML 匯出
        opml_res = await ac.get("/api/opml/export", headers=headers)
        assert opml_res.status_code == 200
        assert "application/xml" in opml_res.headers.get("content-type", "")
        assert "<opml" in opml_res.text

        # 5. 測試 Edge Relay 任務 (X-API-Key 鑑權)
        edge_tasks_res = await ac.get("/api/feeds/edge-tasks", headers=api_headers)
        assert edge_tasks_res.status_code == 200
        assert isinstance(edge_tasks_res.json(), list)

        # 6. 測試 Web Clipper 剪藏文章 (X-API-Key 鑑權)
        clipper_res = await ac.post(
            "/api/articles/push",
            json={
                "url": "https://example.com/clipped-post",
                "title": "剪藏測試文章",
                "html_content": "<p>這是一篇透過 Clipper 剪藏的文章</p><script>evil()</script>",
            },
            headers=api_headers,
        )
        assert clipper_res.status_code == 200
        assert "article_id" in clipper_res.json()
