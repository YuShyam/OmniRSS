"""規則引擎單元測試 (Rule Engine Unit Tests).

Tests AND/OR condition combinations, regex matching, and automated action execution.
"""

import pytest
from omnirss.core.rule_engine import (
    RuleEngine,
    RuleDef,
    RuleCondition,
    RuleAction,
    RuleField,
    RuleOperator,
    RuleActionType,
    MatchMode,
)
from omnirss.sdk.models import ArticleDTO


def test_rule_condition_contains_and_regex():
    """測試包含與正則比對運算子 (Test contains and regex matching)."""
    article = ArticleDTO(
        guid="test-1",
        url="https://example.com/ad-post",
        title="【限時優惠】買一送一特賣活動",
        author="廣告小編",
        content_text="今日全館特價，請勿錯過！",
    )

    # 1. Title contains "限時優惠"
    cond_title = RuleCondition(
        field=RuleField.TITLE,
        operator=RuleOperator.CONTAINS,
        value="限時優惠",
    )
    assert RuleEngine.evaluate_condition(cond_title, article) is True

    # 2. Author equals "廣告小編"
    cond_author = RuleCondition(
        field=RuleField.AUTHOR,
        operator=RuleOperator.EQUALS,
        value="廣告小編",
    )
    assert RuleEngine.evaluate_condition(cond_author, article) is True

    # 3. Regex match on title: r"買[一兩]送一"
    cond_regex = RuleCondition(
        field=RuleField.TITLE,
        operator=RuleOperator.REGEX,
        value=r"買[一兩]送一",
    )
    assert RuleEngine.evaluate_condition(cond_regex, article) is True

    # 4. Negative match: Content not contains "保證獲利"
    cond_neg = RuleCondition(
        field=RuleField.CONTENT,
        operator=RuleOperator.NOT_CONTAINS,
        value="保證獲利",
    )
    assert RuleEngine.evaluate_condition(cond_neg, article) is True


def test_rule_actions_and_stop_processing():
    """測試規則動作執行與停止後續規則 (Test rule actions and stop processing)."""
    article = ArticleDTO(
        guid="test-2",
        url="https://example.com/spam",
        title="常見垃圾廣告標題",
        content_text="這是一篇垃圾廣告文章",
    )

    # 規則 1 (高優先權): 標題包含「廣告」 -> 標記已讀 + 丟入垃圾桶 + 停止後續處理
    rule_spam = RuleDef(
        id="rule-1",
        rule_name="廣告過濾器",
        priority=100,
        is_active=True,
        match_mode=MatchMode.ALL,
        conditions=[
            RuleCondition(
                field=RuleField.TITLE,
                operator=RuleOperator.CONTAINS,
                value="廣告",
            )
        ],
        actions=[
            RuleAction(action=RuleActionType.MARK_READ),
            RuleAction(action=RuleActionType.TRASH),
            RuleAction(action=RuleActionType.STOP_PROCESSING),
        ],
    )

    # 規則 2 (低優先權): 標題包含「標題」 -> 加星標 (因被 stop_processing 截斷，不應被執行)
    rule_star = RuleDef(
        id="rule-2",
        rule_name="星標標題",
        priority=10,
        is_active=True,
        match_mode=MatchMode.ALL,
        conditions=[
            RuleCondition(
                field=RuleField.TITLE,
                operator=RuleOperator.CONTAINS,
                value="標題",
            )
        ],
        actions=[
            RuleAction(action=RuleActionType.STAR),
        ],
    )

    processed_art, executed = RuleEngine.process_article(article, [rule_spam, rule_star])

    assert processed_art.is_read is True
    assert "trashed" in processed_art.extra_tags
    assert processed_art.is_starred is False  # 規則 2 未被執行
    assert any("mark_read" in a for a in executed)
    assert any("trash" in a for a in executed)


def test_rule_condition_empty_and_not_empty_operators():
    """測試空值與非空值比對運算子 (Test empty, not empty, equals/not_equals blank)."""
    article_with_title = ArticleDTO(
        guid="test-3",
        url="https://example.com/item3",
        title="有標題文章",
        author="",
        content_text="內文",
    )
    article_blank_title = ArticleDTO(
        guid="test-4",
        url="https://example.com/item4",
        title="",
        author="某作者",
        content_text="",
    )

    # 1. 標題 不是 空白 (IS_NOT_EMPTY)
    cond_not_empty = RuleCondition(
        field=RuleField.TITLE,
        operator=RuleOperator.IS_NOT_EMPTY,
        value="",
    )
    assert RuleEngine.evaluate_condition(cond_not_empty, article_with_title) is True
    assert RuleEngine.evaluate_condition(cond_not_empty, article_blank_title) is False

    # 2. 標題 為 空白 (IS_EMPTY)
    cond_empty = RuleCondition(
        field=RuleField.TITLE,
        operator=RuleOperator.IS_EMPTY,
        value="",
    )
    assert RuleEngine.evaluate_condition(cond_empty, article_with_title) is False
    assert RuleEngine.evaluate_condition(cond_empty, article_blank_title) is True

    # 3. 標題 not_equals "" (不是空白)
    cond_not_eq_blank = RuleCondition(
        field=RuleField.TITLE,
        operator=RuleOperator.NOT_EQUALS,
        value="",
    )
    assert RuleEngine.evaluate_condition(cond_not_eq_blank, article_with_title) is True
    assert RuleEngine.evaluate_condition(cond_not_eq_blank, article_blank_title) is False

    # 4. 作者 equals "" (作者為空)
    cond_author_eq_blank = RuleCondition(
        field=RuleField.AUTHOR,
        operator=RuleOperator.EQUALS,
        value="",
    )
    assert RuleEngine.evaluate_condition(cond_author_eq_blank, article_with_title) is True
    assert RuleEngine.evaluate_condition(cond_author_eq_blank, article_blank_title) is False

