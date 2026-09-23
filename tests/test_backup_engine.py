"""備份與 OPML 引擎單元測試 (Backup & OPML Engine Unit Tests).

Tests OPML 2.0 hierarchical import/export and sanitized backup redaction.
"""

import pytest
from omnirss.core.backup_engine import BackupEngine

SAMPLE_OPML = """<?xml version="1.0" encoding="utf-8"?>
<opml version="2.0">
  <head>
    <title>My Subscriptions</title>
  </head>
  <body>
    <outline text="科技資訊" title="科技資訊">
      <outline type="rss" text="iThome" title="iThome" xmlUrl="https://www.ithome.com.tw/rss" htmlUrl="https://www.ithome.com.tw"/>
      <outline type="rss" text="TechNews" title="TechNews" xmlUrl="https://technews.tw/feed/" htmlUrl="https://technews.tw"/>
    </outline>
    <outline type="rss" text="獨立部落格" title="獨立部落格" xmlUrl="https://blog.example.com/feed.xml" htmlUrl="https://blog.example.com"/>
  </body>
</opml>
"""


def test_parse_opml_hierarchy():
    """測試 OPML 2.0 階層目錄匯入解析 (Test OPML 2.0 hierarchical import)."""
    items = BackupEngine.parse_opml(SAMPLE_OPML)

    assert len(items) == 3

    # 1. 科技資訊/iThome
    item1 = items[0]
    assert item1.category_name == "科技資訊"
    assert item1.feed.title == "iThome"
    assert item1.feed.feed_url == "https://www.ithome.com.tw/rss"
    assert item1.feed.site_url == "https://www.ithome.com.tw"

    # 2. 科技資訊/TechNews
    item2 = items[1]
    assert item2.category_name == "科技資訊"
    assert item2.feed.title == "TechNews"

    # 3. 未分類/獨立部落格
    item3 = items[2]
    assert item3.category_name is None
    assert item3.feed.title == "獨立部落格"
    assert item3.feed.feed_url == "https://blog.example.com/feed.xml"


def test_generate_opml_roundtrip():
    """測試 OPML 生成並重新解析之往返一致性 (Test OPML generation and parse roundtrip)."""
    feeds = [
        {
            "title": "新聞網",
            "feed_url": "https://news.example.com/rss",
            "site_url": "https://news.example.com",
            "category_name": "即時新聞",
        },
        {
            "title": "個人日誌",
            "feed_url": "https://me.example.com/atom",
            "site_url": "https://me.example.com",
            "category_name": None,
        },
    ]

    generated_xml = BackupEngine.generate_opml(feeds, title="OmniRSS Export Test")
    assert "<opml version=\"2.0\">" in generated_xml
    assert "即時新聞" in generated_xml
    assert "https://news.example.com/rss" in generated_xml

    # 重新解析驗證
    reparsed = BackupEngine.parse_opml(generated_xml)
    assert len(reparsed) == 2
    assert reparsed[0].category_name == "即時新聞"
    assert reparsed[0].feed.title == "新聞網"
    assert reparsed[1].category_name is None
    assert reparsed[1].feed.title == "個人日誌"


def test_sanitized_user_backup():
    """測試機敏金鑰與密碼脫敏 (Test sensitive credentials redaction)."""
    user_settings = {
        "theme": "dark",
        "api_key": "secret-xyz-123456",
        "nested": {
            "jwt_token_secret": "my-ultra-secret-key",
            "display_language": "zh-TW",
        },
    }
    rules = [{"id": "r1", "name": "過濾"}]
    feeds = [{"url": "https://test.com/feed"}]
    plugin_configs = [{"plugin_id": "gemini", "gemini_api_key": "AIzaSy..."}]

    backup_pkg = BackupEngine.export_user_backup(
        user_id="user-001",
        user_settings=user_settings,
        rules=rules,
        feeds=feeds,
        plugin_configs=plugin_configs,
    )

    assert backup_pkg["settings"]["theme"] == "dark"
    assert backup_pkg["settings"]["api_key"] == "[REDACTED]"
    assert backup_pkg["settings"]["nested"]["jwt_token_secret"] == "[REDACTED]"
    assert backup_pkg["settings"]["nested"]["display_language"] == "zh-TW"
    assert backup_pkg["plugin_configs"][0]["gemini_api_key"] == "[REDACTED]"
