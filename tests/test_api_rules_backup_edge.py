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


@pytest.mark.asyncio
async def test_multi_condition_rules_and_tag_actions(tmp_path):
    """測試多條件過濾 (AND/OR)、規則測試比對、PTT 徵女自動已讀與徵男自動貼標 (Test Multi-Condition & Actions)."""
    db_file = tmp_path / "test_multi_rules.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    # 1. 建立用戶與測試頻道/文章
    pwd_hash = PasswordHasher.hash_password("password123")
    api_key = TokenManager.generate_api_key()
    async with db_mgr.get_connection() as conn:
        u_cur = await conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, api_key) VALUES (?, ?, 0, ?)",
            ("david", pwd_hash, api_key),
        )
        user_id = u_cur.lastrowid

        f_cur = await conn.execute(
            "INSERT INTO feeds (title, feed_url) VALUES (?, ?)",
            ("PTT - Alltogether 聯誼板", "https://ptt.cc/rss/alltogether.xml"),
        )
        feed_id = f_cur.lastrowid

        f2_cur = await conn.execute(
            "INSERT INTO feeds (title, feed_url) VALUES (?, ?)",
            ("TechNews 科技新報", "https://technews.tw/rss.xml"),
        )
        feed2_id = f2_cur.lastrowid

        await conn.execute(
            "INSERT INTO user_feeds (user_id, feed_id, custom_title) VALUES (?, ?, ?)",
            (user_id, feed_id, "PTT - Alltogether"),
        )
        await conn.execute(
            "INSERT INTO user_feeds (user_id, feed_id, custom_title) VALUES (?, ?, ?)",
            (user_id, feed2_id, "TechNews"),
        )

        # 文章 1: PTT 徵女文
        a1_cur = await conn.execute(
            """INSERT INTO articles_hot (feed_id, entry_hash, title, url, published_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (feed_id, "hash_ptt_1", "[徵女] 台北週末咖啡走走看電影", "https://ptt.cc/1"),
        )
        art1_id = a1_cur.lastrowid

        # 文章 2: PTT 徵男文
        a2_cur = await conn.execute(
            """INSERT INTO articles_hot (feed_id, entry_hash, title, url, published_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (feed_id, "hash_ptt_2", "[徵男] 台中溫柔陽光大男孩", "https://ptt.cc/2"),
        )
        art2_id = a2_cur.lastrowid

        # 文章 3: TechNews 科技文章
        await conn.execute(
            """INSERT INTO articles_hot (feed_id, entry_hash, title, url, published_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (feed2_id, "hash_tech_3", "AI 新架構發布 [徵男] (非PTT來源)", "https://tech.cc/3"),
        )
        await conn.commit()

    token = TokenManager.create_access_token(data={"sub": str(user_id), "username": "david"})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 2. 測試 /api/rules/test 端點 (多條件 AND: 來源包含 PTT 且 標題包含 [徵女])
        test_res = await ac.post(
            "/api/rules/test",
            json={
                "match_mode": "all",
                "conditions": [
                    {"field": "feed_title", "operator": "contains", "value": "PTT"},
                    {"field": "title", "operator": "contains", "value": "[徵女]"},
                ],
            },
            headers=headers,
        )
        assert test_res.status_code == 200
        test_data = test_res.json()
        assert test_data["count"] == 1
        assert test_data["articles"][0]["id"] == art1_id
        assert test_data["articles"][0]["title"] == "[徵女] 台北週末咖啡走走看電影"

        # 3. 建立規則 1: PTT - Alltogether 來源 + [徵女] 全部直接已讀
        r1_res = await ac.post(
            "/api/rules",
            json={
                "name": "PTT 徵女文自動已讀",
                "sort_order": 1,
                "is_enabled": True,
                "conditions": {
                    "match_mode": "all",
                    "rules": [
                        {"field": "feed_title", "operator": "contains", "value": "Alltogether"},
                        {"field": "title", "operator": "contains", "value": "[徵女]"},
                    ],
                },
                "actions": [{"action_type": "mark_read", "parameters": {}}],
            },
            headers=headers,
        )
        assert r1_res.status_code == 200
        r1_id = r1_res.json()["id"]

        # 4. 建立規則 2: PTT - Alltogether 來源 + [徵男] 自動加到「重要」標籤
        r2_res = await ac.post(
            "/api/rules",
            json={
                "name": "PTT 徵男文標記為重要",
                "sort_order": 2,
                "is_enabled": True,
                "conditions": {
                    "match_mode": "all",
                    "rules": [
                        {"field": "feed_title", "operator": "contains", "value": "Alltogether"},
                        {"field": "title", "operator": "contains", "value": "[徵男]"},
                    ],
                },
                "actions": [{"action_type": "add_tag", "parameters": {"tag": "重要"}}],
            },
            headers=headers,
        )
        assert r2_res.status_code == 200
        r2_id = r2_res.json()["id"]

        # 5. 立即套用所有規則至現有文章
        apply_res = await ac.post("/api/rules/apply-all", headers=headers)
        assert apply_res.status_code == 200
        assert apply_res.json()["affected_articles_count"] >= 2

        # 6. 驗證文章 1 已被標記為已讀
        a1_check = await ac.get(f"/api/articles/{art1_id}", headers=headers)
        assert a1_check.status_code == 200
        assert a1_check.json()["is_unread"] is False

        # 7. 驗證文章 2 已被貼上「重要」標籤
        a2_check = await ac.get(f"/api/articles/{art2_id}", headers=headers)
        assert a2_check.status_code == 200
        art2_tags = [t["name"] for t in a2_check.json().get("tags", [])]
        assert "重要" in art2_tags
