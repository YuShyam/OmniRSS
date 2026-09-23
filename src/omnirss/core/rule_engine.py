"""智慧過濾與規則引擎 (Intelligent Filtering & Rule Engine).

This module implements QuiteRSS-style conditional rule matching (AND/OR logic, regex,
field comparisons) and automated action execution (mark_read, star, trash, add_tag, notify).
"""

import logging
import re
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field

from omnirss.sdk.models import ArticleDTO

logger = logging.getLogger("omnirss.rules")


class MatchMode(str, Enum):
    """條件組合比對模式 (Condition Combination Match Mode)."""

    ALL = "all"  # AND 邏輯：所有條件皆須滿足
    ANY = "any"  # OR 邏輯：任一條件滿足即可


class RuleField(str, Enum):
    """比對目標欄位 (Target Field for Rule Evaluation)."""

    TITLE = "title"
    AUTHOR = "author"
    CONTENT = "content"
    URL = "url"
    FEED_TITLE = "feed_title"
    TAG = "tag"


class RuleOperator(str, Enum):
    """比對運算子 (Rule Comparison Operator)."""

    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    REGEX = "regex"


class RuleActionType(str, Enum):
    """觸發動作類型 (Triggered Action Type)."""

    MARK_READ = "mark_read"
    STAR = "star"
    TRASH = "trash"
    ADD_TAG = "add_tag"
    NOTIFY = "notify"
    AI_SUMMARY = "ai_summary"
    STOP_PROCESSING = "stop_processing"


class RuleCondition(BaseModel):
    """規則單一條件模型 (Single Rule Condition)."""

    field: RuleField
    operator: RuleOperator
    value: str
    case_sensitive: bool = False


class RuleAction(BaseModel):
    """規則觸發動作模型 (Triggered Action Model)."""

    action: RuleActionType
    params: dict[str, Any] = Field(default_factory=dict)


class RuleDef(BaseModel):
    """使用者自訂過濾規則完整定義 (User-Defined Filter Rule Definition)."""

    id: str
    rule_name: str
    priority: int = 0
    is_active: bool = True
    match_mode: MatchMode = MatchMode.ALL
    conditions: list[RuleCondition] = Field(default_factory=list)
    actions: list[RuleAction] = Field(default_factory=list)


class RuleEngine:
    """過濾與規則執行引擎 (Rule Filtering and Action Execution Engine)."""

    @classmethod
    def evaluate_condition(
        cls,
        condition: RuleCondition,
        article: ArticleDTO,
        feed_title: Optional[str] = None,
    ) -> bool:
        """評估單一條件是否命中 (Evaluate a single condition against an article).

        :param condition: 規則條件 (Condition)
        :param article: 待檢驗之文章 DTO (Article DTO)
        :param feed_title: 來源頻道名稱 (Optional feed title)
        :return: True 表條件滿足，False 表不滿足
        """
        # 1. 抽取欲比對之欄位字串 (Extract field string value)
        field_val = ""
        if condition.field == RuleField.TITLE:
            field_val = article.title or ""
        elif condition.field == RuleField.AUTHOR:
            field_val = article.author or ""
        elif condition.field == RuleField.CONTENT:
            field_val = (
                article.content_text
                or article.snippet
                or article.content_html
                or ""
            )
        elif condition.field == RuleField.URL:
            field_val = article.url or ""
        elif condition.field == RuleField.FEED_TITLE:
            field_val = feed_title or ""
        elif condition.field == RuleField.TAG:
            field_val = " ".join(article.extra_tags)

        # 2. 處理大小寫敏感性 (Handle case-sensitivity)
        target_val = condition.value
        if not condition.case_sensitive:
            field_val = field_val.lower()
            target_val = target_val.lower()

        # 3. 執行運算子比對 (Execute operator comparison)
        op = condition.operator
        if op == RuleOperator.CONTAINS:
            return target_val in field_val
        elif op == RuleOperator.NOT_CONTAINS:
            return target_val not in field_val
        elif op == RuleOperator.EQUALS:
            return field_val == target_val
        elif op == RuleOperator.NOT_EQUALS:
            return field_val != target_val
        elif op == RuleOperator.STARTS_WITH:
            return field_val.startswith(target_val)
        elif op == RuleOperator.ENDS_WITH:
            return field_val.endswith(target_val)
        elif op == RuleOperator.REGEX:
            flags = 0 if condition.case_sensitive else re.IGNORECASE
            try:
                pattern = re.compile(condition.value, flags=flags)
                return bool(pattern.search(field_val))
            except re.error as e:
                logger.warning(
                    f"Invalid regex pattern '{condition.value}' in rule evaluation: {e}"
                )
                return False

        return False

    @classmethod
    def evaluate_rule(
        cls,
        rule: RuleDef,
        article: ArticleDTO,
        feed_title: Optional[str] = None,
    ) -> bool:
        """評估整條規則是否命中 (Evaluate whether a rule matches an article).

        :param rule: 規則定義 (Rule definition)
        :param article: 文章 DTO (Article DTO)
        :param feed_title: 來源頻道標題 (Optional feed title)
        :return: True 表命中規則
        """
        if not rule.is_active or not rule.conditions:
            return False

        if rule.match_mode == MatchMode.ALL:
            # AND 邏輯：所有條件皆需符合
            return all(
                cls.evaluate_condition(cond, article, feed_title)
                for cond in rule.conditions
            )
        elif rule.match_mode == MatchMode.ANY:
            # OR 邏輯：任一條件符合即可
            return any(
                cls.evaluate_condition(cond, article, feed_title)
                for cond in rule.conditions
            )

        return False

    @classmethod
    def apply_actions(
        cls,
        actions: list[RuleAction],
        article: ArticleDTO,
    ) -> tuple[ArticleDTO, list[str], bool]:
        """對文章套用動作清單 (Apply actions to article).

        :param actions: 欲執行之動作清單 (List of actions)
        :param article: 目標文章 DTO (Target article DTO)
        :return: (變更後的 ArticleDTO, 執行的動作名稱清單, 是否中斷後續規則 stop_processing)
        """
        executed: list[str] = []
        stop_processing = False

        for act in actions:
            if act.action == RuleActionType.MARK_READ:
                article.is_read = True
                executed.append("mark_read")
            elif act.action == RuleActionType.STAR:
                article.is_starred = True
                executed.append("star")
            elif act.action == RuleActionType.TRASH:
                # 丟入垃圾桶：附加 [trashed] 標籤且設為已讀
                article.is_read = True
                if "trashed" not in article.extra_tags:
                    article.extra_tags.append("trashed")
                executed.append("trash")
            elif act.action == RuleActionType.ADD_TAG:
                tag_name = act.params.get("tag_name", "").strip()
                if tag_name and tag_name not in article.extra_tags:
                    article.extra_tags.append(tag_name)
                    executed.append(f"add_tag:{tag_name}")
            elif act.action == RuleActionType.NOTIFY:
                executed.append("notify")
            elif act.action == RuleActionType.AI_SUMMARY:
                executed.append("ai_summary")
            elif act.action == RuleActionType.STOP_PROCESSING:
                stop_processing = True
                executed.append("stop_processing")

        return article, executed, stop_processing

    @classmethod
    def process_article(
        cls,
        article: ArticleDTO,
        rules: list[RuleDef],
        feed_title: Optional[str] = None,
    ) -> tuple[ArticleDTO, list[str]]:
        """按照優先權由高至低依序套用所有作用中規則 (Process an article through all active rules in priority order).

        :param article: 輸入之文章 DTO (Input article DTO)
        :param rules: 使用者過濾規則清單 (List of user rules)
        :param feed_title: 來源頻道標題 (Optional feed title)
        :return: (處理後的 ArticleDTO, 所有已觸發動作摘要清單)
        """
        # 依優先權降序排序 (Sort by priority descending)
        sorted_rules = sorted(
            [r for r in rules if r.is_active],
            key=lambda x: x.priority,
            reverse=True,
        )

        all_executed_actions: list[str] = []
        current_article = article

        for rule in sorted_rules:
            if cls.evaluate_rule(rule, current_article, feed_title):
                logger.debug(
                    f"Rule '{rule.rule_name}' matched for article '{current_article.title}'"
                )
                current_article, executed, stop = cls.apply_actions(
                    rule.actions, current_article
                )
                all_executed_actions.extend(
                    [f"{rule.rule_name} -> {act}" for act in executed]
                )
                if stop:
                    logger.debug(
                        f"Rule '{rule.rule_name}' requested stop_processing; skipping remaining rules."
                    )
                    break

        return current_article, all_executed_actions
