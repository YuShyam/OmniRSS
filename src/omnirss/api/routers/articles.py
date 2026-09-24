"""文章串流與狀態切換路由控制器 (Articles Streaming & State Router).

This module handles paginated article feeds, FTS5 full-text search, read/starred toggles,
and batch mark-read operations.
"""

from typing import Optional
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status

from omnirss.api.dependencies import get_current_user, get_db
from omnirss.core.crawler_engine import CrawlerEngine
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
    is_unread: Optional[bool] = Query(None, description="是否未讀 (True/False)"),
    is_starred: Optional[bool] = Query(None, description="是否星標 (True/False)"),
    q: Optional[str] = Query(None, description="關鍵字全文搜尋"),
    search: Optional[str] = Query(None, description="搜尋關鍵字 (別名)"),
    page: int = Query(1, ge=1, description="頁碼"),
    page_size: int = Query(50, ge=1, le=200, description="每頁筆數"),
    limit: Optional[int] = Query(None, description="限制回傳筆數 (別名)"),
    offset: Optional[int] = Query(None, description="偏移筆數 (別名)"),
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

    # 整合 is_read 與 is_unread
    effective_is_read = is_read
    if is_unread is not None:
        effective_is_read = not is_unread

    if effective_is_read is not None:
        conditions.append("COALESCE(uas.is_read, 0) = ?")
        params.append(1 if effective_is_read else 0)

    if is_starred is not None:
        conditions.append("COALESCE(uas.is_starred, 0) = ?")
        params.append(1 if is_starred else 0)

    search_kw = q or search
    if search_kw and search_kw.strip():
        kw = search_kw.strip()
        if len(kw) >= 3:
            # 長詞 (>=3 字元) 使用 FTS5 Trigram 倒排索引 + LIKE 容錯
            safe_fts_kw = '"' + kw.replace('"', '""') + '"'
            like_kw = f"%{kw}%"
            conditions.append(
                "(a.id IN (SELECT rowid FROM articles_fts WHERE articles_fts MATCH ?) OR a.title LIKE ? OR a.snippet LIKE ? OR a.author LIKE ?)"
            )
            params.extend([safe_fts_kw, like_kw, like_kw, like_kw])
        else:
            # 短詞 (<3 字元，如單字「台」、「AI」、「科技」) 自動容錯使用 LIKE 模糊比對
            like_kw = f"%{kw}%"
            conditions.append(
                "(a.title LIKE ? OR a.snippet LIKE ? OR a.author LIKE ?)"
            )
            params.extend([like_kw, like_kw, like_kw])

    where_clause = " WHERE " + " AND ".join(conditions)
    sort_column = "a.published_at" if sort_by == "published_at" else "a.created_at"
    sort_order = "ASC" if sort_dir.lower() == "asc" else "DESC"

    # 計算分頁
    actual_limit = limit if limit is not None else page_size
    actual_offset = offset if offset is not None else (page - 1) * page_size

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
    fetch_params = list(params) + [actual_limit, actual_offset]
    cur = await conn.execute(query_sql, tuple(fetch_params))
    rows = await cur.fetchall()

    items: list[ArticleListItemDTO] = []
    for r in rows:
        read_bool = bool(r["is_read"])
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
                is_read=read_bool,
                is_unread=not read_bool,
                is_starred=bool(r["is_starred"]),
                tags=[],
            )
        )

    return ArticleListResponseDTO(
        total=total,
        page=page,
        page_size=actual_limit,
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
               a.title, a.url, a.author, a.snippet, a.content_html, a.content_text,
               a.cover_image_url, a.published_at,
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

    content_html = row["content_html"] or (f"<p>{row['snippet']}</p>" if row["snippet"] else "<p>本篇無額外內文</p>")
    content_text = row["content_text"] or row["snippet"] or ""
    read_bool = bool(row["is_read"])

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
        is_read=read_bool,
        is_unread=not read_bool,
        is_starred=bool(row["is_starred"]),
        content_html=content_html,
        content_text=content_text,
        tags=[],
    )


@router.patch("/{article_id}/state")
async def update_article_state_patch(
    article_id: int,
    patch: dict,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """整合切換單篇文章狀態 (Update Article Read/Star State via Patch)."""
    user_id = user["id"]
    is_read = None
    if "is_read" in patch:
        is_read = 1 if patch["is_read"] else 0
    elif "is_unread" in patch:
        is_read = 0 if patch["is_unread"] else 1

    is_starred = 1 if patch.get("is_starred") else 0 if "is_starred" in patch else None

    # 確保該關聯存在
    cur = await conn.execute(
        "SELECT is_read, is_starred FROM user_article_states WHERE user_id = ? AND article_id = ?",
        (user_id, article_id),
    )
    row = await cur.fetchone()
    if not row:
        await conn.execute(
            """
            INSERT INTO user_article_states (user_id, article_id, is_read, is_starred, starred_at)
            VALUES (?, ?, ?, ?, CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END)
            """,
            (user_id, article_id, is_read or 0, is_starred or 0, is_starred or 0),
        )
    else:
        updates = []
        params = []
        if is_read is not None:
            updates.append("is_read = ?")
            params.append(is_read)
        if is_starred is not None:
            updates.append("is_starred = ?")
            updates.append("starred_at = CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END")
            params.extend([is_starred, is_starred])
        if updates:
            params.extend([user_id, article_id])
            await conn.execute(
                f"UPDATE user_article_states SET {', '.join(updates)} WHERE user_id = ? AND article_id = ?",
                tuple(params),
            )

    await conn.commit()
    return {"article_id": article_id, "success": True}


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


@router.post("/mark-all-read")
@router.put("/mark-all-read")
async def mark_all_read_flexible(
    req: Optional[dict] = None,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """批次標記已讀 (Batch Mark All Read across Scope)."""
    user_id = user["id"]
    feed_id = (req or {}).get("feed_id") or ((req or {}).get("target_id") if (req or {}).get("scope") == "feed" else None)
    cat_id = (req or {}).get("category_id") or ((req or {}).get("target_id") if (req or {}).get("scope") == "category" else None)

    if feed_id:
        target_articles_sql = """
            SELECT a.id FROM articles_hot a
            JOIN user_feeds uf ON a.feed_id = uf.feed_id
            WHERE uf.user_id = ? AND a.feed_id = ?
        """
        params = (user_id, feed_id)
    elif cat_id:
        target_articles_sql = """
            SELECT a.id FROM articles_hot a
            JOIN user_feeds uf ON a.feed_id = uf.feed_id
            WHERE uf.user_id = ? AND uf.category_id = ?
        """
        params = (user_id, cat_id)
    else:
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
    return {"marked_count": len(rows), "status": "success"}


@router.post("/{article_id}/fetch-full-content", response_model=ArticleDetailDTO)
async def fetch_article_full_content(
    article_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> ArticleDetailDTO:
    """透過 Trafilatura 抓取原始網頁全文並更新文章 (Fetch Full Web Page Content via Trafilatura)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        SELECT a.id, a.feed_id, a.url, a.title, a.author, a.snippet, a.published_at,
               a.cover_image_url, COALESCE(uf.custom_title, f.title) as feed_title,
               uf.category_id, c.name as category_name,
               COALESCE(uas.is_read, 0) as is_read,
               COALESCE(uas.is_starred, 0) as is_starred,
               f.requires_flaresolverr
        FROM articles_hot a
        JOIN feeds f ON a.feed_id = f.id
        JOIN user_feeds uf ON a.feed_id = uf.feed_id
        LEFT JOIN categories c ON uf.category_id = c.id
        LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
        WHERE a.id = ? AND uf.user_id = ?
        """,
        (article_id, user_id),
    )
    row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Article not found")

    article_url = row["url"]
    if not article_url:
        raise HTTPException(status_code=400, detail="Article URL is empty")

    crawler = CrawlerEngine()
    try:
        crawl_result = await crawler.fetch_feed(
            url=article_url,
            requires_flaresolverr=bool(row["requires_flaresolverr"]),
        )
        if crawl_result.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Failed to fetch original page: HTTP {crawl_result.status_code}")

        html_raw = crawl_result.body_bytes.decode("utf-8", errors="replace")
        extracted_text = CrawlerEngine.extract_full_text_from_html(html_raw, base_url=article_url)
        if not extracted_text:
            extracted_text = row["snippet"] or "無法提取有效內文"

        # 封裝為結構化段落 HTML
        paragraphs = extracted_text.split("\n\n")
        new_content_html = "".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())
        new_snippet = extracted_text[:200]

        await conn.execute(
            """
            UPDATE articles_hot
            SET content_html = ?, content_text = ?, snippet = ?
            WHERE id = ?
            """,
            (new_content_html, extracted_text, new_snippet, article_id),
        )
        await conn.commit()

        read_bool = bool(row["is_read"])
        return ArticleDetailDTO(
            id=row["id"],
            feed_id=row["feed_id"],
            feed_title=row["feed_title"],
            category_id=row["category_id"],
            category_name=row["category_name"],
            title=row["title"],
            url=row["url"],
            author=row["author"],
            snippet=new_snippet,
            cover_image_url=row["cover_image_url"],
            published_at=row["published_at"],
            is_read=read_bool,
            is_unread=not read_bool,
            is_starred=bool(row["is_starred"]),
            content_html=new_content_html,
            content_text=extracted_text,
            tags=[],
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}")
