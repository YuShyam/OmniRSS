"""爬蟲引擎單元測試 (Crawler Engine Unit Tests).

Tests Auto-Referer extraction, exponential backoff calculation, feed parsing,
and 3-stage fallback mechanisms.
"""

import pytest
from datetime import datetime, timezone, timedelta
from omnirss.core.crawler_engine import (
    CrawlerEngine,
    get_origin_referer,
    calculate_next_check_time,
)

SAMPLE_RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>OmniRSS Tech News</title>
    <link>https://tech.example.com</link>
    <description>Latest technology news and benchmarks</description>
    <item>
      <title>Python 3.13 Released with Faster JIT</title>
      <link>https://tech.example.com/posts/python-313</link>
      <guid>tech-post-101</guid>
      <pubDate>Wed, 23 Sep 2026 12:00:00 GMT</pubDate>
      <description>&lt;p&gt;Python 3.13 introduces experimental JIT compiler.&lt;/p&gt;&lt;script&gt;alert('xss')&lt;/script&gt;</description>
      <author>lead_engineer@example.com</author>
      <category>Python</category>
    </item>
  </channel>
</rss>
"""

SAMPLE_ATOM_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>OmniRSS Atom Feed</title>
  <link href="https://atom.example.com"/>
  <updated>2026-09-23T14:00:00Z</updated>
  <id>urn:uuid:60a76c80-d399-11d9-b91C-0003939e0af6</id>
  <entry>
    <title>SQLite WAL Mode Scaling Guide</title>
    <link href="https://atom.example.com/sqlite-wal"/>
    <id>tag:atom.example.com,2026:sqlite-wal</id>
    <updated>2026-09-23T14:00:00Z</updated>
    <summary>Deep dive into SQLite WAL concurrency.</summary>
    <content type="html">&lt;p&gt;WAL mode enables concurrent reads while writing.&lt;/p&gt;</content>
  </entry>
</feed>
"""


def test_auto_referer_extraction():
    """測試 Auto-Referer 根網域抽取 (Test Auto-Referer root origin extraction)."""
    assert get_origin_referer("https://www.mobile01.com/rss/news.xml") == "https://www.mobile01.com/"
    assert get_origin_referer("http://example.org:8080/feed/rss") == "http://example.org:8080/"


def test_exponential_backoff_calculation():
    """測試錯誤指數退避演算法 (Test exponential backoff with jitter)."""
    base_time = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)

    # 0 次錯誤：延遲約等於 60 分鐘
    t0 = calculate_next_check_time(60, error_count=0, base_time=base_time)
    diff0 = (t0 - base_time).total_seconds() / 60
    assert 50 <= diff0 <= 70

    # 3 次錯誤：2^3 = 8 倍延遲 (60 * 8 = 480 分鐘)
    t3 = calculate_next_check_time(60, error_count=3, base_time=base_time)
    diff3 = (t3 - base_time).total_seconds() / 60
    assert 400 <= diff3 <= 550

    # 10 次錯誤：鉗制在上限 1440 分鐘 (24小時)
    t10 = calculate_next_check_time(60, error_count=10, base_time=base_time)
    diff10 = (t10 - base_time).total_seconds() / 60
    assert 1200 <= diff10 <= 1600


def test_parse_rss_feed_and_sanitization():
    """測試 RSS 2.0 解析與 HTML 脫毒 (Test RSS 2.0 parsing and script defanging)."""
    crawler = CrawlerEngine()
    articles, feed_meta = crawler.parse_feed_content(SAMPLE_RSS_XML, "https://tech.example.com/rss")

    assert feed_meta is not None
    assert feed_meta.title == "OmniRSS Tech News"
    assert feed_meta.site_url == "https://tech.example.com"

    assert len(articles) == 1
    art = articles[0]
    assert art.guid == "tech-post-101"
    assert art.title == "Python 3.13 Released with Faster JIT"
    assert art.url == "https://tech.example.com/posts/python-313"
    assert "alert" not in art.content_html
    assert "<script>" not in art.content_html
    assert "Python" in art.extra_tags


def test_parse_atom_feed():
    """測試 Atom 格式解析 (Test Atom feed parsing)."""
    crawler = CrawlerEngine()
    articles, feed_meta = crawler.parse_feed_content(SAMPLE_ATOM_XML, "https://atom.example.com/atom.xml")

    assert feed_meta is not None
    assert feed_meta.title == "OmniRSS Atom Feed"

    assert len(articles) == 1
    art = articles[0]
    assert art.title == "SQLite WAL Mode Scaling Guide"
    assert art.guid == "tag:atom.example.com,2026:sqlite-wal"
    assert "WAL mode enables" in art.content_text


def test_extract_full_text_from_html():
    """測試 Trafilatura HTML 內文萃取 (Test Trafilatura full text extraction)."""
    html = """
    <html>
      <head><title>Test Article</title></head>
      <body>
        <nav><a href="/">Home</a></nav>
        <main>
          <h1>Real Deep Article</h1>
          <p>This is the essential paragraph containing vital information.</p>
        </main>
        <footer>Copyright 2026</footer>
      </body>
    </html>
    """
    text = CrawlerEngine.extract_full_text_from_html(html, "https://example.com/article")
    assert text is not None
    assert "essential paragraph" in text


def test_raw_image_url_conversion():
    """測試純圖片網址轉為 img 標籤 (Test bare image URL conversion)."""
    crawler = CrawlerEngine()
    feed_with_image = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Photo Feed</title>
        <link>https://photo.example.com</link>
        <item>
          <title>Sunset Photo</title>
          <link>https://photo.example.com/sunset</link>
          <guid>photo-1</guid>
          <description>https://photo.example.com/images/sunset.jpg</description>
        </item>
      </channel>
    </rss>
    """
    articles, _ = crawler.parse_feed_content(feed_with_image, "https://photo.example.com/rss")
    assert len(articles) == 1
    assert "<img src=\"https://photo.example.com/images/sunset.jpg\"" in articles[0].content_html
