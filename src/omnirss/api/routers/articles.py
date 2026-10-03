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


def detect_applied_plugins(url: str = "", html: str = "", ai_summary: Optional[str] = None) -> list[str]:
    """檢測文章實際套用之外掛清單 (Detect plugins actually executed on article content)."""
    plugins: list[str] = []
    html_str = html or ""
    # 根據 DOM 實際含有外掛加工特徵 class 判斷
    if "ptt-meta-card" in html_str or "ptt-pushes-card" in html_str or "ptt-article-content" in html_str:
        plugins.append("omnirss/ptt-enhancer")
    if "m01-article" in html_str or "m01-figure" in html_str or "m01-quote" in html_str:
        plugins.append("omnirss/mobile01-enhancer")
    if "yh-article" in html_str or "yh-figure" in html_str or "yh-body" in html_str or "caas-body" in html_str:
        plugins.append("omnirss/yahoo-enhancer")
    if ai_summary and len(ai_summary.strip()) > 0:
        plugins.append("omnirss/gemini-summary")
    return plugins



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
    if search_kw and search_kw.strip() and search_kw.strip().lower() not in ("null", "undefined"):
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

    if feed_id is not None:
        # 1. 指定單一頻道時：直查無須跨頻道去重
        count_sql = f"""
            SELECT COUNT(*) as total
            FROM articles_hot a
            JOIN user_feeds uf ON a.feed_id = uf.feed_id
            LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
            {where_clause}
        """
        query_sql = f"""
            SELECT a.id, a.feed_id, COALESCE(uf.custom_title, f.title) as feed_title,
                   uf.category_id, c.name as category_name,
                   a.title, a.url, a.author, a.snippet, a.cover_image_url, a.published_at,
                   COALESCE(uas.is_read, 0) as is_read,
                   COALESCE(uas.is_starred, 0) as is_starred,
                   uas.highlight_color,
                   a.content_html,
                   a.ai_summary,
                   NULL as all_feed_titles
            FROM articles_hot a
            JOIN feeds f ON a.feed_id = f.id
            JOIN user_feeds uf ON a.feed_id = uf.feed_id
            LEFT JOIN categories c ON uf.category_id = c.id
            LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
            {where_clause}
            ORDER BY {sort_column} {sort_order}
            LIMIT ? OFFSET ?
        """
    else:
        # 2. 全站或分類視角：以標準化 URL 執行跨頻道展示層去重聚合
        count_sql = f"""
            SELECT COUNT(DISTINCT rtrim(a.url, '/')) as total
            FROM articles_hot a
            JOIN user_feeds uf ON a.feed_id = uf.feed_id
            LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
            {where_clause}
        """
        query_sql = f"""
            SELECT a.id, a.feed_id, COALESCE(uf.custom_title, f.title) as feed_title,
                   uf.category_id, c.name as category_name,
                   a.title, a.url, a.author, a.snippet, a.cover_image_url, a.published_at,
                   MAX(COALESCE(uas.is_read, 0)) as is_read,
                   MAX(COALESCE(uas.is_starred, 0)) as is_starred,
                   MAX(uas.highlight_color) as highlight_color,
                   a.content_html,
                   a.ai_summary,
                   GROUP_CONCAT(DISTINCT COALESCE(uf.custom_title, f.title)) as all_feed_titles
            FROM articles_hot a
            JOIN feeds f ON a.feed_id = f.id
            JOIN user_feeds uf ON a.feed_id = uf.feed_id
            LEFT JOIN categories c ON uf.category_id = c.id
            LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
            {where_clause}
            GROUP BY rtrim(a.url, '/')
            ORDER BY {sort_column} {sort_order}
            LIMIT ? OFFSET ?
        """

    c_cur = await conn.execute(count_sql, tuple(params))
    total = (await c_cur.fetchone())["total"]

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
        all_feeds_raw = r["all_feed_titles"] if "all_feed_titles" in r.keys() else None
        dup_feeds: Optional[list[str]] = None
        if all_feeds_raw:
            feed_list = [f.strip() for f in str(all_feeds_raw).split(",") if f.strip()]
            main_title = r["feed_title"]
            extra = [f for f in feed_list if f != main_title]
            if extra:
                dup_feeds = extra

        html_val = r["content_html"] if "content_html" in r.keys() else ""
        ai_sum_val = r["ai_summary"] if "ai_summary" in r.keys() else None
        applied_plugs = detect_applied_plugins(r["url"] or "", html_val or "", ai_sum_val)

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
                highlight_color=r["highlight_color"],
                tags=article_tags_map.get(r["id"], []),
                applied_plugins=applied_plugs,
                duplicate_feeds=dup_feeds,
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
               a.ai_summary, a.cover_image_url, a.published_at,
               COALESCE(uas.is_read, 0) as is_read,
               COALESCE(uas.is_starred, 0) as is_starred,
               uas.highlight_color
        FROM articles_hot a
        JOIN feeds f ON a.feed_id = f.id
        JOIN user_feeds uf ON a.feed_id = uf.feed_id
        LEFT JOIN categories c ON uf.category_id = c.id
        LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
        WHERE a.id = ? AND uf.user_id = ?
    """
    try:
        cur = await conn.execute(query_sql, (article_id, user_id))
    except Exception as query_err:
        if "no such column" in str(query_err).lower() and "ai_summary" in str(query_err).lower():
            try:
                await conn.execute("ALTER TABLE articles_hot ADD COLUMN ai_summary TEXT;")
                await conn.commit()
            except Exception as exc:
                logger.debug(f"Non-fatal exception adding ai_summary column to articles_hot: {exc}")
            cur = await conn.execute(query_sql, (article_id, user_id))
        else:
            raise

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
    applied_plugs = detect_applied_plugins(row["url"] or "", content_html, row["ai_summary"])

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
        highlight_color=row["highlight_color"],
        content_html=content_html,
        content_text=content_text,
        ai_summary=row["ai_summary"],
        tags=tags,
        applied_plugins=applied_plugs,
    )


async def _get_all_sibling_article_ids(conn: aiosqlite.Connection, user_id: int, article_id: int) -> list[int]:
    """取得同一用戶所訂閱頻道中，與指定文章具有相同標準化網址的所有文章 ID (Get all sibling article IDs across feeds)."""
    cur = await conn.execute("SELECT url FROM articles_hot WHERE id = ?", (article_id,))
    row = await cur.fetchone()
    if not row or not row["url"]:
        return [article_id]

    url = row["url"]
    s_cur = await conn.execute(
        """
        SELECT a.id FROM articles_hot a
        JOIN user_feeds uf ON a.feed_id = uf.feed_id
        WHERE uf.user_id = ? AND rtrim(a.url, '/') = rtrim(?, '/')
        """,
        (user_id, url),
    )
    s_rows = await s_cur.fetchall()
    return [r["id"] for r in s_rows] if s_rows else [article_id]


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
    highlight_color = patch.get("highlight_color") if "highlight_color" in patch else None

    target_ids = await _get_all_sibling_article_ids(conn, user_id, article_id)
    for aid in target_ids:
        cur = await conn.execute(
            "SELECT is_read, is_starred, is_trash, highlight_color FROM user_article_states WHERE user_id = ? AND article_id = ?",
            (user_id, aid),
        )
        row = await cur.fetchone()
        if not row:
            await conn.execute(
                """
                INSERT INTO user_article_states (user_id, article_id, is_read, is_starred, is_trash, highlight_color, starred_at)
                VALUES (?, ?, ?, ?, ?, ?, CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END)
                """,
                (user_id, aid, is_read or 0, is_starred or 0, is_trash or 0, highlight_color, is_starred or 0),
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
            if "highlight_color" in patch:
                updates.append("highlight_color = ?")
                params.append(highlight_color)
            if updates:
                params.extend([user_id, aid])
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
    target_ids = await _get_all_sibling_article_ids(conn, user_id, article_id)
    for aid in target_ids:
        await conn.execute(
            """
            INSERT INTO user_article_states (user_id, article_id, is_read)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, article_id) DO UPDATE SET is_read = excluded.is_read
            """,
            (user_id, aid, 1 if is_read else 0),
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
    target_ids = await _get_all_sibling_article_ids(conn, user_id, article_id)
    for aid in target_ids:
        await conn.execute(
            """
            INSERT INTO user_article_states (user_id, article_id, is_starred, starred_at)
            VALUES (?, ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
            ON CONFLICT(user_id, article_id) DO UPDATE SET
                is_starred = excluded.is_starred,
                starred_at = excluded.starred_at
            """,
            (user_id, aid, 1 if is_starred else 0, 1 if is_starred else 0),
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
    cat_id = (req or {}).get("category_id")
    scope = (req or {}).get("scope")
    if cat_id is None and scope == "category":
        cat_id = (req or {}).get("target_id", "uncategorized")

    is_uncategorized = (scope == "uncategorized") or (
        cat_id is not None and str(cat_id).strip().lower() in ("uncategorized", "null", "none", "0")
    )

    if feed_id:
        target_articles_sql = """
            SELECT a.id FROM articles_hot a
            JOIN user_feeds uf ON a.feed_id = uf.feed_id
            WHERE uf.user_id = ? AND a.feed_id = ?
        """
        params = (user_id, feed_id)
    elif is_uncategorized:
        target_articles_sql = """
            SELECT a.id FROM articles_hot a
            JOIN user_feeds uf ON a.feed_id = uf.feed_id
            WHERE uf.user_id = ? AND uf.category_id IS NULL
        """
        params = (user_id,)
    elif cat_id is not None and str(cat_id).isdigit():
        target_articles_sql = """
            SELECT a.id FROM articles_hot a
            JOIN user_feeds uf ON a.feed_id = uf.feed_id
            WHERE uf.user_id = ? AND uf.category_id = ?
        """
        params = (user_id, int(cat_id))
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
    elif is_uncategorized:
        await conn.execute("UPDATE user_feeds SET unread_count = 0 WHERE user_id = ? AND category_id IS NULL", (user_id,))
    elif cat_id is not None and str(cat_id).isdigit():
        await conn.execute("UPDATE user_feeds SET unread_count = 0 WHERE user_id = ? AND category_id = ?", (user_id, int(cat_id)))
        await conn.execute("UPDATE categories SET unread_count = 0 WHERE user_id = ? AND id = ?", (user_id, int(cat_id)))
    else:
        await conn.execute("UPDATE user_feeds SET unread_count = 0 WHERE user_id = ?", (user_id,))
        await conn.execute("UPDATE categories SET unread_count = 0 WHERE user_id = ?", (user_id,))

    await conn.commit()
    return {"marked_count": len(rows), "status": "success"}


@router.post("/{article_id}/fetch-full-content", response_model=ArticleDetailDTO)
async def fetch_article_full_content(
    article_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> ArticleDetailDTO:
    """透過多階梯全文引擎抓取原始網頁全文並更新文章 (Fetch Full Web Page Content via Multi-Tier Engine)."""
    from omnirss.core.database import get_db_manager
    from omnirss.core.security import HTMLSanitizer

    user_id = user["id"]
    query_sql = """
        SELECT a.id, a.feed_id, a.url, a.title, a.author, a.snippet, a.published_at,
               a.ai_summary, a.cover_image_url, COALESCE(uf.custom_title, f.title) as feed_title,
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
    """
    try:
        cur = await conn.execute(query_sql, (article_id, user_id))
    except Exception as query_err:
        if "no such column" in str(query_err).lower() and "ai_summary" in str(query_err).lower():
            try:
                db_mgr = get_db_manager()
                async with db_mgr.write_transaction() as wconn:
                    await wconn.execute("ALTER TABLE articles_hot ADD COLUMN ai_summary TEXT;")
                    await wconn.commit()
            except Exception as exc:
                logger.debug(f"Non-fatal exception adding ai_summary column to articles_hot in fetch: {exc}")
            cur = await conn.execute(query_sql, (article_id, user_id))
        else:
            raise

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
        
        new_content_html = None
        extracted_text = ""
        new_snippet = ""

        if status_code < 400 and html_raw:
            from omnirss.core.plugin_manager import get_plugin_manager
            from omnirss.sdk.models import ArticleDTO
            pm = get_plugin_manager()
            raw_dto = ArticleDTO(
                id=article_id,
                feed_id=row["feed_id"],
                title=row["title"],
                url=article_url,
                author=row["author"],
                content_html=html_raw,
                content_text=HTMLSanitizer.extract_text(html_raw),
                snippet=HTMLSanitizer.extract_snippet(html_raw, max_chars=200),
            )
            # 優先讓專屬處理外掛（如 PTT / Yahoo / Mobile01）解析原始完整 HTML
            try:
                processed_full = await pm.execute_all_processors(
                    raw_dto, user_id=user["id"], trigger_source="manual"
                )
                if processed_full and processed_full.content_html and processed_full.content_html != html_raw:
                    new_content_html = processed_full.content_html
                    extracted_text = processed_full.content_text or HTMLSanitizer.extract_text(new_content_html)
                    new_snippet = HTMLSanitizer.extract_snippet(new_content_html, max_chars=200)
            except Exception as proc_err:
                logger.debug(f"Plugin pipeline bypass on manual full text: {proc_err}")

            # 若無專屬外掛處理，回退至 Trafilatura 通用全文萃取
            if not new_content_html:
                extracted_html = CrawlerEngine.extract_full_text_from_html(html_raw, base_url=article_url)
                if extracted_html:
                    new_content_html = extracted_html
                    extracted_text = HTMLSanitizer.extract_text(extracted_html)
                    new_snippet = HTMLSanitizer.extract_snippet(extracted_html, max_chars=200)

        if not new_content_html:
            extracted_text = row["snippet"] or "無法自遠端網站提取全文內容"
            new_content_html = f"<p>{extracted_text}</p>"
            new_snippet = extracted_text[:200]

        db_mgr = get_db_manager()
        async with db_mgr.write_transaction() as wconn:
            await wconn.execute(
                """
                UPDATE articles_hot
                SET content_html = ?, content_text = ?, snippet = ?
                WHERE id = ?
                """,
                (new_content_html, extracted_text, new_snippet, article_id),
            )
            await wconn.commit()

        read_bool = bool(row["is_read"])
        applied_plugs = detect_applied_plugins(row["url"] or "", new_content_html, row["ai_summary"])
        t_cur = await conn.execute(
            """
            SELECT t.id, t.name, t.color_hex
            FROM article_tags at
            JOIN tags t ON at.tag_id = t.id
            WHERE at.article_id = ? AND t.user_id = ?
            ORDER BY t.sort_order ASC, t.id ASC
            """,
            (article_id, user_id),
        )
        tags = [{"id": tr["id"], "name": tr["name"], "color_hex": tr["color_hex"]} for tr in await t_cur.fetchall()]

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
            ai_summary=row["ai_summary"],
            highlight_color=row["highlight_color"] if "highlight_color" in row.keys() else None,
            tags=tags,
            applied_plugins=applied_plugs,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}")
