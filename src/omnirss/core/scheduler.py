"""非同步定時排程引擎 (Asynchronous Task Scheduler Engine).

This module manages background cron and interval jobs using APScheduler,
including dynamic feed polling with backoff recalculation and database maintenance.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from omnirss.core.crawler_engine import (
    CrawlerEngine,
    calculate_next_check_time,
)
from omnirss.core.database import DatabaseManager, compute_entry_hash
from omnirss.core.rule_engine import RuleDef, RuleEngine
from omnirss.sdk.models import ArticleDTO

logger = logging.getLogger("omnirss.scheduler")


class OmniScheduler:
    """非同步定時排程管理器 (Asynchronous Task Scheduler Manager).

    Coordinates feed fetching workers, conditional backoff schedules,
    and storage optimization routines.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        crawler_engine: Optional[CrawlerEngine] = None,
        poll_interval_seconds: int = 60,
    ) -> None:
        """初始化排程器 (Initialize scheduler).

        :param db_manager: 資料庫管理器實例 (DatabaseManager instance)
        :param crawler_engine: 爬蟲引擎實例；若無則自動初始化 (CrawlerEngine instance)
        :param poll_interval_seconds: 排程器探測待抓取頻道之週期秒數 (Poll check interval)
        """
        self.db = db_manager
        self.crawler = crawler_engine or CrawlerEngine()
        self.poll_interval = poll_interval_seconds
        self.scheduler = AsyncIOScheduler()
        self._is_running = False

    def start(self) -> None:
        """啟動非同步排程器 (Start the background scheduler)."""
        if self._is_running:
            return

        # 註冊待更新頻道探測任務 (Register feed polling job)
        self.scheduler.add_job(
            self.poll_due_feeds,
            "interval",
            seconds=self.poll_interval,
            id="job_poll_due_feeds",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

        # 註冊資料庫日常維護任務 (每小時執行一次) (Register maintenance job hourly)
        self.scheduler.add_job(
            self.maintain_database,
            "interval",
            hours=1,
            id="job_db_maintenance",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

        self.scheduler.start()
        self._is_running = True
        logger.info("OmniRSS background scheduler started.")

    def shutdown(self, wait: bool = False) -> None:
        """停止非同步排程器 (Gracefully shutdown scheduler)."""
        if not self._is_running:
            return

        self.scheduler.shutdown(wait=wait)
        self._is_running = False
        logger.info("OmniRSS background scheduler stopped.")

    async def poll_due_feeds(self) -> int:
        """探測並抓取所有已到期之訂閱頻道 (Poll and fetch all overdue feeds).

        :return: 本次成功處理的頻道數量 (Number of processed feeds)
        """
        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id, feed_url, title, etag_header, last_modified_header,
                       check_interval_minutes, error_count, requires_flaresolverr
                FROM feeds
                WHERE is_paused = 0 AND (next_check_at <= CURRENT_TIMESTAMP)
                ORDER BY error_count ASC, next_check_at ASC
                LIMIT 50
                """
            )
            due_feeds = await cursor.fetchall()

        if not due_feeds:
            return 0

        logger.info(
            f"Scheduler found {len(due_feeds)} due feeds for crawling."
        )

        tasks = [self._process_single_feed(dict(row)) for row in due_feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_count = sum(1 for r in results if r is True)
        return processed_count

    async def _process_single_feed(self, feed_row: dict[str, Any]) -> bool:
        """抓取並處理單一頻道之最新內容 (Fetch and ingest a single feed).

        :param feed_row: 頻道資料列字典 (Feed database row)
        :return: True 表處理完成
        """
        feed_id = feed_row["id"]
        feed_url = feed_row["feed_url"]
        etag = feed_row.get("etag_header")
        last_modified = feed_row.get("last_modified_header")
        interval_mins = feed_row.get("check_interval_minutes") or 30
        error_count = feed_row.get("error_count") or 0
        requires_flaresolverr = bool(feed_row.get("requires_flaresolverr", 0))

        try:
            # 1. 執行高韌性非同步抓取 (Execute resilient crawl)
            crawl_result = await self.crawler.fetch_feed(
                url=feed_url,
                etag=etag,
                last_modified=last_modified,
                requires_flaresolverr=requires_flaresolverr,
            )

            # 2. 處理 HTTP 304 零流量快取命中 (Handle 304 Not Modified)
            if (
                crawl_result.status_code == 304
                or not crawl_result.is_modified
                and crawl_result.status_code == 200
            ):
                next_check = calculate_next_check_time(
                    interval_mins, error_count=0
                )
                async with self.db.get_connection() as conn:
                    await conn.execute(
                        """
                        UPDATE feeds
                        SET last_checked_at = CURRENT_TIMESTAMP,
                            next_check_at = ?,
                            error_count = 0,
                            last_error_message = NULL
                        WHERE id = ?
                        """,
                        (next_check.strftime("%Y-%m-%d %H:%M:%S"), feed_id),
                    )
                    await conn.commit()
                return True

            # 3. 若抓取失敗，套用指數退避排程 (Handle crawl failure with backoff)
            if crawl_result.status_code >= 400 or crawl_result.error_message:
                new_error_count = error_count + 1
                next_check = calculate_next_check_time(
                    interval_mins, error_count=new_error_count
                )
                err_msg = crawl_result.error_message or f"HTTP {crawl_result.status_code}"
                async with self.db.get_connection() as conn:
                    await conn.execute(
                        """
                        UPDATE feeds
                        SET last_checked_at = CURRENT_TIMESTAMP,
                            next_check_at = ?,
                            error_count = ?,
                            last_error_message = ?
                        WHERE id = ?
                        """,
                        (
                            next_check.strftime("%Y-%m-%d %H:%M:%S"),
                            new_error_count,
                            err_msg,
                            feed_id,
                        ),
                    )
                    await conn.commit()
                return False

            # 4. 抓取成功：載入使用者過濾規則並執行入庫 (Ingest articles with rule processing)
            await self._ingest_articles(feed_id, feed_row, crawl_result)

            # 5. 更新頻道成功中繼資料 (Update feed metadata on success)
            next_check = calculate_next_check_time(interval_mins, error_count=0)
            async with self.db.get_connection() as conn:
                await conn.execute(
                    """
                    UPDATE feeds
                    SET last_checked_at = CURRENT_TIMESTAMP,
                        next_check_at = ?,
                        etag_header = ?,
                        last_modified_header = ?,
                        error_count = 0,
                        last_error_message = NULL
                    WHERE id = ?
                    """,
                    (
                        next_check.strftime("%Y-%m-%d %H:%M:%S"),
                        crawl_result.etag,
                        crawl_result.last_modified,
                        feed_id,
                    ),
                )
                await conn.commit()

            return True

        except Exception as e:
            logger.exception(f"Unhandled error polling feed '{feed_url}': {e}")
            new_error_count = error_count + 1
            next_check = calculate_next_check_time(
                interval_mins, error_count=new_error_count
            )
            async with self.db.get_connection() as conn:
                await conn.execute(
                    """
                    UPDATE feeds
                    SET last_checked_at = CURRENT_TIMESTAMP,
                        next_check_at = ?,
                        error_count = ?,
                        last_error_message = ?
                    WHERE id = ?
                    """,
                    (
                        next_check.strftime("%Y-%m-%d %H:%M:%S"),
                        new_error_count,
                        str(e),
                        feed_id,
                    ),
                )
                await conn.commit()
            return False

    async def _ingest_articles(
        self,
        feed_id: int,
        feed_row: dict[str, Any],
        crawl_result: Any,
    ) -> None:
        """將抓取到的文章套用過濾規則並寫入資料庫 (Apply rules and insert articles into hot storage)."""
        async with self.db.get_connection() as conn:
            # 獲取訂閱該頻道的使用者清單
            u_cursor = await conn.execute(
                "SELECT user_id FROM user_feeds WHERE feed_id = ?", (feed_id,)
            )
            user_rows = await u_cursor.fetchall()
            subscribed_user_ids = [r["user_id"] for r in user_rows]

            # 載入所有相關使用者的過濾規則
            user_rules_map: dict[int, list[RuleDef]] = {}
            for uid in subscribed_user_ids:
                r_cursor = await conn.execute(
                    """
                    SELECT id, name, sort_order, is_enabled, conditions_json, actions_json
                    FROM user_rules
                    WHERE user_id = ? AND is_enabled = 1
                    ORDER BY sort_order ASC
                    """,
                    (uid,),
                )
                rules: list[RuleDef] = []
                for row in await r_cursor.fetchall():
                    try:
                        conds = json.loads(row["conditions_json"])
                        acts = json.loads(row["actions_json"])
                        rules.append(
                            RuleDef(
                                id=str(row["id"]),
                                rule_name=row["name"],
                                priority=row["sort_order"],
                                is_active=bool(row["is_enabled"]),
                                match_mode="all",
                                conditions=conds,
                                actions=acts,
                            )
                        )
                    except Exception:
                        pass
                user_rules_map[uid] = rules

        feed_title = feed_row.get("title", "")
        for article in crawl_result.articles:
            entry_hash = compute_entry_hash(
                feed_id, article.guid, article.url
            )
            published_str = article.published_at.strftime("%Y-%m-%d %H:%M:%S")

            async with self.db.get_connection() as conn:
                # 寫入 articles_hot
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO articles_hot (
                        feed_id, entry_hash, title, url, author, snippet, cover_image_url, published_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        feed_id,
                        entry_hash,
                        article.title,
                        article.url,
                        article.author,
                        article.snippet,
                        article.cover_image_url,
                        published_str,
                    ),
                )

                # 查詢該文章之自增 id
                a_cur = await conn.execute(
                    "SELECT id FROM articles_hot WHERE entry_hash = ?",
                    (entry_hash,),
                )
                a_row = await a_cur.fetchone()
                if not a_row:
                    continue
                article_db_id = a_row["id"]

                # 為每位訂閱使用者套用規則並寫入狀態表
                for uid in subscribed_user_ids:
                    rules = user_rules_map.get(uid, [])
                    processed_article, _ = RuleEngine.process_article(
                        article.model_copy(), rules, feed_title=feed_title
                    )

                    await conn.execute(
                        """
                        INSERT OR IGNORE INTO user_article_states (
                            user_id, article_id, is_read, is_starred
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            uid,
                            article_db_id,
                            1 if processed_article.is_read else 0,
                            1 if processed_article.is_starred else 0,
                        ),
                    )

                await conn.commit()

    async def maintain_database(self) -> None:
        """執行資料庫維護 (Execute database maintenance and WAL checkpoint)."""
        logger.info("Starting scheduled database maintenance...")
        async with self.db.get_connection() as conn:
            await conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        logger.info("Database maintenance completed successfully.")
