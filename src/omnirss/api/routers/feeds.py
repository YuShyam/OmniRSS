"""分類與訂閱源路由控制器 (Categories & Feeds Router).

This module handles hierarchical feed trees, category management, feed subscription,
unsubscription, and manual refresh triggers.
"""

from typing import Optional
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from omnirss.api.dependencies import get_current_user, get_db
from omnirss.api.schemas import (
    CategoryCreateRequest,
    CategoryDTO,
    CategoryUpdateRequest,
    FeedCreateRequest,
    FeedTreeCategoryDTO,
    FeedTreeItemDTO,
    FeedTreeResponseDTO,
    FeedUpdateRequest,
)
from omnirss.core.crawler_engine import CrawlerEngine
from omnirss.core.database import compute_entry_hash

router = APIRouter(prefix="/api", tags=["Feeds & Categories"])


# =============================================================================
# 階層訂閱樹 (Feed Tree)
# =============================================================================

@router.get("/feeds/tree", response_model=FeedTreeResponseDTO)
async def get_feed_tree(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> FeedTreeResponseDTO:
    """取得當前使用者階層式訂閱目錄樹 (Get User Hierarchical Subscription Tree)."""
    user_id = user["id"]

    # 1. 查詢所有分類
    c_cur = await conn.execute(
        """
        SELECT id, name, sort_order, unread_count
        FROM categories
        WHERE user_id = ?
        ORDER BY sort_order ASC, name ASC
        """,
        (user_id,),
    )
    categories_rows = await c_cur.fetchall()

    # 2. 查詢該用戶所有訂閱頻道
    f_cur = await conn.execute(
        """
        SELECT f.id, COALESCE(uf.custom_title, f.title) as display_title,
               f.feed_url, f.site_url, f.icon_hash, uf.unread_count,
               f.error_count, f.last_error_message, f.last_checked_at, f.is_paused,
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
            unread_count=c["unread_count"],
            feeds=[],
        )

    uncategorized_feeds: list[FeedTreeItemDTO] = []
    total_unread = 0

    for f in feeds_rows:
        total_unread += f["unread_count"]
        item = FeedTreeItemDTO(
            id=f["id"],
            title=f["display_title"],
            feed_url=f["feed_url"],
            site_url=f["site_url"],
            icon_hash=f["icon_hash"],
            unread_count=f["unread_count"],
            error_count=f["error_count"],
            last_error_message=f["last_error_message"],
            last_checked_at=f["last_checked_at"],
            is_paused=bool(f["is_paused"]),
        )
        cat_id = f["category_id"]
        if cat_id in cat_dict:
            cat_dict[cat_id].feeds.append(item)
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

    return FeedTreeResponseDTO(
        total_unread=total_unread,
        categories=categories_list,
    )


# =============================================================================
# 分類目錄管理 (Category CRUD)
# =============================================================================

@router.get("/categories", response_model=list[CategoryDTO])
async def list_categories(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> list[CategoryDTO]:
    """取得當前使用者之所有分類目錄清單 (List Categories)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        SELECT id, name, sort_order, unread_count, custom_retention_days
        FROM categories
        WHERE user_id = ?
        ORDER BY sort_order ASC, name ASC
        """,
        (user_id,),
    )
    rows = await cur.fetchall()
    return [
        CategoryDTO(
            id=r["id"],
            name=r["name"],
            sort_order=r["sort_order"],
            unread_count=r["unread_count"],
            custom_retention_days=r["custom_retention_days"],
        )
        for r in rows
    ]


@router.post("/categories", response_model=CategoryDTO)
async def create_category(
    req: CategoryCreateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> CategoryDTO:
    """建立新分類目錄 (Create Category)."""
    user_id = user["id"]
    try:
        cur = await conn.execute(
            """
            INSERT INTO categories (user_id, name, sort_order, custom_retention_days)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, req.name, req.sort_order, req.custom_retention_days),
        )
        await conn.commit()
        cat_id = cur.lastrowid
        return CategoryDTO(
            id=cat_id,
            name=req.name,
            sort_order=req.sort_order,
            unread_count=0,
            custom_retention_days=req.custom_retention_days,
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
    conn: aiosqlite.Connection = Depends(get_db),
) -> CategoryDTO:
    """更新分類目錄 (Update Category)."""
    user_id = user["id"]
    cur = await conn.execute(
        "SELECT id, name, sort_order, unread_count, custom_retention_days FROM categories WHERE id = ? AND user_id = ?",
        (category_id, user_id),
    )
    row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Category not found")

    new_name = req.name if req.name is not None else row["name"]
    new_sort = req.sort_order if req.sort_order is not None else row["sort_order"]
    new_ret = req.custom_retention_days if req.custom_retention_days is not None else row["custom_retention_days"]

    await conn.execute(
        """
        UPDATE categories
        SET name = ?, sort_order = ?, custom_retention_days = ?
        WHERE id = ? AND user_id = ?
        """,
        (new_name, new_sort, new_ret, category_id, user_id),
    )
    await conn.commit()

    return CategoryDTO(
        id=category_id,
        name=new_name,
        sort_order=new_sort,
        unread_count=row["unread_count"],
        custom_retention_days=new_ret,
    )


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """刪除分類目錄 (Delete Category, feeds will become uncategorized)."""
    user_id = user["id"]
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
    """取得當前使用者之所有訂閱頻道清單 (List User Subscribed Feeds)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        SELECT f.id, COALESCE(uf.custom_title, f.title) as title,
               f.feed_url, f.site_url, f.icon_hash, uf.unread_count,
               f.error_count, f.last_error_message, f.last_checked_at, f.is_paused,
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
    conn: aiosqlite.Connection = Depends(get_db),
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
            INSERT INTO feeds (title, feed_url, site_url, check_interval_minutes, next_check_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (feed_title, req.feed_url, site_url, req.check_interval_minutes),
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

    return {"feed_id": feed_id, "message": "Feed subscribed successfully"}


@router.put("/feeds/{feed_id}", response_model=dict)
async def update_feed(
    feed_id: int,
    req: FeedUpdateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
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

    if req.check_interval_minutes is not None or req.is_paused is not None:
        await conn.execute(
            """
            UPDATE feeds
            SET check_interval_minutes = COALESCE(?, check_interval_minutes),
                is_paused = COALESCE(?, is_paused)
            WHERE id = ?
            """,
            (req.check_interval_minutes, 1 if req.is_paused else 0 if req.is_paused is not None else None, feed_id),
        )

    await conn.commit()
    return {"message": "Feed settings updated successfully"}


@router.delete("/feeds/{feed_id}")
async def unsubscribe_feed(
    feed_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """取消訂閱頻道 (Unsubscribe Feed)."""
    user_id = user["id"]
    await conn.execute(
        "DELETE FROM user_feeds WHERE user_id = ? AND feed_id = ?",
        (user_id, feed_id),
    )
    await conn.commit()
    return {"message": "Feed successfully unsubscribed"}


@router.post("/feeds/{feed_id}/refresh")
async def refresh_single_feed(
    feed_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """手動強制立即更新頻道 (Force Manual Refresh Single Feed)."""
    user_id = user["id"]
    f_cur = await conn.execute(
        """
        SELECT f.id, f.feed_url, f.title, f.etag_header, f.last_modified_header
        FROM user_feeds uf
        JOIN feeds f ON uf.feed_id = f.id
        WHERE uf.user_id = ? AND f.id = ?
        """,
        (user_id, feed_id),
    )
    feed_row = await f_cur.fetchone()
    if not feed_row:
        raise HTTPException(status_code=404, detail="Feed not found")

    crawler = CrawlerEngine()
    res = await crawler.fetch_feed(
        url=feed_row["feed_url"],
        etag=feed_row["etag_header"],
        last_modified=feed_row["last_modified_header"],
    )

    if res.articles:
        for a in res.articles:
            h = compute_entry_hash(feed_id, a.guid, a.url)
            await conn.execute(
                """
                INSERT OR IGNORE INTO articles_hot (
                    feed_id, entry_hash, title, url, author, snippet, content_html, content_text, cover_image_url, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feed_id,
                    h,
                    a.title,
                    a.url,
                    a.author,
                    a.snippet,
                    a.content_html,
                    a.content_text,
                    a.cover_image_url,
                    a.published_at.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            # 取得文章 id
            a_cur = await conn.execute("SELECT id FROM articles_hot WHERE entry_hash = ?", (h,))
            a_id = (await a_cur.fetchone())["id"]
            await conn.execute(
                "INSERT OR IGNORE INTO user_article_states (user_id, article_id, is_read) VALUES (?, ?, 0)",
                (user_id, a_id),
            )
        await conn.commit()

    return {
        "status_code": res.status_code,
        "is_modified": res.is_modified,
        "articles_found": len(res.articles),
        "message": "Feed refreshed successfully",
    }


@router.post("/feeds/refresh-all")
async def refresh_all_feeds(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """手動強制立即更新該使用者之所有訂閱頻道 (Force Manual Refresh All Feeds)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        SELECT f.id, f.feed_url, f.etag_header, f.last_modified_header
        FROM user_feeds uf
        JOIN feeds f ON uf.feed_id = f.id
        WHERE uf.user_id = ? AND f.is_paused = 0
        """,
        (user_id,),
    )
    feeds_rows = await cur.fetchall()

    crawler = CrawlerEngine()
    total_articles = 0

    for f_row in feeds_rows:
        try:
            feed_id = f_row["id"]
            res = await crawler.fetch_feed(
                url=f_row["feed_url"],
                etag=f_row["etag_header"],
                last_modified=f_row["last_modified_header"],
            )
            if res.articles:
                for a in res.articles:
                    h = compute_entry_hash(feed_id, a.guid, a.url)
                    await conn.execute(
                        """
                        INSERT OR IGNORE INTO articles_hot (
                            feed_id, entry_hash, title, url, author, snippet, content_html, content_text, cover_image_url, published_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            feed_id,
                            h,
                            a.title,
                            a.url,
                            a.author,
                            a.snippet,
                            a.content_html,
                            a.content_text,
                            a.cover_image_url,
                            a.published_at.strftime("%Y-%m-%d %H:%M:%S"),
                        ),
                    )
                    a_cur = await conn.execute("SELECT id FROM articles_hot WHERE entry_hash = ?", (h,))
                    a_row = await a_cur.fetchone()
                    if a_row:
                        await conn.execute(
                            "INSERT OR IGNORE INTO user_article_states (user_id, article_id, is_read) VALUES (?, ?, 0)",
                            (user_id, a_row["id"]),
                        )
                total_articles += len(res.articles)
        except Exception:
            continue

    await conn.commit()
    return {"message": "All feeds refreshed successfully", "articles_found": total_articles}

