"""外掛管理與遙測監控路由控制器 (Plugins & Telemetry Router).

This module handles listing plugins, viewing circuit breaker states, updating plugin configs,
and executing universal processor plugins against articles.
"""

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Optional
import aiosqlite
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from omnirss.api.dependencies import get_current_admin, get_current_user, get_db, get_write_db
from omnirss.api.schemas import ArticleDetailDTO, PluginConfigUpdateRequest, PluginExecutionLogDTO, PluginTelemetryDTO
from omnirss.core.plugin_manager import get_plugin_manager
from omnirss.sdk.models import ArticleDTO

router = APIRouter(prefix="/api/plugins", tags=["Plugins & Telemetry"])


@router.get("", response_model=list[PluginTelemetryDTO])
async def list_plugins(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> list[PluginTelemetryDTO]:
    """取得所有外掛清單與即時遙測數據 (List Plugins and Telemetry Metrics)."""
    user_id = user["id"]
    mgr = get_plugin_manager()
    manifests = mgr.loaded_manifests if hasattr(mgr, "loaded_manifests") else (mgr.list_manifests() if hasattr(mgr, "list_manifests") else {})

    # 讀取熔斷管理器即時記憶體指標與 DB 歷史指標
    from omnirss.core.circuit_breaker import get_circuit_breaker
    cb = get_circuit_breaker()

    cur = await conn.execute(
        """
        SELECT plugin_id, is_enabled, is_tripped, total_runs, success_runs, error_runs,
               consecutive_errors, avg_duration_ms, last_error_message, last_error_traceback
        FROM plugins_telemetry
        """
    )
    db_metrics = {r["plugin_id"]: dict(r) for r in await cur.fetchall()}

    # 讀取該用戶之個人外掛設定
    cur_u = await conn.execute(
        "SELECT plugin_id, config_json FROM user_plugin_configs WHERE user_id = ?",
        (user_id,),
    )
    user_configs = {r["plugin_id"]: json.loads(r["config_json"]) for r in await cur_u.fetchall()}

    results: list[PluginTelemetryDTO] = []
    for p_id, m in manifests.items():
        metric = db_metrics.get(p_id, {})
        rec = cb.get_or_create_record(p_id)
        u_cfg = user_configs.get(p_id, {})
        
        # 同步向 PluginManager 登記用戶自訂設定
        if u_cfg:
            mgr.set_user_config(user_id, p_id, u_cfg)

        # 雙向融合記憶體實時指標與 DB 指標 (確保零延遲即時呈現)
        total_runs = max(rec.total_runs, metric.get("total_runs", 0))
        success_runs = max(rec.success_runs, metric.get("success_runs", 0))
        error_runs = max(rec.error_runs, metric.get("error_runs", 0))
        consecutive_errors = max(rec.consecutive_errors, metric.get("consecutive_errors", 0))
        avg_duration_ms = rec.avg_duration_ms or metric.get("avg_duration_ms", 0)
        last_error_message = rec.last_error_message or metric.get("last_error_message")
        last_error_traceback = rec.last_error_traceback or metric.get("last_error_traceback")
        is_tripped = rec.is_tripped or bool(metric.get("is_tripped", False))
        is_enabled = rec.is_enabled if metric.get("is_enabled") is None else bool(metric.get("is_enabled"))

        # 同步狀態至記憶體物件，防止後續執行被舊記憶體值覆蓋
        rec.is_enabled = is_enabled
        rec.is_tripped = is_tripped

        results.append(
            PluginTelemetryDTO(
                plugin_id=p_id,
                name=m.name,
                version=m.version,
                slot_type=m.slot_type.value if hasattr(m.slot_type, "value") else str(m.slot_type),
                is_enabled=is_enabled,
                is_tripped=is_tripped,
                total_runs=total_runs,
                success_runs=success_runs,
                error_runs=error_runs,
                consecutive_errors=consecutive_errors,
                avg_duration_ms=avg_duration_ms,
                last_error_message=last_error_message,
                last_error_traceback=last_error_traceback,
                description=m.description,
                author=m.author,
                config_schema=m.config_schema,
                default_config=m.default_config,
                user_config=u_cfg,
                match_patterns=m.match_patterns or [],
                badge=m.badge,
            )
        )
    return results


class PluginToggleRequest(BaseModel):
    """外掛啟用狀態切換請求 (Plugin Toggle Request Payload)."""
    is_enabled: Optional[bool] = None


@router.post("/toggle")
async def toggle_plugin_query(
    plugin_id: str = Query(..., description="外掛識別碼 (Plugin ID)"),
    payload: Optional[PluginToggleRequest] = Body(default=None),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """切換外掛啟用／停用狀態 (Toggle Plugin Enabled State via Query)."""
    return await _toggle_plugin_impl(plugin_id, payload, conn)


@router.post("/{plugin_id:path}/toggle")
async def toggle_plugin_path(
    plugin_id: str,
    payload: Optional[PluginToggleRequest] = Body(default=None),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """切換外掛啟用／停用狀態 (Toggle Plugin Enabled State via Path)."""
    return await _toggle_plugin_impl(plugin_id, payload, conn)


async def _toggle_plugin_impl(
    plugin_id: str,
    payload: Optional[PluginToggleRequest],
    conn: aiosqlite.Connection,
) -> dict:
    cur = await conn.execute(
        "SELECT is_enabled FROM plugins_telemetry WHERE plugin_id = ?",
        (plugin_id,),
    )
    row = await cur.fetchone()
    current_enabled = bool(row["is_enabled"]) if row else True
    new_enabled = payload.is_enabled if (payload and payload.is_enabled is not None) else (not current_enabled)

    await conn.execute(
        """
        INSERT INTO plugins_telemetry (plugin_id, is_enabled)
        VALUES (?, ?)
        ON CONFLICT(plugin_id) DO UPDATE SET is_enabled = excluded.is_enabled
        """,
        (plugin_id, 1 if new_enabled else 0),
    )
    await conn.commit()

    # 同步熔斷器狀態
    from omnirss.core.circuit_breaker import get_circuit_breaker
    cb = get_circuit_breaker()
    record = cb.get_or_create_record(plugin_id)
    if record:
        record.is_enabled = new_enabled

    return {"plugin_id": plugin_id, "is_enabled": new_enabled}


@router.post("/{plugin_id:path}/reset-circuit")
async def reset_plugin_circuit(
    plugin_id: str,
    admin: dict = Depends(get_current_admin),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """手動重置外掛熔斷器保護 (Reset Plugin Circuit Breaker)."""
    await conn.execute(
        """
        UPDATE plugins_telemetry
        SET is_tripped = 0, consecutive_errors = 0, last_error_message = NULL
        WHERE plugin_id = ?
        """,
        (plugin_id,),
    )
    await conn.commit()
    return {"plugin_id": plugin_id, "message": "Circuit breaker successfully reset"}


@router.get("/{plugin_id:path}/config")
async def get_plugin_config(
    plugin_id: str,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """讀取外掛目前生效之個人設定 (Get User Plugin Config)."""
    user_id = user["id"]
    cur = await conn.execute(
        "SELECT config_json FROM user_plugin_configs WHERE user_id = ? AND plugin_id = ?",
        (user_id, plugin_id),
    )
    row = await cur.fetchone()
    config = json.loads(row["config_json"]) if row else {}
    return {"plugin_id": plugin_id, "config": config}


@router.put("/{plugin_id:path}/config")
async def update_plugin_config(
    plugin_id: str,
    req: PluginConfigUpdateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """更新使用者外掛私有設定 (Update User Plugin Config)."""
    user_id = user["id"]
    mgr = get_plugin_manager()
    mgr.set_user_config(user_id, plugin_id, req.config)

    await conn.execute(
        """
        INSERT INTO user_plugin_configs (user_id, plugin_id, config_json)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, plugin_id) DO UPDATE SET
            config_json = excluded.config_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, plugin_id, json.dumps(req.config)),
    )
    await conn.commit()
    return {"plugin_id": plugin_id, "message": "Plugin config updated successfully", "config": req.config}


@router.post("/{plugin_id:path}/execute-article/{article_id}", response_model=ArticleDetailDTO)
async def execute_article_processor_plugin(
    plugin_id: str,
    article_id: int,
    action_param: Optional[str] = Query(None),
    preset_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> ArticleDetailDTO:
    """通用文章外掛執行插槽 (Universal Article Processor Plugin Dispatcher Slot)."""
    user_id = user["id"]
    mgr = get_plugin_manager()

    if plugin_id not in mgr.loaded_plugins:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin '{plugin_id}' is not loaded or does not exist.",
        )

    # 同步該用戶在外掛的私有設定 (確保 DB 與 Memory 同步)
    cur_u = await conn.execute(
        "SELECT config_json FROM user_plugin_configs WHERE user_id = ? AND plugin_id = ?",
        (user_id, plugin_id),
    )
    row_u = await cur_u.fetchone()
    if row_u and row_u["config_json"]:
        try:
            u_cfg = json.loads(row_u["config_json"])
            mgr.set_user_config(user_id, plugin_id, u_cfg)
        except Exception as exc:
            logger.warning(f"Failed to parse user plugin config for {plugin_id}: {exc}")

    # 1. 抓取文章詳情 (含動態欄位自癒防衛)
    query_sql = """
        SELECT a.id, a.feed_id, a.url, a.title, a.author, a.snippet, a.content_html, a.content_text,
               a.ai_summary, a.published_at, a.cover_image_url,
               COALESCE(uf.custom_title, f.title) as feed_title,
               uf.category_id, c.name as category_name,
               COALESCE(uas.is_read, 0) as is_read,
               COALESCE(uas.is_starred, 0) as is_starred
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
            from omnirss.core.database import get_db_manager
            db_mgr = get_db_manager()
            try:
                async with db_mgr.write_transaction() as write_conn:
                    await write_conn.execute("ALTER TABLE articles_hot ADD COLUMN ai_summary TEXT;")
                    await write_conn.commit()
            except Exception as alter_err:
                logger.debug(f"Articles_hot ai_summary column already exists or alter skipped: {alter_err}")
            cur = await conn.execute(query_sql, (article_id, user_id))
        else:
            raise

    row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found.")

    # 2. 轉換為 ArticleDTO (傳遞 ai_summary=None 以強制依照最新設定重新生成)
    article_dto = ArticleDTO(
        id=row["id"],
        feed_id=row["feed_id"],
        title=row["title"],
        url=row["url"],
        author=row["author"],
        content_html=row["content_html"] or "",
        content_text=row["content_text"] or row["snippet"] or "",
        snippet=row["snippet"] or "",
        cover_image_url=row["cover_image_url"],
        ai_summary=None,
        published_at=row["published_at"],
    )

    # 2.5 檢查外掛是否被停用
    from omnirss.core.circuit_breaker import get_circuit_breaker
    cb = get_circuit_breaker()
    rec = cb.get_or_create_record(plugin_id)
    if not rec.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"外掛「{plugin_id}」目前已停用，請先於外掛管理面板中開啟啟用。",
        )

    # 3. 執行外掛 (支援傳入指定 action_param / preset_id 並記錄日誌)
    effective_param = (action_param or preset_id or "").strip() or None
    if effective_param:
        if not re.match(r"^[a-zA-Z0-9_\-]+$", effective_param):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid action parameter format. Only alphanumeric, dashes and underscores are allowed.",
            )
    extra_cfg = {"prompt_style": effective_param, "selected_preset": effective_param} if effective_param else None
    try:
        processed_dto = await mgr.execute_processor(
            plugin_id=plugin_id,
            article=article_dto,
            user_id=user_id,
            extra_config=extra_cfg,
            action_param=effective_param,
            trigger_source="manual",
        )
    except Exception as exc:
        logger.warning(f"Plugin execution failed for '{plugin_id}': {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    if processed_dto is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Plugin '{plugin_id}' returned no output for article {article_id}",
        )

    # 4. 若外掛更新了內容或摘要，同步存入資料庫 (使用獨立局部 write_transaction 避免長事務與鎖競爭)
    has_summary_update = processed_dto.ai_summary is not None and processed_dto.ai_summary != row["ai_summary"]
    has_content_update = (
        bool(processed_dto.content_html and processed_dto.content_html != row["content_html"])
        or bool(processed_dto.content_text and processed_dto.content_text != row["content_text"])
    )

    if has_summary_update or has_content_update:
        from omnirss.core.database import get_db_manager
        db_mgr = get_db_manager()
        async with db_mgr.write_transaction() as write_conn:
            if has_summary_update and has_content_update:
                await write_conn.execute(
                    "UPDATE articles_hot SET ai_summary = ?, content_html = ?, content_text = ? WHERE id = ?",
                    (
                        processed_dto.ai_summary,
                        processed_dto.content_html or row["content_html"],
                        processed_dto.content_text or row["content_text"],
                        article_id,
                    ),
                )
            elif has_summary_update:
                await write_conn.execute(
                    "UPDATE articles_hot SET ai_summary = ? WHERE id = ?",
                    (processed_dto.ai_summary, article_id),
                )
            elif has_content_update:
                await write_conn.execute(
                    "UPDATE articles_hot SET content_html = ?, content_text = ? WHERE id = ?",
                    (
                        processed_dto.content_html or row["content_html"],
                        processed_dto.content_text or row["content_text"],
                        article_id,
                    ),
                )
    read_bool = bool(row["is_read"])
    published_val = row["published_at"]
    if isinstance(published_val, str):
        try:
            published_val = datetime.fromisoformat(published_val)
        except Exception as exc:
            logger.debug(f"Failed to parse article published_at '{published_val}': {exc}")
            published_val = datetime.now(timezone.utc)
    elif not published_val:
        published_val = datetime.now(timezone.utc)

    # 5. 計算完整套用外掛清單與標籤 (Compute applied_plugins and fetch tags for complete DTO)
    from omnirss.api.routers.articles import detect_applied_plugins

    final_html = processed_dto.content_html or row["content_html"] or ""
    final_summary = processed_dto.ai_summary if processed_dto.ai_summary is not None else row["ai_summary"]
    applied_plugs = detect_applied_plugins(row["url"] or "", final_html, final_summary)
    if plugin_id not in applied_plugs and (processed_dto.content_html or processed_dto.ai_summary):
        applied_plugs.append(plugin_id)

    # 查詢文章標籤
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
        snippet=row["snippet"] or "",
        content_html=final_html,
        content_text=processed_dto.content_text or row["content_text"] or row["snippet"] or "",
        ai_summary=final_summary,
        cover_image_url=row["cover_image_url"],
        published_at=published_val,
        is_read=read_bool,
        is_unread=not read_bool,
        is_starred=bool(row["is_starred"]),
        highlight_color=row["highlight_color"] if "highlight_color" in row.keys() else None,
        tags=tags,
        applied_plugins=applied_plugs,
    )


@router.get("/logs", response_model=list[PluginExecutionLogDTO])
async def get_plugin_logs_query(
    plugin_id: str = Query(..., description="外掛識別碼 (Plugin ID)"),
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> list[PluginExecutionLogDTO]:
    """取得指定外掛之獨立執行歷史日誌清單 (Get Plugin Execution Logs via Query)."""
    return await _get_plugin_logs_impl(plugin_id, limit, conn)


@router.get("/{plugin_id:path}/logs", response_model=list[PluginExecutionLogDTO])
async def get_plugin_logs_path(
    plugin_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> list[PluginExecutionLogDTO]:
    """取得指定外掛之獨立執行歷史日誌清單 (Get Plugin Execution Logs via Path Compatibility)."""
    return await _get_plugin_logs_impl(plugin_id, limit, conn)


async def _get_plugin_logs_impl(
    plugin_id: str,
    limit: int,
    conn: aiosqlite.Connection,
) -> list[PluginExecutionLogDTO]:
    cur = await conn.execute(
        """
        SELECT id, plugin_id, user_id, article_id, article_title,
               trigger_source, action_param, status, duration_ms,
               output_preview, error_message, error_traceback, executed_at
        FROM plugin_execution_logs
        WHERE plugin_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (plugin_id, limit),
    )
    rows = await cur.fetchall()
    return [
        PluginExecutionLogDTO(
            id=r["id"],
            plugin_id=r["plugin_id"],
            user_id=r["user_id"],
            article_id=r["article_id"],
            article_title=r["article_title"],
            trigger_source=r["trigger_source"],
            action_param=r["action_param"],
            status=r["status"],
            duration_ms=r["duration_ms"],
            output_preview=r["output_preview"],
            error_message=r["error_message"],
            error_traceback=r["error_traceback"],
            executed_at=str(r["executed_at"]),
        )
        for r in rows
    ]


@router.delete("/logs/clear")
async def clear_plugin_logs(
    plugin_id: str = Query(..., description="外掛識別碼 (Plugin ID)"),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict[str, Any]:
    """一鍵清空指定外掛之所有執行日誌與遙測執行記錄 (Clear Plugin Execution Logs via Query)."""
    return await _clear_plugin_logs_impl(plugin_id, conn)


@router.delete("/{plugin_id:path}/logs")
async def clear_plugin_logs_path(
    plugin_id: str,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict[str, Any]:
    """一鍵清空指定外掛之所有執行日誌與遙測執行記錄 (Clear Plugin Execution Logs via Path Compatibility)."""
    return await _clear_plugin_logs_impl(plugin_id, conn)


async def _clear_plugin_logs_impl(plugin_id: str, conn: aiosqlite.Connection) -> dict[str, Any]:
    # 1. 清空執行歷史日誌明細
    await conn.execute("DELETE FROM plugin_execution_logs WHERE plugin_id = ?", (plugin_id,))

    # 2. 清空並重置遙測統計指標
    await conn.execute(
        """
        UPDATE plugins_telemetry SET
            total_runs = 0,
            success_runs = 0,
            error_runs = 0,
            consecutive_errors = 0,
            last_duration_ms = 0,
            avg_duration_ms = 0,
            last_error_message = NULL,
            last_error_traceback = NULL,
            last_run_at = NULL
        WHERE plugin_id = ?
        """,
        (plugin_id,),
    )
    await conn.commit()

    # 3. 同步重置記憶體熔斷器與遙測計數器
    try:
        from omnirss.core.circuit_breaker import get_circuit_breaker
        cb = get_circuit_breaker()
        rec = cb.get_or_create_record(plugin_id)
        rec.total_runs = 0
        rec.success_runs = 0
        rec.error_runs = 0
        rec.consecutive_errors = 0
        rec.last_duration_ms = 0
        rec.avg_duration_ms = 0
        rec.last_error_message = None
        rec.last_error_traceback = None
        rec.last_run_at = None
    except Exception as exc:
        logger.warning(f"Failed to reset circuit breaker memory record for {plugin_id}: {exc}")

    return {"plugin_id": plugin_id, "message": "Plugin logs and execution telemetry cleared successfully."}


@router.post("/batch-apply")
async def batch_apply_plugin(
    plugin_id: str = Query(..., description="外掛識別碼 (Plugin ID)"),
    limit: Optional[int] = Query(None, description="可選之處理文章上限 (預設全量無上限)"),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict[str, Any]:
    """將指定外掛批次重新套用至現存符合網址模式之文章 (Batch Apply Plugin to Existing Articles)."""
    mgr = get_plugin_manager()
    manifest = mgr.get_manifest(plugin_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Plugin manifest not found")

    from omnirss.core.pattern_matcher import match_url_patterns
    patterns = list(manifest.match_patterns or ["*"])
    
    # 特殊擴充：若為 Yahoo 外掛，額外擴充 *yahoo* 特徵相容
    if "yahoo" in plugin_id.lower() and "*yahoo*" not in patterns:
        patterns.append("*yahoo*")

    sql = """
        SELECT a.id, a.feed_id, a.entry_hash, a.title, a.url, a.author, a.content_html, a.content_text, a.snippet, a.ai_summary, a.published_at, f.feed_url as feed_url
        FROM articles_hot a
        LEFT JOIN feeds f ON a.feed_id = f.id
        ORDER BY a.id DESC
    """
    params = []
    if limit and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)

    cur = await conn.execute(sql, tuple(params))
    rows = await cur.fetchall()

    processed_count = 0
    updated_count = 0
    pending_updates: list[tuple[str, str, str, Optional[str], int]] = []

    from omnirss.core.database import get_db_manager
    db_mgr = get_db_manager()

    for r in rows:
        url = r["url"] or ""
        feed_url = r["feed_url"] or ""
        content_html = r["content_html"] or ""
        
        # 嘗試匹配文章 URL 或 Feed URL
        matches_article = match_url_patterns(url, patterns) if (patterns and url) else False
        matches_feed = match_url_patterns(feed_url, patterns) if (patterns and feed_url) else False

        if patterns and not (matches_article or matches_feed):
            continue

        dto = ArticleDTO(
            id=r["id"],
            feed_id=r["feed_id"],
            guid=r["entry_hash"] or "",
            title=r["title"],
            url=url,
            feed_url=feed_url,
            author=r["author"],
            content_html=content_html,
            content_text=r["content_text"] or "",
            snippet=r["snippet"] or "",
            ai_summary=r["ai_summary"] or "",
            published_at=r["published_at"] or datetime.now(timezone.utc),
        )

        try:
            processed_dto = await mgr.execute_processor(
                plugin_id=plugin_id,
                article=dto,
                user_id=user["id"],
                trigger_source="manual",
            )
            processed_count += 1
            
            if processed_dto:
                new_html = processed_dto.content_html or r["content_html"]
                new_text = processed_dto.content_text or r["content_text"]
                new_snippet = processed_dto.snippet or r["snippet"]
                new_ai_summary = processed_dto.ai_summary if processed_dto.ai_summary is not None else r["ai_summary"]

                is_changed = (
                    new_html != r["content_html"]
                    or new_text != r["content_text"]
                    or new_snippet != r["snippet"]
                    or new_ai_summary != r["ai_summary"]
                )

                if is_changed:
                    pending_updates.append((
                        new_html,
                        new_text,
                        new_snippet,
                        new_ai_summary,
                        r["id"],
                    ))
                    updated_count += 1
        except Exception as err:
            logger.warning(f"Batch apply plugin warning for article {r['id']}: {err}")

    # 批次原子寫入，大幅提升速度並避免鎖爭搶
    if pending_updates:
        async with db_mgr.write_transaction() as wconn:
            for upd in pending_updates:
                await wconn.execute(
                    "UPDATE articles_hot SET content_html = ?, content_text = ?, snippet = ?, ai_summary = ? WHERE id = ?",
                    upd,
                )
            await wconn.commit()

    return {
        "plugin_id": plugin_id,
        "processed_count": processed_count,
        "updated_count": updated_count,
        "message": f"成功掃描並處理 {processed_count} 篇文章，已更新 {updated_count} 篇",
    }


