"""排程器單元與整合測試 (Scheduler Unit & Integration Tests).

Tests periodic polling orchestration, database insertion, and rule dispatching.
"""

import pytest
import json
from omnirss.core.database import DatabaseManager, compute_entry_hash
from omnirss.core.scheduler import OmniScheduler
from omnirss.core.crawler_engine import CrawlResult
from omnirss.sdk.models import ArticleDTO


@pytest.mark.asyncio
async def test_scheduler_feed_polling_and_rules(tmp_path):
    """測試排程器頻道輪詢、規則過濾與文章寫入 (Test scheduler feed polling, rules, and ingestion)."""
    db_file = tmp_path / "test_scheduler.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()

    # 1. 建立測試使用者與頻道
    async with db_mgr.get_connection() as conn:
        u_cur = await conn.execute(
            "INSERT INTO users (username, password_hash, api_key) VALUES (?, ?, ?)",
            ("alice", "hash123", "ak_alice_1234567890"),
        )
        user_id = u_cur.lastrowid

        f_cur = await conn.execute(
            """
            INSERT INTO feeds (title, feed_url, check_interval_minutes, is_paused, next_check_at)
            VALUES (?, ?, ?, 0, datetime('now', '-1 minute'))
            """,
            ("Mock News", "https://mock.example.com/rss", 60),
        )
        feed_id = f_cur.lastrowid

        await conn.execute(
            "INSERT INTO user_feeds (user_id, feed_id) VALUES (?, ?)",
            (user_id, feed_id),
        )

        # 建立一條使用者規則：標題包含「廣告」-> 標記已讀 + 丟入垃圾桶
        rule_conds = [{"field": "title", "operator": "contains", "value": "廣告", "case_sensitive": False}]
        rule_acts = [{"action": "mark_read"}, {"action": "trash"}]
        await conn.execute(
            """
            INSERT INTO user_rules (user_id, name, is_enabled, sort_order, conditions_json, actions_json)
            VALUES (?, ?, 1, 10, ?, ?)
            """,
            (user_id, "廣告攔截", json.dumps(rule_conds), json.dumps(rule_acts)),
        )
        await conn.commit()

    # 2. 模擬爬蟲抓取結果
    class MockCrawler:
        async def fetch_feed(self, url, etag=None, last_modified=None, requires_flaresolverr=False):
            return CrawlResult(
                url=url,
                status_code=200,
                is_modified=True,
                etag='"mock-etag-1"',
                articles=[
                    ArticleDTO(
                        guid="art-1",
                        url="https://mock.example.com/1",
                        title="優質正常新聞標題",
                        content_text="今日頭條重點整理",
                    ),
                    ArticleDTO(
                        guid="art-2",
                        url="https://mock.example.com/2",
                        title="【廣告】限時好康促銷",
                        content_text="買到賺到不要錯過",
                    ),
                ],
            )

    scheduler = OmniScheduler(db_manager=db_mgr, crawler_engine=MockCrawler())

    # 3. 執行到期頻道探測
    processed = await scheduler.poll_due_feeds()
    assert processed == 1

    # 4. 驗證資料庫寫入與未讀/已讀狀態
    async with db_mgr.get_connection() as conn:
        # 檢查 articles_hot 表
        c1 = await conn.execute("SELECT COUNT(*) as cnt FROM articles_hot WHERE feed_id = ?", (feed_id,))
        r1 = await c1.fetchone()
        assert r1["cnt"] == 2

        # 檢查 user_article_states 表
        h1 = compute_entry_hash(feed_id, "art-1", "https://mock.example.com/1")
        a1_cur = await conn.execute("SELECT id FROM articles_hot WHERE entry_hash = ?", (h1,))
        a1_row = await a1_cur.fetchone()
        s1 = await conn.execute(
            "SELECT is_read FROM user_article_states WHERE user_id = ? AND article_id = ?",
            (user_id, a1_row["id"]),
        )
        row1 = await s1.fetchone()
        assert row1["is_read"] == 0

        # art-2 (廣告) 應被規則命中自動設為已讀 (is_read = 1)
        h2 = compute_entry_hash(feed_id, "art-2", "https://mock.example.com/2")
        a2_cur = await conn.execute("SELECT id FROM articles_hot WHERE entry_hash = ?", (h2,))
        a2_row = await a2_cur.fetchone()
        s2 = await conn.execute(
            "SELECT is_read FROM user_article_states WHERE user_id = ? AND article_id = ?",
            (user_id, a2_row["id"]),
        )
        row2 = await s2.fetchone()
        assert row2["is_read"] == 1

        # 檢查 feeds 表中的 etag 與 error_count
        f_cur = await conn.execute("SELECT etag_header, last_checked_at, error_count FROM feeds WHERE id = ?", (feed_id,))
        f_row = await f_cur.fetchone()
        assert f_row["etag_header"] == '"mock-etag-1"'
        assert f_row["error_count"] == 0


@pytest.mark.asyncio
async def test_scheduler_trigger_refresh_and_progress(tmp_path):
    """測試手動觸發即時重新整理與即時進度追蹤機制 (Test manual trigger refresh and real-time progress tracking)."""
    db_file = tmp_path / "test_refresh_prog.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()

    # 1. 建立 3 個測試頻道
    async with db_mgr.get_connection() as conn:
        for i, name in enumerate(["Alpha News", "Beta Tech", "Gamma Daily"], 1):
            await conn.execute(
                """
                INSERT INTO feeds (title, feed_url, check_interval_minutes, is_paused)
                VALUES (?, ?, 30, 0)
                """,
                (name, f"https://example.com/rss_{i}"),
            )
        await conn.commit()

    class MockProgressCrawler:
        async def fetch_feed(self, url, etag=None, last_modified=None, requires_flaresolverr=False):
            return CrawlResult(
                url=url,
                status_code=200,
                is_modified=True,
                articles=[
                    ArticleDTO(
                        guid=f"art-{url}",
                        url=f"{url}/article-1",
                        title=f"Title for {url}",
                        content_text="Sample content",
                    )
                ],
            )

    scheduler = OmniScheduler(db_manager=db_mgr, crawler_engine=MockProgressCrawler())

    # 2. 觸發手動更新
    res = await scheduler.trigger_refresh()
    assert res["refreshed_count"] == 3
    assert res["total_attempted"] == 3
    assert res["new_articles"] == 3

    # 3. 檢查進度物件重設狀態
    prog = scheduler.get_refresh_progress()
    assert prog["is_running"] is False
    assert prog["current_feed"] == ""
    assert prog["completed"] == 3
    assert prog["new_articles"] == 3


@pytest.mark.asyncio
async def test_scheduler_cancel_refresh(tmp_path):
    """測試手動即時終止所有進行中的更新任務 (Test cancelling ongoing crawl refresh)."""
    import asyncio
    db_file = tmp_path / "test_cancel.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()

    async with db_mgr.get_connection() as conn:
        for i in range(5):
            await conn.execute(
                "INSERT INTO feeds (title, feed_url, check_interval_minutes, is_paused) VALUES (?, ?, 60, 0)",
                (f"Feed {i}", f"https://slow.example.com/{i}"),
            )
        await conn.commit()

    class SlowMockCrawler:
        async def fetch_feed(self, url, etag=None, last_modified=None, requires_flaresolverr=False):
            await asyncio.sleep(2.0)
            return CrawlResult(url=url, status_code=200, is_modified=True, articles=[])

    scheduler = OmniScheduler(db_manager=db_mgr, crawler_engine=SlowMockCrawler())

    # 背景啟動更新
    refresh_task = asyncio.create_task(scheduler.trigger_refresh())
    await asyncio.sleep(0.1)
    assert scheduler.get_refresh_progress()["is_running"] is True

    # 觸發中斷
    cancelled = scheduler.cancel_refresh()
    assert cancelled >= 1
    assert scheduler.get_refresh_progress()["is_running"] is False

    await refresh_task


@pytest.mark.asyncio
async def test_scheduler_5_tier_ingestion_pipeline(tmp_path):
    """測試 5 階梯標準收錄管線 (Test 5-tier ingestion pipeline: pre-filter -> enrichment -> rule matching -> atomic DB write)."""
    db_file = tmp_path / "test_5tier.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()

    # 1. 建立測試用戶與設定包含內文關鍵字之規則
    async with db_mgr.get_connection() as conn:
        u_cur = await conn.execute(
            "INSERT INTO users (username, password_hash, api_key) VALUES (?, ?, ?)",
            ("bob", "hash123", "ak_bob_1234567890"),
        )
        user_id = u_cur.lastrowid

        f_cur = await conn.execute(
            """
            INSERT INTO feeds (title, feed_url, check_interval_minutes, is_paused, auto_full_text)
            VALUES (?, ?, ?, 0, 1)
            """,
            ("Tech News", "https://tech.example.com/feed.xml", 60),
        )
        feed_id = f_cur.lastrowid

        await conn.execute(
            "INSERT INTO user_feeds (user_id, feed_id) VALUES (?, ?)",
            (user_id, feed_id),
        )

        # 規則：內文包含「旗艦晶片」-> 自動打標籤「科技」
        rule_conds = [{"field": "content", "operator": "contains", "value": "旗艦晶片", "case_sensitive": False}]
        rule_acts = [{"action": "add_tag", "params": {"tag_name": "科技"}}]
        await conn.execute(
            """
            INSERT INTO user_rules (user_id, name, is_enabled, sort_order, conditions_json, actions_json)
            VALUES (?, ?, 1, 1, ?, ?)
            """,
            (user_id, "科技晶片標記", json.dumps(rule_conds), json.dumps(rule_acts)),
        )
        await conn.commit()

    # 2. 模擬爬蟲抓取結果 (RSS 只有 50 字摘要，但 fetch_web_page 提供完整全文)
    class PipelineMockCrawler:
        async def fetch_feed(self, url, etag=None, last_modified=None, requires_flaresolverr=False, force_refresh=False):
            return CrawlResult(
                url=url,
                status_code=200,
                is_modified=True,
                articles=[
                    ArticleDTO(
                        guid="art-chip-1",
                        url="https://tech.example.com/chip-review",
                        title="最新處理器評測摘要",
                        snippet="處理器發表會重點...",
                        content_html="<p>處理器發表會重點...</p>",
                        content_text="處理器發表會重點...",
                    )
                ],
            )

        async def fetch_web_page(self, url, requires_flaresolverr=False):
            html = """
            <html>
                <head><title>最新處理器評測</title></head>
                <body>
                    <article>
                        <h1>最新處理器深度評測</h1>
                        <p>這款全新的旗艦晶片採用了 2nm 先進製程，效能大幅提升且功耗顯著下降。</p>
                        <p>在各項基準測試中展現出極致實力。</p>
                    </article>
                </body>
            </html>
            """
            return 200, html

    scheduler = OmniScheduler(db_manager=db_mgr, crawler_engine=PipelineMockCrawler())

    # 3. 執行輪詢
    processed = await scheduler.poll_due_feeds()
    assert processed == 1

    # 4. 驗證：入庫的文章在寫入時就已經包含完整全文與正確的規則標籤
    async with db_mgr.get_connection() as conn:
        a_cur = await conn.execute("SELECT * FROM articles_hot WHERE feed_id = ?", (feed_id,))
        art = await a_cur.fetchone()
        assert art is not None
        assert "旗艦晶片" in art["content_html"]

        # 驗證規則引擎成功命中全文並打上「科技」標籤
        t_cur = await conn.execute(
            """
            SELECT t.name FROM tags t
            JOIN article_tags at ON t.id = at.tag_id
            WHERE at.article_id = ?
            """,
            (art["id"],),
        )
        tags = [r["name"] for r in await t_cur.fetchall()]
        assert "科技" in tags



