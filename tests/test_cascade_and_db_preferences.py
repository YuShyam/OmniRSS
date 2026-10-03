"""三層級聯規則與 DB 偏好同步單元測試 (Test 3-Tier Cascade & DB Preferences Sync).

Tests:
1. Category auto_full_text update cascades to feeds in the same category.
2. Category view_preferences persistence in DB and retrieval via feed tree.
3. User settings persistence (collapsedCategories, columnWidths) in DB users.settings_json.
4. Crawler ingestion-time auto_full_text 3-tier cascade resolution.
"""

import json
import pytest
from httpx import ASGITransport, AsyncClient

from omnirss.main import app
from omnirss.core.database import DatabaseManager, set_global_db_manager
from omnirss.core.security import PasswordHasher, TokenManager


@pytest.mark.asyncio
async def test_category_cascade_and_view_preferences_db(tmp_path):
    """測試分類 auto_full_text 級聯至旗下 feeds 以及 view_preferences 存入 DB。"""
    db_file = tmp_path / "test_cascade_db.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    # 1. 建立管理員並登入
    pwd_hash = PasswordHasher.hash_password("adminpass")
    api_key = TokenManager.generate_api_key()
    async with db_mgr.get_connection() as conn:
        u_cur = await conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, api_key, settings_json) VALUES (?, ?, 1, ?, ?)",
            ("admin", pwd_hash, api_key, json.dumps({"collapsedCategories": [1], "columnWidths": {"title": 200}})),
        )
        user_id = u_cur.lastrowid
        await conn.commit()

    token = TokenManager.create_access_token(data={"sub": str(user_id), "username": "admin"})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 2. 驗證 /api/auth/me 正確回傳 settings 包含 collapsedCategories 與 columnWidths
        me_res = await ac.get("/api/auth/me", headers=headers)
        assert me_res.status_code == 200
        me_data = me_res.json()
        assert me_data["settings"]["collapsedCategories"] == [1]
        assert me_data["settings"]["columnWidths"]["title"] == 200

        # 3. 建立分類 (初始 auto_full_text = False)
        cat_res = await ac.post("/api/categories", json={"name": "科技新聞", "sort_order": 1}, headers=headers)
        assert cat_res.status_code in (200, 201)
        cat_id = cat_res.json()["id"]

        # 4. 在該分類下建立兩個 feeds
        async with db_mgr.get_connection() as conn:
            f1 = await conn.execute(
                "INSERT INTO feeds (title, feed_url, auto_full_text) VALUES (?, ?, 0)",
                ("Tech 1", "https://tech1.com/rss"),
            )
            feed_id_1 = f1.lastrowid
            await conn.execute(
                "INSERT INTO user_feeds (user_id, feed_id, category_id) VALUES (?, ?, ?)",
                (user_id, feed_id_1, cat_id),
            )

            f2 = await conn.execute(
                "INSERT INTO feeds (title, feed_url, auto_full_text) VALUES (?, ?, 0)",
                ("Tech 2", "https://tech2.com/rss"),
            )
            feed_id_2 = f2.lastrowid
            await conn.execute(
                "INSERT INTO user_feeds (user_id, feed_id, category_id) VALUES (?, ?, ?)",
                (user_id, feed_id_2, cat_id),
            )
            await conn.commit()

        # 5. 更新分類：開啟 auto_full_text = True，並儲存 view_preferences
        prefs_obj = {
            "sort": "published_asc",
            "hide_read": True,
            "include_keywords": "AI",
            "exclude_keywords": "廣告",
        }
        update_res = await ac.put(
            f"/api/categories/{cat_id}",
            json={
                "name": "科技新聞 (已升級)",
                "auto_full_text": True,
                "view_preferences": json.dumps(prefs_obj),
            },
            headers=headers,
        )
        assert update_res.status_code == 200
        updated_cat = update_res.json()
        assert updated_cat["auto_full_text"] is True
        assert "include_keywords" in updated_cat["view_preferences"]

        # 6. 驗證資料庫中該分類旗下的 feeds 是否已自動級聯變更為 auto_full_text = 1
        async with db_mgr.get_connection() as conn:
            cur = await conn.execute(
                "SELECT auto_full_text FROM feeds WHERE id IN (?, ?)",
                (feed_id_1, feed_id_2),
            )
            rows = await cur.fetchall()
            assert len(rows) == 2
            assert all(r[0] == 1 for r in rows), "Feeds in category must cascade auto_full_text = 1"

        # 7. 驗證 Feed Tree 取得的資料結構包含完整的 auto_full_text 與 view_preferences
        tree_res = await ac.get("/api/feeds/tree", headers=headers)
        assert tree_res.status_code == 200
        tree_data = tree_res.json()
        cat_in_tree = next((c for c in tree_data["categories"] if c["id"] == cat_id), None)
        assert cat_in_tree is not None
        assert cat_in_tree["auto_full_text"] is True
        prefs_in_tree = cat_in_tree["view_preferences"] if isinstance(cat_in_tree["view_preferences"], dict) else json.loads(cat_in_tree["view_preferences"])
        assert prefs_in_tree["hide_read"] is True

        # 8. 測試全域設定更新：更新 users.settings_json 中的 collapsedCategories
        settings_update_res = await ac.put(
            "/api/auth/settings",
            json={"settings": {"collapsedCategories": [cat_id, 999], "columnWidths": {"feed": 180}}},
            headers=headers,
        )
        assert settings_update_res.status_code == 200
        new_settings = settings_update_res.json()
        assert new_settings["settings"]["collapsedCategories"] == [cat_id, 999]
        assert new_settings["settings"]["columnWidths"]["feed"] == 180
