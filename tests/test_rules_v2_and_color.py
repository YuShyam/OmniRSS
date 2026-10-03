"""QuiteRSS 等級過濾規則 2.0 與自訂色碼高亮整合測試 (Rules v2 & Highlight Color Integration Tests).

Tests QuiteRSS-style scope matching (All / Category / Feeds), nested condition groups (Outer AND, Inner OR/AND),
multi-action pipelines, and custom row highlight colors (set_color hex).
"""

import pytest
from httpx import AsyncClient, ASGITransport

from omnirss.core.database import DatabaseManager, set_global_db_manager, compute_entry_hash
from omnirss.core.security import PasswordHasher, TokenManager
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
from omnirss.main import app
from omnirss.sdk.models import ArticleDTO


# ==============================================================================
# 1. 核心邏輯單元測試 (RuleEngine Unit Tests)
# ==============================================================================


def test_scenario_1_keyword_filtering_and_trash():
    """測試案例 1: 指定分類來源，標題符合 (優惠 OR 促銷) AND !技術 -> 執行已讀 + 移至垃圾桶 (Test Scenario 1)."""
    # 規則設定：
    # Scope: Category ID 5 (科技)
    # Group 1 (OR): 標題包含「優惠」 OR 標題包含「促銷」
    # Group 2 (AND): 標題不包含「技術」
    # Actions: 已讀 (mark_read) + 刪除 (trash)
    rule = RuleDef(
        id="rule-scenario-1",
        rule_name="促銷廣告過濾器",
        scope_type=RuleScopeType.CATEGORY,
        scope_category_id=5,
        condition_groups=[
            ConditionGroup(
                match_mode=MatchMode.ANY,
                conditions=[
                    RuleCondition(field=RuleField.TITLE, operator=RuleOperator.CONTAINS, value="優惠"),
                    RuleCondition(field=RuleField.TITLE, operator=RuleOperator.CONTAINS, value="促銷"),
                ],
            ),
            ConditionGroup(
                match_mode=MatchMode.ALL,
                conditions=[
                    RuleCondition(field=RuleField.TITLE, operator=RuleOperator.NOT_CONTAINS, value="技術"),
                ],
            ),
        ],
        actions=[
            RuleAction(action=RuleActionType.MARK_READ),
            RuleAction(action=RuleActionType.TRASH),
        ],
    )

    # 命中情境 A: 目標分類 (cat 5), 標題「[優惠] 雲端主機限時特價」 -> 命中
    art_hit = ArticleDTO(
        guid="art-1",
        url="https://news.example.com/1",
        title="[優惠] 雲端主機限時特價",
        content_text="雲端主機特價活動開跑",
    )
    assert RuleEngine.evaluate_rule(rule, art_hit, category_id=5) is True
    processed, actions = RuleEngine.process_article(art_hit, [rule], category_id=5)
    assert processed.is_read is True
    assert "trashed" in processed.extra_tags

    # 未命中情境 B: 非目標分類 (cat 2), 標題「[優惠] 雲端主機限時特價」 -> Scope 阻擋
    assert RuleEngine.evaluate_rule(rule, art_hit, category_id=2) is False

    # 未命中情境 C: 目標分類, 標題「[促銷] 雲端主機技術架構介紹」 -> 因包含「技術」被 Group 2 阻擋
    art_miss = ArticleDTO(
        guid="art-2",
        url="https://news.example.com/2",
        title="[促銷] 雲端主機技術架構介紹",
        content_text="探討雲端主機技術架構",
    )
    assert RuleEngine.evaluate_rule(rule, art_miss, category_id=5) is False


def test_scenario_2_author_blacklist_and_star():
    """測試案例 2: 指定分類來源，標題符合 (資安 OR 漏洞) AND 作者 != spammer_bot -> 加入重要標籤 + 待讀標籤 + 加星 (Test Scenario 2)."""
    rule = RuleDef(
        id="rule-scenario-2",
        rule_name="資安快訊標記",
        scope_type=RuleScopeType.CATEGORY,
        scope_category_id=5,
        condition_groups=[
            ConditionGroup(
                match_mode=MatchMode.ANY,
                conditions=[
                    RuleCondition(field=RuleField.TITLE, operator=RuleOperator.CONTAINS, value="資安"),
                    RuleCondition(field=RuleField.TITLE, operator=RuleOperator.CONTAINS, value="漏洞"),
                ],
            ),
            ConditionGroup(
                match_mode=MatchMode.ALL,
                conditions=[
                    RuleCondition(field=RuleField.AUTHOR, operator=RuleOperator.NOT_EQUALS, value="spammer_bot"),
                ],
            ),
        ],
        actions=[
            RuleAction(action=RuleActionType.ADD_TAGS, params={"tags": ["重要", "待讀"]}),
            RuleAction(action=RuleActionType.STAR),
        ],
    )

    # 命中情境: 作者是 alice, 標題包含「資安」
    art_good = ArticleDTO(
        guid="art-3",
        url="https://news.example.com/3",
        title="[資安] 重大零日漏洞修補通報",
        author="alice",
        content_text="請各單位儘速完成安全性更新",
    )
    assert RuleEngine.evaluate_rule(rule, art_good, category_id=5) is True
    processed, _ = RuleEngine.process_article(art_good, [rule], category_id=5)
    assert processed.is_starred is True
    assert "重要" in processed.extra_tags
    assert "待讀" in processed.extra_tags

    # 未命中情境: 作者是 spammer_bot (黑名單)
    art_spammer = ArticleDTO(
        guid="art-4",
        url="https://news.example.com/4",
        title="[資安] 重大零日漏洞修補通報",
        author="spammer_bot",
        content_text="黑名單發文",
    )
    assert RuleEngine.evaluate_rule(rule, art_spammer, category_id=5) is False


def test_rule_scope_matching_all_category_feeds():
    """測試新聞源範圍比對 (All / Category / Feeds Scope Matching)."""
    # 1. 全域 (All)
    rule_all = RuleDef(
        id="r-all",
        rule_name="全域規則",
        scope_type=RuleScopeType.ALL,
        conditions=[RuleCondition(field=RuleField.TITLE, value="OpenAI")],
        actions=[RuleAction(action=RuleActionType.STAR)],
    )
    art = ArticleDTO(guid="1", url="u", title="OpenAI 釋出最新模型")
    assert RuleEngine.evaluate_rule(rule_all, art, feed_id=1, category_id=10) is True

    # 2. 指定分類 (Category)
    rule_cat = RuleDef(
        id="r-cat",
        rule_name="科技分類規則",
        scope_type=RuleScopeType.CATEGORY,
        scope_category_id=10,
        conditions=[RuleCondition(field=RuleField.TITLE, value="OpenAI")],
        actions=[RuleAction(action=RuleActionType.STAR)],
    )
    assert RuleEngine.evaluate_rule(rule_cat, art, feed_id=1, category_id=10) is True
    assert RuleEngine.evaluate_rule(rule_cat, art, feed_id=1, category_id=20) is False

    # 3. 指定頻道 (Feeds 多選)
    rule_feeds = RuleDef(
        id="r-feeds",
        rule_name="指定頻道規則",
        scope_type=RuleScopeType.FEEDS,
        scope_feed_ids=[101, 102],
        conditions=[RuleCondition(field=RuleField.TITLE, value="OpenAI")],
        actions=[RuleAction(action=RuleActionType.STAR)],
    )
    assert RuleEngine.evaluate_rule(rule_feeds, art, feed_id=101) is True
    assert RuleEngine.evaluate_rule(rule_feeds, art, feed_id=102) is True
    assert RuleEngine.evaluate_rule(rule_feeds, art, feed_id=103) is False


def test_rule_action_set_color():
    """測試自訂標題底色高亮動作 (Test Action: set_color)."""
    rule_color = RuleDef(
        id="r-color",
        rule_name="重大快訊紅標高亮",
        conditions=[RuleCondition(field=RuleField.TITLE, value="【快訊】")],
        actions=[
            RuleAction(action=RuleActionType.SET_COLOR, params={"color": "#e11d48"}),
        ],
    )
    art = ArticleDTO(
        guid="news-1",
        url="https://news.example.com/1",
        title="【快訊】市場重大波動通知",
    )
    processed, actions = RuleEngine.process_article(art, [rule_color])
    assert processed.highlight_color == "#e11d48"
    assert any("set_color:#e11d48" in a for a in actions)


# ==============================================================================
# 2. 資料庫與 API 整合端對端測試 (E2E API & Database Integration Tests)
# ==============================================================================


@pytest.mark.asyncio
async def test_rules_v2_api_crud_and_apply_all(tmp_path):
    """測試 QuiteRSS v2 規則 API 建立、取得、與批次套用至現有文章 (Test Rules v2 API CRUD & Batch Apply)."""
    db_file = tmp_path / "test_rules_v2_api.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    # 寫入測試用戶、分類、頻道與文章
    pwd_hash = PasswordHasher.hash_password("adminpass")
    api_key = TokenManager.generate_api_key()
    async with db_mgr.get_connection() as conn:
        u_cur = await conn.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, api_key)
            VALUES ('tester', ?, 1, ?)
            """,
            (pwd_hash, api_key),
        )
        user_id = u_cur.lastrowid
        
        c_cur = await conn.execute(
            """
            INSERT INTO categories (user_id, name, sort_order)
            VALUES (?, '科技新聞', 1)
            """,
            (user_id,),
        )
        cat_id = c_cur.lastrowid

        f_cur = await conn.execute(
            """
            INSERT INTO feeds (title, feed_url, check_interval_minutes)
            VALUES ('TechNews Daily', 'https://technews.example.com/rss', 30)
            """,
        )
        feed_id = f_cur.lastrowid

        await conn.execute(
            """
            INSERT INTO user_feeds (user_id, feed_id, category_id, custom_title)
            VALUES (?, ?, ?, '科技快訊頻道')
            """,
            (user_id, feed_id, cat_id),
        )

        h1 = compute_entry_hash(feed_id, "tech-post-1", "https://news.example.com/1")
        h2 = compute_entry_hash(feed_id, "tech-post-2", "https://news.example.com/2")

        a1_cur = await conn.execute(
            """
            INSERT INTO articles_hot (feed_id, entry_hash, title, url, author, content_text, published_at)
            VALUES (?, ?, '[快訊] 伺服器重大安全性更新發布', 'https://news.example.com/1', 'bob', '發布最新修補程式', datetime('now'))
            """,
            (feed_id, h1),
        )
        art1_id = a1_cur.lastrowid

        a2_cur = await conn.execute(
            """
            INSERT INTO articles_hot (feed_id, entry_hash, title, url, author, content_text, published_at)
            VALUES (?, ?, '[分享] 開源架構設計心得', 'https://news.example.com/2', 'clara', '架構演進討論', datetime('now'))
            """,
            (feed_id, h2),
        )
        art2_id = a2_cur.lastrowid

        await conn.execute(
            """
            INSERT INTO user_article_states (user_id, article_id, is_read, is_starred)
            VALUES (?, ?, 0, 0), (?, ?, 0, 0)
            """,
            (user_id, art1_id, user_id, art2_id),
        )
        await conn.commit()

    token = TokenManager.create_access_token(data={"sub": str(user_id), "username": "tester"})
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 建立 QuiteRSS v2 規則 (含 Scope, Condition Groups, Set Color)
        rule_payload = {
            "name": "重大安全性更新高亮與標記",
            "sort_order": 50,
            "is_enabled": True,
            "scope_type": "category",
            "scope_category_id": cat_id,
            "scope_feed_ids": [],
            "condition_groups": [
                {
                    "match_mode": "any",
                    "conditions": [
                        {"field": "title", "operator": "contains", "value": "安全性更新", "case_sensitive": False}
                    ]
                }
            ],
            "actions": [
                {"action": "mark_read", "params": {}},
                {"action": "set_color", "params": {"color": "#ec4899"}},
                {"action": "add_tags", "params": {"tags": ["安全性"]}}
            ]
        }
        res = await client.post("/api/rules", json=rule_payload, headers=headers)
        assert res.status_code in (200, 201)
        rule_data = res.json()
        assert rule_data["name"] == "重大安全性更新高亮與標記"
        assert rule_data["scope_type"] == "category"
        assert rule_data["scope_category_id"] == cat_id
        assert len(rule_data["condition_groups"]) == 1

        # 2. 測試規則條件預覽 (Test Conditions against existing articles)
        test_res = await client.post(
            "/api/rules/test",
            json={
                "scope_type": "category",
                "scope_category_id": cat_id,
                "condition_groups": rule_payload["condition_groups"],
            },
            headers=headers,
        )
        assert test_res.status_code == 200
        test_data = test_res.json()
        assert test_data["matched_count"] >= 1
        assert any(a["id"] == art1_id for a in test_data["matched_articles"])

        # 3. 批次套用所有規則至現有文章 (Apply All Rules)
        apply_res = await client.post("/api/rules/apply-all", headers=headers)
        assert apply_res.status_code == 200
        apply_data = apply_res.json()
        assert apply_data["affected_articles"] >= 1

        # 4. 驗證資料庫狀態與文章查詢 API 回傳 highlight_color
        arts_res = await client.get("/api/articles", headers=headers)
        assert arts_res.status_code == 200
        arts_list = arts_res.json()["items"]

        art_target = next(a for a in arts_list if a["id"] == art1_id)
        assert art_target["is_read"] is True
        assert art_target["highlight_color"] == "#ec4899"
        assert any(t.get("name") == "安全性" if isinstance(t, dict) else t == "安全性" for t in art_target["tags"])

        art_other = next(a for a in arts_list if a["id"] == art2_id)
        assert art_other["is_read"] is False
        assert art_other["highlight_color"] is None
