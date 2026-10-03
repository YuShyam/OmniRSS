"""智慧過濾與規則引擎 (Intelligent Filtering & Rule Engine).

This module implements QuiteRSS-style conditional rule matching (Target Scope, AND/OR logic groups, regex,
field comparisons) and automated action execution (mark_read, mark_unread, star, unstar, trash, add_tag, set_color, notify).
"""

import logging
import re
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator

from omnirss.sdk.models import ArticleDTO

logger = logging.getLogger("omnirss.rules")


class MatchMode(str, Enum):
    """條件組合比對模式 (Condition Combination Match Mode)."""

    ALL = "all"  # AND 邏輯：所有條件皆須滿足
    ANY = "any"  # OR 邏輯：任一條件滿足即可


class RuleScopeType(str, Enum):
    """規則套用之新聞源範圍 (Target Feed Scope for Rule Evaluation)."""

    ALL = "all"  # 全域：所有訂閱頻道
    CATEGORY = "category"  # 特定分類
    FEEDS = "feeds"  # 指定頻道 (支援多選)


class RuleField(str, Enum):
    """比對目標欄位 (Target Field for Rule Evaluation)."""

    TITLE = "title"
    AUTHOR = "author"
    CONTENT = "content"
    CONTENT_HTML = "content_html"
    URL = "url"
    FEED_TITLE = "feed_title"
    TAG = "tag"
    IS_READ = "is_read"
    IS_STARRED = "is_starred"


class RuleOperator(str, Enum):
    """比對運算子 (Rule Comparison Operator)."""

    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    REGEX = "regex"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"


class RuleActionType(str, Enum):
    """觸發動作類型 (Triggered Action Type)."""

    MARK_READ = "mark_read"
    MARK_UNREAD = "mark_unread"
    STAR = "star"
    UNSTAR = "unstar"
    TRASH = "trash"
    RESTORE_TRASH = "restore_trash"
    ADD_TAG = "add_tag"
    ADD_TAGS = "add_tags"
    SET_COLOR = "set_color"
    NOTIFY = "notify"
    AI_SUMMARY = "ai_summary"
    EXECUTE_PLUGIN = "execute_plugin"
    RUN_PLUGIN = "run_plugin"
    STOP_PROCESSING = "stop_processing"


class RuleCondition(BaseModel):
    """規則單一條件模型 (Single Rule Condition)."""

    field: RuleField = RuleField.TITLE
    operator: RuleOperator = RuleOperator.CONTAINS
    value: str = ""
    case_sensitive: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_condition(cls, data: Any) -> Any:
        """防衛性解析字串或欄位別名 (Defensively normalize string or dict payload)."""
        if isinstance(data, str):
            return {
                "field": RuleField.TITLE,
                "operator": RuleOperator.CONTAINS,
                "value": data,
                "case_sensitive": False,
            }
        if isinstance(data, dict):
            field = data.get("field", "title")
            if field in ("content_text", "content_html"):
                data["field"] = "content"
            elif field in ("link",):
                data["field"] = "url"
            elif field in ("feed",):
                data["field"] = "feed_title"
            if "operator" not in data:
                data["operator"] = "contains"
            if "value" not in data:
                data["value"] = ""
        return data


class ConditionGroup(BaseModel):
    """條件邏輯群組模型 (Condition Group Model with Inner Match Mode)."""

    match_mode: MatchMode = MatchMode.ALL
    conditions: list[RuleCondition] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_group(cls, data: Any) -> Any:
        """防衛性轉換列表或字典結構 (Normalize list or dict to ConditionGroup)."""
        if isinstance(data, list):
            return {"match_mode": MatchMode.ALL, "conditions": data}
        if isinstance(data, dict):
            conds = data.get("conditions") or data.get("rules") or []
            mode = data.get("match_mode", "all")
            return {"match_mode": mode, "conditions": conds}
        return data


class RuleAction(BaseModel):
    """規則觸發動作模型 (Triggered Action Model)."""

    action: RuleActionType = RuleActionType.MARK_READ
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_action(cls, data: Any) -> Any:
        """防衛性解析字串或動作別名 (Defensively normalize string or dict payload)."""
        if isinstance(data, str):
            return {"action": data, "params": {}}
        if isinstance(data, dict):
            act = data.get("action") or data.get("action_type") or "mark_read"
            params = data.get("params") or data.get("parameters") or {}
            # 若為 set_color，將 hex 或 color 參數統一至 color
            if act == "set_color" and "color" not in params and "hex" in params:
                params["color"] = params["hex"]
            return {"action": act, "params": params}
        return data


class RuleDef(BaseModel):
    """使用者自訂過濾規則完整定義 (User-Defined Filter Rule Definition)."""

    id: str
    rule_name: str
    priority: int = 0
    is_active: bool = True
    scope_type: RuleScopeType = RuleScopeType.ALL
    scope_category_id: Optional[int] = None
    scope_feed_ids: list[int] = Field(default_factory=list)
    match_mode: MatchMode = MatchMode.ALL
    conditions: list[RuleCondition] = Field(default_factory=list)
    condition_groups: list[ConditionGroup] = Field(default_factory=list)
    actions: list[RuleAction] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_rule_def(cls, data: Any) -> Any:
        """防衛性相容別名欄位與型態 (Defensively normalize dictionary aliases into RuleDef)."""
        if isinstance(data, dict):
            data = dict(data)
            if "rule_name" not in data:
                data["rule_name"] = data.get("name") or data.get("title") or "未命名規則"
            if "id" not in data or data["id"] is None:
                data["id"] = str(data.get("rule_id") or "0")
            else:
                data["id"] = str(data["id"])
            if "priority" not in data:
                data["priority"] = data.get("sort_order", 0)
            if "is_active" not in data:
                data["is_active"] = data.get("is_enabled", True)
            if "scope_type" not in data:
                data["scope_type"] = data.get("scope", "all")
            if data.get("conditions") is None:
                data["conditions"] = []
            if data.get("condition_groups") is None:
                data["condition_groups"] = []
            if data.get("actions") is None:
                data["actions"] = []
        return data

    @model_validator(mode="after")
    def sync_condition_groups(self) -> "RuleDef":
        """同步平坦條件與條件群組模型 (Ensure condition groups consistency)."""
        if not self.condition_groups and self.conditions:
            self.condition_groups = [
                ConditionGroup(match_mode=self.match_mode, conditions=self.conditions)
            ]
        elif self.condition_groups and not self.conditions:
            # 平坦收集所有條件供舊版 API 相容存取
            flat: list[RuleCondition] = []
            for g in self.condition_groups:
                flat.extend(g.conditions)
            self.conditions = flat
        return self


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
        elif condition.field == RuleField.CONTENT_HTML:
            field_val = article.content_html or ""
        elif condition.field == RuleField.URL:
            field_val = article.url or ""
        elif condition.field == RuleField.FEED_TITLE:
            field_val = feed_title or ""
        elif condition.field == RuleField.TAG:
            field_val = " ".join(article.extra_tags)
        elif condition.field == RuleField.IS_READ:
            field_val = "read" if article.is_read else "unread"
        elif condition.field == RuleField.IS_STARRED:
            field_val = "starred" if article.is_starred else "unstarred"

        # 2. 處理大小寫敏感性 (Handle case-sensitivity)
        target_val = condition.value
        if not condition.case_sensitive:
            field_val = field_val.lower()
            target_val = target_val.lower()

        # 3. 執行運算子比對 (Execute operator comparison)
        op = condition.operator
        if op == RuleOperator.IS_EMPTY:
            return field_val.strip() == ""
        elif op == RuleOperator.IS_NOT_EMPTY:
            return field_val.strip() != ""
        elif op == RuleOperator.CONTAINS:
            return target_val in field_val
        elif op == RuleOperator.NOT_CONTAINS:
            if target_val == "":
                return field_val.strip() != ""
            return target_val not in field_val
        elif op == RuleOperator.EQUALS:
            if target_val == "":
                return field_val.strip() == ""
            return field_val == target_val
        elif op == RuleOperator.NOT_EQUALS:
            if target_val == "":
                return field_val.strip() != ""
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
    def evaluate_condition_group(
        cls,
        group: ConditionGroup,
        article: ArticleDTO,
        feed_title: Optional[str] = None,
    ) -> bool:
        """評估單一條件群組內部是否命中 (Evaluate a single condition group).

        :param group: 條件群組 (Condition Group)
        :param article: 文章 DTO
        :param feed_title: 來源頻道標題
        :return: True 表該群組條件滿足
        """
        if not group.conditions:
            return True

        if group.match_mode == MatchMode.ALL:
            return all(
                cls.evaluate_condition(cond, article, feed_title)
                for cond in group.conditions
            )
        elif group.match_mode == MatchMode.ANY:
            return any(
                cls.evaluate_condition(cond, article, feed_title)
                for cond in group.conditions
            )
        return False

    @classmethod
    def evaluate_rule(
        cls,
        rule: RuleDef,
        article: ArticleDTO,
        feed_id: Optional[int] = None,
        category_id: Optional[int] = None,
        feed_title: Optional[str] = None,
    ) -> bool:
        """評估整條規則是否命中 (Evaluate whether a rule matches an article with Scope and Groups).

        :param rule: 規則定義 (Rule definition)
        :param article: 文章 DTO (Article DTO)
        :param feed_id: 來源頻道 ID (Optional feed ID)
        :param category_id: 所屬分類 ID (Optional category ID)
        :param feed_title: 來源頻道標題 (Optional feed title)
        :return: True 表命中規則
        """
        if not rule.is_active:
            return False

        # 1. 新聞源範圍 Scope 比對 (Target Feed Scope Evaluation)
        if rule.scope_type == RuleScopeType.CATEGORY:
            if rule.scope_category_id is not None and category_id is not None:
                if int(category_id) != int(rule.scope_category_id):
                    return False
        elif rule.scope_type == RuleScopeType.FEEDS:
            if rule.scope_feed_ids and feed_id is not None:
                feed_ids_int = [int(fid) for fid in rule.scope_feed_ids]
                if int(feed_id) not in feed_ids_int:
                    return False

        # 2. 條件群組評估 (Condition Groups Evaluation - Multi-groups connected via AND)
        groups = rule.condition_groups
        if not groups and rule.conditions:
            groups = [ConditionGroup(match_mode=rule.match_mode, conditions=rule.conditions)]

        if not groups:
            return False

        # 外層多個群組必須全部滿足 (AND across groups)
        return all(
            cls.evaluate_condition_group(grp, article, feed_title)
            for grp in groups
        )

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
            elif act.action == RuleActionType.MARK_UNREAD:
                article.is_read = False
                executed.append("mark_unread")
            elif act.action == RuleActionType.STAR:
                article.is_starred = True
                executed.append("star")
            elif act.action == RuleActionType.UNSTAR:
                article.is_starred = False
                executed.append("unstar")
            elif act.action == RuleActionType.TRASH:
                # 丟入垃圾桶：附加 [trashed] 標籤且設為已讀
                article.is_read = True
                if "trashed" not in article.extra_tags:
                    article.extra_tags.append("trashed")
                executed.append("trash")
            elif act.action == RuleActionType.RESTORE_TRASH:
                if "trashed" in article.extra_tags:
                    article.extra_tags.remove("trashed")
                executed.append("restore_trash")
            elif act.action == RuleActionType.SET_COLOR:
                # QuiteRSS 底色高亮自訂標色
                color = str(act.params.get("color") or act.params.get("hex") or "").strip()
                article.highlight_color = color if color else None
                executed.append(f"set_color:{color}")
            elif act.action == RuleActionType.ADD_TAG:
                tag_name = (act.params.get("tag_name") or act.params.get("tag") or "").strip()
                if tag_name and tag_name not in article.extra_tags:
                    article.extra_tags.append(tag_name)
                    executed.append(f"add_tag:{tag_name}")
            elif act.action == RuleActionType.ADD_TAGS:
                tags_input = act.params.get("tags") or []
                if isinstance(tags_input, str):
                    tags_list = [t.strip() for t in tags_input.replace(",", " ").split() if t.strip()]
                elif isinstance(tags_input, list):
                    tags_list = [str(t).strip() for t in tags_input if str(t).strip()]
                else:
                    tags_list = []
                for t in tags_list:
                    if t and t not in article.extra_tags:
                        article.extra_tags.append(t)
                        executed.append(f"add_tag:{t}")
            elif act.action == RuleActionType.NOTIFY:
                executed.append("notify")
            elif act.action == RuleActionType.AI_SUMMARY:
                preset = str(act.params.get("preset") or act.params.get("preset_id") or act.params.get("param") or "").strip()
                if preset:
                    executed.append(f"execute_plugin:omnirss/gemini-summary:{preset}")
                else:
                    executed.append("execute_plugin:omnirss/gemini-summary")
            elif act.action in (RuleActionType.EXECUTE_PLUGIN, RuleActionType.RUN_PLUGIN):
                p_id = str(act.params.get("plugin_id") or act.params.get("id") or "").strip()
                if not p_id:
                    # 未指定 plugin_id 則跳過，不硬編碼任何外掛作為預設值
                    executed.append("execute_plugin:skipped:missing_plugin_id")
                    continue
                param = str(act.params.get("param") or act.params.get("preset") or act.params.get("preset_id") or "").strip()
                if param:
                    executed.append(f"execute_plugin:{p_id}:{param}")
                else:
                    executed.append(f"execute_plugin:{p_id}")
            elif act.action == RuleActionType.STOP_PROCESSING:
                stop_processing = True
                executed.append("stop_processing")

        return article, executed, stop_processing

    @classmethod
    def process_article(
        cls,
        article: ArticleDTO,
        rules: list[RuleDef],
        feed_id: Optional[int] = None,
        category_id: Optional[int] = None,
        feed_title: Optional[str] = None,
    ) -> tuple[ArticleDTO, list[str]]:
        """按照優先權由高至低依序套用所有作用中規則 (Process an article through all active rules in priority order).

        :param article: 輸入之文章 DTO (Input article DTO)
        :param rules: 使用者過濾規則清單 (List of user rules)
        :param feed_id: 來源頻道 ID (Optional feed ID)
        :param category_id: 所屬分類 ID (Optional category ID)
        :param feed_title: 來源頻道標題 (Optional feed title)
        :return: (處理後的 ArticleDTO, 所有已觸發動作摘要清單)
        """
        # 依優先權降序排序 (Sort by priority descending)
        normalized_rules: list[RuleDef] = []
        for r in rules:
            if isinstance(r, RuleDef):
                normalized_rules.append(r)
            elif isinstance(r, dict):
                normalized_rules.append(RuleDef.model_validate(r))

        sorted_rules = sorted(
            [r for r in normalized_rules if r.is_active],
            key=lambda x: x.priority,
            reverse=True,
        )

        all_executed_actions: list[str] = []
        current_article = article

        for rule in sorted_rules:
            if cls.evaluate_rule(
                rule,
                current_article,
                feed_id=feed_id,
                category_id=category_id,
                feed_title=feed_title,
            ):
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
