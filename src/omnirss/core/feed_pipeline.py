"""頻道與文章處理流水線引擎 (Feed & Article Ingestion Pipeline Engine).

This module encapsulates the 5-tier article ingestion pipeline:
1. Network crawl & 304 cache handling
2. 3-tier date resolution & pre-filtering
3. In-memory plugin enrichment & non-blocking full-text extraction
4. Atomic database ingestion & rule matching
5. Non-blocking rule plugin execution
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Optional

from omnirss.core.crawler_engine import (
    CrawlerEngine,
    calculate_next_check_time,
)
from omnirss.core.database import (
    DatabaseManager,
    compute_entry_hash,
    get_db_manager,
    normalize_article_url,
)
from omnirss.core.rule_engine import RuleDef, RuleEngine
from omnirss.sdk.models import ArticleDTO

logger = logging.getLogger("omnirss.feed_pipeline")


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

    支援動態相對滾動視窗代碼（'today', '7days', '30days', '90days', '180days', '365days'）與絕對日期。

    :param feed_min_date: 來源頻道自訂起始日期字串或代碼
    :param feed_force_min: 來源是否勾選強制特許
    :param cat_min_date: 所屬分類自訂起始日期字串或代碼
    :param cat_force_min: 分類是否勾選強制向下套用
    :param global_min_date: 系統全域預設起始日期字串或代碼
    :param global_force_min: 全域是否勾選強制向下套用
    :return: 最終生效之 datetime 物件，或 None (代表不限起始日期)
    """
    def parse_dt(d_str: Optional[str]) -> Optional[datetime]:
        if not d_str:
            return None
        clean = str(d_str).strip().lower()
        if clean in ("", "none", "null", "default", "all", "1970-01-01 00:00:00", "1970-01-01"):
            return None
        now_utc = datetime.now(timezone.utc)
        if clean == "today":
            return now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        if clean in ("7days", "7d"):
            return now_utc - timedelta(days=7)
        if clean in ("30days", "30d"):
            return now_utc - timedelta(days=30)
        if clean in ("90days", "90d"):
            return now_utc - timedelta(days=90)
        if clean in ("180days", "180d"):
            return now_utc - timedelta(days=180)
        if clean in ("365days", "365d", "1year"):
            return now_utc - timedelta(days=365)

        # 絕對固定日期解析 (YYYY-MM-DD 或 ISO 格式)
        try:
            iso_clean = str(d_str).strip().replace("Z", "+00:00")
            if len(iso_clean) == 10:  # YYYY-MM-DD
                return datetime.strptime(iso_clean, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            dt = datetime.fromisoformat(iso_clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
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


class FeedPipeline:
    """單一頻道處理流水線 (Feed Ingestion & Processing Pipeline)."""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        crawler_engine: Optional[CrawlerEngine] = None,
    ) -> None:
        self.db = db_manager or get_db_manager()
        self.crawler = crawler_engine or CrawlerEngine()

    async def process_single_feed(
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

            try:
                crawl_result = await asyncio.wait_for(
                    self.crawler.fetch_feed(**kwargs),
                    timeout=25.0,
                )
            except asyncio.TimeoutError:
                from omnirss.core.crawler_engine import CrawlResult
                logger.warning(f"Network crawl timeout (25s) for feed: {feed_url}")
                crawl_result = CrawlResult(
                    url=feed_url,
                    status_code=408,
                    is_modified=False,
                    error_message="HTTP Request Timeout (25s)",
                )

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
            new_arts = await self.ingest_articles_atomic(feed_id, feed_row, crawl_result, next_check)
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

    async def ingest_articles_atomic(
        self,
        feed_id: int,
        feed_row: dict[str, Any],
        crawl_result: Any,
        next_check: datetime,
    ) -> int:
        """單一原子交易寫入文章與更新未讀數 (Single atomic ingestion transaction under write lock).

        生命週期標準管線：
        1. 來源抓取完成 ➔ 2. 日期快篩 ➔ 3. 外掛增強與無鎖全文萃取 ➔ 4. 規則引擎匹配 ➔ 5. 極速原子入庫。
        """
        new_inserted_count = 0
        is_auto_full_text = bool(feed_row.get("auto_full_text", 0))

        # 1. 快速唯讀查詢訂閱此頻道之用戶與其過濾規則、生效收錄時間與全文偏好 (Read subscriptions, rules and settings)
        async with self.db.get_connection() as rconn:
            u_cursor = await rconn.execute(
                "SELECT user_id, category_id FROM user_feeds WHERE feed_id = ?", (feed_id,)
            )
            user_rows = await u_cursor.fetchall()
            subscribed_users = [(r["user_id"], r["category_id"]) for r in user_rows]
            subscribed_user_ids = [u[0] for u in subscribed_users]

            user_rules_map: dict[int, list[RuleDef]] = {}
            for uid in subscribed_user_ids:
                r_cursor = await rconn.execute(
                    """
                    SELECT id, name, sort_order, is_enabled,
                           COALESCE(scope_type, 'all') as scope_type,
                           scope_category_id,
                           COALESCE(scope_feed_ids_json, '[]') as scope_feed_ids_json,
                           COALESCE(match_mode, 'all') as match_mode,
                           COALESCE(condition_groups_json, '[]') as condition_groups_json,
                           conditions_json, actions_json
                    FROM user_rules
                    WHERE user_id = ? AND is_enabled = 1
                    ORDER BY sort_order ASC
                    """,
                    (uid,),
                )
                rules: list[RuleDef] = []
                for row in await r_cursor.fetchall():
                    try:
                        from omnirss.api.routers.rules import parse_db_rule_row
                        rules.append(parse_db_rule_row(row))
                    except Exception as ex:
                        logger.warning(f"Error parsing user rule {row['id']}: {ex}")
                user_rules_map[uid] = rules

            # 解析三層收錄起始時間與自動擷取全文策略 (Resolve 3-Tier Effective Min Publish Date & Auto Full-Text)
            cat_ids = [u[1] for u in subscribed_users if u[1] is not None]
            cat_min_date = None
            cat_force_min = False
            cat_auto_full = False
            if cat_ids:
                c_cur = await rconn.execute(
                    "SELECT custom_min_date, COALESCE(force_min_date, 0) as force_min_date, COALESCE(auto_full_text, 0) as auto_full_text FROM categories WHERE id = ?",
                    (cat_ids[0],),
                )
                c_row = await c_cur.fetchone()
                if c_row:
                    cat_min_date = c_row["custom_min_date"]
                    cat_force_min = bool(c_row["force_min_date"])
                    cat_auto_full = bool(c_row["auto_full_text"])

            user_ids = [u[0] for u in subscribed_users if u[0] is not None]
            user_global_min_date = None
            user_global_force_min = False
            user_global_auto_full = False
            if user_ids:
                u_cur = await rconn.execute(
                    "SELECT settings_json FROM users WHERE id = ?",
                    (user_ids[0],),
                )
                u_row = await u_cur.fetchone()
                if u_row and u_row["settings_json"]:
                    try:
                        u_settings = json.loads(u_row["settings_json"])
                        if isinstance(u_settings, dict):
                            user_global_min_date = u_settings.get("minPublishDate") or u_settings.get("min_publish_date")
                            user_global_force_min = bool(u_settings.get("forceMinDate") or u_settings.get("force_min_date"))
                            user_global_auto_full = bool(u_settings.get("autoFullText", False))
                    except Exception:
                        pass

        from omnirss.core.config import get_settings
        global_settings = get_settings()
        global_min_date = user_global_min_date or global_settings.retention.min_publish_date
        global_force_min = user_global_force_min or bool(global_settings.retention.force_min_date)

        effective_min_dt = resolve_effective_min_publish_date(
            feed_min_date=feed_row.get("min_publish_date"),
            feed_force_min=bool(feed_row.get("force_min_date", 0)),
            cat_min_date=cat_min_date,
            cat_force_min=cat_force_min,
            global_min_date=global_min_date,
            global_force_min=global_force_min,
        )

        # 三層級聯判定 auto_full_text: 來源 > 分類 > 全域
        feed_auto_ft = feed_row.get("auto_full_text")
        if feed_auto_ft is not None and bool(feed_auto_ft):
            is_auto_full_text = True
        elif cat_auto_full:
            is_auto_full_text = True
        elif user_global_auto_full:
            is_auto_full_text = True
        else:
            is_auto_full_text = False

        # 2. 前置生失效快篩 (Pre-filter by effective_min_dt before network processing)
        raw_articles = crawl_result.articles or []
        valid_articles = []
        for article in raw_articles:
            if effective_min_dt and article.published_at:
                art_pub = article.published_at if article.published_at.tzinfo else article.published_at.replace(tzinfo=timezone.utc)
                eff_dt = effective_min_dt if effective_min_dt.tzinfo else effective_min_dt.replace(tzinfo=timezone.utc)
                if art_pub < eff_dt:
                    continue
            valid_articles.append(article)

        # 3. 外掛增強與無鎖全文萃取管線 (Autonomous Enrichment & Generic Full-Text Pipeline in Memory)
        from omnirss.core.plugin_manager import get_plugin_manager
        from omnirss.core.security import HTMLSanitizer
        pm = get_plugin_manager()
        requires_flaresolverr = bool(feed_row.get("requires_flaresolverr", 0))

        async def enrich_single_article(art: Any) -> Any:
            # 3A. 優先流經專屬處理外掛 (PTT / Yahoo / Mobile01 等會自主爬取完整網頁)
            try:
                art = await pm.execute_all_processors(art, trigger_source="feed_crawl")
            except Exception as p_err:
                logger.debug(f"Plugin pipeline bypass for '{art.title}': {p_err}")

            # 3B. 若無專屬外掛處理且頻道開啟 auto_full_text，在此無鎖階段一併提取通用全文
            is_custom_enriched = (
                "ptt-meta-card" in (art.content_html or "")
                or "yh-article" in (art.content_html or "")
                or "m01-article" in (art.content_html or "")
            )
            if not is_custom_enriched and is_auto_full_text and art.url:
                try:
                    curr_len = len((art.content_html or "").strip())
                    if curr_len < 300:
                        st, html_raw = await self.crawler.fetch_web_page(
                            url=art.url,
                            requires_flaresolverr=requires_flaresolverr,
                        )
                        if st < 400 and html_raw:
                            ext_html = await asyncio.to_thread(
                                CrawlerEngine.extract_full_text_from_html, html_raw, base_url=art.url
                            )
                            if ext_html and len(ext_html.strip()) > curr_len:
                                art.content_html = ext_html
                                art.content_text = HTMLSanitizer.extract_text(ext_html)
                                art.snippet = HTMLSanitizer.extract_snippet(ext_html, max_chars=200)
                except Exception as ft_err:
                    logger.debug(f"In-memory full-text extract notice for '{art.title}': {ft_err}")

            return art

        if valid_articles:
            art_sem = asyncio.Semaphore(5)
            async def limited_enrich(art: Any) -> Any:
                async with art_sem:
                    return await enrich_single_article(art)
            preprocessed_articles = list(await asyncio.gather(*(limited_enrich(a) for a in valid_articles)))
        else:
            preprocessed_articles = []

        feed_title = feed_row.get("title", "")
        plugin_actions_to_run: list[tuple[int, str, Optional[str], int]] = []

        # 4. 極速單一原子交易寫入資料庫與規則匹配 (Atomic DB Ingestion & Rule Matching)
        async with self.db.write_transaction() as conn:
            for article in preprocessed_articles:
                clean_url = normalize_article_url(article.url) if article.url else ""
                clean_guid = article.guid or clean_url or article.title

                entry_hash = compute_entry_hash(
                    feed_id, clean_guid, clean_url or article.url
                )
                published_str = article.published_at.strftime("%Y-%m-%d %H:%M:%S")

                # 防衛性判重：先檢查此頻道中是否已有同 entry_hash 或同標準化 URL 的現存文章
                existing_cur = await conn.execute(
                    """
                    SELECT id, entry_hash, url FROM articles_hot
                    WHERE feed_id = ? AND (
                        entry_hash = ? OR (url != '' AND rtrim(url, '/') = rtrim(?, '/'))
                    )
                    LIMIT 1
                    """,
                    (feed_id, entry_hash, clean_url or article.url),
                )
                existing_row = await existing_cur.fetchone()

                if existing_row:
                    article_db_id = existing_row["id"]
                    # 若現存資料之 URL 未標準化或 entry_hash 為舊版，即時同步更新
                    if existing_row["url"] != (clean_url or article.url) or existing_row["entry_hash"] != entry_hash:
                        await conn.execute(
                            "UPDATE articles_hot SET url = ?, entry_hash = ? WHERE id = ?",
                            (clean_url or article.url, entry_hash, article_db_id),
                        )
                else:
                    # 於寫入 DB 前已於無鎖前置階段完成外掛與全文處理，此處直接執行極速原子寫入
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
                            clean_url or article.url,
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
                    else:
                        continue

                # 4B. 執行規則引擎匹配 (以包含完整全文與外掛結構的文章執行精準過濾)
                for uid, u_cat_id in subscribed_users:
                    rules = user_rules_map.get(uid, [])
                    processed_article, executed = RuleEngine.process_article(
                        article.model_copy(),
                        rules,
                        feed_id=feed_id,
                        category_id=u_cat_id,
                        feed_title=feed_title,
                    )

                    is_trash = 1 if any("trash" in x for x in executed) or "trashed" in processed_article.extra_tags else 0
                    is_read = 1 if processed_article.is_read else 0
                    is_starred = 1 if processed_article.is_starred else 0
                    highlight_color = processed_article.highlight_color

                    await conn.execute(
                        """
                        INSERT OR IGNORE INTO user_article_states (
                            user_id, article_id, is_read, is_starred, is_trash, highlight_color, starred_at
                        ) VALUES (?, ?, ?, ?, ?, ?, CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END)
                        """,
                        (
                            uid,
                            article_db_id,
                            is_read,
                            is_starred,
                            is_trash,
                            highlight_color,
                            is_starred,
                        ),
                    )

                    # 處理自動打標籤 (Add Tag) 與外掛動作 (Execute Plugin)
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
                        elif "execute_plugin:" in act_item:
                            parts = act_item.split("execute_plugin:", 1)[1].split(":", 1)
                            p_id = parts[0].strip()
                            p_param = parts[1].strip() if len(parts) > 1 else None
                            if p_id:
                                plugin_actions_to_run.append((article_db_id, p_id, p_param, uid))

            # 4C. 更新頻道成功中繼資料
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

            # 4D. 精準自癒與校正該頻道及分類之未讀計數
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

        # 5. 若命中規則外掛動作（例如自動 AI 摘要），以非阻塞協程在背景執行外掛 (Non-blocking background rule plugin executor)
        if plugin_actions_to_run:
            asyncio.create_task(
                self.auto_execute_rule_plugins(plugin_actions_to_run)
            )

        return new_inserted_count

    async def auto_fetch_full_text(
        self,
        article_items: list[Any],
        requires_flaresolverr: bool = False,
    ) -> None:
        """非同步背景自動抓取文章全文與展開推文/圖片 (Background auto fetch full text for new articles).

        :param article_items: (article_id, url) 或 (article_id, url, title) 清單
        :param requires_flaresolverr: 是否需經由 FlareSolverr 代理
        """
        from omnirss.core.plugin_manager import get_plugin_manager
        from omnirss.core.security import HTMLSanitizer
        from omnirss.sdk.models import ArticleDTO

        pm = get_plugin_manager()

        for item in article_items:
            if not item:
                continue
            if len(item) >= 3:
                article_id, article_url, article_title = item[0], item[1], item[2]
            else:
                article_id, article_url = item[0], item[1]
                article_title = ""

            if not article_url:
                continue
            try:
                crawl_res = await self.crawler.fetch_feed(
                    url=article_url,
                    requires_flaresolverr=requires_flaresolverr,
                )
                if crawl_res.status_code < 400 and crawl_res.content_bytes:
                    html_raw = crawl_res.content_bytes.decode("utf-8", errors="replace")
                    extracted_html = await asyncio.to_thread(
                        CrawlerEngine.extract_full_text_from_html, html_raw, base_url=article_url
                    )
                    if extracted_html:
                        extracted_text = HTMLSanitizer.extract_text(extracted_html)
                        new_snippet = HTMLSanitizer.extract_snippet(extracted_html, max_chars=200)

                        # 將新萃取之全文內文流經外掛處理管線 (Pipeline full text through processor plugins)
                        full_art = ArticleDTO(
                            id=article_id,
                            feed_id=0,
                            title=article_title or "",
                            url=article_url,
                            content_html=extracted_html,
                            content_text=extracted_text,
                            snippet=new_snippet,
                        )
                        try:
                            processed_full = await pm.execute_all_processors(
                                full_art, trigger_source="feed_crawl"
                            )
                            extracted_html = processed_full.content_html or extracted_html
                            extracted_text = processed_full.content_text or extracted_text
                            new_snippet = HTMLSanitizer.extract_snippet(extracted_html, max_chars=200)
                        except Exception as proc_err:
                            logger.debug(f"Full-text processor pipeline bypass for article {article_id}: {proc_err}")

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

    async def auto_execute_rule_plugins(
        self,
        plugin_actions: list[tuple[int, str, Optional[str], int]],
    ) -> None:
        """非同步背景執行規則觸發之外掛動作 (Background async executor for rule-triggered plugins).

        :param plugin_actions: (article_id, plugin_id, param, user_id) 清單
        """
        from omnirss.core.plugin_manager import get_plugin_manager
        from omnirss.sdk.models import ArticleDTO
        mgr = get_plugin_manager()

        for article_id, plugin_id, param, user_id in plugin_actions:
            try:
                # 讀取文章最新內容
                async with self.db.get_connection() as conn:
                    cur = await conn.execute(
                        """
                        SELECT id, guid, url, title, author, published_at,
                               content_html, content_text, snippet, ai_summary
                        FROM articles_hot WHERE id = ?
                        """,
                        (article_id,),
                    )
                    row = await cur.fetchone()
                    if not row:
                        continue

                    dto = ArticleDTO(
                        guid=row["guid"],
                        url=row["url"],
                        title=row["title"],
                        author=row["author"],
                        content_html=row["content_html"] or "",
                        content_text=row["content_text"] or "",
                        snippet=row["snippet"] or "",
                        ai_summary=row["ai_summary"],
                    )

                # 透過 PluginManager 執行外掛 (標記為規則自動觸發)
                updated_dto = await mgr.execute_processor(
                    plugin_id=plugin_id,
                    article=dto,
                    user_id=user_id,
                    action_param=param,
                    trigger_source="rule",
                )

                if updated_dto:
                    fields_to_update = []
                    params_to_update = []
                    if updated_dto.ai_summary and updated_dto.ai_summary != dto.ai_summary:
                        fields_to_update.append("ai_summary = ?")
                        params_to_update.append(updated_dto.ai_summary)
                    if updated_dto.content_html and updated_dto.content_html != dto.content_html:
                        fields_to_update.append("content_html = ?")
                        params_to_update.append(updated_dto.content_html)
                    if updated_dto.content_text and updated_dto.content_text != dto.content_text:
                        fields_to_update.append("content_text = ?")
                        params_to_update.append(updated_dto.content_text)
                    if updated_dto.snippet and updated_dto.snippet != dto.snippet:
                        fields_to_update.append("snippet = ?")
                        params_to_update.append(updated_dto.snippet)

                    if fields_to_update:
                        params_to_update.append(article_id)
                        sql = f"UPDATE articles_hot SET {', '.join(fields_to_update)} WHERE id = ?"
                        async with self.db.write_transaction() as conn:
                            await conn.execute(sql, tuple(params_to_update))
                            await conn.commit()
            except Exception as e:
                logger.debug(
                    f"Rule plugin '{plugin_id}' execution skipped/failed for article {article_id}: {e}"
                )
