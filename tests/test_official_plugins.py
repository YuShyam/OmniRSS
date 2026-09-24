"""官方 4 大外掛單元與整合測試 (Official Plugins Unit & Integration Tests).

Tests Gemini Summary, SimHash Deduplication, Generic Scraper, and Gomaji Deals plugins.
"""

from datetime import datetime, timezone
import pytest
from omnirss.core.plugin_manager import PluginManager
from omnirss.sdk.models import ArticleDTO
from plugins.processors.gemini_summary.plugin import GeminiSummaryProcessorPlugin
from plugins.processors.simhash_dedup.plugin import SimHashProcessorPlugin
from plugins.sources.generic_scraper.plugin import GenericScraperPlugin
from plugins.sources.gomaji.plugin import GomajiDealsPlugin


@pytest.mark.asyncio
async def test_simhash_dedup_plugin() -> None:
    """測試 SimHash 轉貼去重外掛 (Test SimHash deduplication processor)."""
    plugin = SimHashProcessorPlugin(
        plugin_id="omnirss/simhash-dedup",
        config={
            "hamming_distance_threshold": 3,
            "action_mode": "cluster",
            "auto_tag_name": "轉貼報導",
        },
    )
    await plugin.initialize()

    article1 = ArticleDTO(
        title="科技巨頭發表最新一代量子運算晶片，運算效能提升千倍",
        url="https://news-a.com/quantum-1",
        feed_url="https://news-a.com/rss",
        content_text="科技巨頭今日正式發表新一代量子運算處理器，具備超導量子位元架構，突破低溫散熱瓶頸。",
        published_at=datetime.now(timezone.utc),
    )

    # 處理第一篇文章 (基準)
    res1 = await plugin.process(article1)
    assert res1 is not None
    assert "轉貼報導" not in res1.custom_tags

    # 第二篇內容極度相似之文章 (抄襲/轉貼)
    article2 = ArticleDTO(
        title="科技巨頭發表最新一代量子運算晶片，運算效能大幅提升千倍",
        url="https://news-b.com/quantum-repost",
        feed_url="https://news-b.com/rss",
        content_text="科技巨頭今日正式發表新一代量子運算處理器，具備超導量子位元架構，突破低溫散熱瓶頸！",
        published_at=datetime.now(timezone.utc),
    )

    res2 = await plugin.process(article2)
    assert res2 is not None
    assert "轉貼報導" in res2.custom_tags, "SimHash 應精準偵測轉貼並自動附加標籤"


@pytest.mark.asyncio
async def test_gemini_summary_plugin_fallback() -> None:
    """測試 Gemini 摘要外掛之繁中條列摘要 (Test Gemini summary fallback)."""
    plugin = GeminiSummaryProcessorPlugin(
        plugin_id="omnirss/gemini-summary",
        config={
            "api_key": "",
            "summary_bullets": 3,
        },
    )
    await plugin.initialize()

    long_text = (
        "微核心架構是現代作業系統與高可靠性中介軟體的設計典範。\n"
        "透過將非關鍵模組移出核心空間，顯著減少了單點崩潰對全系統的影響。\n"
        "在 RSS 閱讀器領域，微核心搭配 SQLite WAL 能夠兼顧極致效能與資料安全。\n"
        "結合 Anti-SSRF 網關更能有效防禦內部網路探測攻擊。"
    )

    article = ArticleDTO(
        title="微核心架構深度解析",
        url="https://tech.local/microkernel",
        feed_url="https://tech.local/rss",
        content_text=long_text,
        published_at=datetime.now(timezone.utc),
    )

    res = await plugin.process(article)
    assert res is not None
    assert res.ai_summary is not None
    assert "-" in res.ai_summary
    assert len(res.ai_summary.split("\n")) <= 4


@pytest.mark.asyncio
async def test_plugin_manager_discovery() -> None:
    """測試全外掛目錄自動掃描與載入 (Test full plugins directory discovery)."""
    from pathlib import Path
    plugins_dir = Path(__file__).resolve().parents[1] / "plugins"
    pm = PluginManager(plugins_dir)
    count = pm.discover_and_load()
    assert count >= 4, f"應至少成功載入 4 個官方外掛，實際載入: {count}"

    manifests = pm.list_manifests()
    assert "omnirss/gemini-summary" in manifests
    assert "omnirss/simhash-dedup" in manifests
    assert "omnirss/generic-scraper" in manifests
    assert "omnirss/gomaji-deals" in manifests


class MockResponse:
    """模擬 HTTP 回應物件 (Mock HTTP Response)."""

    def __init__(self, text: str, headers: dict | None = None) -> None:
        self.text = text
        self.headers = headers or {"content-type": "text/html"}


class MockHttpClient:
    """模擬非同步 HTTP 客戶端 (Mock Async HTTP Client)."""

    def __init__(self, response: MockResponse) -> None:
        self._response = response

    async def get(self, url: str) -> MockResponse:
        return self._response


@pytest.mark.asyncio
async def test_generic_scraper_json_parsing() -> None:
    """測試通用爬蟲外掛 JSON 解析 (Test generic scraper JSON feed parsing)."""
    import json
    from omnirss.sdk.context import PluginContext

    plugin = GenericScraperPlugin(plugin_id="omnirss/generic-scraper")
    json_payload = json.dumps([
        {
            "title": "量子運算晶片研發新突破",
            "url": "https://tech.org/posts/quantum-v2",
            "content": "研究團隊突破低溫超導技術，效能大幅躍進。",
            "cover": "https://tech.org/cover.png",
        }
    ])
    ctx = PluginContext(
        plugin_id="omnirss/generic-scraper",
        config={},
        http_client=MockHttpClient(
            MockResponse(json_payload, {"content-type": "application/json"})
        ),
    )
    articles = await plugin.fetch("https://api.tech.org/feed.json", context=ctx)
    assert len(articles) == 1
    assert articles[0].title == "量子運算晶片研發新突破"
    assert articles[0].url == "https://tech.org/posts/quantum-v2"
    assert articles[0].cover_image_url == "https://tech.org/cover.png"


@pytest.mark.asyncio
async def test_gomaji_deals_html_parsing() -> None:
    """測試 Gomaji 優惠情報外掛 HTML 解析 (Test Gomaji deals HTML parsing)."""
    from omnirss.sdk.context import PluginContext

    plugin = GomajiDealsPlugin(
        plugin_id="omnirss/gomaji-deals",
        config={"auto_tag": "超值團購"},
    )
    html_payload = """
    <html>
      <body>
        <div class="product-card">
          <a href="/store/12345">【台北君悅酒店】凱菲屋平日雙人吃到飽</a>
          <img src="//img.gomaji.com/cover.jpg" />
          <span>優惠特價 1999 元</span>
        </div>
      </body>
    </html>
    """
    ctx = PluginContext(
        plugin_id="omnirss/gomaji-deals",
        config={"auto_tag": "超值團購"},
        http_client=MockHttpClient(
            MockResponse(html_payload, {"content-type": "text/html"})
        ),
    )
    articles = await plugin.fetch("https://www.gomaji.com/taipei", context=ctx)
    assert len(articles) == 1
    assert "台北君悅酒店" in articles[0].title
    assert articles[0].url == "https://www.gomaji.com/store/12345"
    assert "超值團購" in articles[0].custom_tags
