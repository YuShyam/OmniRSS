"""資料備份與 OPML 匯出入路由控制器 (Backup & OPML Router).

This module handles OPML 2.0 import/export and sanitized JSON backup/restore.
"""

import json
from pathlib import Path
import secrets
import shutil
import aiosqlite
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from loguru import logger

from omnirss.api.dependencies import get_current_user, get_db
from omnirss.core.backup_engine import BackupEngine
from omnirss.core.config import get_settings
from omnirss.core.database import get_db_manager, init_db_sync

router = APIRouter(prefix="/api", tags=["Backup & OPML"])


@router.get("/opml/export")
async def export_opml(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> Response:
    """匯出 OPML 2.0 訂閱清單 (Export OPML 2.0 XML)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        SELECT f.title, f.feed_url, f.site_url, c.name as category_name
        FROM user_feeds uf
        JOIN feeds f ON uf.feed_id = f.id
        LEFT JOIN categories c ON uf.category_id = c.id
        WHERE uf.user_id = ?
        ORDER BY c.sort_order ASC, f.title ASC
        """,
        (user_id,),
    )
    rows = await cur.fetchall()
    feeds_data = [dict(r) for r in rows]

    opml_xml = BackupEngine.generate_opml(
        feeds_data, title=f"OmniRSS Subscriptions ({user['username']})"
    )
    return Response(
        content=opml_xml,
        media_type="application/xml",
        headers={
            "Content-Disposition": f"attachment; filename=omnirss_subscriptions_{user['username']}.opml"
        },
    )


@router.post("/opml/import")
async def import_opml(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """匯入 OPML 2.0 訂閱檔 (Import OPML 2.0 File)."""
    user_id = user["id"]
    content_bytes = await file.read()

    try:
        items = BackupEngine.parse_opml(content_bytes)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse OPML file: {e}",
        )

    categories_cache: dict[str, int] = {}
    imported_count = 0

    for item in items:
        cat_id = None
        if item.category_name:
            if item.category_name not in categories_cache:
                c_cur = await conn.execute(
                    "SELECT id FROM categories WHERE user_id = ? AND name = ?",
                    (user_id, item.category_name),
                )
                c_row = await c_cur.fetchone()
                if c_row:
                    cat_id = c_row["id"]
                else:
                    new_c = await conn.execute(
                        "INSERT INTO categories (user_id, name) VALUES (?, ?)",
                        (user_id, item.category_name),
                    )
                    cat_id = new_c.lastrowid
                categories_cache[item.category_name] = cat_id
            else:
                cat_id = categories_cache[item.category_name]

        # 寫入 feeds 池
        f_cur = await conn.execute(
            "SELECT id FROM feeds WHERE feed_url = ?",
            (item.feed.feed_url,),
        )
        f_row = await f_cur.fetchone()
        if f_row:
            feed_id = f_row["id"]
        else:
            ins_f = await conn.execute(
                """
                INSERT INTO feeds (title, feed_url, site_url)
                VALUES (?, ?, ?)
                """,
                (item.feed.title, item.feed.feed_url, item.feed.site_url),
            )
            feed_id = ins_f.lastrowid

        # 建立 user_feeds 關聯
        await conn.execute(
            """
            INSERT OR IGNORE INTO user_feeds (user_id, feed_id, category_id, custom_title)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, feed_id, cat_id, item.feed.title),
        )
        imported_count += 1

    await conn.commit()
    return {
        "imported_count": imported_count,
        "imported_feeds": imported_count,
        "message": "OPML imported successfully",
    }


@router.get("/user/backup")
async def export_user_backup(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """匯出已脫敏之個人全套設定與規則 (Export Sanitized User Backup JSON)."""
    user_id = user["id"]

    # 1. 查詢個人偏好
    settings = json.loads(user.get("settings_json") or "{}")

    # 2. 查詢過濾規則
    r_cur = await conn.execute(
        "SELECT name, sort_order, is_enabled, conditions_json, actions_json FROM user_rules WHERE user_id = ?",
        (user_id,),
    )
    rules = [
        {
            "name": r["name"],
            "sort_order": r["sort_order"],
            "is_enabled": bool(r["is_enabled"]),
            "conditions": json.loads(r["conditions_json"]),
            "actions": json.loads(r["actions_json"]),
        }
        for r in await r_cur.fetchall()
    ]

    # 3. 查詢訂閱清單
    f_cur = await conn.execute(
        """
        SELECT f.feed_url, COALESCE(uf.custom_title, f.title) as title, c.name as category_name
        FROM user_feeds uf
        JOIN feeds f ON uf.feed_id = f.id
        LEFT JOIN categories c ON uf.category_id = c.id
        WHERE uf.user_id = ?
        """,
        (user_id,),
    )
    feeds = [dict(r) for r in await f_cur.fetchall()]

    # 4. 查詢個人外掛設定
    p_cur = await conn.execute(
        "SELECT plugin_id, config_json FROM user_plugin_configs WHERE user_id = ?",
        (user_id,),
    )
    plugin_configs = [
        {"plugin_id": r["plugin_id"], "config": json.loads(r["config_json"])}
        for r in await p_cur.fetchall()
    ]

    return BackupEngine.export_user_backup(
        user_id=str(user_id),
        user_settings=settings,
        rules=rules,
        feeds=feeds,
        plugin_configs=plugin_configs,
    )


@router.post("/settings/purge-database")
async def purge_database(
    user: dict = Depends(get_current_user),
) -> dict:
    """徹底清空資料庫所有訂閱、文章、快取與標籤 (Purge all database records & caches with self-healing).

    ⚠️ 刻意不使用 Depends(get_write_db)，因為 write_transaction 的 asyncio.Lock 在整個
    請求 scope 內持有，若在 except 中呼叫 init_db_sync（同步 sqlite3.connect），會因為
    無法取得 SQLite write lock 而死鎖 60 秒。改為手動 async with 確保 lock 在 self-healing
    前已完整釋放。
    """
    is_admin = bool(user.get("is_admin", False))
    db_mgr = get_db_manager()
    db_path = Path(db_mgr.db_path)
    err_msg: str = ""

    # ── 正常路徑：write_transaction context 完整 exit 後才進入 except ─────────
    try:
        async with db_mgr.write_transaction() as conn:
            await conn.execute("DELETE FROM user_article_states")
            await conn.execute("DELETE FROM article_tags")
            await conn.execute("DELETE FROM articles_hot")
            await conn.execute("DELETE FROM archives_cold")
            await conn.execute("DELETE FROM user_feeds")
            await conn.execute("DELETE FROM feeds")
            await conn.execute("DELETE FROM categories")
            await conn.execute("DELETE FROM tags")
            await conn.execute("DELETE FROM user_rules")
            await conn.execute("DELETE FROM plugins_telemetry")
            try:
                await conn.execute("DELETE FROM assets")
            except Exception as exc:
                logger.debug(f"Non-fatal exception deleting assets during purge: {exc}")
            await conn.commit()
            try:
                await conn.execute("VACUUM")
            except Exception as exc:
                logger.debug(f"Non-fatal exception running VACUUM during purge: {exc}")

        return {
            "status": "success",
            "message": "資料庫與快取已徹底清空",
            "is_admin_purge": True,
        }
    except Exception as exc:
        err_msg = str(exc)
        logger.warning(f"Purge database error ({err_msg}). Attempting self-healing recovery...")

    # ── 到此 write_transaction 的 async with 已完整 exit，write_lock 已釋放 ────
    if not ("malformed" in err_msg.lower() or "corrupt" in err_msg.lower() or "disk image" in err_msg.lower()):
        raise HTTPException(status_code=500, detail=f"資料庫清空失敗: {err_msg}")

    # 用戶資料取自 JWT payload（損壞 DB 無法查詢，直接用記憶體資料）
    saved_user = {
        "id": user["id"],
        "username": user["username"],
        "password_hash": user.get("password_hash", ""),
        "is_admin": 1 if is_admin else 0,
        "api_key": user.get("api_key", secrets.token_hex(16)),
        "settings_json": user.get("settings_json", "{}"),
    }

    # 備份損壞檔案
    try:
        if db_path.exists():
            bak_file = db_path.with_name(f"{db_path.name}.corrupted_bak")
            shutil.copy2(db_path, bak_file)
            logger.info(f"Corrupted DB backed up → {bak_file}")
    except Exception as bak_err:
        logger.debug(f"Backup corrupted file notice: {bak_err}")

    # ⚠️ 刪除損壞原始檔（含 WAL / SHM 殘留），讓 init_db_sync 建立全新乾淨資料庫
    for target in [db_path,
                   db_path.with_name(db_path.name + "-wal"),
                   db_path.with_name(db_path.name + "-shm")]:
        try:
            if target.exists():
                target.unlink()
        except Exception as del_err:
            logger.warning(f"Remove file notice ({target.name}): {del_err}")

    # 同步重建全新 schema（write_lock 已釋放，init_db_sync 可安全取得 SQLite write lock）
    init_db_sync(db_path)

    # 重新注入用戶資料（直接開新連線，不走 write_lock 避免 re-entrant 死鎖）
    new_conn = await aiosqlite.connect(str(db_path), timeout=30.0)
    try:
        new_conn.row_factory = aiosqlite.Row
        await new_conn.execute(
            """
            INSERT OR REPLACE INTO users (id, username, password_hash, is_admin, api_key, settings_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (saved_user["id"], saved_user["username"], saved_user["password_hash"],
             saved_user["is_admin"], saved_user["api_key"], saved_user["settings_json"]),
        )
        await new_conn.commit()
    finally:
        await new_conn.close()

    return {
        "status": "success",
        "message": "已偵測並自動修復壞損磁區，資料庫結構已徹底重建清空！",
        "is_admin_purge": is_admin,
        "self_healed": True,
    }

