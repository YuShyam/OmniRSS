"""分類、頻道與文章 API 測試套件 (Feeds & Articles API Integration Tests).

Tests feed trees, category management, article queries, read/star toggles, and batch operations.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from omnirss.core.database import DatabaseManager, set_global_db_manager, compute_entry_hash
from omnirss.core.security import PasswordHasher, TokenManager
from omnirss.main import app


@pytest.mark.asyncio
async def test_feeds_and_articles_api(tmp_path):
    """測試分類、訂閱樹、文章列表分頁與狀態切換 API (Test Feeds & Articles API)."""
    db_file = tmp_path / "test_feeds_articles_api.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    # 1. 建立測試用戶
    pwd_hash = PasswordHasher.hash_password("mypassword")
    api_key = TokenManager.generate_api_key()
    async with db_mgr.get_connection() as conn:
        u_cur = await conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, api_key) VALUES (?, ?, 0, ?)",
            ("bob", pwd_hash, api_key),
        )
        user_id = u_cur.lastrowid
        await conn.commit()

    token = TokenManager.create_access_token(data={"sub": str(user_id), "username": "bob"})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 2. 建立分類目錄
        cat_res = await ac.post("/api/categories", json={"name": "科技資訊", "sort_order": 1}, headers=headers)
        assert cat_res.status_code == 200
        cat_id = cat_res.json()["id"]

        # 3. 新增自訂訂閱頻道
        async with db_mgr.get_connection() as conn:
            f_cur = await conn.execute(
                "INSERT INTO feeds (title, feed_url, check_interval_minutes) VALUES (?, ?, ?)",
                ("Tech Blog", "https://tech.example.com/rss", 30),
            )
            feed_id = f_cur.lastrowid
            await conn.execute(
                "INSERT INTO user_feeds (user_id, feed_id, category_id, custom_title) VALUES (?, ?, ?, ?)",
                (user_id, feed_id, cat_id, "我的科技網誌"),
            )

            # 寫入兩篇熱文章 (含完整 content_html 與 content_text)
            h1 = compute_entry_hash(feed_id, "post-1", "https://tech.example.com/1")
            h2 = compute_entry_hash(feed_id, "post-2", "https://tech.example.com/2")
            await conn.execute(
                """
                INSERT INTO articles_hot (feed_id, entry_hash, title, url, snippet, content_html, content_text, published_at)
                VALUES (?, ?, 'Python 效能評測', 'https://tech.example.com/1', 'JIT 性能分析', '<p>完整長文：包含圖表與分析 <img src=\"https://example.com/pic.png\"/></p>', '完整長文：包含圖表與分析', datetime('now'))
                """,
                (feed_id, h1),
            )
            a1_id = (await (await conn.execute("SELECT id FROM articles_hot WHERE entry_hash = ?", (h1,))).fetchone())["id"]

            await conn.execute(
                """
                INSERT INTO articles_hot (feed_id, entry_hash, title, url, snippet, content_html, content_text, published_at)
                VALUES (?, ?, 'FastAPI 最佳實踐', 'https://tech.example.com/2', '非同步架構設計', '<p>完整指南第二篇</p>', '完整指南第二篇', datetime('now', '-1 hour'))
                """,
                (feed_id, h2),
            )
            a2_id = (await (await conn.execute("SELECT id FROM articles_hot WHERE entry_hash = ?", (h2,))).fetchone())["id"]

            await conn.execute("INSERT INTO user_article_states (user_id, article_id, is_read) VALUES (?, ?, 0)", (user_id, a1_id))
            await conn.execute("INSERT INTO user_article_states (user_id, article_id, is_read) VALUES (?, ?, 0)", (user_id, a2_id))
            await conn.commit()

        # 4. 取得訂閱樹
        tree_res = await ac.get("/api/feeds/tree", headers=headers)
        assert tree_res.status_code == 200
        tree_data = tree_res.json()
        assert len(tree_data["categories"]) >= 1

        # 5. 查詢文章列表與單篇完整內文
        articles_res = await ac.get("/api/articles?page=1&page_size=10", headers=headers)
        assert articles_res.status_code == 200
        art_data = articles_res.json()
        assert art_data["total"] == 2
        assert len(art_data["items"]) == 2

        detail_res = await ac.get(f"/api/articles/{a1_id}", headers=headers)
        assert detail_res.status_code == 200
        detail_data = detail_res.json()
        assert "<img" in detail_data["content_html"]
        assert "完整長文" in detail_data["content_text"]

        # 6. 標記單篇文章已讀與加星
        read_res = await ac.put(f"/api/articles/{a1_id}/read?is_read=true", headers=headers)
        assert read_res.status_code == 200

        star_res = await ac.put(f"/api/articles/{a1_id}/star?is_starred=true", headers=headers)
        assert star_res.status_code == 200

        # 7. 短詞搜尋測試 (驗證短詞 LIKE 與 FTS 雙軌)
        search_short = await ac.get("/api/articles?search=Py", headers=headers)
        assert search_short.status_code == 200
        assert search_short.json()["total"] >= 1

        # 8. 分類更新 (名稱與獨立保留天數)
        cat_update_res = await ac.put(f"/api/categories/{cat_id}", json={"name": "深度科技", "custom_retention_days": 14}, headers=headers)
        assert cat_update_res.status_code == 200
        assert cat_update_res.json()["name"] == "深度科技"
        assert cat_update_res.json()["custom_retention_days"] == 14

        # 9. 批次全站標記已讀
        batch_res = await ac.put("/api/articles/mark-all-read", json={"scope": "all"}, headers=headers)
        assert batch_res.status_code == 200
        assert batch_res.json()["marked_count"] >= 1
