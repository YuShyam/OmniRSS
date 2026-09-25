"""分類與訂閱源路由控制器 (Categories & Feeds Router).

This module handles hierarchical feed trees, category management, feed subscription,
unsubscription, and manual refresh triggers.
"""

import asyncio
from typing import Optional
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from omnirss.api.dependencies import get_current_user, get_db, get_write_db
from omnirss.api.schemas import (
    CategoryCreateRequest,
    CategoryDTO,
    CategoryUpdateRequest,
    FeedCreateRequest,
    FeedTestRequest,
    FeedTestResponse,
    FeedTreeCategoryDTO,
    FeedTreeItemDTO,
    FeedTreeResponseDTO,
    FeedUpdateRequest,
    RefreshProgressDTO,
)
from omnirss.core.crawler_engine import CrawlerEngine
from omnirss.core.database import compute_entry_hash

router = APIRouter(prefix="/api", tags=["Feeds & Categories"])


@router.post("/feeds/test-url", response_model=FeedTestResponse)
async def test_feed_url(
    req: FeedTestRequest,
    user: dict = Depends(get_current_user),
) -> FeedTestResponse:
    """測試訂閱源網址連線與解析 (Test Feed URL Connection & Parse Feed)."""
    crawler = CrawlerEngine()
    auth = None
    if req.auth_username and req.auth_password:
        auth = (req.auth_username, req.auth_password)

    try:
        crawl_res = await crawler.fetch_feed(
            url=req.feed_url,
            requires_flaresolverr=req.requires_flaresolverr,
            force_refresh=True,
            auth=auth,
        )
        if crawl_res.error:
            return FeedTestResponse(
                status="error",
                http_status=crawl_res.status_code or 400,
                error_detail=crawl_res.error,
            )

        title = crawl_res.feed_metadata.title if crawl_res.feed_metadata else None
        site_url = crawl_res.feed_metadata.site_url if crawl_res.feed_metadata else None
        item_count = len(crawl_res.articles)

        return FeedTestResponse(
            status="ok",
            http_status=crawl_res.status_code or 200,
            title=title,
            site_url=site_url,
            item_count=item_count,
        )
    except Exception as e:
        return FeedTestResponse(
            status="error",
            error_detail=str(e),
        )



# =============================================================================
# 階層訂閱樹 (Feed Tree)
# =============================================================================

@router.get("/feeds/tree", response_model=FeedTreeResponseDTO)
async def get_feed_tree(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> FeedTreeResponseDTO:
    """取得當前使用者階層式訂閱目錄樹 (Get User Hierarchical Subscription Tree with Dynamic Accurate Unread Counts)."""
    user_id = user["id"]

    # 1. 查詢所有分類
    c_cur = await conn.execute(
        """
        SELECT id, name, sort_order
        FROM categories
        WHERE user_id = ?
        ORDER BY sort_order ASC, name ASC
        """,
        (user_id,),
    )
    categories_rows = await c_cur.fetchall()

    # 2. 查詢該用戶所有訂閱頻道（動態精確子查詢未讀數，徹底杜絕舊快取計數不一致）
    f_cur = await conn.execute(
        """
        SELECT f.id, COALESCE(uf.custom_title, f.title) as display_title,
               f.feed_url, f.site_url, f.icon_hash,
               (
                   SELECT COUNT(*) FROM articles_hot a
                   LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
                   WHERE a.feed_id = f.id AND COALESCE(uas.is_read, 0) = 0 AND COALESCE(uas.is_trash, 0) = 0
               ) as unread_count,
               f.error_count, f.last_error_message, f.last_checked_at, f.is_paused,
               COALESCE(f.auto_full_text, 0) as auto_full_text,
               f.min_publish_date, COALESCE(f.force_min_date, 0) as force_min_date,
               uf.category_id
        FROM user_feeds uf
        JOIN feeds f ON uf.feed_id = f.id
        WHERE uf.user_id = ?
        ORDER BY display_title ASC
        """,
        (user_id,),
    )
    feeds_rows = await f_cur.fetchall()

    # 組織樹狀結構
    cat_dict: dict[Optional[int], FeedTreeCategoryDTO] = {}
    for c in categories_rows:
        cat_dict[c["id"]] = FeedTreeCategoryDTO(
            id=c["id"],
            name=c["name"],
            sort_order=c["sort_order"],
            unread_count=0,
            feeds=[],
        )

    uncategorized_feeds: list[FeedTreeItemDTO] = []
    total_unread = 0

    for f in feeds_rows:
        feed_unread = int(f["unread_count"] or 0)
        total_unread += feed_unread
        item = FeedTreeItemDTO(
            id=f["id"],
            title=f["display_title"],
            feed_url=f["feed_url"],
            site_url=f["site_url"],
            icon_hash=f["icon_hash"],
            unread_count=feed_unread,
            error_count=f["error_count"],
            last_error_message=f["last_error_message"],
            last_checked_at=f["last_checked_at"],
            is_paused=bool(f["is_paused"]),
            auto_full_text=bool(f["auto_full_text"]),
            min_publish_date=f["min_publish_date"],
            force_min_date=bool(f["force_min_date"]),
        )
        cat_id = f["category_id"]
        if cat_id in cat_dict:
            cat_dict[cat_id].feeds.append(item)
            cat_dict[cat_id].unread_count += feed_unread
        else:
            uncategorized_feeds.append(item)

    categories_list = list(cat_dict.values())
    if uncategorized_feeds:
        categories_list.append(
            FeedTreeCategoryDTO(
                id=None,
                name="未分類",
                sort_order=99999,
                unread_count=sum(f.unread_count for f in uncategorized_feeds),
                feeds=uncategorized_feeds,
            )
        )

    # 3. 查詢星標文章、垃圾桶文章與總文章數量
    s_cur = await conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM user_article_states WHERE user_id = ? AND is_starred = 1 AND COALESCE(is_trash, 0) = 0) as starred_count,
            (SELECT COUNT(*) FROM user_article_states WHERE user_id = ? AND is_trash = 1) as trash_count,
            (SELECT COUNT(*) FROM articles_hot a JOIN user_feeds uf ON a.feed_id = uf.feed_id LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id WHERE uf.user_id = ? AND COALESCE(uas.is_trash, 0) = 0) as total_articles
        """,
        (user_id, user_id, user_id),
    )
    counts_row = await s_cur.fetchone()
    starred_count = int(counts_row["starred_count"] or 0) if counts_row else 0
    trash_count = int(counts_row["trash_count"] or 0) if counts_row else 0
    total_articles = int(counts_row["total_articles"] or 0) if counts_row else 0

    return FeedTreeResponseDTO(
        total_unread=total_unread,
        total_articles=total_articles,
        starred_count=starred_count,
        trash_count=trash_count,
        categories=categories_list,
    )


# =============================================================================
# 分類目錄管理 (Category CRUD & Stats)
# =============================================================================

@router.get("/categories", response_model=list[CategoryDTO])
async def list_categories(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> list[CategoryDTO]:
    """取得當前使用者之所有分類目錄清單 (List Categories with Dynamic Unread Counts)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        SELECT c.id, c.name, c.sort_order, c.custom_retention_days, c.custom_interval_minutes,
               c.custom_min_date, COALESCE(c.force_min_date, 0) as force_min_date,
               (
                   SELECT COUNT(*) FROM articles_hot a
                   JOIN user_feeds uf ON a.feed_id = uf.feed_id
                   LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
                   WHERE uf.category_id = c.id AND uf.user_id = c.user_id AND COALESCE(uas.is_read, 0) = 0
               ) as unread_count,
               (
                   SELECT CASE WHEN COUNT(f.id) > 0 AND SUM(CASE WHEN f.is_paused = 0 THEN 1 ELSE 0 END) = 0 THEN 1 ELSE 0 END
                   FROM user_feeds uf
                   JOIN feeds f ON uf.feed_id = f.id
                   WHERE uf.category_id = c.id AND uf.user_id = c.user_id
               ) as is_paused
        FROM categories c
        WHERE c.user_id = ?
        ORDER BY c.sort_order ASC, c.name ASC
        """,
        (user_id,),
    )
    rows = await cur.fetchall()
    return [
        CategoryDTO(
            id=r["id"],
            name=r["name"],
            sort_order=r["sort_order"],
            unread_count=r["unread_count"] or 0,
            custom_retention_days=r["custom_retention_days"],
            custom_interval_minutes=r["custom_interval_minutes"],
            custom_min_date=r["custom_min_date"],
            force_min_date=bool(r["force_min_date"]),
            is_paused=bool(r["is_paused"]),
        )
        for r in rows
    ]


@router.get("/categories/{category_id}/stats", response_model=dict)
async def get_category_stats(
    category_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """取得特定分類的即時健康度與統計資訊 (Get Category Real-time Stats Dashboard)."""
    user_id = user["id"]
    cat_cur = await conn.execute(
        "SELECT id, name, custom_retention_days, custom_interval_minutes, custom_min_date, COALESCE(force_min_date, 0) as force_min_date FROM categories WHERE id = ? AND user_id = ?",
        (category_id, user_id),
    )
    cat_row = await cat_cur.fetchone()
    if not cat_row:
        raise HTTPException(status_code=404, detail="Category not found")

    stats_cur = await conn.execute(
        """
        SELECT 
            COUNT(DISTINCT uf.feed_id) as feed_count,
            COUNT(DISTINCT a.id) as article_count,
            COALESCE(SUM(CASE WHEN a.id IS NOT NULL AND COALESCE(uas.is_read, 0) = 0 THEN 1 ELSE 0 END), 0) as unread_count,
            MAX(a.published_at) as last_article_at,
            MAX(f.last_checked_at) as last_checked_at,
            SUM(CASE WHEN f.is_paused = 1 THEN 1 ELSE 0 END) as paused_feed_count
        FROM user_feeds uf
        JOIN feeds f ON uf.feed_id = f.id
        LEFT JOIN articles_hot a ON a.feed_id = f.id
        LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
        WHERE uf.category_id = ? AND uf.user_id = ?
        """,
        (category_id, user_id),
    )
    stats = await stats_cur.fetchone()

    feed_count = stats["feed_count"] or 0
    paused_feed_count = stats["paused_feed_count"] or 0
    is_paused = feed_count > 0 and (feed_count == paused_feed_count)

    return {
        "category_id": category_id,
        "name": cat_row["name"],
        "custom_retention_days": cat_row["custom_retention_days"],
        "custom_interval_minutes": cat_row["custom_interval_minutes"],
        "custom_min_date": cat_row["custom_min_date"],
        "force_min_date": bool(cat_row["force_min_date"]),
        "feed_count": feed_count,
        "article_count": stats["article_count"] or 0,
        "unread_count": stats["unread_count"] or 0,
        "last_article_at": stats["last_article_at"],
        "last_checked_at": stats["last_checked_at"],
        "is_paused": is_paused,
    }


@router.post("/categories", response_model=CategoryDTO)
async def create_category(
    req: CategoryCreateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> CategoryDTO:
    """建立新分類目錄 (Create Category)."""
    user_id = user["id"]
    try:
        cur = await conn.execute(
            """
            INSERT INTO categories (user_id, name, sort_order, custom_retention_days, custom_interval_minutes, custom_min_date, force_min_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, req.name, req.sort_order, req.custom_retention_days, req.custom_interval_minutes, req.custom_min_date, 1 if req.force_min_date else 0),
        )
        await conn.commit()
        cat_id = cur.lastrowid
        return CategoryDTO(
            id=cat_id,
            name=req.name,
            sort_order=req.sort_order,
            unread_count=0,
            custom_retention_days=req.custom_retention_days,
            custom_interval_minutes=req.custom_interval_minutes,
            custom_min_date=req.custom_min_date,
            force_min_date=req.force_min_date,
            is_paused=False,
        )
    except aiosqlite.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category '{req.name}' already exists",
        )


@router.put("/categories/{category_id}", response_model=CategoryDTO)
async def update_category(
    category_id: int,
    req: CategoryUpdateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> CategoryDTO:
    """更新分類目錄與連動控制 (Update Category & Cascade Pause/Resume/Interval Feeds)."""
    user_id = user["id"]
    cur = await conn.execute(
        "SELECT id, name, sort_order, unread_count, custom_retention_days, custom_interval_minutes, custom_min_date, COALESCE(force_min_date, 0) as force_min_date FROM categories WHERE id = ? AND user_id = ?",
        (category_id, user_id),
    )
    row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Category not found")

    new_name = req.name if req.name is not None else row["name"]
    new_sort = req.sort_order if req.sort_order is not None else row["sort_order"]
    new_ret = req.custom_retention_days if req.custom_retention_days is not None else row["custom_retention_days"]
    new_interval = req.custom_interval_minutes if req.custom_interval_minutes is not None else row["custom_interval_minutes"]
    new_min_date = req.custom_min_date if req.custom_min_date is not None else row["custom_min_date"]
    new_force_min = (1 if req.force_min_date else 0) if req.force_min_date is not None else row["force_min_date"]

    await conn.execute(
        """
        UPDATE categories
        SET name = ?, sort_order = ?, custom_retention_days = ?, custom_interval_minutes = ?, custom_min_date = ?, force_min_date = ?
        WHERE id = ? AND user_id = ?
        """,
        (new_name, new_sort, new_ret, new_interval, new_min_date, new_force_min, category_id, user_id),
    )

    # 若指定 is_paused，連動設定該分類下所有訂閱頻道的 is_paused
    if req.is_paused is not None:
        target_paused = 1 if req.is_paused else 0
        await conn.execute(
            """
            UPDATE feeds
            SET is_paused = ?
            WHERE id IN (
                SELECT feed_id FROM user_feeds WHERE user_id = ? AND category_id = ?
            )
            """,
            (target_paused, user_id, category_id),
        )

    # 若指定 custom_interval_minutes 且大於 0，連動更新該分類下所有頻道的 check_interval_minutes
    if req.custom_interval_minutes is not None and req.custom_interval_minutes > 0:
        await conn.execute(
            """
            UPDATE feeds
            SET check_interval_minutes = ?
            WHERE id IN (
                SELECT feed_id FROM user_feeds WHERE user_id = ? AND category_id = ?
            )
            """,
            (req.custom_interval_minutes, user_id, category_id),
        )

    await conn.commit()

    return CategoryDTO(
        id=category_id,
        name=new_name,
        sort_order=new_sort,
        unread_count=row["unread_count"] or 0,
        custom_retention_days=new_ret,
        custom_interval_minutes=new_interval,
        custom_min_date=new_min_date,
        force_min_date=bool(new_force_min),
        is_paused=bool(req.is_paused) if req.is_paused is not None else False,
    )



@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """刪除分類目錄 (Delete Category, feeds will become uncategorized)."""
    user_id = user["id"]
    await conn.execute(
        "UPDATE user_feeds SET category_id = NULL WHERE user_id = ? AND category_id = ?",
        (user_id, category_id),
    )
    await conn.execute(
        "DELETE FROM categories WHERE id = ? AND user_id = ?",
        (category_id, user_id),
    )
    await conn.commit()
    return {"message": "Category successfully deleted"}


# =============================================================================
# 訂閱頻道管理 (Feeds CRUD)
# =============================================================================

@router.get("/feeds", response_model=list[dict])
async def list_feeds(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> list[dict]:
    """取得當前使用者之所有訂閱頻道清單 (List User Subscribed Feeds with Dynamic Unread Counts)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        SELECT f.id, COALESCE(uf.custom_title, f.title) as title,
               f.feed_url, f.site_url, f.icon_hash,
               (
                   SELECT COUNT(*) FROM articles_hot a
                   LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
                   WHERE a.feed_id = f.id AND COALESCE(uas.is_read, 0) = 0
               ) as unread_count,
               f.error_count, f.last_error_message, f.last_checked_at, f.is_paused,
               COALESCE(f.auto_full_text, 0) as auto_full_text,
               uf.category_id
        FROM user_feeds uf
        JOIN feeds f ON uf.feed_id = f.id
        WHERE uf.user_id = ?
        ORDER BY title ASC
        """,
        (user_id,),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]

@router.post("/feeds", response_model=dict)
async def subscribe_feed(
    req: FeedCreateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """新增訂閱頻道 (Subscribe Feed)."""
    user_id = user["id"]

    # 1. 檢查 feeds 池中是否已存在此網址
    f_cur = await conn.execute(
        "SELECT id, title, feed_url FROM feeds WHERE feed_url = ?",
        (req.feed_url,),
    )
    feed_row = await f_cur.fetchone()

    if feed_row:
        feed_id = feed_row["id"]
    else:
        # 初次訂閱：透過爬蟲安全探測一次
        crawler = CrawlerEngine()
        crawl_res = await crawler.fetch_feed(req.feed_url)
        feed_title = req.custom_title or req.title or (crawl_res.feed_metadata.title if crawl_res.feed_metadata else req.feed_url)
        site_url = crawl_res.feed_metadata.site_url if crawl_res.feed_metadata else None

        c_cur = await conn.execute(
            """
            INSERT INTO feeds (title, feed_url, site_url, check_interval_minutes, next_check_at, requires_flaresolverr, auto_full_text)
            VALUES (?, ?, ?, ?, datetime('now'), ?, ?)
            """,
            (feed_title, req.feed_url, site_url, req.check_interval_minutes, 1 if req.requires_flaresolverr else 0, 1 if req.auto_full_text else 0),
        )
        feed_id = c_cur.lastrowid

    # 2. 建立 user_feeds 關聯
    try:
        user_custom_title = req.custom_title or req.title
        await conn.execute(
            """
            INSERT INTO user_feeds (user_id, feed_id, category_id, custom_title, custom_retention_days)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, feed_id, req.category_id, user_custom_title, req.custom_retention_days),
        )
        await conn.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feed is already subscribed by this user",
        )

    # 觸發一次非同步抓取
    from omnirss.core.scheduler import get_global_scheduler
    scheduler = get_global_scheduler()
    if scheduler:
        asyncio.create_task(scheduler.trigger_refresh(feed_id=feed_id))

    return {"feed_id": feed_id, "message": "Feed subscribed successfully"}


@router.get("/feeds/{feed_id}", response_model=dict)
async def get_feed_details(
    feed_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """取得單一訂閱頻道的完整屬性與健康資訊 (Get Feed Details & Health Log)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        SELECT f.id, f.title as original_title, COALESCE(uf.custom_title, f.title) as display_title,
               uf.custom_title, f.feed_url, f.site_url, f.icon_hash,
               f.check_interval_minutes, uf.custom_retention_days,
               f.error_count, f.last_error_message, f.last_checked_at, f.is_paused,
               f.requires_flaresolverr, COALESCE(f.auto_full_text, 0) as auto_full_text,
               f.min_publish_date, COALESCE(f.force_min_date, 0) as force_min_date,
               f.auth_username, f.auth_password,
               uf.category_id,
               (
                   SELECT COUNT(*) FROM articles_hot a
                   WHERE a.feed_id = f.id
               ) as total_articles,
               (
                   SELECT COUNT(*) FROM articles_hot a
                   LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
                   WHERE a.feed_id = f.id AND COALESCE(uas.is_read, 0) = 0
               ) as unread_articles
        FROM user_feeds uf
        JOIN feeds f ON uf.feed_id = f.id
        WHERE uf.user_id = ? AND uf.feed_id = ?
        """,
        (user_id, feed_id),
    )
    row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Subscribed feed not found")
    return dict(row)


@router.put("/feeds/{feed_id}", response_model=dict)
async def update_feed(
    feed_id: int,
    req: FeedUpdateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """修改個人訂閱頻道設定 (Update Subscribed Feed Settings)."""
    user_id = user["id"]
    cur = await conn.execute(
        "SELECT feed_id FROM user_feeds WHERE user_id = ? AND feed_id = ?",
        (user_id, feed_id),
    )
    if not await cur.fetchone():
        raise HTTPException(status_code=404, detail="Subscribed feed not found")

    if req.custom_title is not None or req.category_id is not None or req.custom_retention_days is not None:
        await conn.execute(
            """
            UPDATE user_feeds
            SET custom_title = COALESCE(?, custom_title),
                category_id = ?,
                custom_retention_days = ?
            WHERE user_id = ? AND feed_id = ?
            """,
            (req.custom_title, req.category_id, req.custom_retention_days, user_id, feed_id),
        )

    if (
        req.check_interval_minutes is not None
        or req.is_paused is not None
        or req.requires_flaresolverr is not None
        or req.auto_full_text is not None
        or req.feed_url is not None
        or req.site_url is not None
        or req.min_publish_date is not None
        or req.force_min_date is not None
        or req.auth_username is not None
        or req.auth_password is not None
    ):
        await conn.execute(
            """
            UPDATE feeds
            SET check_interval_minutes = COALESCE(?, check_interval_minutes),
                is_paused = COALESCE(?, is_paused),
                requires_flaresolverr = COALESCE(?, requires_flaresolverr),
                auto_full_text = COALESCE(?, auto_full_text),
                feed_url = COALESCE(?, feed_url),
                site_url = COALESCE(?, site_url),
                min_publish_date = COALESCE(?, min_publish_date),
                force_min_date = COALESCE(?, force_min_date),
                auth_username = COALESCE(?, auth_username),
                auth_password = COALESCE(?, auth_password)
            WHERE id = ?
            """,
            (
                req.check_interval_minutes,
                (1 if req.is_paused else 0) if req.is_paused is not None else None,
                (1 if req.requires_flaresolverr else 0) if req.requires_flaresolverr is not None else None,
                (1 if req.auto_full_text else 0) if req.auto_full_text is not None else None,
                req.feed_url,
                req.site_url,
                req.min_publish_date,
                (1 if req.force_min_date else 0) if req.force_min_date is not None else None,
                req.auth_username,
                req.auth_password,
                feed_id,
            ),
        )

    await conn.commit()
    return {"message": "Feed settings updated successfully"}




@router.delete("/feeds/{feed_id}")
async def unsubscribe_feed(
    feed_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """取消訂閱頻道 (Unsubscribe Feed)."""
    user_id = user["id"]
    await conn.execute(
        "DELETE FROM user_feeds WHERE user_id = ? AND feed_id = ?",
        (user_id, feed_id),
    )
    await conn.commit()
    return {"message": "Feed successfully unsubscribed"}


# =============================================================================
# 手動重新整理與即時抓取 (Manual Refresh Endpoints)
# =============================================================================

@router.post("/feeds/refresh")
@router.post("/feeds/refresh-all")
async def refresh_feeds_pipeline(
    req: Optional[dict] = None,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """手動強制立即更新所有或指定頻道/分類 (Force Manual Refresh via Scheduler Single-Writer Pipeline)."""
    feed_id = (req or {}).get("feed_id")
    category_id = (req or {}).get("category_id")
    from omnirss.core.scheduler import OmniScheduler, get_global_scheduler

    scheduler = get_global_scheduler()
    if not scheduler:
        # Fallback 建立臨時實例執行
        scheduler = OmniScheduler()

    refresh_result = await scheduler.trigger_refresh(feed_id=feed_id, category_id=category_id)
    if isinstance(refresh_result, dict):
        updated_count = int(refresh_result.get("refreshed_count", 0))
        new_arts = int(refresh_result.get("new_articles", 0))
        total_attempted = int(refresh_result.get("total_attempted", 0))
    else:
        updated_count = int(refresh_result or 0)
        new_arts = 0
        total_attempted = updated_count

    return {
        "status": "success",
        "message": f"成功完成即時重新整理，共更新 {updated_count} 個訂閱頻道 (新增 {new_arts} 篇文章)",
        "updated_feeds": updated_count,
        "new_articles": new_arts,
        "total_attempted": total_attempted,
    }


@router.post("/feeds/{feed_id}/refresh")
async def refresh_single_feed_endpoint(
    feed_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """手動強制更新單一頻道 (Force Manual Refresh Single Feed via Pipeline)."""
    from omnirss.core.scheduler import OmniScheduler, get_global_scheduler

    scheduler = get_global_scheduler()
    if not scheduler:
        scheduler = OmniScheduler()

    refresh_result = await scheduler.trigger_refresh(feed_id=feed_id)
    if isinstance(refresh_result, dict):
        updated_count = int(refresh_result.get("refreshed_count", 0))
        new_arts = int(refresh_result.get("new_articles", 0))
    else:
        updated_count = int(refresh_result or 0)
        new_arts = 0

    return {
        "status": "success",
        "message": "單一頻道即時更新完畢",
        "updated_feeds": updated_count,
        "new_articles": new_arts,
    }


@router.post("/categories/{category_id}/refresh")
async def refresh_category_feeds_endpoint(
    category_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """手動強制更新單一分類下之所有頻道 (Force Manual Refresh Feeds Under Category via Pipeline)."""
    from omnirss.core.scheduler import OmniScheduler, get_global_scheduler

    scheduler = get_global_scheduler()
    if not scheduler:
        scheduler = OmniScheduler()

    refresh_result = await scheduler.trigger_refresh(category_id=category_id)
    if isinstance(refresh_result, dict):
        updated_count = int(refresh_result.get("refreshed_count", 0))
        new_arts = int(refresh_result.get("new_articles", 0))
    else:
        updated_count = int(refresh_result or 0)
        new_arts = 0

    return {
        "status": "success",
        "message": f"分類頻道即時更新完畢，共更新 {updated_count} 個訂閱頻道",
        "updated_feeds": updated_count,
        "new_articles": new_arts,
    }


@router.get("/feeds/refresh/progress", response_model=RefreshProgressDTO)
async def get_refresh_progress_endpoint(
    user: dict = Depends(get_current_user),
) -> RefreshProgressDTO:
    """取得當前全局即時更新/抓取進度 (Get Real-time Refresh Progress)."""
    from omnirss.core.scheduler import get_global_scheduler

    scheduler = get_global_scheduler()
    if scheduler:
        prog = scheduler.get_refresh_progress()
        return RefreshProgressDTO(
            is_running=bool(prog.get("is_running", False)),
            total_feeds=int(prog.get("total", prog.get("total_feeds", 0))),
            completed_feeds=int(prog.get("completed", prog.get("completed_feeds", 0))),
            current_feed_name=prog.get("current_feed", prog.get("current_feed_name")) or None,
            new_articles_count=int(prog.get("new_articles", prog.get("new_articles_count", 0))),
            started_at=prog.get("started_at"),
            finished_at=prog.get("finished_at"),
        )
    return RefreshProgressDTO()


