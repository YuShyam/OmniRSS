"""邊緣中繼與網頁快剪路由控制器 (Edge Relay & Web Clipper Router).

This module handles browser extension Edge Relay RSS XML ingestion and Web Clipper article pushes,
authenticated with user API keys and enforcing multi-tenant isolation.
"""

from datetime import datetime, timezone
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from omnirss.api.dependencies import get_db, verify_api_key
from omnirss.api.schemas import EdgeRelayIngestRequest, EdgeTaskFeedDTO, WebClipperPushRequest
from omnirss.core.crawler_engine import CrawlerEngine
from omnirss.core.database import compute_entry_hash
from omnirss.core.security import HTMLSanitizer

router = APIRouter(prefix="/api", tags=["Edge Relay & Web Clipper"])


@router.get("/feeds/edge-tasks", response_model=list[EdgeTaskFeedDTO])
async def get_edge_tasks(
    user: dict = Depends(verify_api_key),
    conn: aiosqlite.Connection = Depends(get_db),
) -> list[EdgeTaskFeedDTO]:
    """獲取當前用戶專屬之受阻頻道待抓取任務 (Get Edge Relay Due Feeds for Authenticated User)."""
    user_id = user["id"]
    # 嚴格多租戶隔離：僅查詢該使用者自己訂閱且遭遇 403 / 錯誤之頻道
    cur = await conn.execute(
        """
        SELECT f.id as feed_id, f.feed_url, COALESCE(uf.custom_title, f.title) as title, f.last_error_message
        FROM user_feeds uf
        JOIN feeds f ON uf.feed_id = f.id
        WHERE uf.user_id = ? AND (f.error_count > 0 OR f.requires_flaresolverr = 1)
        ORDER BY f.error_count DESC
        """,
        (user_id,),
    )
    rows = await cur.fetchall()
    return [
        EdgeTaskFeedDTO(
            feed_id=r["feed_id"],
            feed_url=r["feed_url"],
            title=r["title"],
            last_error_message=r["last_error_message"],
        )
        for r in rows
    ]


@router.post("/feeds/{feed_id}/ingest")
async def ingest_edge_feed(
    feed_id: int,
    req: EdgeRelayIngestRequest,
    user: dict = Depends(verify_api_key),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """接收瀏覽器邊緣中繼回傳之原始 RSS/Atom XML (Ingest Edge-Relayed RSS Payload)."""
    user_id = user["id"]

    # 驗證該用戶是否確實訂閱此頻道
    cur = await conn.execute(
        "SELECT feed_id FROM user_feeds WHERE user_id = ? AND feed_id = ?",
        (user_id, feed_id),
    )
    if not await cur.fetchone():
        raise HTTPException(status_code=403, detail="Not authorized for this feed")

    f_cur = await conn.execute("SELECT feed_url FROM feeds WHERE id = ?", (feed_id,))
    feed_row = await f_cur.fetchone()
    if not feed_row:
        raise HTTPException(status_code=404, detail="Feed not found")

    feed_url = feed_row["feed_url"]
    crawler = CrawlerEngine()
    articles, _ = crawler.parse_feed_content(req.raw_xml.encode("utf-8"), feed_url)

    ingested_count = 0
    for a in articles:
        h = compute_entry_hash(feed_id, a.guid, a.url)
        await conn.execute(
            """
            INSERT OR IGNORE INTO articles_hot (feed_id, entry_hash, title, url, author, snippet, cover_image_url, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (feed_id, h, a.title, a.url, a.author, a.snippet, a.cover_image_url, a.published_at.strftime("%Y-%m-%d %H:%M:%S")),
        )
        a_cur = await conn.execute("SELECT id FROM articles_hot WHERE entry_hash = ?", (h,))
        a_id = (await a_cur.fetchone())["id"]
        await conn.execute(
            "INSERT OR IGNORE INTO user_article_states (user_id, article_id, is_read) VALUES (?, ?, 0)",
            (user_id, a_id),
        )
        ingested_count += 1

    # 重置頻道錯誤次數
    await conn.execute(
        """
        UPDATE feeds
        SET error_count = 0, last_error_message = NULL, last_checked_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (feed_id,),
    )
    await conn.commit()

    return {
        "feed_id": feed_id,
        "articles_ingested": ingested_count,
        "message": "Edge payload successfully ingested",
    }


@router.post("/articles/push")
async def push_clipped_article(
    req: WebClipperPushRequest,
    user: dict = Depends(verify_api_key),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """接收 Web Clipper 一鍵網頁剪藏文章 (Push Web Clipper Article)."""
    user_id = user["id"]

    # 1. 查找或建立剪藏專用預設頻道 (Web Clipper System Feed)
    clipper_url = f"system://clipper/{user_id}"
    f_cur = await conn.execute("SELECT id FROM feeds WHERE feed_url = ?", (clipper_url,))
    f_row = await f_cur.fetchone()
    if f_row:
        feed_id = f_row["id"]
    else:
        c_cur = await conn.execute(
            "INSERT INTO feeds (title, feed_url, check_interval_minutes, is_paused) VALUES ('網頁剪藏', ?, 1440, 1)",
            (clipper_url,),
        )
        feed_id = c_cur.lastrowid
        await conn.execute(
            "INSERT OR IGNORE INTO user_feeds (user_id, feed_id, custom_title) VALUES (?, ?, '網頁剪藏')",
            (user_id, feed_id),
        )

    # 2. 脫毒清洗文章 HTML
    clean_html = HTMLSanitizer.clean(req.html_content)
    snippet = HTMLSanitizer.extract_snippet(clean_html, max_chars=200)
    entry_hash = compute_entry_hash(feed_id, req.url, req.url)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    await conn.execute(
        """
        INSERT OR IGNORE INTO articles_hot (feed_id, entry_hash, title, url, author, snippet, cover_image_url, published_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (feed_id, entry_hash, req.title, req.url, req.author, snippet, req.cover_image_url, now_str),
    )

    a_cur = await conn.execute("SELECT id FROM articles_hot WHERE entry_hash = ?", (entry_hash,))
    a_id = (await a_cur.fetchone())["id"]
    await conn.execute(
        "INSERT OR IGNORE INTO user_article_states (user_id, article_id, is_read, is_starred) VALUES (?, ?, 0, 1)",
        (user_id, a_id),
    )
    await conn.commit()

    return {"article_id": a_id, "message": "Article clipped successfully"}
