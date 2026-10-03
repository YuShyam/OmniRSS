"""過濾與規則管理路由控制器 (Rules Management Router).

This module handles CRUD endpoints for QuiteRSS-style conditional rules.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Optional
import aiosqlite
from fastapi import APIRouter, Body, Depends, HTTPException, status

logger = logging.getLogger(__name__)

from omnirss.api.dependencies import get_current_user, get_db, get_write_db
from omnirss.api.schemas import (
    RuleCreateRequest,
    RuleResponseDTO,
    RuleUpdateRequest,
)
from omnirss.core.rule_engine import (
    ConditionGroup,
    MatchMode,
    RuleAction,
    RuleActionType,
    RuleCondition,
    RuleDef,
    RuleEngine,
    RuleField,
    RuleOperator,
    RuleScopeType,
)
from omnirss.sdk.models import ArticleDTO

router = APIRouter(prefix="/api/rules", tags=["Filter Rules"])


def parse_db_rule_row(r: Any) -> RuleDef:
    """防衛性解析資料庫儲存之規則資料列為 RuleDef 物件 (Parse DB Row to RuleDef)."""
    scope_type_str = r["scope_type"] if "scope_type" in r.keys() and r["scope_type"] else "all"
    scope_cat_id = r["scope_category_id"] if "scope_category_id" in r.keys() else None
    
    scope_feeds_raw = r["scope_feed_ids_json"] if "scope_feed_ids_json" in r.keys() and r["scope_feed_ids_json"] else "[]"
    try:
        scope_feed_ids = [int(x) for x in json.loads(scope_feeds_raw)]
    except Exception as exc:
        logger.warning(f"Failed to parse scope_feed_ids_json: {exc}")
        scope_feed_ids = []

    match_mode_str = r["match_mode"] if "match_mode" in r.keys() and r["match_mode"] else "all"

    # 解析 condition_groups 與 conditions
    condition_groups: list[ConditionGroup] = []
    groups_raw = r["condition_groups_json"] if "condition_groups_json" in r.keys() and r["condition_groups_json"] else "[]"
    try:
        groups_data = json.loads(groups_raw)
        if isinstance(groups_data, list):
            for g in groups_data:
                if isinstance(g, dict):
                    g_mode = g.get("match_mode", "all")
                    g_conds_raw = g.get("conditions") or g.get("rules") or []
                    g_conds: list[RuleCondition] = []
                    for c in g_conds_raw:
                        if isinstance(c, dict):
                            f = c.get("field", "title")
                            if f in ("content_text",):
                                f = "content"
                            elif f in ("link",):
                                f = "url"
                            elif f in ("feed",):
                                f = "feed_title"
                            g_conds.append(
                                RuleCondition(
                                    field=RuleField(f),
                                    operator=RuleOperator(c.get("operator", "contains")),
                                    value=str(c.get("value", "")),
                                    case_sensitive=bool(c.get("case_sensitive", False)),
                                )
                            )
                    condition_groups.append(ConditionGroup(match_mode=MatchMode(g_mode), conditions=g_conds))
    except Exception as exc:
        logger.warning(f"Failed to parse condition_groups_json: {exc}")
        condition_groups = []

    # 兼容舊版平坦 conditions_json
    conditions_flat: list[RuleCondition] = []
    conds_raw = r["conditions_json"] if "conditions_json" in r.keys() and r["conditions_json"] else "[]"
    try:
        conds_data = json.loads(conds_raw)
        if isinstance(conds_data, list):
            for c in conds_data:
                if isinstance(c, str):
                    c = {"field": "title", "operator": "contains", "value": c}
                if isinstance(c, dict):
                    f = c.get("field", "title")
                    if f in ("content_text",):
                        f = "content"
                    elif f in ("link",):
                        f = "url"
                    elif f in ("feed",):
                        f = "feed_title"
                    conditions_flat.append(
                        RuleCondition(
                            field=RuleField(f),
                            operator=RuleOperator(c.get("operator", "contains")),
                            value=str(c.get("value", "")),
                            case_sensitive=bool(c.get("case_sensitive", False)),
                        )
                    )
        elif isinstance(conds_data, dict):
            inner_conds = conds_data.get("rules") or conds_data.get("conditions") or []
            for c in inner_conds:
                if isinstance(c, dict):
                    f = c.get("field", "title")
                    conditions_flat.append(
                        RuleCondition(
                            field=RuleField(f),
                            operator=RuleOperator(c.get("operator", "contains")),
                            value=str(c.get("value", "")),
                            case_sensitive=bool(c.get("case_sensitive", False)),
                        )
                    )
    except Exception as exc:
        logger.warning(f"Failed to parse conditions_json: {exc}")

    # 解析 actions
    actions: list[RuleAction] = []
    acts_raw = r["actions_json"] if "actions_json" in r.keys() and r["actions_json"] else "[]"
    try:
        acts_data = json.loads(acts_raw)
        if isinstance(acts_data, str):
            acts_data = [{"action": acts_data, "params": {}}]
        if isinstance(acts_data, list):
            for a in acts_data:
                if isinstance(a, str):
                    a = {"action": a, "params": {}}
                if isinstance(a, dict):
                    act_type = a.get("action") or a.get("action_type") or "mark_read"
                    params = a.get("params") or a.get("parameters") or {}
                    actions.append(RuleAction(action=RuleActionType(act_type), params=params))
    except Exception as exc:
        logger.warning(f"Failed to parse actions_json: {exc}")

    return RuleDef(
        id=str(r["id"]),
        rule_name=r["name"],
        priority=r["sort_order"] if "sort_order" in r.keys() else 0,
        is_active=bool(r["is_enabled"]) if "is_enabled" in r.keys() else True,
        scope_type=RuleScopeType(scope_type_str),
        scope_category_id=scope_cat_id,
        scope_feed_ids=scope_feed_ids,
        match_mode=MatchMode(match_mode_str),
        conditions=conditions_flat,
        condition_groups=condition_groups,
        actions=actions,
    )


@router.get("/export")
async def export_user_rules(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict[str, Any]:
    """匯出當前用戶的所有過濾規則為 JSON 格式 (Export User Rules to JSON with Semantic Anchors)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        SELECT name, sort_order, is_enabled,
               COALESCE(scope_type, 'all') as scope_type,
               scope_category_id,
               COALESCE(scope_feed_ids_json, '[]') as scope_feed_ids_json,
               COALESCE(match_mode, 'all') as match_mode,
               COALESCE(condition_groups_json, '[]') as condition_groups_json,
               conditions_json, actions_json
        FROM user_rules
        WHERE user_id = ?
        ORDER BY sort_order ASC, id ASC
        """,
        (user_id,),
    )
    rows = await cur.fetchall()

    # 預先載入分類與頻道名稱對照表（注入語意錨點，支援跨環境精準還原）
    cat_cur = await conn.execute("SELECT id, name FROM categories WHERE user_id = ?", (user_id,))
    cats_map = {row["id"]: row["name"] for row in await cat_cur.fetchall()}

    feed_cur = await conn.execute(
        """
        SELECT f.id, f.feed_url, COALESCE(uf.custom_title, f.title) as title
        FROM feeds f
        LEFT JOIN user_feeds uf ON f.id = uf.feed_id AND uf.user_id = ?
        """,
        (user_id,),
    )
    feeds_map = {row["id"]: (row["feed_url"], row["title"]) for row in await feed_cur.fetchall()}

    rules_data = []
    for r in rows:
        scope_cat_id = r["scope_category_id"]
        scope_cat_name = cats_map.get(scope_cat_id) if scope_cat_id else None

        scope_feed_ids = json.loads(r["scope_feed_ids_json"]) if r["scope_feed_ids_json"] else []
        scope_feed_urls = []
        scope_feed_titles = []
        for fid in scope_feed_ids:
            if fid in feeds_map:
                f_url, f_title = feeds_map[fid]
                if f_url:
                    scope_feed_urls.append(f_url)
                if f_title:
                    scope_feed_titles.append(f_title)

        rules_data.append({
            "name": r["name"],
            "sort_order": r["sort_order"],
            "is_enabled": bool(r["is_enabled"]),
            "scope_type": r["scope_type"],
            "scope_category_id": scope_cat_id,
            "scope_category_name": scope_cat_name,
            "scope_feed_ids": scope_feed_ids,
            "scope_feed_urls": scope_feed_urls,
            "scope_feed_titles": scope_feed_titles,
            "match_mode": r["match_mode"],
            "conditions": json.loads(r["conditions_json"]) if r["conditions_json"] else [],
            "condition_groups": json.loads(r["condition_groups_json"]) if r["condition_groups_json"] else [],
            "actions": json.loads(r["actions_json"]) if r["actions_json"] else [],
        })

    return {
        "version": "1.1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "total_rules": len(rules_data),
        "rules": rules_data,
    }


@router.post("/import")
async def import_user_rules(
    payload: dict[str, Any] = Body(...),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict[str, Any]:
    """匯入過濾規則並自動重配語意 ID (Import Filter Rules with Smart ID Resolution)."""
    user_id = user["id"]
    raw_rules = payload.get("rules")
    if raw_rules is None and isinstance(payload, list):
        raw_rules = payload
    elif raw_rules is None and ("conditions" in payload or "condition_groups" in payload):
        raw_rules = [payload]

    if not isinstance(raw_rules, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="匯入資料格式錯誤，必須包含 'rules' 清單或規則陣列",
        )

    mode = payload.get("mode", "merge")
    if mode == "replace":
        await conn.execute("DELETE FROM user_rules WHERE user_id = ?", (user_id,))

    # 預先讀取當前使用者的分類與頻道以供精準語意解析
    cat_cur = await conn.execute("SELECT id, name FROM categories WHERE user_id = ?", (user_id,))
    existing_cats_by_name = {row["name"].strip().lower(): row["id"] for row in await cat_cur.fetchall()}

    feed_cur = await conn.execute(
        """
        SELECT f.id, f.feed_url, COALESCE(uf.custom_title, f.title) as title
        FROM feeds f
        LEFT JOIN user_feeds uf ON f.id = uf.feed_id AND uf.user_id = ?
        """,
        (user_id,),
    )
    feed_rows = await feed_cur.fetchall()
    existing_feeds_by_url = {row["feed_url"].strip().lower(): row["id"] for row in feed_rows if row["feed_url"]}
    existing_feeds_by_title = {row["title"].strip().lower(): row["id"] for row in feed_rows if row["title"]}
    existing_feed_ids_set = {row["id"] for row in feed_rows}

    imported_count = 0
    for r in raw_rules:
        if not isinstance(r, dict):
            continue
        name = r.get("name") or r.get("rule_name") or f"匯入規則 #{imported_count + 1}"
        sort_order = int(r.get("sort_order") or r.get("priority") or 10)
        is_enabled = 1 if r.get("is_enabled", True) else 0
        scope_type = r.get("scope_type") or r.get("scope") or "all"
        scope_category_id = r.get("scope_category_id")
        scope_category_name = r.get("scope_category_name")
        scope_feed_ids = r.get("scope_feed_ids") or []
        scope_feed_urls = r.get("scope_feed_urls") or []
        scope_feed_titles = r.get("scope_feed_titles") or []
        match_mode = r.get("match_mode", "all")
        cond_groups = r.get("condition_groups") or []
        conds = r.get("conditions") or []
        actions = r.get("actions") or []

        # 1. 智慧解析分類 ID
        if scope_type == "category":
            resolved_cat_id = None
            if scope_category_name and scope_category_name.strip().lower() in existing_cats_by_name:
                resolved_cat_id = existing_cats_by_name[scope_category_name.strip().lower()]
            elif scope_category_id and scope_category_id in existing_cats_by_name.values():
                resolved_cat_id = scope_category_id
            scope_category_id = resolved_cat_id

        # 2. 智慧解析頻道 ID
        if scope_type == "feeds":
            resolved_feed_ids = []
            # 優先依據 feed_url 精準匹配
            if scope_feed_urls:
                for u in scope_feed_urls:
                    if u and u.strip().lower() in existing_feeds_by_url:
                        fid = existing_feeds_by_url[u.strip().lower()]
                        if fid not in resolved_feed_ids:
                            resolved_feed_ids.append(fid)
            # 次選依據 feed_title 匹配
            if not resolved_feed_ids and scope_feed_titles:
                for t_name in scope_feed_titles:
                    if t_name and t_name.strip().lower() in existing_feeds_by_title:
                        fid = existing_feeds_by_title[t_name.strip().lower()]
                        if fid not in resolved_feed_ids:
                            resolved_feed_ids.append(fid)
            # 若都沒有語意欄位（舊版匯出檔），校驗原有 ID 是否在現有資料庫存在
            if not resolved_feed_ids and scope_feed_ids:
                resolved_feed_ids = [fid for fid in scope_feed_ids if fid in existing_feed_ids_set]

            scope_feed_ids = resolved_feed_ids

        if not cond_groups and conds:
            cond_list = conds if isinstance(conds, list) else (conds.get("rules") or conds.get("conditions") or [])
            cond_groups = [{"match_mode": match_mode, "conditions": cond_list}]

        await conn.execute(
            """
            INSERT INTO user_rules (
                user_id, name, sort_order, is_enabled,
                scope_type, scope_category_id, scope_feed_ids_json,
                match_mode, condition_groups_json, conditions_json, actions_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                name,
                sort_order,
                is_enabled,
                scope_type,
                scope_category_id,
                json.dumps(scope_feed_ids),
                match_mode,
                json.dumps(cond_groups),
                json.dumps(conds),
                json.dumps(actions),
            ),
        )
        imported_count += 1

    await conn.commit()
    return {
        "success": True,
        "imported_count": imported_count,
        "mode": mode,
        "message": f"成功匯入 {imported_count} 條過濾規則",
    }


@router.get("", response_model=list[RuleResponseDTO])
async def list_user_rules(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> list[RuleResponseDTO]:
    """查詢當前用戶之所有過濾規則 (List User Filter Rules)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        SELECT id, name, sort_order, is_enabled,
               COALESCE(scope_type, 'all') as scope_type,
               scope_category_id,
               COALESCE(scope_feed_ids_json, '[]') as scope_feed_ids_json,
               COALESCE(match_mode, 'all') as match_mode,
               COALESCE(condition_groups_json, '[]') as condition_groups_json,
               conditions_json, actions_json, hit_count, created_at
        FROM user_rules
        WHERE user_id = ?
        ORDER BY sort_order ASC, id ASC
        """,
        (user_id,),
    )
    rows = await cur.fetchall()

    results: list[RuleResponseDTO] = []
    for r in rows:
        conds_val = json.loads(r["conditions_json"]) if r["conditions_json"] else []
        cond_groups_val = json.loads(r["condition_groups_json"]) if r["condition_groups_json"] else []
        scope_feeds_val = json.loads(r["scope_feed_ids_json"]) if r["scope_feed_ids_json"] else []

        results.append(
            RuleResponseDTO(
                id=r["id"],
                name=r["name"],
                sort_order=r["sort_order"],
                is_enabled=bool(r["is_enabled"]),
                scope_type=r["scope_type"],
                scope_category_id=r["scope_category_id"],
                scope_feed_ids=scope_feeds_val,
                match_mode=r["match_mode"],
                conditions=conds_val,
                condition_groups=cond_groups_val,
                actions=json.loads(r["actions_json"]) if r["actions_json"] else [],
                hit_count=r["hit_count"],
                created_at=r["created_at"],
            )
        )
    return results


@router.post("", response_model=RuleResponseDTO)
async def create_user_rule(
    req: RuleCreateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> RuleResponseDTO:
    """建立自訂過濾規則 (Create Filter Rule)."""
    user_id = user["id"]

    cond_groups = req.condition_groups or []
    conds = req.conditions or []

    # 若未傳入 condition_groups 但有 conditions，自動包裝
    if not cond_groups and conds:
        cond_list = conds if isinstance(conds, list) else (conds.get("rules") or conds.get("conditions") or [])
        cond_groups = [{"match_mode": req.match_mode, "conditions": cond_list}]

    cur = await conn.execute(
        """
        INSERT INTO user_rules (
            user_id, name, sort_order, is_enabled,
            scope_type, scope_category_id, scope_feed_ids_json,
            match_mode, condition_groups_json, conditions_json, actions_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            req.name,
            req.sort_order,
            1 if req.is_enabled else 0,
            req.scope_type,
            req.scope_category_id,
            json.dumps(req.scope_feed_ids or []),
            req.match_mode,
            json.dumps(cond_groups),
            json.dumps(conds),
            json.dumps(req.actions or []),
        ),
    )
    await conn.commit()
    rule_id = cur.lastrowid

    # 讀取完整列
    r_cur = await conn.execute(
        """
        SELECT id, name, sort_order, is_enabled,
               COALESCE(scope_type, 'all') as scope_type,
               scope_category_id,
               COALESCE(scope_feed_ids_json, '[]') as scope_feed_ids_json,
               COALESCE(match_mode, 'all') as match_mode,
               COALESCE(condition_groups_json, '[]') as condition_groups_json,
               conditions_json, actions_json, hit_count, created_at
        FROM user_rules
        WHERE id = ?
        """,
        (rule_id,),
    )
    r = await r_cur.fetchone()

    return RuleResponseDTO(
        id=r["id"],
        name=r["name"],
        sort_order=r["sort_order"],
        is_enabled=bool(r["is_enabled"]),
        scope_type=r["scope_type"],
        scope_category_id=r["scope_category_id"],
        scope_feed_ids=json.loads(r["scope_feed_ids_json"]) if r["scope_feed_ids_json"] else [],
        match_mode=r["match_mode"],
        conditions=json.loads(r["conditions_json"]) if r["conditions_json"] else [],
        condition_groups=json.loads(r["condition_groups_json"]) if r["condition_groups_json"] else [],
        actions=json.loads(r["actions_json"]) if r["actions_json"] else [],
        hit_count=r["hit_count"],
        created_at=r["created_at"],
    )


@router.put("/{rule_id}", response_model=RuleResponseDTO)
async def update_user_rule(
    rule_id: int,
    req: RuleUpdateRequest,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> RuleResponseDTO:
    """修改過濾規則 (Update Filter Rule)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        SELECT id, name, sort_order, is_enabled,
               COALESCE(scope_type, 'all') as scope_type,
               scope_category_id,
               COALESCE(scope_feed_ids_json, '[]') as scope_feed_ids_json,
               COALESCE(match_mode, 'all') as match_mode,
               COALESCE(condition_groups_json, '[]') as condition_groups_json,
               conditions_json, actions_json, hit_count, created_at
        FROM user_rules
        WHERE id = ? AND user_id = ?
        """,
        (rule_id, user_id),
    )
    row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")

    new_name = req.name if req.name is not None else row["name"]
    new_sort = req.sort_order if req.sort_order is not None else row["sort_order"]
    new_enabled = req.is_enabled if req.is_enabled is not None else bool(row["is_enabled"])
    new_scope_type = req.scope_type if req.scope_type is not None else row["scope_type"]
    new_scope_cat = req.scope_category_id if req.scope_category_id is not None else row["scope_category_id"]
    new_scope_feeds = json.dumps(req.scope_feed_ids) if req.scope_feed_ids is not None else row["scope_feed_ids_json"]
    new_match_mode = req.match_mode if req.match_mode is not None else row["match_mode"]
    new_cond_groups = json.dumps(req.condition_groups) if req.condition_groups is not None else row["condition_groups_json"]
    new_conds = json.dumps(req.conditions) if req.conditions is not None else row["conditions_json"]
    new_acts = json.dumps(req.actions) if req.actions is not None else row["actions_json"]

    await conn.execute(
        """
        UPDATE user_rules
        SET name = ?, sort_order = ?, is_enabled = ?,
            scope_type = ?, scope_category_id = ?, scope_feed_ids_json = ?,
            match_mode = ?, condition_groups_json = ?, conditions_json = ?, actions_json = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            new_name,
            new_sort,
            1 if new_enabled else 0,
            new_scope_type,
            new_scope_cat,
            new_scope_feeds,
            new_match_mode,
            new_cond_groups,
            new_conds,
            new_acts,
            rule_id,
            user_id,
        ),
    )
    await conn.commit()

    return RuleResponseDTO(
        id=rule_id,
        name=new_name,
        sort_order=new_sort,
        is_enabled=new_enabled,
        scope_type=new_scope_type,
        scope_category_id=new_scope_cat,
        scope_feed_ids=json.loads(new_scope_feeds) if new_scope_feeds else [],
        match_mode=new_match_mode,
        conditions=json.loads(new_conds) if new_conds else [],
        condition_groups=json.loads(new_cond_groups) if new_cond_groups else [],
        actions=json.loads(new_acts) if new_acts else [],
        hit_count=row["hit_count"],
        created_at=row["created_at"],
    )


@router.delete("/{rule_id}")
async def delete_user_rule(
    rule_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """刪除過濾規則 (Delete Filter Rule)."""
    user_id = user["id"]
    await conn.execute(
        "DELETE FROM user_rules WHERE id = ? AND user_id = ?",
        (rule_id, user_id),
    )
    await conn.commit()
    return {"message": "Rule successfully deleted"}


@router.post("/test")
async def test_rule_conditions(
    req: Any = Body(...),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """測試自訂過濾規則條件，預覽目前資料庫中會匹配到的文章 (Test Filter Rule Conditions)."""
    user_id = user["id"]
    limit = 20
    scope_type = "all"
    scope_cat_id = None
    scope_feed_ids = []
    match_mode_str = "all"
    groups_list = []

    if isinstance(req, dict):
        limit = min(req.get("limit", 20), 50)
        scope_type = req.get("scope_type", "all")
        scope_cat_id = req.get("scope_category_id")
        scope_feed_ids = [int(fid) for fid in req.get("scope_feed_ids", [])]
        match_mode_str = req.get("match_mode", "all")
        if req.get("condition_groups"):
            groups_list = req.get("condition_groups")
        elif req.get("conditions"):
            conds_raw = req.get("conditions")
            c_list = conds_raw if isinstance(conds_raw, list) else (conds_raw.get("rules") or conds_raw.get("conditions") or [])
            groups_list = [{"match_mode": match_mode_str, "conditions": c_list}]
    elif isinstance(req, list):
        groups_list = [{"match_mode": "all", "conditions": req}]

    if not groups_list:
        return {"matched_count": 0, "articles": [], "matched_articles": []}

    try:
        condition_groups: list[ConditionGroup] = []
        for g in groups_list:
            if isinstance(g, dict):
                g_mode = g.get("match_mode", "all")
                g_conds_raw = g.get("conditions") or g.get("rules") or []
                g_conds = []
                for c in g_conds_raw:
                    if isinstance(c, str):
                        c = {"field": "title", "operator": "contains", "value": c}
                    if isinstance(c, dict):
                        f = c.get("field", "title")
                        if f in ("content_text",):
                            f = "content"
                        elif f in ("link",):
                            f = "url"
                        elif f in ("feed",):
                            f = "feed_title"
                        g_conds.append(
                            RuleCondition(
                                field=RuleField(f),
                                operator=RuleOperator(c.get("operator", "contains")),
                                value=str(c.get("value", "")),
                                case_sensitive=bool(c.get("case_sensitive", False)),
                            )
                        )
                condition_groups.append(ConditionGroup(match_mode=MatchMode(g_mode), conditions=g_conds))

        rule = RuleDef(
            id="test",
            rule_name="Test Rule",
            scope_type=RuleScopeType(scope_type),
            scope_category_id=scope_cat_id,
            scope_feed_ids=scope_feed_ids,
            match_mode=MatchMode(match_mode_str),
            condition_groups=condition_groups,
            actions=[],
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"規則條件格式錯誤: {e}")

    where_sql = ["uf.user_id = ?"]
    params = [user_id]

    if rule.scope_type == RuleScopeType.CATEGORY and rule.scope_category_id is not None:
        where_sql.append("uf.category_id = ?")
        params.append(rule.scope_category_id)
    elif rule.scope_type == RuleScopeType.FEEDS and rule.scope_feed_ids:
        placeholders = ",".join("?" for _ in rule.scope_feed_ids)
        where_sql.append(f"a.feed_id IN ({placeholders})")
        params.extend(rule.scope_feed_ids)

    cur = await conn.execute(
        f"""
        SELECT a.id, a.feed_id, uf.category_id, COALESCE(uf.custom_title, f.title) as feed_title,
               a.title, a.url, a.author, a.snippet, a.content_html, a.content_text, a.published_at,
               COALESCE(uas.is_read, 0) as is_read, COALESCE(uas.is_starred, 0) as is_starred
        FROM articles_hot a
        JOIN user_feeds uf ON a.feed_id = uf.feed_id
        JOIN feeds f ON a.feed_id = f.id
        LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
        WHERE {" AND ".join(where_sql)}
        ORDER BY a.published_at DESC
        """,
        params,
    )
    rows = await cur.fetchall()

    matched_articles = []
    total_matched_count = 0
    for r in rows:
        art_dto = ArticleDTO(
            guid=str(r["id"]),
            url=r["url"] or "",
            title=r["title"] or "",
            author=r["author"] or "",
            snippet=r["snippet"] or "",
            content_html=r["content_html"] or "",
            content_text=r["content_text"] or "",
            published_at=r["published_at"],
            is_read=bool(r["is_read"]),
            is_starred=bool(r["is_starred"]),
        )
        if RuleEngine.evaluate_rule(
            rule,
            art_dto,
            feed_id=r["feed_id"],
            category_id=r["category_id"],
            feed_title=r["feed_title"],
        ):
            total_matched_count += 1
            if len(matched_articles) < 50:
                matched_articles.append({
                    "id": r["id"],
                    "title": r["title"],
                    "feed_title": r["feed_title"],
                    "author": r["author"] or "",
                    "published_at": str(r["published_at"]),
                    "snippet": r["snippet"] or "",
                })

    return {
        "count": total_matched_count,
        "matched_count": total_matched_count,
        "tested_sample_size": len(rows),
        "articles": matched_articles,
        "matched_articles": matched_articles,
    }


@router.post("/{rule_id}/apply")
async def apply_single_rule_to_existing(
    rule_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """將指定規則立即套用至現有歷史文章 (Apply Single Rule to Existing Articles)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        SELECT id, name, sort_order, is_enabled,
               COALESCE(scope_type, 'all') as scope_type,
               scope_category_id,
               COALESCE(scope_feed_ids_json, '[]') as scope_feed_ids_json,
               COALESCE(match_mode, 'all') as match_mode,
               COALESCE(condition_groups_json, '[]') as condition_groups_json,
               conditions_json, actions_json
        FROM user_rules
        WHERE id = ? AND user_id = ?
        """,
        (rule_id, user_id),
    )
    row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")

    try:
        rule = parse_db_rule_row(row)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"規則定義解析失敗: {e}")

    where_sql = ["uf.user_id = ?"]
    params = [user_id]

    if rule.scope_type == RuleScopeType.CATEGORY and rule.scope_category_id is not None:
        where_sql.append("uf.category_id = ?")
        params.append(rule.scope_category_id)
    elif rule.scope_type == RuleScopeType.FEEDS and rule.scope_feed_ids:
        placeholders = ",".join("?" for _ in rule.scope_feed_ids)
        where_sql.append(f"a.feed_id IN ({placeholders})")
        params.extend(rule.scope_feed_ids)

    a_cur = await conn.execute(
        f"""
        SELECT a.id, a.feed_id, uf.category_id, COALESCE(uf.custom_title, f.title) as feed_title,
               a.title, a.url, a.author, a.snippet, a.content_html, a.content_text, a.published_at,
               COALESCE(uas.is_read, 0) as is_read, COALESCE(uas.is_starred, 0) as is_starred,
               COALESCE(uas.is_trash, 0) as is_trash, uas.highlight_color
        FROM articles_hot a
        JOIN user_feeds uf ON a.feed_id = uf.feed_id
        JOIN feeds f ON a.feed_id = f.id
        LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
        WHERE {" AND ".join(where_sql)}
        ORDER BY a.published_at DESC
        """,
        params,
    )
    articles = await a_cur.fetchall()

    affected_count = 0
    for r in articles:
        art_dto = ArticleDTO(
            guid=str(r["id"]),
            url=r["url"] or "",
            title=r["title"] or "",
            author=r["author"] or "",
            snippet=r["snippet"] or "",
            content_html=r["content_html"] or "",
            content_text=r["content_text"] or "",
            published_at=r["published_at"],
            is_read=bool(r["is_read"]),
            is_starred=bool(r["is_starred"]),
            highlight_color=r["highlight_color"],
        )
        if RuleEngine.evaluate_rule(
            rule,
            art_dto,
            feed_id=r["feed_id"],
            category_id=r["category_id"],
            feed_title=r["feed_title"],
        ):
            processed_dto, executed, _ = RuleEngine.apply_actions(rule.actions, art_dto)
            if executed:
                is_trash = 1 if "trash" in executed or "trashed" in processed_dto.extra_tags else r["is_trash"]
                is_read = 1 if processed_dto.is_read else r["is_read"]
                is_starred = 1 if processed_dto.is_starred else r["is_starred"]
                highlight_color = processed_dto.highlight_color

                await conn.execute(
                    """
                    INSERT INTO user_article_states (
                        user_id, article_id, is_read, is_starred, is_trash, highlight_color, starred_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END)
                    ON CONFLICT(user_id, article_id) DO UPDATE SET
                        is_read = excluded.is_read,
                        is_starred = excluded.is_starred,
                        is_trash = excluded.is_trash,
                        highlight_color = excluded.highlight_color,
                        starred_at = CASE WHEN excluded.is_starred = 1 AND user_article_states.starred_at IS NULL THEN CURRENT_TIMESTAMP ELSE user_article_states.starred_at END,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, r["id"], is_read, is_starred, is_trash, highlight_color, is_starred),
                )

                # 支援附加標籤 (Add Tag) 關聯
                for act_item in executed:
                    if act_item.startswith("add_tag:"):
                        tag_name = act_item.split(":", 1)[1].strip()
                        if tag_name:
                            t_cur = await conn.execute(
                                "SELECT id FROM tags WHERE user_id = ? AND name = ?",
                                (user_id, tag_name),
                            )
                            t_row = await t_cur.fetchone()
                            if t_row:
                                tag_id = t_row["id"]
                            else:
                                ins_t = await conn.execute(
                                    "INSERT INTO tags (user_id, name, color_hex) VALUES (?, ?, ?)",
                                    (user_id, tag_name, "#ef4444" if tag_name == "重要" else "#3b82f6"),
                                )
                                tag_id = ins_t.lastrowid
                            await conn.execute(
                                "INSERT OR IGNORE INTO article_tags (article_id, tag_id) VALUES (?, ?)",
                                (r["id"], tag_id),
                            )

                affected_count += 1

    await conn.execute(
        "UPDATE user_rules SET hit_count = hit_count + ? WHERE id = ?",
        (affected_count, rule_id),
    )
    await conn.commit()
    return {
        "rule_id": rule_id,
        "affected_articles": affected_count,
        "affected_articles_count": affected_count,
        "count": affected_count,
        "message": f"已成功套用至 {affected_count} 篇現有文章",
    }


@router.post("/apply-all")
async def apply_all_rules_to_existing(
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_write_db),
) -> dict:
    """將所有啟用中的規則批次套用至現有文章 (Apply All Active Rules to Existing Articles)."""
    user_id = user["id"]
    cur = await conn.execute(
        """
        SELECT id, name, sort_order, is_enabled,
               COALESCE(scope_type, 'all') as scope_type,
               scope_category_id,
               COALESCE(scope_feed_ids_json, '[]') as scope_feed_ids_json,
               COALESCE(match_mode, 'all') as match_mode,
               COALESCE(condition_groups_json, '[]') as condition_groups_json,
               conditions_json, actions_json
        FROM user_rules
        WHERE user_id = ? AND is_enabled = 1
        ORDER BY sort_order ASC
        """,
        (user_id,),
    )
    rule_rows = await cur.fetchall()
    if not rule_rows:
        return {
            "affected_articles": 0,
            "affected_articles_count": 0,
            "count": 0,
            "message": "目前沒有任何啟用的過濾規則",
        }

    rules: list[RuleDef] = []
    for row in rule_rows:
        try:
            rules.append(parse_db_rule_row(row))
        except Exception as exc:
            logger.warning(f"Failed to parse rule row ID {row['id']}: {exc}")

    a_cur = await conn.execute(
        """
        SELECT a.id, a.feed_id, uf.category_id, COALESCE(uf.custom_title, f.title) as feed_title,
               a.title, a.url, a.author, a.snippet, a.content_html, a.content_text, a.published_at,
               COALESCE(uas.is_read, 0) as is_read, COALESCE(uas.is_starred, 0) as is_starred,
               COALESCE(uas.is_trash, 0) as is_trash, uas.highlight_color
        FROM articles_hot a
        JOIN user_feeds uf ON a.feed_id = uf.feed_id
        JOIN feeds f ON a.feed_id = f.id
        LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
        WHERE uf.user_id = ?
        ORDER BY a.published_at DESC
        """,
        (user_id,),
    )
    articles = await a_cur.fetchall()

    affected_count = 0
    for r in articles:
        art_dto = ArticleDTO(
            guid=str(r["id"]),
            url=r["url"] or "",
            title=r["title"] or "",
            author=r["author"] or "",
            snippet=r["snippet"] or "",
            content_html=r["content_html"] or "",
            content_text=r["content_text"] or "",
            published_at=r["published_at"],
            is_read=bool(r["is_read"]),
            is_starred=bool(r["is_starred"]),
            highlight_color=r["highlight_color"],
        )
        processed_dto, executed = RuleEngine.process_article(
            art_dto,
            rules,
            feed_id=r["feed_id"],
            category_id=r["category_id"],
            feed_title=r["feed_title"],
        )
        if executed:
            is_trash = 1 if any("trash" in x for x in executed) or "trashed" in processed_dto.extra_tags else r["is_trash"]
            is_read = 1 if processed_dto.is_read else r["is_read"]
            is_starred = 1 if processed_dto.is_starred else r["is_starred"]
            highlight_color = processed_dto.highlight_color

            await conn.execute(
                """
                INSERT INTO user_article_states (
                    user_id, article_id, is_read, is_starred, is_trash, highlight_color, starred_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END)
                ON CONFLICT(user_id, article_id) DO UPDATE SET
                    is_read = excluded.is_read,
                    is_starred = excluded.is_starred,
                    is_trash = excluded.is_trash,
                    highlight_color = excluded.highlight_color,
                    starred_at = CASE WHEN excluded.is_starred = 1 AND user_article_states.starred_at IS NULL THEN CURRENT_TIMESTAMP ELSE user_article_states.starred_at END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, r["id"], is_read, is_starred, is_trash, highlight_color, is_starred),
            )

            # 支援附加標籤 (Add Tag) 關聯
            for act_item in executed:
                if "add_tag:" in act_item:
                    tag_name = act_item.split("add_tag:", 1)[1].strip()
                    if tag_name:
                        t_cur = await conn.execute(
                            "SELECT id FROM tags WHERE user_id = ? AND name = ?",
                            (user_id, tag_name),
                        )
                        t_row = await t_cur.fetchone()
                        if t_row:
                            tag_id = t_row["id"]
                        else:
                            ins_t = await conn.execute(
                                "INSERT INTO tags (user_id, name, color_hex) VALUES (?, ?, ?)",
                                (user_id, tag_name, "#ef4444" if tag_name == "重要" else "#3b82f6"),
                            )
                            tag_id = ins_t.lastrowid
                        await conn.execute(
                            "INSERT OR IGNORE INTO article_tags (article_id, tag_id) VALUES (?, ?)",
                            (r["id"], tag_id),
                        )

            affected_count += 1

    await conn.commit()
    return {
        "affected_articles": affected_count,
        "affected_articles_count": affected_count,
        "count": affected_count,
        "message": f"所有規則已成功套用至 {affected_count} 篇現有文章",
    }
