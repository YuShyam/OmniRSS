"""非同步定時排程引擎 (Asynchronous Task Scheduler Engine).

This module manages background cron and interval jobs using APScheduler,
including dynamic feed polling with backoff recalculation and database maintenance.
Feed processing and article ingestion are delegated to the modular FeedPipeline.
"""

import asyncio
import logging
from typing import Any, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from omnirss.core.crawler_engine import (
    CrawlerEngine,
    calculate_next_check_time,
)
from omnirss.core.database import (
    DatabaseManager,
    get_db_manager,
)
from omnirss.core.feed_pipeline import (
    FeedPipeline,
    resolve_effective_min_publish_date,
)

logger = logging.getLogger("omnirss.scheduler")


class OmniScheduler:
    """非同步定時排程管理器 (Asynchronous Task Scheduler Manager).

    Coordinates feed fetching workers, conditional backoff schedules,
    and storage optimization routines.
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        crawler_engine: Optional[CrawlerEngine] = None,
        poll_interval_seconds: int = 60,
    ) -> None:
        """初始化排程器 (Initialize scheduler).

        :param db_manager: 資料庫管理器實例 (DatabaseManager instance)
        :param crawler_engine: 爬蟲引擎實例；若無則自動初始化 (CrawlerEngine instance)
        :param poll_interval_seconds: 排程器探測待抓取頻道之週期秒數 (Poll check interval)
        """
        self.db = db_manager or get_db_manager()
        self.crawler = crawler_engine or CrawlerEngine()
        self.pipeline = FeedPipeline(db_manager=self.db, crawler_engine=self.crawler)
        self.poll_interval = poll_interval_seconds
        self.scheduler = AsyncIOScheduler()
        self._is_running = False
        self._is_shutting_down = False
        self._active_tasks: set[asyncio.Task] = set()
        self.refresh_progress: dict[str, Any] = {
            "is_running": False,
            "total": 0,
            "completed": 0,
            "current_feed": "",
            "new_articles": 0,
            "errors": 0,
            "started_at": None,
            "finished_at": None,
        }
        set_global_scheduler(self)

    def start(self) -> None:
        """啟動非同步排程器 (Start the background scheduler)."""
        if self._is_running:
            return

        self._is_shutting_down = False
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
        self._is_shutting_down = True
        if not self._is_running:
            return

        try:
            self.scheduler.shutdown(wait=wait)
        except Exception as e:
            logger.warning(f"Error during APScheduler shutdown: {e}")
        self._is_running = False
        logger.info("OmniRSS background scheduler stopped.")

    async def async_shutdown(self, timeout: float = 1.0) -> None:
        """非同步強制停止排程器並取消所有執行中的爬蟲協程 (Cancel all active crawling tasks on shutdown)."""
        self._is_shutting_down = True
        self.shutdown(wait=False)

        # 取消所有進行中的爬蟲與背景協程
        tasks_to_cancel = [t for t in self._active_tasks if not t.done()]
        if tasks_to_cancel:
            logger.info(f"Cancelling {len(tasks_to_cancel)} active crawler task(s)...")
            for t in tasks_to_cancel:
                t.cancel()
            try:
                await asyncio.wait(tasks_to_cancel, timeout=timeout)
            except Exception as e:
                logger.warning(f"Timeout waiting for tasks cancellation: {e}")

        self._active_tasks.clear()
        self.refresh_progress["is_running"] = False
        self.refresh_progress["current_feed"] = ""

    def get_refresh_progress(self) -> dict[str, Any]:
        """取得當前即時抓取進度 (Get real-time refresh progress)."""
        return dict(self.refresh_progress)

    def _get_host_semaphore(self, url: str) -> asyncio.Semaphore:
        """獲取特定主機網域之專屬並發信號量 (Get or create host-level semaphore)."""
        import urllib.parse
        try:
            parsed = urllib.parse.urlparse(url)
            host = (parsed.hostname or parsed.netloc or "default").lower()
        except Exception:
            host = "default"

        if not hasattr(self, "_host_semaphores"):
            self._host_semaphores = {}

        if host not in self._host_semaphores:
            # 針對 PTT 等高敏感 BBS 站點限制同時 3 個連線；其他一般網站 5 個連線
            limit = 3 if "ptt.cc" in host else 5
            self._host_semaphores[host] = asyncio.Semaphore(limit)
        return self._host_semaphores[host]

    async def trigger_refresh(
        self,
        feed_id: Optional[int] = None,
        category_id: Optional[int] = None,
        force_refresh: bool = True,
    ) -> dict[str, Any]:
        """手動觸發即時抓取更新 (Trigger manual on-demand feed refresh).

        :param feed_id: 特定頻道 ID；若指定則只抓取該頻道
        :param category_id: 特定分類 ID (0 為未分類)；若指定則抓取該分類下的活躍頻道
        :param force_refresh: 是否強制穿透快取 (Bypass ETag/304 cache)
        :return: 抓取結果摘要字典
        """
        async with self.db.get_connection() as conn:
            if feed_id is not None:
                cur = await conn.execute(
                    """
                    SELECT id, feed_url, title, etag_header, last_modified_header,
                           check_interval_minutes, error_count, requires_flaresolverr,
                           COALESCE(auto_full_text, 0) as auto_full_text
                    FROM feeds
                    WHERE id = ? AND is_paused = 0
                    """,
                    (feed_id,),
                )
            elif category_id is not None:
                if category_id == 0:
                    cur = await conn.execute(
                        """
                        SELECT f.id, f.feed_url, f.title, f.etag_header, f.last_modified_header,
                               f.check_interval_minutes, f.error_count, f.requires_flaresolverr,
                               COALESCE(f.auto_full_text, 0) as auto_full_text
                        FROM feeds f
                        JOIN user_feeds uf ON f.id = uf.feed_id
                        WHERE f.is_paused = 0 AND uf.category_id IS NULL
                        ORDER BY f.last_checked_at ASC NULLS FIRST
                        """
                    )
                else:
                    cur = await conn.execute(
                        """
                        SELECT f.id, f.feed_url, f.title, f.etag_header, f.last_modified_header,
                               f.check_interval_minutes, f.error_count, f.requires_flaresolverr,
                               COALESCE(f.auto_full_text, 0) as auto_full_text
                        FROM feeds f
                        JOIN user_feeds uf ON f.id = uf.feed_id
                        WHERE f.is_paused = 0 AND uf.category_id = ?
                        ORDER BY f.last_checked_at ASC NULLS FIRST
                        """,
                        (category_id,),
                    )
            else:
                cur = await conn.execute(
                    """
                    SELECT id, feed_url, title, etag_header, last_modified_header,
                           check_interval_minutes, error_count, requires_flaresolverr,
                           COALESCE(auto_full_text, 0) as auto_full_text
                    FROM feeds
                    WHERE is_paused = 0
                    ORDER BY last_checked_at ASC NULLS FIRST
                    """
                )
            target_feeds = [dict(r) for r in await cur.fetchall()]

        if not target_feeds:
            return {"refreshed_count": 0, "total_attempted": 0, "new_articles": 0, "message": "沒有需要抓取的頻道"}

        self.refresh_progress["is_running"] = True
        self.refresh_progress["total"] = len(target_feeds)
        self.refresh_progress["completed"] = 0
        self.refresh_progress["current_feed"] = ""
        self.refresh_progress["new_articles"] = 0
        self.refresh_progress["errors"] = 0

        active_feeds: list[str] = []
        progress_lock = asyncio.Lock()
        sem = asyncio.Semaphore(15)

        async def worker(feed_row: dict[str, Any]) -> bool:
            feed_name = feed_row.get("title") or feed_row["feed_url"]
            feed_url = feed_row.get("feed_url", "")
            host_sem = self._get_host_semaphore(feed_url)
            try:
                async with sem:
                    async with host_sem:
                        async with progress_lock:
                            active_feeds.append(feed_name)
                            self.refresh_progress["current_feed"] = feed_name

                        await asyncio.sleep(0.02)  # 20ms 平滑微延遲防止衝擊目標伺服器
                        res = await self._process_single_feed(feed_row, force_refresh=force_refresh)
                        success, new_arts = res if isinstance(res, tuple) else (bool(res), 0)
                        if success:
                            self.refresh_progress["new_articles"] += new_arts
                        else:
                            self.refresh_progress["errors"] += 1
                        return success
            except asyncio.CancelledError:
                logger.debug(f"Manual feed refresh cancelled: {feed_name}")
                self.refresh_progress["errors"] += 1
                return False
            except Exception as e:
                logger.warning(f"Error refreshing feed {feed_name}: {e}")
                self.refresh_progress["errors"] += 1
                return False
            finally:
                async with progress_lock:
                    if feed_name in active_feeds:
                        active_feeds.remove(feed_name)
                    if active_feeds:
                        self.refresh_progress["current_feed"] = active_feeds[-1]
                    else:
                        self.refresh_progress["current_feed"] = feed_name
                    self.refresh_progress["completed"] += 1

        async def tracked_worker(feed_row: dict[str, Any]) -> bool:
            curr_task = asyncio.current_task()
            if curr_task:
                self._active_tasks.add(curr_task)
            try:
                return await worker(feed_row)
            finally:
                if curr_task:
                    self._active_tasks.discard(curr_task)

        try:
            results = await asyncio.gather(*(tracked_worker(feed) for feed in target_feeds), return_exceptions=True)
            success_count = sum(1 for r in results if r is True)
            return {
                "refreshed_count": success_count,
                "total_attempted": len(target_feeds),
                "new_articles": self.refresh_progress["new_articles"],
            }
        finally:
            self.refresh_progress["is_running"] = False
            self.refresh_progress["current_feed"] = ""

    def cancel_refresh(self) -> int:
        """立即終止所有正在進行的抓取更新任務 (Cancel all active refresh tasks immediately).

        :return: 成功發出取消訊號的任務數量
        """
        cancelled_count = 0
        for task in list(self._active_tasks):
            if not task.done():
                task.cancel()
                cancelled_count += 1
        self.refresh_progress["is_running"] = False
        self.refresh_progress["current_feed"] = ""
        logger.info(f"Manual stop refresh triggered. Cancelled {cancelled_count} active crawl tasks.")
        return cancelled_count

    async def poll_due_feeds(self) -> int:
        """探測並抓取所有已到期之訂閱頻道 (Poll and fetch all overdue feeds).

        :return: 本次成功處理的頻道數量 (Number of processed feeds)
        """
        if self._is_shutting_down:
            return 0

        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id, feed_url, title, etag_header, last_modified_header,
                       check_interval_minutes, error_count, requires_flaresolverr,
                       COALESCE(auto_full_text, 0) as auto_full_text
                FROM feeds
                WHERE is_paused = 0 AND (next_check_at IS NULL OR next_check_at <= CURRENT_TIMESTAMP)
                ORDER BY error_count ASC, next_check_at ASC
                LIMIT 50
                """
            )
            due_feeds = [dict(r) for r in await cursor.fetchall()]

        if not due_feeds or self._is_shutting_down:
            return 0

        logger.info(
            f"Scheduler found {len(due_feeds)} due feeds for crawling."
        )

        sem = asyncio.Semaphore(10)

        async def worker(row: dict[str, Any]) -> bool:
            if self._is_shutting_down:
                return False
            curr_task = asyncio.current_task()
            if curr_task:
                self._active_tasks.add(curr_task)
            feed_url = row.get("feed_url", "")
            feed_id = row.get("id")
            interval_mins = row.get("check_interval_minutes") or 30
            error_count = row.get("error_count") or 0
            host_sem = self._get_host_semaphore(feed_url)
            try:
                async with sem:
                    async with host_sem:
                        res = await self._process_single_feed(row)
                        return res[0] if isinstance(res, tuple) else bool(res)
            except asyncio.CancelledError:
                logger.debug(f"Feed crawl cancelled: {row.get('title') or feed_url}")
                return False
            except Exception as w_err:
                logger.warning(f"Background feed worker exception for {row.get('title') or feed_url}: {w_err}")
                if feed_id:
                    try:
                        next_check = calculate_next_check_time(interval_mins, error_count=error_count + 1)
                        async with self.db.write_transaction() as conn:
                            await conn.execute(
                                """
                                UPDATE feeds
                                SET last_checked_at = CURRENT_TIMESTAMP,
                                    next_check_at = ?,
                                    error_count = error_count + 1,
                                    last_error_message = ?
                                WHERE id = ?
                                """,
                                (next_check.strftime("%Y-%m-%d %H:%M:%S"), str(w_err), feed_id),
                            )
                            await conn.commit()
                    except Exception:
                        pass
                return False
            finally:
                if curr_task:
                    self._active_tasks.discard(curr_task)

        tasks = [worker(row) for row in due_feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_count = sum(1 for r in results if r is True)
        return processed_count

    async def _process_single_feed(
        self,
        feed_row: dict[str, Any],
        force_refresh: bool = False,
    ) -> tuple[bool, int]:
        """抓取並處理單一頻道之最新內容 (委派至 FeedPipeline)."""
        return await self.pipeline.process_single_feed(feed_row, force_refresh=force_refresh)

    async def _ingest_articles_atomic(
        self,
        feed_id: int,
        feed_row: dict[str, Any],
        crawl_result: Any,
        next_check: Any,
    ) -> int:
        """單一原子交易寫入 (向後相容轉發至 FeedPipeline)."""
        return await self.pipeline.ingest_articles_atomic(feed_id, feed_row, crawl_result, next_check)

    async def _auto_fetch_full_text(
        self,
        article_items: list[Any],
        requires_flaresolverr: bool = False,
    ) -> None:
        """非同步背景抓取全文 (向後相容轉發至 FeedPipeline)."""
        await self.pipeline.auto_fetch_full_text(article_items, requires_flaresolverr=requires_flaresolverr)

    async def _auto_execute_rule_plugins(
        self,
        plugin_actions: list[tuple[int, str, Optional[str], int]],
    ) -> None:
        """非同步背景執行規則外掛 (向後相容轉發至 FeedPipeline)."""
        await self.pipeline.auto_execute_rule_plugins(plugin_actions)

    async def maintain_database(self, retention_days: int = 60) -> None:
        """執行資料庫維護與過期文章清理 (Execute database maintenance, retention cleanup, and WAL checkpoint).

        :param retention_days: 預設保留天數 (Default retention days for unstarred articles)
        """
        logger.info("Starting scheduled database maintenance and retention cleanup...")
        async with self.db.write_transaction() as conn:
            cursor = await conn.execute(
                """
                DELETE FROM articles_hot
                WHERE id NOT IN (
                    SELECT article_id FROM user_article_states WHERE is_starred = 1
                )
                AND published_at < datetime('now', '-' || ? || ' days')
                """,
                (retention_days,),
            )
            deleted_count = cursor.rowcount if cursor.rowcount > 0 else 0
            if deleted_count > 0:
                logger.info(
                    f"Retention cleanup purged {deleted_count} expired articles."
                )

            await conn.commit()
            try:
                await conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except Exception:
                pass
        logger.info("Database maintenance completed successfully.")


_GLOBAL_SCHEDULER: Optional[OmniScheduler] = None


def get_global_scheduler() -> Optional[OmniScheduler]:
    """取得全域排程器單例 (Get global scheduler instance)."""
    global _GLOBAL_SCHEDULER
    return _GLOBAL_SCHEDULER


def set_global_scheduler(scheduler: OmniScheduler) -> None:
    """設定全域排程器單例 (Set global scheduler instance)."""
    global _GLOBAL_SCHEDULER
    _GLOBAL_SCHEDULER = scheduler
