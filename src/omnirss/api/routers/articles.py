"""文章串流與狀態切換路由控制器 (Articles Streaming & State Router).

This module handles paginated article feeds, FTS5 full-text search, read/starred toggles,
and batch mark-read operations.
"""

from typing import Optional
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status

from omnirss.api.dependencies import get_current_user, get_db
from omnirss.api.schemas import (
    ArticleDetailDTO,
    ArticleListItemDTO,
    ArticleListResponseDTO,
    MarkReadBatchRequest,
)

router = APIRouter(prefix="/api/articles", tags=["Articles"])


@router.get("", response_model=ArticleListResponseDTO)
async def list_articles(
    feed_id: Optional[int] = Query(None, description="依特定頻道過濾"),
    category_id: Optional[int] = Query(None, description="依特定分類過濾"),
    is_read: Optional[bool] = Query(None, description="是否已讀 (True/False)"),
    is_starred: Optional[bool] = Query(None, description="是否星標 (True/False)"),
    q: Optional[str] = Query(None, description="關鍵字全文搜尋"),
    page: int = Query(1, ge=1, description="頁碼"),
    page_size: int = Query(50, ge=1, le=200, description="每頁筆數"),
    sort_by: str = Query("published_at", description="排序欄位: 'published_at' 或 'created_at'"),
    sort_dir: str = Query("desc", description="排序方向: 'asc' 或 'desc'"),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> ArticleListResponseDTO:
    """分頁查詢文章清單 (List Articles with Filtering and Search)."""
    user_id = user["id"]
    conditions = ["uf.user_id = ?"]
    params: list = [user_id]

    if feed_id is not None:
        conditions.append("a.feed_id = ?")
        params.append(feed_id)

    if category_id is not None:
        conditions.append("uf.category_id = ?")
        params.append(category_id)

    if is_read is not None:
        conditions.append("COALESCE(uas.is_read, 0) = ?")
        params.append(1 if is_read else 0)

    if is_starred is not None:
        conditions.append("COALESCE(uas.is_starred, 0) = ?")
        params.append(1 if is_starred else 0)

    if q and q.strip():
        # FTS5 全文搜尋或 LIKE 搜尋
        conditions.append("(a.title LIKE ? OR a.snippet LIKE ?)")
        search_term = f"%{q.strip()}%"
        params.extend([search_term, search_term])

    where_clause = " WHERE " + " AND ".join(conditions)
    sort_column = "a.published_at" if sort_by == "published_at" else "a.created_at"
    sort_order = "ASC" if sort_dir.lower() == "asc" else "DESC"

    # 1. 計算總筆數 (Count total)
    count_sql = f"""
        SELECT COUNT(*) as total
        FROM articles_hot a
        JOIN user_feeds uf ON a.feed_id = uf.feed_id
        LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
        {where_clause}
    """
    c_cur = await conn.execute(count_sql, tuple(params))
    total = (await c_cur.fetchone())["total"]

    # 2. 分頁讀取資料 (Paginated fetch)
    offset = (page - 1) * page_size
    query_sql = f"""
        SELECT a.id, a.feed_id, COALESCE(uf.custom_title, f.title) as feed_title,
               uf.category_id, c.name as category_name,
               a.title, a.url, a.author, a.snippet, a.cover_image_url, a.published_at,
               COALESCE(uas.is_read, 0) as is_read,
               COALESCE(uas.is_starred, 0) as is_starred
        FROM articles_hot a
        JOIN feeds f ON a.feed_id = f.id
        JOIN user_feeds uf ON a.feed_id = uf.feed_id
        LEFT JOIN categories c ON uf.category_id = c.id
        LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
        {where_clause}
        ORDER BY {sort_column} {sort_order}
        LIMIT ? OFFSET ?
    """
    fetch_params = list(params) + [page_size, offset]
    cur = await conn.execute(query_sql, tuple(fetch_params))
    rows = await cur.fetchall()

    items: list[ArticleListItemDTO] = []
    for r in rows:
        items.append(
            ArticleListItemDTO(
                id=r["id"],
                feed_id=r["feed_id"],
                feed_title=r["feed_title"],
                category_id=r["category_id"],
                category_name=r["category_name"],
                title=r["title"],
                url=r["url"],
                author=r["author"],
                snippet=r["snippet"] or "",
                cover_image_url=r["cover_image_url"],
                published_at=r["published_at"],
                is_read=bool(r["is_read"]),
                is_starred=bool(r["is_starred"]),
                tags=[],
            )
        )

    return ArticleListResponseDTO(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


@router.get("/{article_id}", response_model=ArticleDetailDTO)
async def get_article_detail(
    article_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> ArticleDetailDTO:
    """取得單篇文章完整內容 (Get Article Detail with HTML)."""
    user_id = user["id"]
    query_sql = """
        SELECT a.id, a.feed_id, COALESCE(uf.custom_title, f.title) as feed_title,
               uf.category_id, c.name as category_name,
               a.title, a.url, a.author, a.snippet, a.cover_image_url, a.published_at,
               COALESCE(uas.is_read, 0) as is_read,
               COALESCE(uas.is_starred, 0) as is_starred
        FROM articles_hot a
        JOIN feeds f ON a.feed_id = f.id
        JOIN user_feeds uf ON a.feed_id = uf.feed_id
        LEFT JOIN categories c ON uf.category_id = c.id
        LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
        WHERE a.id = ? AND uf.user_id = ?
    """
    cur = await conn.execute(query_sql, (article_id, user_id))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Article not found")

    content_html = f"<p>{row['snippet']}</p>"
    content_text = row["snippet"] or ""

    return ArticleDetailDTO(
        id=row["id"],
        feed_id=row["feed_id"],
        feed_title=row["feed_title"],
        category_id=row["category_id"],
        category_name=row["category_name"],
        title=row["title"],
        url=row["url"],
        author=row["author"],
        snippet=row["snippet"] or "",
        cover_image_url=row["cover_image_url"],
        published_at=row["published_at"],
        is_read=bool(row["is_read"]),
        is_starred=bool(row["is_starred"]),
        content_html=content_html,
        content_text=content_text,
        tags=[],
    )


@router.put("/{article_id}/read")
async def toggle_article_read(
    article_id: int,
    is_read: bool = Query(True, description="欲設定的已讀狀態"),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """切換單篇文章已讀／未讀狀態 (Toggle Read/Unread State)."""
    user_id = user["id"]
    await conn.execute(
        """
        INSERT INTO user_article_states (user_id, article_id, is_read)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, article_id) DO UPDATE SET is_read = excluded.is_read
        """,
        (user_id, article_id, 1 if is_read else 0),
    )
    await conn.commit()
    return {"article_id": article_id, "is_read": is_read}


@router.put("/{article_id}/star")
async def toggle_article_star(
    article_id: int,
    is_starred: bool = Query(True, description="欲設定的星標狀態"),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """切換單篇文章星標收藏 (Toggle Starred State)."""
    user_id = user["id"]
    await conn.execute(
        """
        INSERT INTO user_article_states (user_id, article_id, is_starred, starred_at)
        VALUES (?, ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
        ON CONFLICT(user_id, article_id) DO UPDATE SET
            is_starred = excluded.is_starred,
            starred_at = excluded.starred_at
        """,
        (user_id, article_id, 1 if is_starred else 0, 1 if is_starred else 0),
    )
    await conn.commit()
    return {"article_id": article_id, "is_starred": is_starred}


@router.put("/mark-all-read")
async def mark_all_read(
    req: MarkReadBatchRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """批次標記已讀 (Batch Mark All Read across Scope)."""
    user_id = user["id"]

    if req.scope == "feed" and req.target_id:
        target_articles_sql = """
            SELECT a.id FROM articles_hot a
            JOIN user_feeds uf ON a.feed_id = uf.feed_id
            WHERE uf.user_id = ? AND a.feed_id = ?
        """
        params = (user_id, req.target_id)
    elif req.scope == "category" and req.target_id:
        target_articles_sql = """
            SELECT a.id FROM articles_hot a
            JOIN user_feeds uf ON a.feed_id = uf.feed_id
            WHERE uf.user_id = ? AND uf.category_id = ?
        """
        params = (user_id, req.target_id)
    else:
        # 全站 (All feeds)
        target_articles_sql = """
            SELECT a.id FROM articles_hot a
            JOIN user_feeds uf ON a.feed_id = uf.feed_id
            WHERE uf.user_id = ?
        """
        params = (user_id,)

    cur = await conn.execute(target_articles_sql, params)
    rows = await cur.fetchall()

    for r in rows:
        await conn.execute(
            """
            INSERT INTO user_article_states (user_id, article_id, is_read)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, article_id) DO UPDATE SET is_read = 1
            """,
            (user_id, r["id"]),
        )

    await conn.commit()
    return {"marked_count": len(rows), "scope": req.scope}
