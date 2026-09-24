"""SQLite WAL 儲存底座與 DDL 遷移引擎 (SQLite WAL Database & Storage Engine).

This module manages async and sync SQLite connection pools, PRAGMA optimizations,
13-table schema DDL migrations, FTS5 full-text search indexing, and real-time triggers.
"""

from contextlib import asynccontextmanager
import hashlib
from pathlib import Path
import sqlite3
from typing import AsyncGenerator, Optional, Union
import aiosqlite
from loguru import logger
from omnirss.core.config import get_settings


DDL_SCHEMA = """
-- 1. 系統使用者表 (System Users)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin BOOLEAN NOT NULL DEFAULT 0,
    api_key TEXT NOT NULL UNIQUE,
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key);

-- 2. 個人訂閱目錄表 (Categories)
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    custom_retention_days INTEGER DEFAULT NULL,
    unread_count INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_categories_user_sort ON categories(user_id, sort_order ASC, name ASC);

-- 3. 全站共用訂閱來源池 (Feeds Pool)
CREATE TABLE IF NOT EXISTS feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    feed_url TEXT NOT NULL UNIQUE,
    site_url TEXT,
    icon_hash TEXT,
    etag_header TEXT,
    last_modified_header TEXT,
    check_interval_minutes INTEGER NOT NULL DEFAULT 30,
    error_count INTEGER NOT NULL DEFAULT 0,
    last_error_message TEXT,
    last_checked_at DATETIME,
    next_check_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_paused BOOLEAN NOT NULL DEFAULT 0,
    requires_flaresolverr BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_feeds_next_check ON feeds(next_check_at ASC) WHERE is_paused = 0;

-- 4. 用戶訂閱關聯表 (User Feeds)
CREATE TABLE IF NOT EXISTS user_feeds (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    feed_id INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    custom_title TEXT,
    custom_retention_days INTEGER DEFAULT NULL,
    unread_count INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, feed_id)
);
CREATE INDEX IF NOT EXISTS idx_user_feeds_cat ON user_feeds(user_id, category_id);

-- 5. 全站共用熱文章中繼資料表 (Hot Articles Metadata Pool)
CREATE TABLE IF NOT EXISTS articles_hot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    entry_hash TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    author TEXT,
    snippet TEXT,
    content_html TEXT,
    content_text TEXT,
    cover_image_url TEXT,
    published_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles_hot(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_feed_pub ON articles_hot(feed_id, published_at DESC);

-- 6. 用戶文章狀態表 (User Article State Trackers)
CREATE TABLE IF NOT EXISTS user_article_states (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    article_id INTEGER NOT NULL REFERENCES articles_hot(id) ON DELETE CASCADE,
    is_read BOOLEAN NOT NULL DEFAULT 0,
    is_starred BOOLEAN NOT NULL DEFAULT 0,
    starred_at DATETIME,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, article_id)
);
CREATE INDEX IF NOT EXISTS idx_user_states_unread ON user_article_states(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_user_states_starred ON user_article_states(user_id, is_starred);

-- 7. 冷資料庫／永久收藏表 (Cold Archives)
CREATE TABLE IF NOT EXISTS archives_cold (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_hash TEXT NOT NULL UNIQUE,
    feed_title TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    author TEXT,
    content_html_compressed BLOB NOT NULL,
    content_text_raw TEXT,
    ai_summary TEXT,
    published_at DATETIME NOT NULL,
    starred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_archives_starred_at ON archives_cold(starred_at DESC);

-- 8. 標籤體系表 (Tags & Article Tags)
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    color_hex TEXT NOT NULL DEFAULT '#3b82f6',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS article_tags (
    article_id INTEGER NOT NULL REFERENCES articles_hot(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (article_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_article_tags_tag ON article_tags(tag_id, article_id);

-- 9. 圖片雜湊去重管理表 (Assets & Asset References)
CREATE TABLE IF NOT EXISTS assets (
    sha256_hash TEXT PRIMARY KEY,
    original_url TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'image/webp',
    width INTEGER,
    height INTEGER,
    file_size_bytes INTEGER NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS asset_references (
    entry_hash TEXT NOT NULL,
    sha256_hash TEXT NOT NULL REFERENCES assets(sha256_hash) ON DELETE CASCADE,
    PRIMARY KEY (entry_hash, sha256_hash)
);

-- 10. 外掛遙測與監控表 (Plugins Telemetry)
CREATE TABLE IF NOT EXISTS plugins_telemetry (
    plugin_id TEXT PRIMARY KEY,
    is_enabled BOOLEAN NOT NULL DEFAULT 1,
    is_tripped BOOLEAN NOT NULL DEFAULT 0,
    total_runs INTEGER NOT NULL DEFAULT 0,
    success_runs INTEGER NOT NULL DEFAULT 0,
    error_runs INTEGER NOT NULL DEFAULT 0,
    consecutive_errors INTEGER NOT NULL DEFAULT 0,
    last_duration_ms INTEGER NOT NULL DEFAULT 0,
    avg_duration_ms INTEGER NOT NULL DEFAULT 0,
    last_error_message TEXT,
    last_error_traceback TEXT,
    last_run_at DATETIME
);

-- 11. 全域外掛設定表 (Global Plugin Configs)
CREATE TABLE IF NOT EXISTS plugin_configs_global (
    plugin_id TEXT PRIMARY KEY,
    config_json TEXT NOT NULL DEFAULT '{}',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 12. 個人外掛偏好表 (User Plugin Configs)
CREATE TABLE IF NOT EXISTS user_plugin_configs (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plugin_id TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, plugin_id)
);
CREATE INDEX IF NOT EXISTS idx_user_plugin ON user_plugin_configs(user_id, plugin_id);

-- 13. 個人智慧過濾與規則表 (User Rules)
CREATE TABLE IF NOT EXISTS user_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    scope_category_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
    scope_feed_id INTEGER REFERENCES feeds(id) ON DELETE CASCADE,
    conditions_json TEXT NOT NULL,
    actions_json TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_user_rules_active ON user_rules(user_id, is_enabled, sort_order ASC);
"""

FTS5_SCHEMA = """
-- FTS5 虛擬全文索引表 (FTS5 Full-Text Index with Trigram Tokenizer)
CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    title,
    author,
    snippet,
    content='articles_hot',
    content_rowid='id',
    tokenize='trigram'
);

-- FTS5 自動同步觸發器 (FTS5 Triggers)
CREATE TRIGGER IF NOT EXISTS trg_articles_hot_ai AFTER INSERT ON articles_hot BEGIN
    INSERT INTO articles_fts(rowid, title, author, snippet) 
    VALUES (new.id, new.title, new.author, new.snippet);
END;

CREATE TRIGGER IF NOT EXISTS trg_articles_hot_ad AFTER DELETE ON articles_hot BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, title, author, snippet) 
    VALUES('delete', old.id, old.title, old.author, old.snippet);
END;
"""

TRIGGERS_UNREAD_SCHEMA = """
-- 未讀計數快取自動同步觸發器 (Unread Count Auto-Sync Triggers)

-- 1. 當插入新使用者文章狀態且為未讀時
CREATE TRIGGER IF NOT EXISTS trg_user_states_unread_inc AFTER INSERT ON user_article_states
WHEN new.is_read = 0
BEGIN
    UPDATE user_feeds
    SET unread_count = unread_count + 1
    WHERE user_id = new.user_id
      AND feed_id = (SELECT feed_id FROM articles_hot WHERE id = new.article_id);

    UPDATE categories
    SET unread_count = unread_count + 1
    WHERE id = (
        SELECT category_id FROM user_feeds
        WHERE user_id = new.user_id
          AND feed_id = (SELECT feed_id FROM articles_hot WHERE id = new.article_id)
    );
END;

-- 2. 當文章被標記為已讀時扣減 (0 -> 1)
CREATE TRIGGER IF NOT EXISTS trg_user_states_read_dec AFTER UPDATE OF is_read ON user_article_states
WHEN old.is_read = 0 AND new.is_read = 1
BEGIN
    UPDATE user_feeds
    SET unread_count = MAX(0, unread_count - 1)
    WHERE user_id = new.user_id
      AND feed_id = (SELECT feed_id FROM articles_hot WHERE id = new.article_id);

    UPDATE categories
    SET unread_count = MAX(0, unread_count - 1)
    WHERE id = (
        SELECT category_id FROM user_feeds
        WHERE user_id = new.user_id
          AND feed_id = (SELECT feed_id FROM articles_hot WHERE id = new.article_id)
    );
END;

-- 3. 當文章由已讀改為未讀時增加 (1 -> 0)
CREATE TRIGGER IF NOT EXISTS trg_user_states_read_revert AFTER UPDATE OF is_read ON user_article_states
WHEN old.is_read = 1 AND new.is_read = 0
BEGIN
    UPDATE user_feeds
    SET unread_count = unread_count + 1
    WHERE user_id = new.user_id
      AND feed_id = (SELECT feed_id FROM articles_hot WHERE id = new.article_id);

    UPDATE categories
    SET unread_count = unread_count + 1
    WHERE id = (
        SELECT category_id FROM user_feeds
        WHERE user_id = new.user_id
          AND feed_id = (SELECT feed_id FROM articles_hot WHERE id = new.article_id)
    );
END;
"""


def compute_entry_hash(feed_id: int, guid: str, url: str) -> str:
    """計算文章物理唯一去重雜湊 (Compute SHA-256 entry hash).

    :param feed_id: 訂閱來源 ID (Feed ID)
    :param guid: 文章 GUID (Article GUID)
    :param url: 文章原文 URL (Article URL)
    :return: 64 位元 16 進位 SHA-256 雜湊 (Entry hash string)
    """
    raw_key = f"{feed_id}:{guid.strip()}:{url.strip()}".encode("utf-8")
    return hashlib.sha256(raw_key).hexdigest()


def apply_pragmas(conn: Union[sqlite3.Connection, aiosqlite.Connection]) -> None:
    """套用 SQLite 效能調優 PRAGMA 指令 (Apply SQLite PRAGMA performance tuning).

    :param conn: 資料庫連線物件 (Database connection)
    """
    pragmas = [
        "PRAGMA journal_mode = WAL;",
        "PRAGMA synchronous = NORMAL;",
        "PRAGMA busy_timeout = 5000;",
        "PRAGMA cache_size = -64000;",
        "PRAGMA temp_store = MEMORY;",
        "PRAGMA foreign_keys = ON;",
        "PRAGMA auto_vacuum = INCREMENTAL;",
    ]
    if isinstance(conn, sqlite3.Connection):
        for p in pragmas:
            conn.execute(p)
    # 若為 aiosqlite，呼叫端需自行非同步 execute


def init_db_sync(db_path: Union[str, Path]) -> None:
    """同步初始化資料庫結構與觸發器 (Synchronously initialize database schema and triggers).

    :param db_path: 資料庫檔案路徑 (Database file path)
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    try:
        conn.row_factory = sqlite3.Row
        apply_pragmas(conn)
        conn.executescript(DDL_SCHEMA)
        # 自動向後相容補齊歷史資料庫欄位 (Auto-migrate existing database columns)
        for col_def in ["content_html TEXT", "content_text TEXT"]:
            try:
                conn.execute(f"ALTER TABLE articles_hot ADD COLUMN {col_def};")
            except sqlite3.OperationalError:
                pass
        try:
            conn.executescript(FTS5_SCHEMA)
        except sqlite3.OperationalError as e:
            logger.warning(f"FTS5 initialization notice: {e}")
        conn.executescript(TRIGGERS_UNREAD_SCHEMA)
        conn.commit()
    finally:
        conn.close()


class DatabaseManager:
    """非同步 SQLite 資料庫管理器 (Asynchronous SQLite Database Manager)."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        if db_path is None:
            settings = get_settings()
            self.db_path = Path(settings.database.path)
        else:
            self.db_path = Path(db_path)

    async def initialize(self) -> None:
        """非同步初始化資料庫表結構 (Async database initialization)."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        init_db_sync(self.db_path)

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """獲取已套用 PRAGMA 調優之非同步資料庫連線 (Get tuned async connection context).

        :return: aiosqlite 連線生成器
        """
        conn = await aiosqlite.connect(str(self.db_path))
        try:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode = WAL;")
            await conn.execute("PRAGMA synchronous = NORMAL;")
            await conn.execute("PRAGMA busy_timeout = 5000;")
            await conn.execute("PRAGMA foreign_keys = ON;")
            yield conn
        finally:
            await conn.close()

    # 常用別名 (Convenience aliases)
    init_db = initialize
    get_db = get_connection

    async def close(self) -> None:
        """關閉連線池 (Close pool, no-op for transient connections)."""
        pass


_DB_MANAGER: Optional[DatabaseManager] = None


def get_db_manager(db_path: Optional[Union[str, Path]] = None) -> DatabaseManager:
    """取得資料庫管理器單例 (Get singleton database manager).

    :param db_path: 自訂資料庫路徑
    :return: DatabaseManager 實例
    """
    global _DB_MANAGER
    if _DB_MANAGER is None or db_path is not None:
        _DB_MANAGER = DatabaseManager(db_path)
    return _DB_MANAGER


def set_global_db_manager(db_manager: DatabaseManager) -> None:
    """設定全域資料庫管理器單例 (Set global singleton database manager)."""
    global _DB_MANAGER
    _DB_MANAGER = db_manager
