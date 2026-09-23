"""資料庫與儲存底座單元測試 (Database and Storage Unit Tests).

Tests SQLite DDL schema creation, FTS5 sync triggers, unread count caching triggers, and image vault deduplication.
"""

from pathlib import Path
import aiosqlite
from PIL import Image
import pytest
from omnirss.core.database import compute_entry_hash
from omnirss.core.image_vault import ImageVault


def test_compute_entry_hash() -> None:
    """測試 Entry Hash 計算之確定性 (Test entry hash determinism)."""
    hash1 = compute_entry_hash(1, "guid-123", "https://example.com/post/1")
    hash2 = compute_entry_hash(1, "guid-123", "https://example.com/post/1")
    hash3 = compute_entry_hash(2, "guid-123", "https://example.com/post/1")

    assert len(hash1) == 64
    assert hash1 == hash2
    assert hash1 != hash3


@pytest.mark.asyncio
async def test_database_tables_and_triggers(async_db_conn: aiosqlite.Connection) -> None:
    """測試資料庫建立、FTS5 全文索引與未讀計數觸發器 (Test tables, FTS5 and unread triggers)."""
    conn = async_db_conn

    # 1. 建立測試用戶
    await conn.execute(
        "INSERT INTO users (username, password_hash, api_key) VALUES (?, ?, ?)",
        ("alice", "argon2_hash_mock", "omni_test_key_123"),
    )
    user_row = await (await conn.execute("SELECT id FROM users WHERE username = 'alice'")).fetchone()
    user_id = user_row["id"]

    # 2. 建立測試分類
    await conn.execute(
        "INSERT INTO categories (user_id, name, sort_order) VALUES (?, ?, ?)",
        (user_id, "10.科技新聞", 10),
    )
    cat_row = await (await conn.execute("SELECT id, unread_count FROM categories WHERE name = '10.科技新聞'")).fetchone()
    cat_id = cat_row["id"]
    assert cat_row["unread_count"] == 0

    # 3. 建立共用來源與訂閱
    await conn.execute(
        "INSERT INTO feeds (title, feed_url) VALUES (?, ?)",
        ("科技報橘", "https://example.com/feed.xml"),
    )
    feed_row = await (await conn.execute("SELECT id FROM feeds WHERE title = '科技報橘'")).fetchone()
    feed_id = feed_row["id"]

    await conn.execute(
        "INSERT INTO user_feeds (user_id, feed_id, category_id) VALUES (?, ?, ?)",
        (user_id, feed_id, cat_id),
    )

    # 4. 插入新文章
    entry_hash = compute_entry_hash(feed_id, "post-001", "https://example.com/post/001")
    await conn.execute(
        """
        INSERT INTO articles_hot (feed_id, entry_hash, title, url, author, snippet, published_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (feed_id, entry_hash, "台積電最新 2nm 晶片進展突破", "https://example.com/post/001", "記者張三", "台積電宣布最新晶片量產..."),
    )
    art_row = await (await conn.execute("SELECT id FROM articles_hot WHERE entry_hash = ?", (entry_hash,))).fetchone()
    article_id = art_row["id"]

    # 5. 驗證 FTS5 觸發器自動建立全文索引
    fts_rows = await (
        await conn.execute("SELECT rowid, title FROM articles_fts WHERE articles_fts MATCH '台積電'")
    ).fetchall()
    assert len(fts_rows) == 1
    assert fts_rows[0]["title"] == "台積電最新 2nm 晶片進展突破"

    # 6. 插入用戶文章未讀狀態 (is_read = 0) ➔ 觸發未讀數增加
    await conn.execute(
        "INSERT INTO user_article_states (user_id, article_id, is_read) VALUES (?, ?, 0)",
        (user_id, article_id),
    )
    await conn.commit()

    uf_row = await (await conn.execute("SELECT unread_count FROM user_feeds WHERE user_id = ? AND feed_id = ?", (user_id, feed_id))).fetchone()
    c_row = await (await conn.execute("SELECT unread_count FROM categories WHERE id = ?", (cat_id,))).fetchone()
    assert uf_row["unread_count"] == 1
    assert c_row["unread_count"] == 1

    # 7. 標記已讀 (0 -> 1) ➔ 觸發未讀數自動扣減為 0
    await conn.execute(
        "UPDATE user_article_states SET is_read = 1 WHERE user_id = ? AND article_id = ?",
        (user_id, article_id),
    )
    await conn.commit()

    uf_row2 = await (await conn.execute("SELECT unread_count FROM user_feeds WHERE user_id = ? AND feed_id = ?", (user_id, feed_id))).fetchone()
    c_row2 = await (await conn.execute("SELECT unread_count FROM categories WHERE id = ?", (cat_id,))).fetchone()
    assert uf_row2["unread_count"] == 0
    assert c_row2["unread_count"] == 0

    # 8. 重新標記為未讀 (1 -> 0) ➔ 觸發未讀數回補為 1
    await conn.execute(
        "UPDATE user_article_states SET is_read = 0 WHERE user_id = ? AND article_id = ?",
        (user_id, article_id),
    )
    await conn.commit()

    uf_row3 = await (await conn.execute("SELECT unread_count FROM user_feeds WHERE user_id = ? AND feed_id = ?", (user_id, feed_id))).fetchone()
    assert uf_row3["unread_count"] == 1


def test_image_vault_dedup(temp_dir: Path) -> None:
    """測試圖片庫 SHA-256 去重與 WebP 轉碼 (Test Image Vault WebP deduplication)."""
    vault = ImageVault(temp_dir / "images")

    # 生成 100x100 測試圖片二進位
    import io
    img = Image.new("RGB", (100, 100), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw_bytes = buf.getvalue()

    # 第一次儲存
    sha256_1, path_1, w1, h1 = vault.store_image(raw_bytes)
    assert path_1.is_file()
    assert path_1.suffix == ".webp"
    assert w1 == 100 and h1 == 100

    # 第二次儲存相同圖檔 (應命中去重快取，回傳相同路徑)
    sha256_2, path_2, w2, h2 = vault.store_image(raw_bytes)
    assert sha256_1 == sha256_2
    assert path_1 == path_2
