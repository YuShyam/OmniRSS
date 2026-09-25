"""過濾與規則管理路由控制器 (Rules Management Router).

This module handles CRUD endpoints for QuiteRSS-style conditional rules.
"""

import json
from typing import Any
import aiosqlite
from fastapi import APIRouter, Body, Depends, HTTPException, status

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


@router.post("/test")
async def test_rule_conditions(
    req: Any = Body(...),
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """測試自訂過濾規則條件，預覽目前資料庫中會匹配到的文章 (Test Filter Rule Conditions)."""
    from omnirss.core.rule_engine import RuleEngine, RuleDef, RuleCondition, MatchMode, RuleField, RuleOperator
    from omnirss.sdk.models import ArticleDTO

    user_id = user["id"]
    if isinstance(req, list):
        conditions_raw = req
        match_mode_str = "all"
        limit = 20
    elif isinstance(req, dict):
        if isinstance(req.get("conditions"), dict):
            inner = req["conditions"]
            conditions_raw = inner.get("rules") or inner.get("conditions") or []
            match_mode_str = inner.get("match_mode", req.get("match_mode", "all"))
        else:
            conditions_raw = req.get("conditions") or req.get("rules") or []
            match_mode_str = req.get("match_mode", "all")
        limit = min(req.get("limit", 20), 50)
    else:
        conditions_raw = []
        match_mode_str = "all"
        limit = 20

    if not conditions_raw:
        return {"matched_count": 0, "articles": [], "matched_articles": []}

    try:
        rule_conds = []
        for c in conditions_raw:
            if isinstance(c, str):
                c = {"field": "title", "operator": "contains", "value": c}
            elif not isinstance(c, dict):
                continue
            f = c.get("field", "title")
            # 兼容前端傳入 content_text 或 content
            if f in ("content_text", "content_html"):
                f = "content"
            elif f in ("link",):
                f = "url"
            elif f in ("feed",):
                f = "feed_title"
            rule_conds.append(
                RuleCondition(
                    field=RuleField(f),
                    operator=RuleOperator(c.get("operator", "contains")),
                    value=str(c.get("value", "")),
                    case_sensitive=bool(c.get("case_sensitive", False)),
                )
            )
        rule = RuleDef(
            id="test",
            rule_name="Test Rule",
            match_mode=MatchMode(match_mode_str),
            conditions=rule_conds,
            actions=[],
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"規則條件格式錯誤: {e}")

    cur = await conn.execute(
        """
        SELECT a.id, a.feed_id, COALESCE(uf.custom_title, f.title) as feed_title,
               a.title, a.url, a.author, a.snippet, a.content_html, a.content_text, a.published_at,
               COALESCE(uas.is_read, 0) as is_read, COALESCE(uas.is_starred, 0) as is_starred
        FROM articles_hot a
        JOIN user_feeds uf ON a.feed_id = uf.feed_id
        JOIN feeds f ON a.feed_id = f.id
        LEFT JOIN user_article_states uas ON a.id = uas.article_id AND uas.user_id = uf.user_id
        WHERE uf.user_id = ?
        ORDER BY a.published_at DESC
        LIMIT 300
        """,
        (user_id,),
    )
    rows = await cur.fetchall()

    matched_articles = []
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
        if RuleEngine.evaluate_rule(rule, art_dto, feed_title=r["feed_title"]):
            matched_articles.append({
                "id": r["id"],
                "title": r["title"],
                "feed_title": r["feed_title"],
                "author": r["author"] or "",
                "published_at": str(r["published_at"]),
                "snippet": r["snippet"] or "",
            })
            if len(matched_articles) >= limit:
                break

    return {
        "count": len(matched_articles),
        "matched_count": len(matched_articles),
        "tested_sample_size": len(rows),
        "articles": matched_articles,
        "matched_articles": matched_articles,
    }


@router.post("/{rule_id}/apply")
async def apply_single_rule_to_existing(
    rule_id: int,
    user: dict = Depends(get_current_user),
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """將指定規則立即套用至現有歷史文章 (Apply Single Rule to Existing Articles)."""
    from omnirss.core.rule_engine import RuleEngine, RuleDef, RuleCondition, RuleAction, MatchMode, RuleActionType, RuleField, RuleOperator
    from omnirss.sdk.models import ArticleDTO

    user_id = user["id"]
    cur = await conn.execute(
        "SELECT id, name, conditions_json, actions_json FROM user_rules WHERE id = ? AND user_id = ?",
        (rule_id, user_id),
    )
    row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")

    try:
        conds_data = json.loads(row["conditions_json"])
        if isinstance(conds_data, dict):
            match_mode_val = conds_data.get("match_mode", "all")
            cond_list = conds_data.get("rules") or conds_data.get("conditions") or []
        elif isinstance(conds_data, list):
            match_mode_val = "all"
            cond_list = conds_data
        elif isinstance(conds_data, str):
            match_mode_val = "all"
            cond_list = [conds_data]
        else:
            match_mode_val = "all"
            cond_list = []

        conds = []
        for c in cond_list:
            if isinstance(c, str):
                c = {"field": "title", "operator": "contains", "value": c}
            elif not isinstance(c, dict):
                continue
            f = c.get("field", "title")
            if f in ("content_text", "content_html"):
                f = "content"
            elif f in ("link",):
                f = "url"
            elif f in ("feed",):
                f = "feed_title"
            conds.append(
                RuleCondition(
                    field=RuleField(f),
                    operator=RuleOperator(c.get("operator", "contains")),
                    value=str(c.get("value", "")),
                    case_sensitive=bool(c.get("case_sensitive", False)),
                )
            )

        acts_raw = json.loads(row["actions_json"])
        if isinstance(acts_raw, str):
            acts_raw = [{"action": acts_raw, "params": {}}]
        elif not isinstance(acts_raw, list):
            acts_raw = []
        acts = []
        for a in acts_raw:
            if isinstance(a, str):
                a = {"action": a, "params": {}}
            elif not isinstance(a, dict):
                continue
            act_type = a.get("action") or a.get("action_type") or "mark_read"
            params = a.get("params") or a.get("parameters") or {}
            acts.append(RuleAction(action=RuleActionType(act_type), params=params))

        rule = RuleDef(
            id=str(row["id"]),
            rule_name=row["name"],
            match_mode=MatchMode(match_mode_val),
            conditions=conds,
            actions=acts,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"規則定義解析失敗: {e}")

    a_cur = await conn.execute(
        """
        SELECT a.id, a.feed_id, COALESCE(uf.custom_title, f.title) as feed_title,
               a.title, a.url, a.author, a.snippet, a.content_html, a.content_text, a.published_at,
               COALESCE(uas.is_read, 0) as is_read, COALESCE(uas.is_starred, 0) as is_starred,
               COALESCE(uas.is_trash, 0) as is_trash
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
        )
        if RuleEngine.evaluate_rule(rule, art_dto, feed_title=r["feed_title"]):
            processed_dto, executed, _ = RuleEngine.apply_actions(rule.actions, art_dto)
            if executed:
                is_trash = 1 if "trash" in executed or "trashed" in processed_dto.extra_tags else r["is_trash"]
                is_read = 1 if processed_dto.is_read else r["is_read"]
                is_starred = 1 if processed_dto.is_starred else r["is_starred"]

                await conn.execute(
                    """
                    INSERT INTO user_article_states (user_id, article_id, is_read, is_starred, is_trash, starred_at)
                    VALUES (?, ?, ?, ?, ?, CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END)
                    ON CONFLICT(user_id, article_id) DO UPDATE SET
                        is_read = excluded.is_read,
                        is_starred = excluded.is_starred,
                        is_trash = excluded.is_trash,
                        starred_at = CASE WHEN excluded.is_starred = 1 AND user_article_states.starred_at IS NULL THEN CURRENT_TIMESTAMP ELSE user_article_states.starred_at END,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, r["id"], is_read, is_starred, is_trash, is_starred),
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
    conn: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """將所有啟用中的規則批次套用至現有文章 (Apply All Active Rules to Existing Articles)."""
    from omnirss.core.rule_engine import RuleEngine, RuleDef, RuleCondition, RuleAction, MatchMode, RuleActionType, RuleField, RuleOperator
    from omnirss.sdk.models import ArticleDTO

    user_id = user["id"]
    cur = await conn.execute(
        "SELECT id, name, sort_order, is_enabled, conditions_json, actions_json FROM user_rules WHERE user_id = ? AND is_enabled = 1 ORDER BY sort_order ASC",
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

    rules = []
    for row in rule_rows:
        try:
            conds_data = json.loads(row["conditions_json"])
            if isinstance(conds_data, dict):
                match_mode_val = conds_data.get("match_mode", "all")
                cond_list = conds_data.get("rules") or conds_data.get("conditions") or []
            elif isinstance(conds_data, list):
                match_mode_val = "all"
                cond_list = conds_data
            elif isinstance(conds_data, str):
                match_mode_val = "all"
                cond_list = [conds_data]
            else:
                match_mode_val = "all"
                cond_list = []

            conds = []
            for c in cond_list:
                if isinstance(c, str):
                    c = {"field": "title", "operator": "contains", "value": c}
                elif not isinstance(c, dict):
                    continue
                f = c.get("field", "title")
                if f in ("content_text", "content_html"):
                    f = "content"
                elif f in ("link",):
                    f = "url"
                elif f in ("feed",):
                    f = "feed_title"
                conds.append(
                    RuleCondition(
                        field=RuleField(f),
                        operator=RuleOperator(c.get("operator", "contains")),
                        value=str(c.get("value", "")),
                        case_sensitive=bool(c.get("case_sensitive", False)),
                    )
                )

            acts_raw = json.loads(row["actions_json"])
            if isinstance(acts_raw, str):
                acts_raw = [{"action": acts_raw, "params": {}}]
            elif not isinstance(acts_raw, list):
                acts_raw = []
            acts = []
            for a in acts_raw:
                if isinstance(a, str):
                    a = {"action": a, "params": {}}
                elif not isinstance(a, dict):
                    continue
                act_type = a.get("action") or a.get("action_type") or "mark_read"
                params = a.get("params") or a.get("parameters") or {}
                acts.append(RuleAction(action=RuleActionType(act_type), params=params))

            rules.append(
                RuleDef(
                    id=str(row["id"]),
                    rule_name=row["name"],
                    priority=row["sort_order"],
                    match_mode=MatchMode(match_mode_val),
                    conditions=conds,
                    actions=acts,
                )
            )
        except Exception:
            pass

    a_cur = await conn.execute(
        """
        SELECT a.id, a.feed_id, COALESCE(uf.custom_title, f.title) as feed_title,
               a.title, a.url, a.author, a.snippet, a.content_html, a.content_text, a.published_at,
               COALESCE(uas.is_read, 0) as is_read, COALESCE(uas.is_starred, 0) as is_starred,
               COALESCE(uas.is_trash, 0) as is_trash
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
        )
        processed_dto, executed = RuleEngine.process_article(art_dto, rules, feed_title=r["feed_title"])
        if executed:
            is_trash = 1 if any("trash" in x for x in executed) or "trashed" in processed_dto.extra_tags else r["is_trash"]
            is_read = 1 if processed_dto.is_read else r["is_read"]
            is_starred = 1 if processed_dto.is_starred else r["is_starred"]

            await conn.execute(
                """
                INSERT INTO user_article_states (user_id, article_id, is_read, is_starred, is_trash, starred_at)
                VALUES (?, ?, ?, ?, ?, CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END)
                ON CONFLICT(user_id, article_id) DO UPDATE SET
                    is_read = excluded.is_read,
                    is_starred = excluded.is_starred,
                    is_trash = excluded.is_trash,
                    starred_at = CASE WHEN excluded.is_starred = 1 AND user_article_states.starred_at IS NULL THEN CURRENT_TIMESTAMP ELSE user_article_states.starred_at END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, r["id"], is_read, is_starred, is_trash, is_starred),
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
