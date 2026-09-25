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
from omnirss.core.database import (
    DatabaseManager,
    compute_entry_hash,
    get_db_manager,
)
from omnirss.core.rule_engine import RuleDef, RuleEngine
from omnirss.sdk.models import ArticleDTO

logger = logging.getLogger("omnirss.scheduler")


def resolve_effective_min_publish_date(
    feed_min_date: Optional[str],
    feed_force_min: bool,
    cat_min_date: Optional[str],
    cat_force_min: bool,
    global_min_date: Optional[str],
    global_force_min: bool,
) -> Optional[datetime]:
    """解析三層收錄起始時間與強制覆蓋優先級 (Resolve 3-tier min publish date hierarchy).

    優先級順序：
    1. 來源強制 (Feed Force)
    2. 全域強制 (Global Force)
    3. 分類強制 (Category Force)
    4. 一般自主繼承 (來源自訂 > 分類自訂 > 全域預設)

    :param feed_min_date: 來源頻道自訂起始日期字串
    :param feed_force_min: 來源是否勾選強制特許
    :param cat_min_date: 所屬分類自訂起始日期字串
    :param cat_force_min: 分類是否勾選強制向下套用
    :param global_min_date: 系統全域預設起始日期字串
    :param global_force_min: 全域是否勾選強制向下套用
    :return: 最終生效之 datetime 物件，或 None (代表不限起始日期)
    """
    def parse_dt(d_str: Optional[str]) -> Optional[datetime]:
        if not d_str:
            return None
        try:
            clean = str(d_str).strip().replace("Z", "+00:00")
            if len(clean) == 10:  # YYYY-MM-DD
                return datetime.strptime(clean, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return datetime.fromisoformat(clean)
        except Exception:
            return None

    feed_dt = parse_dt(feed_min_date)
    cat_dt = parse_dt(cat_min_date)
    global_dt = parse_dt(global_min_date)

    # 1. 來源最高特許
    if feed_force_min and feed_dt:
        return feed_dt
    # 2. 全域強制統一
    if global_force_min and global_dt:
        return global_dt
    # 3. 分類強制統一
    if cat_force_min and cat_dt:
        return cat_dt
    # 4. 一般階層繼承
    return feed_dt or cat_dt or global_dt


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
        self.poll_interval = poll_interval_seconds
        self.scheduler = AsyncIOScheduler()
        self._is_running = False
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

        try:
            self.scheduler.shutdown(wait=wait)
        except Exception as e:
            logger.warning(f"Error during APScheduler shutdown: {e}")
        self._is_running = False
        logger.info("OmniRSS background scheduler stopped.")

    async def async_shutdown(self, timeout: float = 1.0) -> None:
        """非同步強制停止排程器並取消所有執行中的爬蟲協程 (Cancel all active crawling tasks on shutdown)."""
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
        sem = asyncio.Semaphore(40)

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

                        await asyncio.sleep(0.03)  # 30ms 平滑微延遲防止衝擊目標伺服器
                        res = await asyncio.wait_for(
                            self._process_single_feed(feed_row, force_refresh=force_refresh), timeout=25.0
                        )
                        success, new_arts = res if isinstance(res, tuple) else (bool(res), 0)
                        if success:
                            self.refresh_progress["new_articles"] += new_arts
                        else:
                            self.refresh_progress["errors"] += 1
                        return success
            except asyncio.TimeoutError:
                logger.warning(f"Feed crawl timed out (25s cutoff): {feed_name}")
                self.refresh_progress["errors"] += 1
                return False
            except Exception:
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

    async def poll_due_feeds(self) -> int:
        """探測並抓取所有已到期之訂閱頻道 (Poll and fetch all overdue feeds).

        :return: 本次成功處理的頻道數量 (Number of processed feeds)
        """
        async with self.db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id, feed_url, title, etag_header, last_modified_header,
                       check_interval_minutes, error_count, requires_flaresolverr,
                       COALESCE(auto_full_text, 0) as auto_full_text
                FROM feeds
                WHERE is_paused = 0 AND (next_check_at IS NULL OR next_check_at <= CURRENT_TIMESTAMP)
                ORDER BY error_count ASC, next_check_at ASC
                LIMIT 100
                """
            )
            due_feeds = [dict(r) for r in await cursor.fetchall()]

        if not due_feeds:
            return 0

        logger.info(
            f"Scheduler found {len(due_feeds)} due feeds for crawling."
        )

        sem = asyncio.Semaphore(10)

        async def worker(row: dict[str, Any]) -> bool:
            curr_task = asyncio.current_task()
            if curr_task:
                self._active_tasks.add(curr_task)
            try:
                async with sem:
                    res = await self._process_single_feed(row)
                    return res[0] if isinstance(res, tuple) else bool(res)
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
        """抓取並處理單一頻道之最新內容 (Fetch and ingest a single feed).

        :param feed_row: 頻道資料列字典 (Feed database row)
        :param force_refresh: 是否強制穿透快取 (Bypass ETag/304 cache)
        :return: (是否成功, 新增文章數)
        """
        feed_id = feed_row["id"]
        feed_url = feed_row["feed_url"]
        etag = feed_row.get("etag_header")
        last_modified = feed_row.get("last_modified_header")
        interval_mins = feed_row.get("check_interval_minutes") or 30
        error_count = feed_row.get("error_count") or 0
        requires_flaresolverr = bool(feed_row.get("requires_flaresolverr", 0))

        try:
            # 1. 執行純網路 I/O 非同步抓取 (Zero database connection during crawl)
            import inspect
            sig = inspect.signature(self.crawler.fetch_feed)
            kwargs: dict[str, Any] = {
                "url": feed_url,
                "etag": etag,
                "last_modified": last_modified,
                "requires_flaresolverr": requires_flaresolverr,
            }
            if "force_refresh" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                kwargs["force_refresh"] = force_refresh

            crawl_result = await self.crawler.fetch_feed(**kwargs)

            # 2. 處理 HTTP 304 零流量快取命中 (Handle 304 Not Modified)
            if (
                crawl_result.status_code == 304
                or not crawl_result.is_modified
                and crawl_result.status_code == 200
            ):
                next_check = calculate_next_check_time(interval_mins, error_count=0)
                async with self.db.write_transaction() as conn:
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
                return (True, 0)

            # 3. 若抓取失敗，套用指數退避排程 (Handle crawl failure with backoff)
            if crawl_result.status_code >= 400 or crawl_result.error_message:
                new_error_count = error_count + 1
                next_check = calculate_next_check_time(
                    interval_mins, error_count=new_error_count
                )
                err_msg = crawl_result.error_message or f"HTTP {crawl_result.status_code}"
                async with self.db.write_transaction() as conn:
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
                return (False, 0)

            # 4. 抓取成功：在全局寫入鎖下執行單一原子交易入庫 (Ingest articles atomically)
            next_check = calculate_next_check_time(interval_mins, error_count=0)
            new_arts = await self._ingest_articles_atomic(feed_id, feed_row, crawl_result, next_check)
            return (True, new_arts)

        except Exception as e:
            logger.exception(f"Unhandled error polling feed '{feed_url}': {e}")
            new_error_count = error_count + 1
            next_check = calculate_next_check_time(
                interval_mins, error_count=new_error_count
            )
            try:
                async with self.db.write_transaction() as conn:
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
            except Exception:
                pass
            return (False, 0)

    async def _ingest_articles_atomic(
        self,
        feed_id: int,
        feed_row: dict[str, Any],
        crawl_result: Any,
        next_check: datetime,
    ) -> int:
        """單一原子交易寫入文章與更新未讀數 (Single atomic ingestion transaction under write lock)."""
        new_inserted_count = 0
        newly_inserted_articles: list[tuple[int, str]] = []
        is_auto_full_text = bool(feed_row.get("auto_full_text", 0))

        async with self.db.write_transaction() as conn:
            # 1. 獲取訂閱該頻道的使用者與其規則
            u_cursor = await conn.execute(
                "SELECT user_id, category_id FROM user_feeds WHERE feed_id = ?", (feed_id,)
            )
            user_rows = await u_cursor.fetchall()
            subscribed_users = [(r["user_id"], r["category_id"]) for r in user_rows]
            subscribed_user_ids = [u[0] for u in subscribed_users]

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
                        conds_data = json.loads(row["conditions_json"])
                        if isinstance(conds_data, dict):
                            match_mode_val = conds_data.get("match_mode", "all")
                            cond_list = conds_data.get("rules") or conds_data.get("conditions") or []
                        elif isinstance(conds_data, list):
                            match_mode_val = "all"
                            cond_list = conds_data
                        elif isinstance(conds_data, str):
                            match_mode_val = "all"
                            cond_list = [conds_data]
                        else:
                            match_mode_val = "all"
                            cond_list = []

                        from omnirss.core.rule_engine import RuleCondition, RuleAction, MatchMode, RuleActionType, RuleField, RuleOperator
                        conds = []
                        for c in cond_list:
                            if isinstance(c, str):
                                c = {"field": "title", "operator": "contains", "value": c}
                            elif not isinstance(c, dict):
                                continue
                            f = c.get("field", "title")
                            if f in ("content_text", "content_html"):
                                f = "content"
                            elif f in ("link",):
                                f = "url"
                            elif f in ("feed",):
                                f = "feed_title"
                            conds.append(
                                RuleCondition(
                                    field=RuleField(f),
                                    operator=RuleOperator(c.get("operator", "contains")),
                                    value=str(c.get("value", "")),
                                    case_sensitive=bool(c.get("case_sensitive", False)),
                                )
                            )

                        acts_raw = json.loads(row["actions_json"])
                        if isinstance(acts_raw, str):
                            acts_raw = [{"action": acts_raw, "params": {}}]
                        elif not isinstance(acts_raw, list):
                            acts_raw = []
                        acts = []
                        for a in acts_raw:
                            if isinstance(a, str):
                                a = {"action": a, "params": {}}
                            elif not isinstance(a, dict):
                                continue
                            act_type = a.get("action") or a.get("action_type") or "mark_read"
                            params = a.get("params") or a.get("parameters") or {}
                            acts.append(RuleAction(action=RuleActionType(act_type), params=params))

                        rules.append(
                            RuleDef(
                                id=str(row["id"]),
                                rule_name=row["name"],
                                priority=row["sort_order"],
                                is_active=bool(row["is_enabled"]),
                                match_mode=MatchMode(match_mode_val),
                                conditions=conds,
                                actions=acts,
                            )
                        )
                    except Exception as ex:
                        logger.warning(f"Error parsing user rule {row['id']}: {ex}")
                user_rules_map[uid] = rules

            feed_title = feed_row.get("title", "")

            # 2. 解析三層收錄起始時間與強制覆蓋策略 (Resolve 3-Tier Effective Min Publish Date)
            cat_ids = [u[1] for u in subscribed_users if u[1] is not None]
            cat_min_date = None
            cat_force_min = False
            if cat_ids:
                c_cur = await conn.execute(
                    "SELECT custom_min_date, COALESCE(force_min_date, 0) as force_min_date FROM categories WHERE id = ?",
                    (cat_ids[0],),
                )
                c_row = await c_cur.fetchone()
                if c_row:
                    cat_min_date = c_row["custom_min_date"]
                    cat_force_min = bool(c_row["force_min_date"])

            from omnirss.core.config import get_settings
            global_settings = get_settings()
            global_min_date = global_settings.retention.min_publish_date
            global_force_min = bool(global_settings.retention.force_min_date)

            effective_min_dt = resolve_effective_min_publish_date(
                feed_min_date=feed_row.get("min_publish_date"),
                feed_force_min=bool(feed_row.get("force_min_date", 0)),
                cat_min_date=cat_min_date,
                cat_force_min=cat_force_min,
                global_min_date=global_min_date,
                global_force_min=global_force_min,
            )

            # 3. 批量寫入文章與狀態
            for article in crawl_result.articles:
                # 若文章發布時間早於有效起始收錄時間，直接略過
                if effective_min_dt and article.published_at:
                    art_pub = article.published_at
                    if art_pub.tzinfo is None:
                        art_pub = art_pub.replace(tzinfo=timezone.utc)
                    eff_dt = effective_min_dt
                    if eff_dt.tzinfo is None:
                        eff_dt = eff_dt.replace(tzinfo=timezone.utc)
                    if art_pub < eff_dt:
                        continue

                entry_hash = compute_entry_hash(
                    feed_id, article.guid, article.url
                )
                published_str = article.published_at.strftime("%Y-%m-%d %H:%M:%S")

                ins_cur = await conn.execute(
                    """
                    INSERT OR IGNORE INTO articles_hot (
                        feed_id, entry_hash, title, url, author, snippet, content_html, content_text, cover_image_url, published_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        feed_id,
                        entry_hash,
                        article.title,
                        article.url,
                        article.author,
                        article.snippet,
                        article.content_html,
                        article.content_text,
                        article.cover_image_url,
                        published_str,
                    ),
                )
                is_new = ins_cur.rowcount > 0
                if is_new:
                    new_inserted_count += 1

                a_cur = await conn.execute(
                    "SELECT id FROM articles_hot WHERE entry_hash = ?",
                    (entry_hash,),
                )
                a_row = await a_cur.fetchone()
                if not a_row:
                    continue
                article_db_id = a_row["id"]

                if is_new and is_auto_full_text and article.url:
                    newly_inserted_articles.append((article_db_id, article.url))

                for uid in subscribed_user_ids:
                    rules = user_rules_map.get(uid, [])
                    processed_article, executed = RuleEngine.process_article(
                        article.model_copy(), rules, feed_title=feed_title
                    )

                    is_trash = 1 if any("trash" in x for x in executed) or "trashed" in processed_article.extra_tags else 0
                    is_read = 1 if processed_article.is_read else 0
                    is_starred = 1 if processed_article.is_starred else 0

                    await conn.execute(
                        """
                        INSERT OR IGNORE INTO user_article_states (
                            user_id, article_id, is_read, is_starred, is_trash, starred_at
                        ) VALUES (?, ?, ?, ?, ?, CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END)
                        """,
                        (
                            uid,
                            article_db_id,
                            is_read,
                            is_starred,
                            is_trash,
                            is_starred,
                        ),
                    )

                    # 處理自動打標籤 (Add Tag)
                    for act_item in executed:
                        if "add_tag:" in act_item:
                            tag_name = act_item.split("add_tag:", 1)[1].strip()
                            if tag_name:
                                t_cur = await conn.execute(
                                    "SELECT id FROM tags WHERE user_id = ? AND name = ?",
                                    (uid, tag_name),
                                )
                                t_row = await t_cur.fetchone()
                                if t_row:
                                    tag_id = t_row["id"]
                                else:
                                    ins_t = await conn.execute(
                                        "INSERT INTO tags (user_id, name, color_hex) VALUES (?, ?, ?)",
                                        (uid, tag_name, "#ef4444" if tag_name == "重要" else "#3b82f6"),
                                    )
                                    tag_id = ins_t.lastrowid
                                await conn.execute(
                                    "INSERT OR IGNORE INTO article_tags (article_id, tag_id) VALUES (?, ?)",
                                    (article_db_id, tag_id),
                                )

            # 3. 更新頻道成功中繼資料
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

            # 4. 精準自癒與校正該頻道及分類之未讀計數
            for uid, cat_id in subscribed_users:
                await conn.execute(
                    """
                    UPDATE user_feeds
                    SET unread_count = (
                        SELECT COUNT(*)
                        FROM articles_hot a
                        LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = user_feeds.user_id
                        WHERE a.feed_id = user_feeds.feed_id AND COALESCE(uas.is_read, 0) = 0
                    )
                    WHERE user_id = ? AND feed_id = ?
                    """,
                    (uid, feed_id),
                )
                if cat_id is not None:
                    await conn.execute(
                        """
                        UPDATE categories
                        SET unread_count = (
                            SELECT COALESCE(SUM(unread_count), 0)
                            FROM user_feeds
                            WHERE user_feeds.category_id = categories.id AND user_feeds.user_id = categories.user_id
                        )
                        WHERE id = ? AND user_id = ?
                        """,
                        (cat_id, uid),
                    )

            await conn.commit()

        # 5. 若啟用自動抓取全文且有新文章入庫，以非阻塞協程在背景排程抓取全文 (Non-blocking background full-text fetch)
        if newly_inserted_articles:
            asyncio.create_task(
                self._auto_fetch_full_text(
                    newly_inserted_articles,
                    requires_flaresolverr=bool(feed_row.get("requires_flaresolverr", 0)),
                )
            )

        return new_inserted_count

    async def _auto_fetch_full_text(
        self,
        article_items: list[tuple[int, str]],
        requires_flaresolverr: bool = False,
    ) -> None:
        """非同步背景自動抓取文章全文與展開推文/圖片 (Background auto fetch full text for new articles).

        :param article_items: (article_id, url) 清單
        :param requires_flaresolverr: 是否需經由 FlareSolverr 代理
        """
        from omnirss.core.security import HTMLSanitizer

        for article_id, article_url in article_items:
            if not article_url:
                continue
            try:
                crawl_res = await self.crawler.fetch_feed(
                    url=article_url,
                    requires_flaresolverr=requires_flaresolverr,
                )
                if crawl_res.status_code < 400 and crawl_res.content_bytes:
                    html_raw = crawl_res.content_bytes.decode("utf-8", errors="replace")
                    extracted_html = CrawlerEngine.extract_full_text_from_html(html_raw, base_url=article_url)
                    if extracted_html:
                        extracted_text = HTMLSanitizer.extract_text(extracted_html)
                        new_snippet = HTMLSanitizer.extract_snippet(extracted_html, max_chars=200)
                        async with self.db.write_transaction() as conn:
                            await conn.execute(
                                """
                                UPDATE articles_hot
                                SET content_html = ?, content_text = ?, snippet = ?
                                WHERE id = ?
                                """,
                                (extracted_html, extracted_text, new_snippet, article_id),
                            )
                            await conn.commit()
            except Exception as e:
                logger.debug(f"Auto full text fetch skipped for article {article_id}: {e}")

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

