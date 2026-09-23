"""資料便攜備份引擎 (Data Portability & Backup Engine).

This module implements OPML 2.0 bidirectional hierarchical import/export,
as well as sanitized user settings backup and restore functionality.
"""

import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Optional
from xml.dom import minidom
try:
    import defusedxml.ElementTree as DefusedET
except ImportError:
    import xml.etree.ElementTree as DefusedET

from omnirss.sdk.models import FeedDTO

logger = logging.getLogger("omnirss.backup")

# 機敏設定關鍵字 (Sensitive Keys to be Redacted in Backup)
SENSITIVE_KEY_SUBSTRINGS = {
    "secret",
    "password",
    "api_key",
    "token",
    "private_key",
    "credential",
    "auth",
}


class OpmlImportItem:
    """OPML 匯入條目模型 (OPML Import Item)."""

    def __init__(
        self,
        feed: FeedDTO,
        category_name: Optional[str] = None,
    ) -> None:
        self.feed = feed
        self.category_name = category_name

    def __repr__(self) -> str:
        return f"<OpmlImportItem category='{self.category_name}' title='{self.feed.title}' url='{self.feed.feed_url}'>"


class BackupEngine:
    """資料備份與 OPML 轉換引擎 (Backup and OPML Transformation Engine)."""

    @classmethod
    def parse_opml(cls, opml_content: str | bytes) -> list[OpmlImportItem]:
        """安全解析 OPML 2.0 字串或位元組並還原階層目錄 (Parse OPML 2.0 with hierarchy).

        :param opml_content: OPML XML 字串或位元組 (OPML XML payload)
        :return: 解析後的 OpmlImportItem 清單
        """
        if isinstance(opml_content, str):
            opml_bytes = opml_content.encode("utf-8")
        else:
            opml_bytes = opml_content

        # 使用 defusedxml 安全解析防禦實體擴展攻擊 (Safely parse with defusedxml)
        root = DefusedET.fromstring(opml_bytes)

        body = root.find("body")
        if body is None:
            return []

        results: list[OpmlImportItem] = []

        def _traverse_outline(
            element: ET.Element, current_category: Optional[str]
        ) -> None:
            for outline in element.findall("outline"):
                xml_url = outline.get("xmlUrl") or outline.get("xmlurl")
                text = outline.get("text") or outline.get("title") or ""
                html_url = outline.get("htmlUrl") or outline.get("htmlurl")
                description = outline.get("description")

                if xml_url:
                    # 此節點為具體 RSS 訂閱源 (Feed leaf node)
                    feed = FeedDTO(
                        title=text or xml_url,
                        feed_url=xml_url,
                        site_url=html_url,
                        description=description,
                        category_name=current_category,
                    )
                    results.append(
                        OpmlImportItem(
                            feed=feed, category_name=current_category
                        )
                    )
                else:
                    # 此節點為分類資料夾目錄 (Category folder node)
                    folder_name = text.strip() if text else "未分類"
                    # 遞迴走訪子節點 (Recursive traversal)
                    _traverse_outline(outline, current_category=folder_name)

        _traverse_outline(body, current_category=None)
        return results

    @classmethod
    def generate_opml(
        cls,
        feeds: list[dict[str, Any]],
        title: str = "OmniRSS Subscriptions Export",
    ) -> str:
        """根據分類結構生成符合 OPML 2.0 規範之 XML (Generate OPML 2.0 XML string).

        :param feeds: 訂閱頻道字典清單 (List of feed dicts with 'title', 'feed_url', 'site_url', 'category_name')
        :param title: OPML 匯出標題 (Export title)
        :return: 格式化後之 OPML 2.0 XML 字串
        """
        now_str = datetime.now(timezone.utc).strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )

        opml = ET.Element("opml", version="2.0")
        head = ET.SubElement(opml, "head")
        ET.SubElement(head, "title").text = title
        ET.SubElement(head, "dateCreated").text = now_str
        ET.SubElement(head, "docs").text = "http://opml.org/spec2.opml"

        body = ET.SubElement(opml, "body")

        # 依分類分組 (Group by category)
        categories_map: dict[str, list[dict[str, Any]]] = {}
        uncategorized: list[dict[str, Any]] = []

        for f in feeds:
            cat = f.get("category_name")
            if cat and cat.strip():
                categories_map.setdefault(cat.strip(), []).append(f)
            else:
                uncategorized.append(f)

        # 輸出具分類之資料夾 (Output categorized folders)
        for cat_name, cat_feeds in sorted(categories_map.items()):
            folder_elem = ET.SubElement(
                body,
                "outline",
                text=cat_name,
                title=cat_name,
            )
            for f in cat_feeds:
                attrs = {
                    "type": "rss",
                    "text": f.get("title", ""),
                    "title": f.get("title", ""),
                    "xmlUrl": f.get("feed_url", ""),
                }
                if f.get("site_url"):
                    attrs["htmlUrl"] = f["site_url"]
                if f.get("description"):
                    attrs["description"] = f["description"]
                ET.SubElement(folder_elem, "outline", **attrs)

        # 輸出未分類之獨立頻道 (Output uncategorized feeds directly in body)
        for f in uncategorized:
            attrs = {
                "type": "rss",
                "text": f.get("title", ""),
                "title": f.get("title", ""),
                "xmlUrl": f.get("feed_url", ""),
            }
            if f.get("site_url"):
                attrs["htmlUrl"] = f["site_url"]
            if f.get("description"):
                attrs["description"] = f["description"]
            ET.SubElement(body, "outline", **attrs)

        # 美化排版輸出 (Pretty print XML)
        rough_string = ET.tostring(opml, encoding="utf-8")
        parsed_dom = minidom.parseString(rough_string)
        return parsed_dom.toprettyxml(indent="  ", encoding="utf-8").decode(
            "utf-8"
        )

    @classmethod
    def redact_sensitive_data(cls, data: Any) -> Any:
        """遞迴脫敏機敏設定欄位 (Recursively redact sensitive fields).

        :param data: 任意巢狀字典、清單或基本資料型態
        :return: 脫敏後的資料結構 (Sanitized data with [REDACTED] tokens)
        """
        if isinstance(data, dict):
            sanitized: dict[str, Any] = {}
            for k, v in data.items():
                is_sensitive = any(
                    sub in k.lower() for sub in SENSITIVE_KEY_SUBSTRINGS
                )
                if is_sensitive and isinstance(v, (str, int, float, bool)):
                    sanitized[k] = "[REDACTED]"
                else:
                    sanitized[k] = cls.redact_sensitive_data(v)
            return sanitized
        elif isinstance(data, list):
            return [cls.redact_sensitive_data(item) for item in data]
        return data

    @classmethod
    def export_user_backup(
        cls,
        user_id: str,
        user_settings: dict[str, Any],
        rules: list[dict[str, Any]],
        feeds: list[dict[str, Any]],
        plugin_configs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """產出脫敏之使用者全套備份資料包 (Generate sanitized full user backup package).

        :param user_id: 使用者唯一識別碼 (User ID)
        :param user_settings: 個人偏好設定 (User preferences)
        :param rules: 過濾規則清單 (User rules list)
        :param feeds: 訂閱頻道清單 (Subscribed feeds list)
        :param plugin_configs: 個人外掛配置清單 (User plugin configs list)
        :return: 脫敏後的備份 JSON 字典
        """
        raw_package = {
            "version": "1.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "settings": user_settings,
            "rules": rules,
            "feeds": feeds,
            "plugin_configs": plugin_configs,
        }
        return cls.redact_sensitive_data(raw_package)
