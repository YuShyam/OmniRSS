"""文章串流與狀態切換路由控制器 (Articles Streaming & State Router).

This module handles paginated article feeds, FTS5 full-text search, read/starred toggles,
and batch mark-read operations.
"""

from typing import Optional
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status

from omnirss.api.dependencies import get_current_user, get_db, get_write_db
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
    tag: Optional[str] = Query(None, description="依標籤名稱過濾"),
    tag_id: Optional[int] = Query(None, description="依標籤 ID 過濾"),
    is_read: Optional[bool] = Query(None, description="是否已讀 (True/False)"),
    is_unread: Optional[bool] = Query(None, description="是否未讀 (True/False)"),
    is_starred: Optional[bool] = Query(None, description="是否星標 (True/False)"),
    is_trash: Optional[bool] = Query(None, description="是否垃圾桶 (True/False)"),
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
    """分頁查詢文章清單 (List Articles with Filtering, Search, and Tags)."""
    user_id = user["id"]
    conditions = ["uf.user_id = ?"]
    params: list = [user_id]

    if is_trash is True:
        conditions.append("COALESCE(uas.is_trash, 0) = 1")
    else:
        conditions.append("COALESCE(uas.is_trash, 0) = 0")

    if feed_id is not None:
        conditions.append("a.feed_id = ?")
        params.append(feed_id)

    if category_id is not None:
        if category_id == 0:
            conditions.append("uf.category_id IS NULL")
        else:
            conditions.append("uf.category_id = ?")
            params.append(category_id)

    if tag_id is not None:
        conditions.append("a.id IN (SELECT article_id FROM article_tags WHERE tag_id = ?)")
        params.append(tag_id)

    if tag is not None and tag.strip():
        conditions.append(
            "a.id IN (SELECT at.article_id FROM article_tags at JOIN tags t ON at.tag_id = t.id WHERE t.name = ? AND t.user_id = ?)"
        )
        params.extend([tag.strip(), user_id])

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

    # 批次組裝標籤 (Batch fetch article tags)
    article_tags_map: dict[int, list[dict[str, Any]]] = {}
    if rows:
        article_ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in article_ids)
        t_cur = await conn.execute(
            f"""
            SELECT at.article_id, t.id, t.name, t.color_hex
            FROM article_tags at
            JOIN tags t ON at.tag_id = t.id
            WHERE at.article_id IN ({placeholders}) AND t.user_id = ?
            ORDER BY t.sort_order ASC, t.id ASC
            """,
            tuple(article_ids) + (user_id,),
        )
        t_rows = await t_cur.fetchall()
        for tr in t_rows:
            article_tags_map.setdefault(tr["article_id"], []).append({
                "id": tr["id"],
                "name": tr["name"],
                "color_hex": tr["color_hex"],
            })

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
                tags=article_tags_map.get(r["id"], []),
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
    """取得單篇文章完整內容 (Get Article Detail with HTML and Tags)."""
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

    # 取得文章標籤
    t_cur = await conn.execute(
        """
        SELECT t.id, t.name, t.color_hex
        FROM tags t
        JOIN article_tags at ON t.id = at.tag_id
        WHERE at.article_id = ? AND t.user_id = ?
        ORDER BY t.sort_order ASC, t.id ASC
        """,
        (article_id, user_id),
    )
    tags = [dict(tr) for tr in await t_cur.fetchall()]

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
        tags=tags,
    )


@router.patch("/{article_id}/state")
async def update_article_state_patch(
    article_id: int,
    patch: dict,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """整合切換單篇文章狀態 (Update Article Read/Star State via Patch)."""
    user_id = user["id"]
    is_read = None
    if "is_read" in patch:
        is_read = 1 if patch["is_read"] else 0
    elif "is_unread" in patch:
        is_read = 0 if patch["is_unread"] else 1

    is_starred = 1 if patch.get("is_starred") else 0 if "is_starred" in patch else None
    is_trash = 1 if patch.get("is_trash") else 0 if "is_trash" in patch else None

    # 確保該關聯存在
    cur = await conn.execute(
        "SELECT is_read, is_starred, is_trash FROM user_article_states WHERE user_id = ? AND article_id = ?",
        (user_id, article_id),
    )
    row = await cur.fetchone()
    if not row:
        await conn.execute(
            """
            INSERT INTO user_article_states (user_id, article_id, is_read, is_starred, is_trash, starred_at)
            VALUES (?, ?, ?, ?, ?, CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END)
            """,
            (user_id, article_id, is_read or 0, is_starred or 0, is_trash or 0, is_starred or 0),
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
        if is_trash is not None:
            updates.append("is_trash = ?")
            params.append(is_trash)
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
    conn: aiosqlite.Connection = Depends(get_write_db),
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
    conn: aiosqlite.Connection = Depends(get_write_db),
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


@router.delete("/{article_id}")
async def delete_article(
    article_id: int,
    permanent: bool = Query(False, description="是否永久刪除"),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """刪除單篇文章 (移至垃圾桶或永久刪除)."""
    user_id = user["id"]
    cur = await conn.execute(
        "SELECT is_trash FROM user_article_states WHERE user_id = ? AND article_id = ?",
        (user_id, article_id),
    )
    row = await cur.fetchone()
    
    # 若已在垃圾桶或指定永久刪除，則直接移除用戶狀態
    if permanent or (row and row["is_trash"]):
        await conn.execute(
            "DELETE FROM user_article_states WHERE user_id = ? AND article_id = ?",
            (user_id, article_id),
        )
        await conn.commit()
        return {"article_id": article_id, "deleted": True, "permanent": True}
    else:
        # 移至垃圾桶 (設為 is_trash = 1, is_read = 1)
        await conn.execute(
            """
            INSERT INTO user_article_states (user_id, article_id, is_read, is_trash)
            VALUES (?, ?, 1, 1)
            ON CONFLICT(user_id, article_id) DO UPDATE SET
                is_trash = 1,
                is_read = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, article_id),
        )
        await conn.commit()
        return {"article_id": article_id, "deleted": True, "permanent": False}


@router.post("/{article_id}/trash")
async def toggle_article_trash(
    article_id: int,
    req: Optional[dict] = None,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """移至垃圾桶或自垃圾桶還原 (Toggle Article Trash)."""
    user_id = user["id"]
    is_trash = (req or {}).get("is_trash", True)
    
    await conn.execute(
        """
        INSERT INTO user_article_states (user_id, article_id, is_read, is_trash)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(user_id, article_id) DO UPDATE SET
            is_trash = excluded.is_trash,
            is_read = CASE WHEN excluded.is_trash = 1 THEN 1 ELSE is_read END,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, article_id, 1 if is_trash else 0),
    )
    await conn.commit()
    return {"article_id": article_id, "is_trash": is_trash}


@router.post("/trash/empty")
async def empty_trash(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """清空當前使用者的所有垃圾桶文章 (Empty Trash for User)."""
    user_id = user["id"]
    cur = await conn.execute(
        "DELETE FROM user_article_states WHERE user_id = ? AND is_trash = 1",
        (user_id,),
    )
    deleted_count = cur.rowcount
    await conn.commit()
    return {"deleted_count": deleted_count, "message": f"已清空垃圾桶 ({deleted_count} 篇文章)"}


@router.post("/mark-all-read")
@router.put("/mark-all-read")
async def mark_all_read_flexible(
    req: Optional[dict] = None,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """批次標記已讀並同步歸零未讀計數 (Batch Mark All Read with Single-Writer Write DB)."""
    user_id = user["id"]
    article_ids = (req or {}).get("article_ids")
    if article_ids and isinstance(article_ids, list) and len(article_ids) > 0:
        for aid in article_ids:
            await conn.execute(
                """
                INSERT INTO user_article_states (user_id, article_id, is_read)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, article_id) DO UPDATE SET is_read = 1
                """,
                (user_id, aid),
            )
        await conn.commit()
        return {"marked_count": len(article_ids), "status": "success"}

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

    if feed_id:
        await conn.execute("UPDATE user_feeds SET unread_count = 0 WHERE user_id = ? AND feed_id = ?", (user_id, feed_id))
    elif cat_id:
        await conn.execute("UPDATE user_feeds SET unread_count = 0 WHERE user_id = ? AND category_id = ?", (user_id, cat_id))
        await conn.execute("UPDATE categories SET unread_count = 0 WHERE user_id = ? AND id = ?", (user_id, cat_id))
    else:
        await conn.execute("UPDATE user_feeds SET unread_count = 0 WHERE user_id = ?", (user_id,))
        await conn.execute("UPDATE categories SET unread_count = 0 WHERE user_id = ?", (user_id,))

    await conn.commit()
    return {"marked_count": len(rows), "status": "success"}


@router.post("/{article_id}/fetch-full-content", response_model=ArticleDetailDTO)
async def fetch_article_full_content(
    article_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> ArticleDetailDTO:
    """透過多階梯全文引擎抓取原始網頁全文並更新文章 (Fetch Full Web Page Content via Multi-Tier Engine)."""
    from omnirss.core.security import HTMLSanitizer

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
        status_code, html_raw = await crawler.fetch_web_page(
            url=article_url,
            requires_flaresolverr=bool(row["requires_flaresolverr"]),
        )
        
        extracted_html = None
        if status_code < 400 and html_raw:
            extracted_html = CrawlerEngine.extract_full_text_from_html(html_raw, base_url=article_url)
        
        if extracted_html:
            new_content_html = extracted_html
            extracted_text = HTMLSanitizer.extract_text(extracted_html)
            new_snippet = HTMLSanitizer.extract_snippet(extracted_html, max_chars=200)
        else:
            extracted_text = row["snippet"] or "無法自遠端網站提取全文內容"
            new_content_html = f"<p>{extracted_text}</p>"
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
