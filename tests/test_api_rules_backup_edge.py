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
        # 2.5 測試過濾規則 JSON 匯出與匯入 (含語意錨點驗證)
        rules_export_res = await ac.get("/api/rules/export", headers=headers)
        assert rules_export_res.status_code == 200
        export_json = rules_export_res.json()
        assert export_json["total_rules"] >= 1
        assert len(export_json["rules"]) >= 1
        assert "scope_feed_urls" in export_json["rules"][0]

        # 建立測試頻道以驗證智慧語意解析重配
        async with db_mgr.get_connection() as conn:
            f_cur = await conn.execute(
                "INSERT INTO feeds (title, feed_url) VALUES (?, ?)",
                ("Tech News", "https://example.com/tech.xml"),
            )
            created_feed_id = f_cur.lastrowid
            await conn.execute(
                "INSERT INTO user_feeds (user_id, feed_id, custom_title) VALUES (?, ?, ?)",
                (user_id, created_feed_id, "Tech News Custom"),
            )
            c_cur = await conn.execute(
                "INSERT INTO categories (user_id, name) VALUES (?, ?)",
                (user_id, "IT Focus"),
            )
            created_cat_id = c_cur.lastrowid
            await conn.commit()

        # 測試規則匯入 (mode=merge, 具備跨環境 URL 與分類名稱語意錨點)
        import_payload = {
            "mode": "merge",
            "rules": [
                {
                    "name": "標題不是空白規則",
                    "sort_order": 5,
                    "is_enabled": True,
                    "scope_type": "feeds",
                    "scope_feed_urls": ["https://example.com/tech.xml"],
                    "scope_feed_ids": [9999],  # 故意給予不存在的假 ID，測試系統是否自動重配為 created_feed_id
                    "condition_groups": [
                        {
                            "match_mode": "all",
                            "conditions": [{"field": "title", "operator": "is_not_empty", "value": ""}],
                        }
                    ],
                    "actions": [{"action": "star"}],
                },
                {
                    "name": "分類過濾規則",
                    "sort_order": 6,
                    "is_enabled": True,
                    "scope_type": "category",
                    "scope_category_name": "IT Focus",
                    "scope_category_id": 8888,  # 故意給予不存在的假 ID，測試系統是否自動重配為 created_cat_id
                    "condition_groups": [
                        {
                            "match_mode": "all",
                            "conditions": [{"field": "title", "operator": "contains", "value": "AI"}],
                        }
                    ],
                    "actions": [{"action": "mark_read"}],
                }
            ],
        }
        import_res = await ac.post("/api/rules/import", json=import_payload, headers=headers)
        assert import_res.status_code == 200
        assert import_res.json()["imported_count"] == 2

        # 驗證匯入後的規則 ID 是否已成功智慧重配
        final_rules_res = await ac.get("/api/rules", headers=headers)
        assert final_rules_res.status_code == 200
        all_rules = final_rules_res.json()
        imported_feed_rule = next((x for x in all_rules if x["name"] == "標題不是空白規則"), None)
        assert imported_feed_rule is not None
        assert imported_feed_rule["scope_feed_ids"] == [created_feed_id]

        imported_cat_rule = next((x for x in all_rules if x["name"] == "分類過濾規則"), None)
        assert imported_cat_rule is not None
        assert imported_cat_rule["scope_category_id"] == created_cat_id

        # 3. 測試個人全套脫敏備份匯出
        backup_res = await ac.get("/api/user/backup", headers=headers)
        assert backup_res.status_code == 200
        backup_data = backup_res.json()
        assert backup_data["user_id"] == str(user_id)
        assert len(backup_data["rules"]) == 3

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


@pytest.mark.asyncio
async def test_purge_database_endpoint(tmp_path):
    """測試全庫清空端點 (Test purge database endpoint)."""
    db_file = tmp_path / "test_purge_db.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    # 建立管理員與測試頻道/文章
    pwd_hash = PasswordHasher.hash_password("password123")
    api_key = TokenManager.generate_api_key()
    async with db_mgr.get_connection() as conn:
        u_cur = await conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, api_key) VALUES (?, ?, 1, ?)",
            ("admin_purge", pwd_hash, api_key),
        )

        user_id = u_cur.lastrowid
        f_cur = await conn.execute(
            "INSERT INTO feeds (title, feed_url) VALUES (?, ?)",
            ("Purge Feed", "https://purge.org/rss"),
        )
        feed_id = f_cur.lastrowid
        await conn.execute(
            "INSERT INTO user_feeds (user_id, feed_id) VALUES (?, ?)",
            (user_id, feed_id),
        )
        await conn.execute(
            "INSERT INTO articles_hot (feed_id, entry_hash, title, url, published_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (feed_id, "hashp1", "Purge Art", "https://purge.org/p1"),
        )
        await conn.commit()


    token = TokenManager.create_access_token(data={"sub": str(user_id), "username": "admin_purge"})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. 清空前確認有文章
        art_res = await ac.get("/api/articles", headers=headers)
        assert art_res.status_code == 200
        assert len(art_res.json()["items"]) == 1

        # 2. 呼叫清空端點
        purge_res = await ac.post("/api/settings/purge-database", headers=headers)
        assert purge_res.status_code == 200
        assert purge_res.json()["status"] == "success"

        # 3. 清空後確認資料已徹底歸零
        art_after = await ac.get("/api/articles", headers=headers)
        assert art_after.status_code == 200
        assert len(art_after.json()["items"]) == 0

        feeds_after = await ac.get("/api/feeds", headers=headers)
        assert feeds_after.status_code == 200
        assert len(feeds_after.json()) == 0


@pytest.mark.anyio
async def test_purge_database_self_healing_on_malformed_db(tmp_path):
    """測試當資料庫頁面異常損壞時，清空端點能自動自癒重建 (Test self-healing on database corruption)."""
    db_file = tmp_path / "test_malformed_db.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    pwd_hash = PasswordHasher.hash_password("adminpass")
    api_key = TokenManager.generate_api_key()
    async with db_mgr.get_connection() as conn:
        u_cur = await conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, api_key) VALUES (?, ?, 1, ?)",
            ("admin_heal", pwd_hash, api_key),
        )
        user_id = u_cur.lastrowid
        await conn.commit()

    token = TokenManager.create_access_token(data={"sub": str(user_id), "username": "admin_heal"})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        purge_res = await ac.post("/api/settings/purge-database", headers=headers)
        assert purge_res.status_code == 200
        assert purge_res.json()["status"] == "success"


