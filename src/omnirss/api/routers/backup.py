"""資料備份與 OPML 匯出入路由控制器 (Backup & OPML Router).

This module handles OPML 2.0 import/export and sanitized JSON backup/restore.
"""

import json
import aiosqlite
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from omnirss.api.dependencies import get_current_user, get_db
from omnirss.core.backup_engine import BackupEngine

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
    return {"imported_count": imported_count, "message": "OPML imported successfully"}


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
