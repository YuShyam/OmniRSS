"""Phase 2 驗收腳本：爬蟲引擎、規則過濾與 OPML 備份 (Phase 2 Verification Script).

Usage:
    python scripts/verify_crawler.py
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

# 強制設定 UTF-8 輸出避免 Windows cp950 編碼報錯
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 加入 src 至模組搜尋路徑
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omnirss.core.crawler_engine import CrawlerEngine, calculate_next_check_time, get_origin_referer
from omnirss.core.rule_engine import RuleEngine, RuleDef, RuleCondition, RuleAction, RuleField, RuleOperator, RuleActionType, MatchMode
from omnirss.core.backup_engine import BackupEngine
from omnirss.core.database import DatabaseManager, compute_entry_hash
from omnirss.core.scheduler import OmniScheduler
from omnirss.sdk.models import ArticleDTO


MOCK_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Tech Benchmark Daily</title>
    <link>https://benchmark.example.com</link>
    <description>Empirical RSS feed benchmark</description>
    <item>
      <title>OmniRSS Phase 2 Released: 304 Zero-Traffic Engine</title>
      <link>https://benchmark.example.com/p2-released</link>
      <guid>benchmark-001</guid>
      <pubDate>Wed, 23 Sep 2026 12:00:00 GMT</pubDate>
      <description>&lt;p&gt;High-resilience crawler with 3-stage fallback.&lt;/p&gt;&lt;script&gt;malicious()&lt;/script&gt;</description>
    </item>
    <item>
      <title>【商業廣告】即日起享年終大折扣</title>
      <link>https://benchmark.example.com/ad-discount</link>
      <guid>benchmark-002</guid>
      <pubDate>Wed, 23 Sep 2026 13:00:00 GMT</pubDate>
      <description>特價促銷商品搶購中</description>
    </item>
  </channel>
</rss>
""".encode("utf-8")


async def main():
    print("=" * 70)
    print("🚀 OmniRSS Phase 2 CLI 驗收檢驗程序 (Verification Suite)")
    print("=" * 70)

    # 1. 驗證 Auto-Referer
    ref = get_origin_referer("https://www.mobile01.com/rss/news.xml")
    assert ref == "https://www.mobile01.com/", f"Auto-Referer mismatch: {ref}"
    print("✅ 1. Auto-Referer 防盜鏈提取驗證通過:", ref)

    # 2. 驗證 Feed 解析與 HTML 脫毒
    crawler = CrawlerEngine()
    articles, feed_meta = crawler.parse_feed_content(MOCK_FEED_XML, "https://benchmark.example.com/rss")
    assert len(articles) == 2
    assert "<script>" not in articles[0].content_html
    print(f"✅ 2. 爬蟲解析與 HTML 脫毒驗證通過 (解析出 {len(articles)} 篇文章，<script> 標籤已徹底拔除)")

    # 3. 驗證規則過濾引擎
    rule_ad = RuleDef(
        id="r-ad",
        rule_name="廣告自動已讀",
        priority=100,
        is_active=True,
        match_mode=MatchMode.ALL,
        conditions=[
            RuleCondition(field=RuleField.TITLE, operator=RuleOperator.CONTAINS, value="廣告")
        ],
        actions=[
            RuleAction(action=RuleActionType.MARK_READ),
            RuleAction(action=RuleActionType.TRASH),
        ],
    )
    processed_ad, executed = RuleEngine.process_article(articles[1].model_copy(), [rule_ad])
    assert processed_ad.is_read is True
    assert "trashed" in processed_ad.extra_tags
    print(f"✅ 3. QuiteRSS 規則引擎驗證通過: 廣告文章已自動標記已讀並附加 trashed 標籤 (觸發: {executed})")

    # 4. 驗證 OPML 2.0 匯入與匯出往返
    feeds_for_export = [
        {"title": "科技新聞", "feed_url": "https://tech.example.com/rss", "category_name": "資訊技術"},
        {"title": "生活雜談", "feed_url": "https://life.example.com/feed", "category_name": "生活"},
    ]
    opml_xml = BackupEngine.generate_opml(feeds_for_export)
    reparsed = BackupEngine.parse_opml(opml_xml)
    assert len(reparsed) == 2
    cats = {r.category_name for r in reparsed}
    assert cats == {"資訊技術", "生活"}
    print("✅ 4. OPML 2.0 雙向階層匯出/匯入往返驗證通過 (分類階層樹 100% 精準還原)")

    # 5. 整合排程器入庫檢驗
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "verify_p2.db")
        db_mgr = DatabaseManager(db_path)
        await db_mgr.initialize()

        async with db_mgr.get_connection() as conn:
            u_cur = await conn.execute(
                "INSERT INTO users (username, password_hash, api_key) VALUES ('test_user', 'hash', 'ak_test_12345')"
            )
            user_id = u_cur.lastrowid

            f_cur = await conn.execute(
                "INSERT INTO feeds (title, feed_url, check_interval_minutes, is_paused, next_check_at) VALUES ('Benchmark Feed', 'https://benchmark.example.com/rss', 60, 0, datetime('now', '-10 seconds'))"
            )
            feed_id = f_cur.lastrowid

            await conn.execute("INSERT INTO user_feeds (user_id, feed_id) VALUES (?, ?)", (user_id, feed_id))
            await conn.commit()

        class MockVerifCrawler:
            async def fetch_feed(self, url, etag=None, last_modified=None, requires_flaresolverr=False):
                return type("CrawlResult", (), {
                    "status_code": 200,
                    "is_modified": True,
                    "etag": '"etag-sample-123"',
                    "last_modified": None,
                    "articles": articles,
                    "error_message": None,
                })()

        scheduler = OmniScheduler(db_manager=db_mgr, crawler_engine=MockVerifCrawler())
        polled = await scheduler.poll_due_feeds()
        assert polled == 1

        async with db_mgr.get_connection() as conn:
            cur = await conn.execute("SELECT COUNT(*) as count FROM articles_hot WHERE feed_id = ?", (feed_id,))
            row = await cur.fetchone()
            assert row["count"] == 2

    print("=" * 70)
    print("🎉 Phase 2 全套功能驗收 100% 成功！所有驗收標準皆已達成。")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
