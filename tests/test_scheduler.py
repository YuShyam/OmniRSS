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
