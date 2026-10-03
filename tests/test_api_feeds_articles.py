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
        assert cat_res.status_code in (200, 201)
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

        # 7. 短詞與中括號特殊詞搜尋測試 (驗證短詞 LIKE 與 FTS5 雙軌)
        search_short = await ac.get("/api/articles?search=Py", headers=headers)
        assert search_short.status_code == 200
        assert search_short.json()["total"] >= 1

        search_cjk = await ac.get("/api/articles?search=[測試]", headers=headers)
        assert search_cjk.status_code == 200

        # 8. 分類更新 (名稱、獨立保留天數、獨立抓取頻率連動測試)
        cat_update_res = await ac.put(
            f"/api/categories/{cat_id}",
            json={"name": "深度科技", "custom_retention_days": 14, "custom_interval_minutes": 15},
            headers=headers,
        )
        assert cat_update_res.status_code == 200
        assert cat_update_res.json()["name"] == "深度科技"
        assert cat_update_res.json()["custom_retention_days"] == 14
        assert cat_update_res.json()["custom_interval_minutes"] == 15

        # 驗證該分類底下的 feed check_interval_minutes 已被級聯更新為 15
        async with db_mgr.get_connection() as conn:
            f_row = await (await conn.execute("SELECT check_interval_minutes FROM feeds WHERE id = ?", (feed_id,))).fetchone()
            assert f_row["check_interval_minutes"] == 15

        # 8.5 取得即時抓取進度端點
        prog_res = await ac.get("/api/feeds/refresh/progress", headers=headers)
        assert prog_res.status_code == 200
        prog_data = prog_res.json()
        assert "is_running" in prog_data
        assert "completed_feeds" in prog_data
        assert "total_feeds" in prog_data

        # 8.6 停止即時抓取端點
        stop_res = await ac.post("/api/feeds/refresh/stop", headers=headers)
        assert stop_res.status_code == 200
        assert stop_res.json()["status"] == "stopped"

        # 9. 批次全站標記已讀
        batch_res = await ac.put("/api/articles/mark-all-read", json={"scope": "all"}, headers=headers)
        assert batch_res.status_code == 200
        assert batch_res.json()["marked_count"] >= 1

        # 10. 測試頻道 auto_full_text 更新與取得
        feed_update_res = await ac.put(
            f"/api/feeds/{feed_id}",
            json={"auto_full_text": True},
            headers=headers,
        )
        assert feed_update_res.status_code == 200

        tree_res = await ac.get("/api/feeds/tree", headers=headers)
        assert tree_res.status_code == 200
        tree_categories = tree_res.json()["categories"]
        target_feed = None
        for cat in tree_categories:
            for f in cat["feeds"]:
                if f["id"] == feed_id:
                    target_feed = f
                    break
        assert target_feed is not None
        assert target_feed["auto_full_text"] is True

        # 11. 測試訂閱源屬性詳細取得與更新 (包含 min_publish_date, auth)
        detail_feed_res = await ac.get(f"/api/feeds/{feed_id}", headers=headers)
        assert detail_feed_res.status_code == 200
        feed_prop_data = detail_feed_res.json()
        assert feed_prop_data["id"] == feed_id
        assert "min_publish_date" in feed_prop_data

        feed_prop_update_res = await ac.put(
            f"/api/feeds/{feed_id}",
            json={
                "min_publish_date": "2026-01-01 00:00:00",
                "auth_username": "myuser",
                "auth_password": "mypassword",
            },
            headers=headers,
        )
        assert feed_prop_update_res.status_code == 200

        # 12. 測試 POST /api/feeds/test-url 端點 (含 CrawlResult 成功與失敗防衛驗證)
        test_url_res = await ac.post(
            "/api/feeds/test-url",
            json={"feed_url": "https://tech.example.com/rss", "requires_flaresolverr": False},
            headers=headers,
        )
        assert test_url_res.status_code == 200
        test_url_data = test_url_res.json()
        assert "status" in test_url_data
        # 確保不會發生 'CrawlResult' has no attribute 'error' 之崩潰
        assert test_url_data["status"] in ("ok", "error")
        if test_url_data["status"] == "error":
            assert "error" not in test_url_data.get("error_detail", "").lower() or "crawlresult" not in test_url_data.get("error_detail", "").lower()


@pytest.mark.asyncio
async def test_mark_all_read_uncategorized_scope_isolation(tmp_path):
    """測試未分類頻道標記已讀時具備精準隔離性，絕不波及已分類頻道 (Uncategorized Scope Isolation)."""
    db_file = tmp_path / "test_uncat_mark_read.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/api/auth/setup", json={"username": "testuser", "password": "password123"})
        login_res = await ac.post("/api/auth/login", json={"username": "testuser", "password": "password123"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. 建立分類 Cat A
        cat_res = await ac.post("/api/categories", json={"name": "科技類別"}, headers=headers)
        cat_id = cat_res.json()["id"]

        # 2. 建立已分類頻道 Feed 1 與未分類頻道 Feed 2
        async with db_mgr.get_connection() as conn:
            user_row = await (await conn.execute("SELECT id FROM users WHERE username = 'testuser'")).fetchone()
            user_id = user_row["id"]

            f1_cur = await conn.execute(
                "INSERT INTO feeds (title, feed_url, check_interval_minutes) VALUES ('已分類頻道', 'http://feed1.com/rss', 30)"
            )
            feed1_id = f1_cur.lastrowid
            await conn.execute(
                "INSERT INTO user_feeds (user_id, feed_id, category_id, custom_title) VALUES (?, ?, ?, '已分類頻道')",
                (user_id, feed1_id, cat_id),
            )

            f2_cur = await conn.execute(
                "INSERT INTO feeds (title, feed_url, check_interval_minutes) VALUES ('未分類頻道', 'http://feed2.com/rss', 30)"
            )
            feed2_id = f2_cur.lastrowid
            await conn.execute(
                "INSERT INTO user_feeds (user_id, feed_id, category_id, custom_title) VALUES (?, ?, NULL, '未分類頻道')",
                (user_id, feed2_id),
            )

            # 3. 在資料庫中為兩頻道各插入一篇文章
            await conn.execute(
                """
                INSERT INTO articles_hot (feed_id, entry_hash, title, url, snippet, published_at)
                VALUES (?, 'hash_feed1_1', '已分類文章1', 'http://feed1.com/1', 'snippet1', '2026-09-26 12:00:00')
                """,
                (feed1_id,),
            )
            await conn.execute(
                """
                INSERT INTO articles_hot (feed_id, entry_hash, title, url, snippet, published_at)
                VALUES (?, 'hash_feed2_1', '未分類文章1', 'http://feed2.com/1', 'snippet2', '2026-09-26 12:00:00')
                """,
                (feed2_id,),
            )
            await conn.commit()

        # 4. 針對「未分類」執行標記已讀 (category_id: "uncategorized")
        mark_res = await ac.post("/api/articles/mark-all-read", json={"category_id": "uncategorized"}, headers=headers)
        assert mark_res.status_code == 200
        assert mark_res.json()["marked_count"] == 1

        # 5. 驗證：未分類文章已讀，但已分類文章仍為未讀 (未被誤殺)
        arts_feed1 = await ac.get(f"/api/articles?feed_id={feed1_id}", headers=headers)
        arts_feed2 = await ac.get(f"/api/articles?feed_id={feed2_id}", headers=headers)

        assert arts_feed1.json()["total"] == 1
        assert arts_feed1.json()["items"][0]["is_read"] is False, "已分類文章不應被未分類標記已讀所波及"

        assert arts_feed2.json()["total"] == 1
        assert arts_feed2.json()["items"][0]["is_read"] is True, "未分類文章應成功標記為已讀"


@pytest.mark.asyncio
async def test_cross_feed_deduplication_and_sync(tmp_path):
    """測試跨頻道相同網址文章在全站列表自動去重聚合，且已讀狀態雙向同步 (Cross-Feed Deduplication & Sync)."""
    db_file = tmp_path / "test_cross_dedup.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/api/auth/setup", json={"username": "alice", "password": "password123"})
        login_res = await ac.post("/api/auth/login", json={"username": "alice", "password": "password123"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. 建立兩個頻道：最新文章 與 軟體下載
        async with db_mgr.get_connection() as conn:
            user_row = await (await conn.execute("SELECT id FROM users WHERE username = 'alice'")).fetchone()
            user_id = user_row["id"]

            f1_cur = await conn.execute("INSERT INTO feeds (title, feed_url, check_interval_minutes) VALUES ('最新文章', 'http://forum.com/latest.xml', 30)")
            feed1_id = f1_cur.lastrowid
            await conn.execute("INSERT INTO user_feeds (user_id, feed_id, custom_title) VALUES (?, ?, '論壇 - 最新文章')", (user_id, feed1_id))

            f2_cur = await conn.execute("INSERT INTO feeds (title, feed_url, check_interval_minutes) VALUES ('軟體下載', 'http://forum.com/software.xml', 30)")
            feed2_id = f2_cur.lastrowid
            await conn.execute("INSERT INTO user_feeds (user_id, feed_id, custom_title) VALUES (?, ?, '論壇 - 軟體下載')", (user_id, feed2_id))

            # 2. 兩頻道各自插入一篇相同網址的文章 (一篇有結尾斜線，一篇無結尾斜線)
            await conn.execute(
                """
                INSERT INTO articles_hot (feed_id, entry_hash, title, url, snippet, published_at)
                VALUES (?, 'hash_f1', 'Telegram v10.0 更新釋出', 'https://forum.com/thread/123/', '最新電報更新', '2026-09-26 10:00:00')
                """,
                (feed1_id,),
            )
            a1_row = await (await conn.execute("SELECT id FROM articles_hot WHERE entry_hash = 'hash_f1'")).fetchone()
            a1_id = a1_row["id"]

            await conn.execute(
                """
                INSERT INTO articles_hot (feed_id, entry_hash, title, url, snippet, published_at)
                VALUES (?, 'hash_f2', 'Telegram v10.0 更新釋出', 'https://forum.com/thread/123', '最新電報更新', '2026-09-26 10:00:00')
                """,
                (feed2_id,),
            )
            a2_row = await (await conn.execute("SELECT id FROM articles_hot WHERE entry_hash = 'hash_f2'")).fetchone()
            a2_id = a2_row["id"]

            await conn.commit()

        # 3. 查詢全站文章：驗證自動去重聚合為 1 筆，且 duplicate_feeds 標註另一來源
        all_res = await ac.get("/api/articles", headers=headers)
        assert all_res.status_code == 200
        all_data = all_res.json()
        assert all_data["total"] == 1, "跨頻道相同文章應在全站列表自動去重聚合為 1 筆"
        assert len(all_data["items"]) == 1
        item = all_data["items"][0]
        assert item["duplicate_feeds"] is not None
        assert len(item["duplicate_feeds"]) >= 1

        # 4. 在全站列表標記該文章為已讀
        read_res = await ac.put(f"/api/articles/{item['id']}/read?is_read=true", headers=headers)
        assert read_res.status_code == 200

        # 5. 驗證 Feed 2 單一頻道查詢：文章亦自動同步為已讀
        feed2_res = await ac.get(f"/api/articles?feed_id={feed2_id}", headers=headers)
        assert feed2_res.status_code == 200
        assert feed2_res.json()["total"] == 1
        assert feed2_res.json()["items"][0]["is_read"] is True, "跨頻道同網址文章之已讀狀態應雙向自動同步"


@pytest.mark.asyncio
async def test_feed_update_url_smart_relink_and_collision(tmp_path):
    """測試訂閱源網址修改之智慧重新關聯與衝突防護機制 (Test Feed URL Update with Smart Re-link & Collision Prevention)."""
    db_file = tmp_path / "test_feed_update.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/api/auth/setup", json={"username": "carol", "password": "password123"})
        login_res = await ac.post("/api/auth/login", json={"username": "carol", "password": "password123"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        async with db_mgr.get_connection() as conn:
            user_row = await (await conn.execute("SELECT id FROM users WHERE username = 'carol'")).fetchone()
            user_id = user_row["id"]

            # 建立 Feed 1 (失效網址)
            f1_cur = await conn.execute(
                "INSERT INTO feeds (title, feed_url, error_count, last_error_message) VALUES ('舊新聞源', 'https://news.old.com/rss', 5, '404 Not Found')"
            )
            feed1_id = f1_cur.lastrowid
            await conn.execute("INSERT INTO user_feeds (user_id, feed_id, custom_title) VALUES (?, ?, '我的舊新聞')", (user_id, feed1_id))

            # 建立 Feed 2 (已存在於資料庫共用池中，但此用戶未訂閱)
            f2_cur = await conn.execute(
                "INSERT INTO feeds (title, feed_url, check_interval_minutes) VALUES ('現有優質新聞', 'https://news.existing.com/rss', 60)"
            )
            feed2_id = f2_cur.lastrowid

            # 建立 Feed 3 (此用戶已訂閱的另一個頻道)
            f3_cur = await conn.execute(
                "INSERT INTO feeds (title, feed_url, check_interval_minutes) VALUES ('科技論壇', 'https://forum.tech.com/rss', 30)"
            )
            feed3_id = f3_cur.lastrowid
            await conn.execute("INSERT INTO user_feeds (user_id, feed_id, custom_title) VALUES (?, ?, '我的科技論壇')", (user_id, feed3_id))
            await conn.commit()

        # 1. 測試情境一：將 Feed 1 修改為全新的獨立網址 -> 應成功更新且錯誤次數歸零
        update1_res = await ac.put(
            f"/api/feeds/{feed1_id}",
            json={"feed_url": "https://news.brand-new.com/rss", "custom_title": "全新品牌新聞"},
            headers=headers,
        )
        assert update1_res.status_code == 200
        async with db_mgr.get_connection() as conn:
            f1_check = await (await conn.execute("SELECT feed_url, error_count, last_error_message FROM feeds WHERE id = ?", (feed1_id,))).fetchone()
            assert f1_check["feed_url"] == "https://news.brand-new.com/rss"
            assert f1_check["error_count"] == 0
            assert f1_check["last_error_message"] is None

        # 2. 測試情境二：將 Feed 1 的網址修改為資料庫中已存在的 Feed 2 (用戶尚未訂閱 Feed 2)
        # 應觸發智慧重新關聯 (Smart Re-link)，將用戶訂閱轉移至 feed2_id，並保留自訂標題
        update2_res = await ac.put(
            f"/api/feeds/{feed1_id}",
            json={"feed_url": "https://news.existing.com/rss", "custom_title": "已轉移的現有新聞"},
            headers=headers,
        )
        assert update2_res.status_code == 200
        assert update2_res.json()["feed_id"] == feed2_id

        async with db_mgr.get_connection() as conn:
            # 驗證 user_feeds 關聯已切換至 feed2_id
            uf_check = await (await conn.execute("SELECT feed_id, custom_title FROM user_feeds WHERE user_id = ? AND feed_id = ?", (user_id, feed2_id))).fetchone()
            assert uf_check is not None
            assert uf_check["custom_title"] == "已轉移的現有新聞"

            # 驗證原本無人訂閱的舊 feed1 已被自動清理
            old_f1 = await (await conn.execute("SELECT id FROM feeds WHERE id = ?", (feed1_id,))).fetchone()
            assert old_f1 is None

        # 3. 測試情境三：將 Feed 2 的網址修改為 Feed 3 的網址 (該用戶在其他分類中早已訂閱過 Feed 3)
        # 系統應智慧自動合併：刪除重複的 feed2 關聯，將使用者在 feed3 的分類或標題自動更新為當前指定，回傳 200 成功
        update3_res = await ac.put(
            f"/api/feeds/{feed2_id}",
            json={"feed_url": "https://forum.tech.com/rss", "custom_title": "合併後的科技論壇"},
            headers=headers,
        )
        assert update3_res.status_code == 200
        assert update3_res.json()["feed_id"] == feed3_id

        async with db_mgr.get_connection() as conn:
            # 驗證用戶已無 feed2 關聯
            uf2 = await (await conn.execute("SELECT * FROM user_feeds WHERE user_id = ? AND feed_id = ?", (user_id, feed2_id))).fetchone()
            assert uf2 is None

            # 驗證 feed3 關聯已更新為新標題
            uf3 = await (await conn.execute("SELECT custom_title FROM user_feeds WHERE user_id = ? AND feed_id = ?", (user_id, feed3_id))).fetchone()
            assert uf3 is not None
            assert uf3["custom_title"] == "合併後的科技論壇"





