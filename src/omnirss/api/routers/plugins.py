"""外掛管理與遙測監控路由控制器 (Plugins & Telemetry Router).

This module handles listing plugins, viewing circuit breaker states, and updating plugin configs.
"""

import json
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from omnirss.api.dependencies import get_current_admin, get_current_user, get_db
from omnirss.api.schemas import PluginConfigUpdateRequest, PluginTelemetryDTO
from omnirss.core.plugin_manager import get_plugin_manager

router = APIRouter(prefix="/api/plugins", tags=["Plugins & Telemetry"])


@router.get("", response_model=list[PluginTelemetryDTO])
async def list_plugins(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> list[PluginTelemetryDTO]:
    """取得所有外掛清單與即時遙測數據 (List Plugins and Telemetry Metrics)."""
    mgr = get_plugin_manager()
    manifests = mgr.list_manifests()

    cur = await conn.execute(
        """
        SELECT plugin_id, is_enabled, is_tripped, total_runs, success_runs, error_runs,
               consecutive_errors, avg_duration_ms, last_error_message
        FROM plugins_telemetry
        """
    )
    db_metrics = {r["plugin_id"]: dict(r) for r in await cur.fetchall()}

    results: list[PluginTelemetryDTO] = []
    for p_id, m in manifests.items():
        metric = db_metrics.get(p_id, {})
        results.append(
            PluginTelemetryDTO(
                plugin_id=p_id,
                name=m.name,
                version=m.version,
                slot_type=m.slot_type.value if hasattr(m.slot_type, "value") else str(m.slot_type),
                is_enabled=bool(metric.get("is_enabled", True)),
                is_tripped=bool(metric.get("is_tripped", False)),
                total_runs=metric.get("total_runs", 0),
                success_runs=metric.get("success_runs", 0),
                error_runs=metric.get("error_runs", 0),
                consecutive_errors=metric.get("consecutive_errors", 0),
                avg_duration_ms=metric.get("avg_duration_ms", 0),
                last_error_message=metric.get("last_error_message"),
            )
        )
    return results


@router.post("/{plugin_id}/toggle")
async def toggle_plugin(
    plugin_id: str,
    admin: dict = Depends(get_current_admin),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """切換外掛啟用／停用狀態 (Toggle Plugin Enabled State)."""
    cur = await conn.execute(
        "SELECT is_enabled FROM plugins_telemetry WHERE plugin_id = ?",
        (plugin_id,),
    )
    row = await cur.fetchone()
    current_enabled = bool(row["is_enabled"]) if row else True
    new_enabled = not current_enabled

    await conn.execute(
        """
        INSERT INTO plugins_telemetry (plugin_id, is_enabled)
        VALUES (?, ?)
        ON CONFLICT(plugin_id) DO UPDATE SET is_enabled = excluded.is_enabled
        """,
        (plugin_id, 1 if new_enabled else 0),
    )
    await conn.commit()
    return {"plugin_id": plugin_id, "is_enabled": new_enabled}


@router.post("/{plugin_id}/reset-circuit")
async def reset_plugin_circuit(
    plugin_id: str,
    admin: dict = Depends(get_current_admin),
    conn: aiosqlite.Connection = Depends(get_db),
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


@router.get("/{plugin_id}/config")
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


@router.put("/{plugin_id}/config")
async def update_plugin_config(
    plugin_id: str,
    req: PluginConfigUpdateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """更新使用者外掛私有設定 (Update User Plugin Config)."""
    user_id = user["id"]
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
    return {"plugin_id": plugin_id, "message": "Plugin config updated successfully"}
