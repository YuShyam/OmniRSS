"""過濾與規則管理路由控制器 (Rules Management Router).

This module handles CRUD endpoints for QuiteRSS-style conditional rules.
"""

import json
import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from omnirss.api.dependencies import get_current_user, get_db
from omnirss.api.schemas import (
    RuleCreateRequest,
    RuleResponseDTO,
    RuleUpdateRequest,
)

router = APIRouter(prefix="/api/rules", tags=["Filter Rules"])


@router.get("", response_model=list[RuleResponseDTO])
async def list_user_rules(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> list[RuleResponseDTO]:
    """查詢當前用戶之所有過濾規則 (List User Filter Rules)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        SELECT id, name, sort_order, is_enabled, conditions_json, actions_json, hit_count, created_at
        FROM user_rules
        WHERE user_id = ?
        ORDER BY sort_order ASC, id ASC
        """,
        (user_id,),
    )
    rows = await cur.fetchall()

    results: list[RuleResponseDTO] = []
    for r in rows:
        results.append(
            RuleResponseDTO(
                id=r["id"],
                name=r["name"],
                sort_order=r["sort_order"],
                is_enabled=bool(r["is_enabled"]),
                conditions=json.loads(r["conditions_json"]),
                actions=json.loads(r["actions_json"]),
                hit_count=r["hit_count"],
                created_at=r["created_at"],
            )
        )
    return results


@router.post("", response_model=RuleResponseDTO)
async def create_user_rule(
    req: RuleCreateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> RuleResponseDTO:
    """建立自訂過濾規則 (Create Filter Rule)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        INSERT INTO user_rules (user_id, name, sort_order, is_enabled, conditions_json, actions_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            req.name,
            req.sort_order,
            1 if req.is_enabled else 0,
            json.dumps(req.conditions),
            json.dumps(req.actions),
        ),
    )
    await conn.commit()
    rule_id = cur.lastrowid

    # 讀取完整列
    r_cur = await conn.execute(
        "SELECT id, name, sort_order, is_enabled, conditions_json, actions_json, hit_count, created_at FROM user_rules WHERE id = ?",
        (rule_id,),
    )
    r = await r_cur.fetchone()

    return RuleResponseDTO(
        id=r["id"],
        name=r["name"],
        sort_order=r["sort_order"],
        is_enabled=bool(r["is_enabled"]),
        conditions=json.loads(r["conditions_json"]),
        actions=json.loads(r["actions_json"]),
        hit_count=r["hit_count"],
        created_at=r["created_at"],
    )


@router.put("/{rule_id}", response_model=RuleResponseDTO)
async def update_user_rule(
    rule_id: int,
    req: RuleUpdateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> RuleResponseDTO:
    """修改過濾規則 (Update Filter Rule)."""
    user_id = user["id"]
    cur = await conn.execute(
        "SELECT id, name, sort_order, is_enabled, conditions_json, actions_json, hit_count, created_at FROM user_rules WHERE id = ? AND user_id = ?",
        (rule_id, user_id),
    )
    row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")

    new_name = req.name if req.name is not None else row["name"]
    new_sort = req.sort_order if req.sort_order is not None else row["sort_order"]
    new_enabled = req.is_enabled if req.is_enabled is not None else bool(row["is_enabled"])
    new_conds = json.dumps(req.conditions) if req.conditions is not None else row["conditions_json"]
    new_acts = json.dumps(req.actions) if req.actions is not None else row["actions_json"]

    await conn.execute(
        """
        UPDATE user_rules
        SET name = ?, sort_order = ?, is_enabled = ?, conditions_json = ?, actions_json = ?
        WHERE id = ? AND user_id = ?
        """,
        (new_name, new_sort, 1 if new_enabled else 0, new_conds, new_acts, rule_id, user_id),
    )
    await conn.commit()

    return RuleResponseDTO(
        id=rule_id,
        name=new_name,
        sort_order=new_sort,
        is_enabled=new_enabled,
        conditions=json.loads(new_conds),
        actions=json.loads(new_acts),
        hit_count=row["hit_count"],
        created_at=row["created_at"],
    )


@router.delete("/{rule_id}")
async def delete_user_rule(
    rule_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """刪除過濾規則 (Delete Filter Rule)."""
    user_id = user["id"]
    await conn.execute(
        "DELETE FROM user_rules WHERE id = ? AND user_id = ?",
        (rule_id, user_id),
    )
    await conn.commit()
    return {"message": "Rule successfully deleted"}
