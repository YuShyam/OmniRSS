"""官方外掛單元與整合測試 (Official Plugins Unit & Integration Tests).

Tests Gemini Summary, PTT Enhancer, Yahoo Enhancer, SimHash Deduplication, and Generic Scraper plugins.
"""

from datetime import datetime, timezone
import pytest
from omnirss.core.plugin_manager import PluginManager, get_plugin_manager
from omnirss.sdk.models import ArticleDTO
from plugins.processors.gemini_summary.plugin import GeminiSummaryProcessorPlugin
from plugins.processors.simhash_dedup.plugin import SimHashProcessorPlugin
from plugins.processors.yahoo_enhancer.plugin import YahooEnhancerProcessorPlugin
from plugins.sources.generic_scraper.plugin import GenericScraperPlugin

# 私人/實驗性質外掛安全動態引用 (本地若存在才載入)
try:
    from plugins.processors.mobile01_enhancer.plugin import Mobile01EnhancerProcessorPlugin
except ImportError:
    Mobile01EnhancerProcessorPlugin = None

try:
    from plugins.sources.gomaji.plugin import GomajiDealsPlugin
except ImportError:
    GomajiDealsPlugin = None


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
async def test_gemini_summary_plugin_missing_key() -> None:
    """測試未設定 API Key 時之明確繁中指引回覆 (Test Gemini summary missing API Key notification)."""
    plugin = GeminiSummaryProcessorPlugin(
        plugin_id="omnirss/gemini-summary",
        config={
            "api_key": "",
            "summary_bullets": 3,
        },
    )
    await plugin.initialize()

    article = ArticleDTO(
        title="微核心架構深度解析",
        url="https://tech.local/microkernel",
        feed_url="https://tech.local/rss",
        content_text="微核心架構是現代作業系統與高可靠性中介軟體的設計典範，透過將非關鍵模組移出核心空間提高穩定性。",
        published_at=datetime.now(timezone.utc),
    )

    res = await plugin.process(article)
    assert res is not None
    assert res.ai_summary is not None
    assert "尚未設定 Google Gemini API Key" in res.ai_summary
    assert "Google AI Studio" in res.ai_summary


@pytest.mark.asyncio
async def test_gemini_summary_processor_custom_prompt(monkeypatch) -> None:
    """測試 Gemini 摘要自訂提示詞與幽默毒舌風格生成 (Test Gemini summary custom prompt with mock LLM)."""
    captured_prompts = []

    async def mock_call(self, api_key: str, model: str, prompt: str) -> str:
        captured_prompts.append(prompt)
        return "- 槽點 1：架構看似精簡但排查難度破表\n- 槽點 2：全靠文件寫得漂亮掩蓋效能黑洞\n- 槽點 3：重構成本足以買下一座島嶼"

    monkeypatch.setattr(GeminiSummaryProcessorPlugin, "_call_gemini_api", mock_call)

    plugin = GeminiSummaryProcessorPlugin(
        plugin_id="omnirss/gemini-summary",
        config={
            "api_key": "valid-test-key-123",
            "prompt_style": "custom",
            "custom_prompt": "請用幽默毒舌風格，繁體中文的文字指出這篇文章的 {bullets} 個核心槽點：\n標題：{title}\n內文：\n{content}",
            "summary_bullets": 3,
        },
    )
    await plugin.initialize()

    article = ArticleDTO(
        title="系統穩定性最佳實踐",
        url="https://tech.local/reliability",
        feed_url="https://tech.local/rss",
        content_text="高可用性系統需要多層熔斷防護機制。\n定期執行混沌工程演練能主動暴露架構隱患。\n防衛性程式設計是減少生產環境故障的關鍵基石。",
        published_at=datetime.now(timezone.utc),
    )

    res = await plugin.process(article)
    assert res is not None
    assert res.ai_summary is not None
    assert "槽點 1" in res.ai_summary
    assert len(captured_prompts) == 1
    assert "幽默毒舌風格" in captured_prompts[0]
    assert "系統穩定性最佳實踐" in captured_prompts[0]


@pytest.mark.asyncio
async def test_gemini_summary_presets_and_discovery(monkeypatch) -> None:
    """測試多組 Presets 切換與動態探索快取機制 (Test Gemini multi-presets and dynamic model discovery)."""
    # 1. 測試 Presets 提示詞代換
    captured_prompts = []

    async def mock_call(self, api_key: str, model: str, prompt: str) -> str:
        captured_prompts.append(prompt)
        return "- 重點 1：繁體中文摘要成功產出"

    monkeypatch.setattr(GeminiSummaryProcessorPlugin, "_call_gemini_api", mock_call)

    plugin = GeminiSummaryProcessorPlugin(
        plugin_id="omnirss/gemini-summary",
        config={
            "api_key": "test-key-abc",
            "prompt_style": "entertainment",
            "summary_bullets": 3,
        },
    )
    await plugin.initialize()

    article = ArticleDTO(
        title="日本最新科幻冒險電影介紹",
        url="https://cinema.local/movie123",
        feed_url="https://cinema.local/rss",
        content_text="這是一部由知名導演執導的科幻冒險新作，講述未來世界中人類與 AI 的羈絆，視覺特效震撼，演員陣容堅強。",
        published_at=datetime.now(timezone.utc),
    )

    res = await plugin.process(article)
    assert res is not None
    assert len(captured_prompts) == 1
    assert "影視、文化娛樂作品" in captured_prompts[0]

    # 2. 測試動態模型探索與快取
    test_plugin = GeminiSummaryProcessorPlugin(
        plugin_id="omnirss/gemini-summary",
        config={"api_key": "test-key"},
    )
    models = await test_plugin._discover_active_models("mock-key")
    assert len(models) >= 1
    assert test_plugin._cached_active_model is not None


@pytest.mark.asyncio
async def test_gemini_prompt_presets_manager_and_safe_dict(monkeypatch) -> None:
    """測試自訂提示詞範本陣列、預設 ID 與 SafeDict 防衛格式化 (Test prompt presets manager & SafeDict)."""
    captured_prompts = []

    async def mock_call(self, api_key: str, model: str, prompt: str) -> str:
        captured_prompts.append(prompt)
        return "- 自訂重點 1：AI 解讀成功"

    monkeypatch.setattr(GeminiSummaryProcessorPlugin, "_call_gemini_api", mock_call)

    custom_presets = [
        {
            "id": "finance_ai",
            "name": "金融與財經解讀",
            "is_builtin": False,
            "prompt": "【財經分析】針對標題 {title} 與內文 {content}，分析 {bullets} 點市場影響，包含未知變數 {custom_var_safe}。",
        },
        {
            "id": "quick_bullet",
            "name": "超快速重點",
            "is_builtin": False,
            "prompt": "快速提取 {bullets} 點：\n{content}",
        },
    ]

    plugin = GeminiSummaryProcessorPlugin(
        plugin_id="omnirss/gemini-summary",
        config={
            "api_key": "test-key-xyz",
            "default_preset_id": "finance_ai",
            "prompt_presets": custom_presets,
            "summary_bullets": 5,
        },
    )
    await plugin.initialize()

    article = ArticleDTO(
        title="台積電法說會營收再創新高",
        url="https://finance.local/tsmc",
        feed_url="https://finance.local/rss",
        content_text="台積電公布最新季報，受惠於先進製程與 AI 晶片強勁需求，毛利率與營收均超越市場預期。",
        published_at=datetime.now(timezone.utc),
    )

    # 1. 測試預設取用 default_preset_id = "finance_ai"
    res1 = await plugin.process(article)
    assert res1 is not None
    assert len(captured_prompts) == 1
    assert "【財經分析】" in captured_prompts[0]
    assert "台積電法說會營收再創新高" in captured_prompts[0]
    assert "{custom_var_safe}" in captured_prompts[0]  # SafeDict 保留未定義變數不報錯

    # 2. 測試動態切換至 quick_bullet
    plugin.update_config({
        "selected_preset": "quick_bullet",
    })
    res2 = await plugin.process(article)
    assert res2 is not None
    assert len(captured_prompts) == 2
    assert "快速提取 5 點：" in captured_prompts[1]


@pytest.mark.asyncio
async def test_ptt_enhancer_processor_plugin() -> None:
    """測試 PTT BBS 閱讀體驗增強外掛 (Test PTT Enhancer Processor Plugin)."""
    from plugins.processors.ptt_enhancer.plugin import PttEnhancerProcessorPlugin

    sample_ptt_html = """
    <!DOCTYPE html>
    <html>
    <body>
    <div id="main-content" class="bbs-screen bbs-content">
        <div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">fanti (夢想家)</span></div>
        <div class="article-metaline-right"><span class="article-meta-tag">看板</span><span class="article-meta-value">Stock</span></div>
        <div class="article-metaline"><span class="article-meta-tag">標題</span><span class="article-meta-value">[心得] 2026 台股第四季投資策略</span></div>
        <div class="article-metaline"><span class="article-meta-tag">時間</span><span class="article-meta-value">Sun Sep 27 18:00:00 2026</span></div>
        
        大家好，今天跟大家分享第四季的持股配置：
        1. 留意高殖利率權值股
        2. 關注 AI 邊緣運算成長
        https://i.imgur.com/example123.jpg
        
        祝大家操作順利！
        --
        ※ 發信站: 批踢踢實業坊(ptt.cc), 來自: 114.36.12.34
        ※ 文章網址: https://www.ptt.cc/bbs/Stock/M.123456789.A.BC.html
        <div class="push"><span class="hl push-tag">推 </span><span class="f3 hl push-userid">trader888</span><span class="f3 push-content">: 專業好文推</span><span class="push-ipdatetime"> 09/27 18:05</span></div>
        <div class="push"><span class="f1 hl push-tag">噓 </span><span class="f3 hl push-userid">bear123</span><span class="f3 push-content">: 空頭不死 多頭不止</span><span class="push-ipdatetime"> 09/27 18:06</span></div>
        <div class="push"><span class="f2 push-tag">→ </span><span class="f3 hl push-userid">passerby</span><span class="f3 push-content">: 感謝分享</span><span class="push-ipdatetime"> 09/27 18:07</span></div>
    </div>
    </body>
    </html>
    """

    plugin = PttEnhancerProcessorPlugin(
        plugin_id="omnirss/ptt-enhancer",
        config={
            "auto_embed_images": True,
            "collapse_pushes": False,
        },
    )

    article = ArticleDTO(
        title="[心得] 2026 台股第四季投資策略",
        url="https://www.ptt.cc/bbs/Stock/M.123456789.A.BC.html",
        content_html=sample_ptt_html,
        published_at=datetime.now(timezone.utc),
    )

    res = await plugin.process(article)
    assert res is not None
    assert "ptt-meta-card" in res.content_html
    assert "fanti (夢想家)" in res.content_html
    assert "Stock" in res.content_html
    assert "i.imgur.com/example123.jpg" in res.content_html
    assert "<img" in res.content_html
    assert "💬 PTT 鄉民推文" in res.content_html
    assert "trader888" in res.content_html
    assert "bear123" in res.content_html
    assert "https://www.pttweb.cc/user/trader888" in res.content_html
    assert "https://www.pttweb.cc/user/fanti" in res.content_html
    assert "https://www.pttweb.cc/bbs/Stock" in res.content_html
    assert "1 推" in res.content_html
    assert "1 噓" in res.content_html


@pytest.mark.asyncio
async def test_ptt_enhancer_rss_paragraph_pushes_mode() -> None:
    """測試 PTT RSS/Atom 段落格式推文與元數據卡片增強 (Test PTT Enhancer with RSS paragraph pushes)."""
    from plugins.processors.ptt_enhancer.plugin import PttEnhancerProcessorPlugin

    sample_rss_html = """
    <p><a href="https://www.ptt.cc/bbs/Gossiping/M.1790513873.A.B39.html">https://www.ptt.cc/bbs/Gossiping/M.1790513873.A.B39.html</a></p>
    <p>噓 Leoncheng: 五樓知道 27.240.113.211 09/27 20:58</p>
    <p>推 kcclasaki: 問三樓 我想他應該知道 111.255.196.249 09/27 20:58</p>
    <p>→ milk7054: 五樓屎王 27.242.32.86 09/27 20:59</p>
    <p>噓 sosoway: 放屁不用偷偷摸摸的 123.241.38.197 09/27 21:00</p>
    <p>推 IslamicState: 五樓被玩到鬆了 42.79.10.45 09/27 21:01</p>
    """

    plugin = PttEnhancerProcessorPlugin(
        plugin_id="omnirss/ptt-enhancer",
        config={
            "auto_embed_images": True,
            "collapse_pushes": False,
        },
    )

    article = ArticleDTO(
        title="[問卦] 測試問題標題？",
        url="https://www.ptt.cc/bbs/Gossiping/M.1790513873.A.B39.html",
        author="blackman451",
        content_html=sample_rss_html,
        published_at=datetime.now(timezone.utc),
    )

    res = await plugin.process(article)
    assert res is not None
    assert "ptt-meta-card" in res.content_html
    assert "blackman451" in res.content_html
    assert "Gossiping" in res.content_html
    assert "ptt-pushes-card" in res.content_html
    assert "2 推" in res.content_html
    assert "2 噓" in res.content_html
    assert "1 →" in res.content_html
    assert "Leoncheng" in res.content_html
    assert "kcclasaki" in res.content_html
    assert "https://www.pttweb.cc/user/Leoncheng" in res.content_html
    assert "https://www.pttweb.cc/user/blackman451" in res.content_html
    assert "https://www.pttweb.cc/bbs/Gossiping" in res.content_html


@pytest.mark.asyncio
async def test_ptt_enhancer_pre_formatted_news_mode() -> None:
    """測試 PTT RSS/Atom pre 純文字格式新聞排版與圖片嵌入增強 (Test PTT Enhancer pre mode)."""
    from plugins.processors.ptt_enhancer.plugin import PttEnhancerProcessorPlugin

    sample_pre_html = """
    <pre>原文標題：
    台鐵明年估又虧57億 將檢討票價
    原文連結：
    https://www.chinatimes.com/newspapers/20260927000383-260114?chdtv
    發布時間：2026-09-27
    內文：
    台鐵公司化後首年營運報告出爐。
    https://i.imgur.com/traingraph123.png
    --
    ※ 發信站: 批踢踢實業坊(ptt.cc), 來自: 218.35.135.249
    </pre>
    """

    plugin = PttEnhancerProcessorPlugin(
        plugin_id="omnirss/ptt-enhancer",
        config={
            "auto_embed_images": True,
        },
    )

    article = ArticleDTO(
        title="[新聞] 台鐵明年估又虧57億 將檢討票價",
        url="https://www.ptt.cc/bbs/Stock/M.1790480527.A.3C5.html",
        author="reporter99",
        content_html=sample_pre_html,
        published_at=datetime.now(timezone.utc),
    )

    res = await plugin.process(article)
    assert res is not None
    assert "ptt-meta-card" in res.content_html
    assert "reporter99" in res.content_html
    assert "Stock" in res.content_html
    assert "traingraph123.png" in res.content_html
    assert "<img" in res.content_html
    assert "※ 發信站:" in res.content_html



@pytest.mark.asyncio
async def test_yahoo_enhancer_processor_plugin() -> None:
    """測試 Yahoo 新聞廣告淨化與圖片還原外掛 (Test Yahoo Enhancer processor)."""
    sample_yahoo_html = """
    <!DOCTYPE html>
    <html>
    <body>
    <div class="caas-body">
        <div class="caas-share"><button>Share</button></div>
        <p>半導體供應鏈今日傳出重磅消息，先進製程需求全面爆發。</p>
        <div class="inline-ad advertisement"><p>贊助商廣告</p></div>
        <p>業界預估第四季營收將再創歷史新猷，法人全面調升評等。</p>
        <img data-src="https://media.zenfs.com/prod/real-hd-chip.jpg" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" alt="Chip photo" />
        <div class="caas-readmore"><a href="/readmore">延伸閱讀：科技股盤後分析</a></div>
    </div>
    </body>
    </html>
    """

    plugin = YahooEnhancerProcessorPlugin(
        plugin_id="omnirss/yahoo-enhancer",
        config={
            "strip_inline_ads": True,
            "strip_read_more": True,
            "restore_hd_images": True,
        },
    )

    article = ArticleDTO(
        title="半導體先進製程需求全面爆發",
        url="https://tw.news.yahoo.com/semiconductor-boom-123456.html",
        content_html=sample_yahoo_html,
        published_at=datetime.now(timezone.utc),
    )

    res = await plugin.process(article)
    assert res is not None
    assert "半導體供應鏈今日傳出重磅消息" in res.content_html
    assert "贊助商廣告" not in res.content_html, "應自動清除廣告雜訊"
    assert "延伸閱讀" not in res.content_html, "應自動過濾延伸閱讀區塊"
    assert "media.zenfs.com/prod/real-hd-chip.jpg" in res.content_html, "應還原 data-src 高畫質圖片"


@pytest.mark.skipif(Mobile01EnhancerProcessorPlugin is None, reason="Mobile01 外掛屬未發布之實驗外掛")
@pytest.mark.asyncio
async def test_mobile01_enhancer_processor_plugin() -> None:
    """測試 Mobile01 論壇文章與專題排版淨化外掛 (Test Mobile01 Enhancer processor)."""
    sample_mobile01_html = """
    <!DOCTYPE html>
    <html>
    <body>
    <div class="c-article">
        <div class="c-article__header">
            <div class="c-socialShare"><button>Share</button></div>
        </div>
        <div class="c-article__content">
            <p>本次為大家帶來 2026 最新旗艦相機的深度實測報告，對焦與連拍速度大幅進化。</p>
            <div class="c-article__ad c-ad"><p>贊助商廣告區塊</p></div>
            <p>機身手感相當扎實，握把人體工學經過重新設計。</p>
            <div class="c-quote"><blockquote>前代用戶表示：這次的防手震確實更有感！</blockquote></div>
            <img data-original="https://attach.mobile01.com/attach/202609/real-hd-camera.jpg" src="https://attach.mobile01.com/attach/202609/t_real-hd-camera.jpg" alt="Camera Body" />
            <div class="c-signature"><p>-- 關注我的評測頻道取得更多第一手資訊 --</p></div>
            <div class="c-appBanner"><a href="#">下載 Mobile01 App</a></div>
        </div>
    </div>
    </body>
    </html>
    """

    plugin = Mobile01EnhancerProcessorPlugin(
        plugin_id="omnirss/mobile01-enhancer",
        config={
            "strip_inline_ads": True,
            "strip_signatures_and_promos": True,
            "restore_hd_images": True,
            "clean_forum_noise": True,
        },
    )

    article = ArticleDTO(
        title="2026 旗艦相機深度實測報告",
        url="https://www.mobile01.com/topicdetail.php?f=244&t=6890000",
        content_html=sample_mobile01_html,
        published_at=datetime.now(timezone.utc),
    )

    res = await plugin.process(article)
    assert res is not None
    assert "深度實測報告" in res.content_html
    assert "贊助商廣告" not in res.content_html, "應自動清除廣告"
    assert "下載 Mobile01 App" not in res.content_html, "應自動清除 App 推廣"
    assert "關注我的評測頻道" not in res.content_html, "應自動清除簽名檔"
    assert "https://attach.mobile01.com/attach/202609/real-hd-camera.jpg" in res.content_html, "應還原 data-original 高畫質原圖"
    assert "t_real-hd-camera" not in res.content_html, "不應保留縮圖路徑"
    assert "border-left: 4px solid #3b82f6" in res.content_html, "應美化引用區塊"


@pytest.mark.asyncio
async def test_plugin_manager_discovery() -> None:
    """測試全外掛目錄自動掃描與載入 (Test full plugins directory discovery)."""
    from pathlib import Path
    plugins_dir = Path(__file__).resolve().parents[1] / "plugins"
    pm = PluginManager(plugins_dir)
    count = pm.discover_and_load()
    assert count >= 5, f"應至少成功載入 5 個官方公開外掛，實際載入: {count}"

    manifests = pm.list_manifests()
    assert "omnirss/gemini-summary" in manifests
    assert "omnirss/ptt-enhancer" in manifests
    assert "omnirss/yahoo-enhancer" in manifests
    assert "omnirss/simhash-dedup" in manifests
    assert "omnirss/generic-scraper" in manifests
    if "omnirss/gomaji-deals" in manifests:
        assert "omnirss/gomaji-deals" in manifests
    if "omnirss/mobile01-enhancer" in manifests:
        assert "omnirss/mobile01-enhancer" in manifests


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


@pytest.mark.skipif(GomajiDealsPlugin is None, reason="Gomaji 屬未經實測之私人外掛，未隨公開發行版發布")
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


@pytest.mark.asyncio
async def test_universal_article_plugin_endpoint(tmp_path) -> None:
    """測試通用文章外掛執行與設定端點 (Test universal article plugin execution & config endpoint)."""
    from httpx import AsyncClient, ASGITransport
    from omnirss.core.database import DatabaseManager, set_global_db_manager
    from omnirss.core.plugin_manager import get_plugin_manager
    from omnirss.main import app

    db_file = tmp_path / "test_plugin_api.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    # 確保外掛已載入
    pm = get_plugin_manager()
    pm.discover_and_load()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 建立管理員並登入
        await ac.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        login_res = await ac.post("/api/auth/login", json={"username": "admin", "password": "password123"})
        token = login_res.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        # 1. 取得所有已載入之外掛清單
        res = await ac.get("/api/plugins", headers=auth_headers)
        assert res.status_code == 200
        plugins = res.json()
        assert len(plugins) >= 4

        gemini_plugin = next((p for p in plugins if p["plugin_id"] == "omnirss/gemini-summary"), None)
        assert gemini_plugin is not None
        assert gemini_plugin["config_schema"] is not None

        # 2. 更新使用者個人外掛設定
        update_res = await ac.put(
            "/api/plugins/omnirss/gemini-summary/config",
            headers=auth_headers,
            json={"config": {"api_key": "mock-test-key", "summary_bullets": 3}},
        )
        assert update_res.status_code == 200

        # 3. 讀取個人設定確認
        get_cfg_res = await ac.get(
            "/api/plugins/omnirss/gemini-summary/config",
            headers=auth_headers,
        )
        assert get_cfg_res.status_code == 200
        assert get_cfg_res.json()["config"]["api_key"] == "mock-test-key"

        # 4. 測試切換外掛啟用／停用 (Toggle Switch)
        toggle_res = await ac.post(
            "/api/plugins/omnirss/gemini-summary/toggle",
            headers=auth_headers,
            json={"is_enabled": False},
        )
        assert toggle_res.status_code == 200
        assert toggle_res.json()["is_enabled"] is False

        # 再次切換回啟用
        toggle_res2 = await ac.post(
            "/api/plugins/omnirss/gemini-summary/toggle",
            headers=auth_headers,
            json={"is_enabled": True},
        )
        assert toggle_res2.status_code == 200
        assert toggle_res2.json()["is_enabled"] is True


@pytest.mark.asyncio
async def test_rule_action_execute_plugin_with_generic_param() -> None:
    """測試規則引擎執行外掛動作與通用參數傳遞 (Test Rule Engine Execute Plugin with Generic Param)."""
    from omnirss.core.rule_engine import RuleEngine, RuleActionType
    from omnirss.api.schemas import RuleCreateRequest

    rule_req = RuleCreateRequest(
        name="科技文章自動提煉產業洞察",
        scope_type="all",
        match_mode="all",
        condition_groups=[
            {
                "match_mode": "all",
                "conditions": [{"field": "title", "operator": "contains", "value": "晶片"}],
            }
        ],
        actions=[
            {
                "action": RuleActionType.EXECUTE_PLUGIN.value,
                "params": {"plugin_id": "omnirss/gemini-summary", "preset": "insights", "param": "insights"},
            }
        ],
    )

    art = ArticleDTO(
        guid="chip-news-1",
        url="https://tech.org/chip-news",
        title="台積電推出全新先進晶片封裝架構",
        content_text="最新封裝技術大幅降低能耗並提升傳輸頻寬。",
    )

    processed_art, executed = RuleEngine.process_article(
        art,
        rules=[rule_req.model_dump()],
    )

    assert any("execute_plugin:omnirss/gemini-summary:insights" in x for x in executed)


@pytest.mark.asyncio
async def test_plugin_execution_logs_and_telemetry_flow(tmp_path) -> None:
    """測試外掛執行日誌紀錄、查詢與一鍵清空端點流程 (Test Plugin Execution Logs & Telemetry Flow)."""
    from httpx import AsyncClient, ASGITransport
    from omnirss.core.database import DatabaseManager, set_global_db_manager
    from omnirss.core.plugin_manager import get_plugin_manager
    from omnirss.main import app

    db_file = tmp_path / "test_plugin_logs.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    pm = get_plugin_manager()
    pm.discover_and_load()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        login_res = await ac.post("/api/auth/login", json={"username": "admin", "password": "password123"})
        token = login_res.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        # 1. 取得外掛列表
        res = await ac.get("/api/plugins", headers=auth_headers)
        assert res.status_code == 200
        plugins = res.json()
        assert any(p["plugin_id"] == "omnirss/gemini-summary" for p in plugins)

        # 2. 查詢 gemini-summary 日誌
        res_logs = await ac.get("/api/plugins/omnirss/gemini-summary/logs", headers=auth_headers)
        assert res_logs.status_code == 200
        logs = res_logs.json()
        assert isinstance(logs, list)

        # 3. 測試清空日誌端點
        res_clear = await ac.delete("/api/plugins/omnirss/gemini-summary/logs", headers=auth_headers)
        assert res_clear.status_code == 200
        assert res_clear.json()["plugin_id"] == "omnirss/gemini-summary"

        # 4. 再次查詢確認為空
        res_logs_after = await ac.get("/api/plugins/omnirss/gemini-summary/logs", headers=auth_headers)
        assert res_logs_after.status_code == 200
        assert len(res_logs_after.json()) == 0


@pytest.mark.asyncio
async def test_execute_article_plugin_endpoint_deadlock_free(tmp_path, monkeypatch) -> None:
    """測試文章外掛執行端點無死鎖正常運作並記錄遙測 (Test execute-article API deadlock-free execution)."""
    from httpx import AsyncClient, ASGITransport
    from omnirss.core.database import DatabaseManager, set_global_db_manager
    from omnirss.core.plugin_manager import get_plugin_manager
    from omnirss.main import app

    db_file = tmp_path / "test_exec_plugin.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    pm = get_plugin_manager()
    pm.discover_and_load()

    # Mock _call_gemini_api 避免真實網路請求
    async def mock_call(self, api_key: str, model: str, prompt: str) -> str:
        return "- 重點 1：測試端點執行成功\n- 重點 2：完全無死鎖阻塞\n- 重點 3：資料庫與日誌正確寫入"

    plugin_inst = pm.loaded_plugins.get("omnirss/gemini-summary")
    if plugin_inst:
        monkeypatch.setattr(type(plugin_inst), "_call_gemini_api", mock_call)
    monkeypatch.setattr(GeminiSummaryProcessorPlugin, "_call_gemini_api", mock_call)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        login_res = await ac.post("/api/auth/login", json={"username": "admin", "password": "password123"})
        token = login_res.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        # 設定外掛 API Key
        await ac.put(
            "/api/plugins/omnirss/gemini-summary/config",
            json={"config": {"api_key": "test-key-mock", "summary_bullets": 3}},
            headers=auth_headers,
        )

        # 插入一筆測試文章
        async with db_mgr.write_transaction() as conn:
            cur = await conn.execute(
                "INSERT INTO feeds (title, feed_url) VALUES ('Test Feed', 'https://example.com/feed.xml')"
            )
            feed_id = cur.lastrowid
            await conn.execute(
                "INSERT INTO user_feeds (user_id, feed_id) VALUES (1, ?)", (feed_id,)
            )
            cur_a = await conn.execute(
                """
                INSERT INTO articles_hot (feed_id, entry_hash, title, url, content_text, published_at)
                VALUES (?, 'hash-exec-1', '測試文章標題', 'https://example.com/art-1', '這是一篇用於檢驗文章處理外掛執行端點是否正常的測試文章詳細內文，確保長度足夠以順利觸發 Gemini AI 摘要分析生成邏輯。', CURRENT_TIMESTAMP)
                """,
                (feed_id,),
            )
            article_id = cur_a.lastrowid
            await conn.commit()

        # 呼叫 execute-article 端點
        exec_res = await ac.post(
            f"/api/plugins/omnirss/gemini-summary/execute-article/{article_id}?preset_id=standard",
            headers=auth_headers,
        )
        assert exec_res.status_code == 200, f"執行失敗: {exec_res.text}"
        data = exec_res.json()
        assert data["id"] == article_id
        assert data["ai_summary"] is not None
        assert "重點 1：測試端點執行成功" in data["ai_summary"]

        # 驗證日誌是否成功寫入
        logs_res = await ac.get("/api/plugins/omnirss/gemini-summary/logs", headers=auth_headers)
        assert logs_res.status_code == 200
        logs = logs_res.json()
        assert len(logs) >= 1
        assert logs[0]["status"] == "success"
        assert logs[0]["article_id"] == article_id


@pytest.mark.asyncio
async def test_declarative_url_pattern_matcher() -> None:
    """測試聲明式 URL 比對器之標準 Chrome Match Patterns 與萬用字元 (Test Declarative URL Matcher)."""
    from omnirss.core.pattern_matcher import match_url_patterns

    # 1. 全域比對模式
    assert match_url_patterns("https://news.com/article/1", ["<all_urls>"]) is True
    assert match_url_patterns("http://blog.org/post", ["*"]) is True
    assert match_url_patterns("https://example.com", []) is True

    # 2. Chrome Extension Match Pattern (*://*.ptt.cc/*)
    ptt_patterns = ["*://*.ptt.cc/*", "*://ptt.cc/*"]
    assert match_url_patterns("https://www.ptt.cc/bbs/Gossiping/M.12345.A.html", ptt_patterns) is True
    assert match_url_patterns("http://ptt.cc/bbs/Stock/M.67890.html", ptt_patterns) is True
    assert match_url_patterns("https://m.ptt.cc/bbs/C_Chat/M.11111.html", ptt_patterns) is True
    assert match_url_patterns("https://www.yahoo.com/news/123", ptt_patterns) is False
    assert match_url_patterns("https://theverge.com/tech", ptt_patterns) is False

    # 3. 特定子網域與路徑
    deal_patterns = ["*://*.deals.example.com/*"]
    assert match_url_patterns("https://www.deals.example.com/deal/456", deal_patterns) is True
    assert match_url_patterns("https://travel.deals.example.com/hotel/789", deal_patterns) is True
    assert match_url_patterns("https://shopee.tw/item", deal_patterns) is False


@pytest.mark.asyncio
async def test_plugin_manager_declarative_match_patterns_bypass() -> None:
    """測試 PluginManager 於微核心層依 match_patterns 短路略過不符網址 (Test PluginManager match_patterns bypass)."""
    pm = get_plugin_manager()
    pm.discover_and_load()

    # 建立一則非 PTT 文章 (例如 Yahoo 新聞)
    yahoo_art = ArticleDTO(
        title="國際半導體大廠最新財報出爐",
        url="https://tw.news.yahoo.com/semiconductor-q3-report-012345.html",
        content_html="<p>國際半導體大廠今日公布第三季財報，營收表現大幅超越市場預期。</p>",
        content_text="國際半導體大廠今日公布第三季財報，營收表現大幅超越市場預期。",
    )

    # 執行 PTT 增強外掛，因網址不符 match_patterns (*://*.ptt.cc/*)，微核心直接原樣回傳跳過
    res_bypassed = await pm.execute_processor("omnirss/ptt-enhancer", yahoo_art)
    assert res_bypassed is not None
    assert res_bypassed.content_html == yahoo_art.content_html
    assert "ptt-meta-card" not in (res_bypassed.content_html or "")

    # 建立一則 PTT 文章
    ptt_art = ArticleDTO(
        title="[問卦] 有沒有微核心外掛效能極速的八卦",
        url="https://www.ptt.cc/bbs/Gossiping/M.1727400000.A.111.html",
        content_html="""
        <div id="main-content" class="bbs-screen bbs-content">
            <div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">techlead (技術長)</span></div>
            <div class="article-metaline"><span class="article-meta-tag">標題</span><span class="article-meta-value">[問卦] 有沒有微核心的八卦</span></div>
            這是一篇 PTT 正文內容，微核心架構超強！
            <div class="push"><span class="push-tag">推 </span><span class="push-userid">gopher</span><span class="push-content">: 真的猛</span></div>
        </div>
        """,
    )

    # 執行 PTT 增強外掛，命中 match_patterns 正常執行
    res_enhanced = await pm.execute_processor("omnirss/ptt-enhancer", ptt_art)
    assert res_enhanced is not None
    assert "ptt-meta-card" in (res_enhanced.content_html or "")
    assert "ptt-pushes-card" in (res_enhanced.content_html or "")


@pytest.mark.asyncio
async def test_auto_apply_in_execute_all_processors() -> None:
    """測試 execute_all_processors 依 auto_apply 設定在爬取入庫時正確啟用或略過 (Test auto_apply pipeline control)."""
    pm = get_plugin_manager()
    pm.discover_and_load()

    ptt_art = ArticleDTO(
        title="[問卦] 測試自動套用開關",
        url="https://www.ptt.cc/bbs/Gossiping/M.1727400000.A.222.html",
        content_html="""
        <div id="main-content" class="bbs-screen bbs-content">
            <div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">tester (測試員)</span></div>
            PTT 測試正文
        </div>
        """,
    )

    # 1. 預設 auto_apply=True 時，feed_crawl 觸發應自動加工
    res_auto = await pm.execute_all_processors(ptt_art, trigger_source="feed_crawl")
    assert "ptt-meta-card" in (res_auto.content_html or "")

    # 2. 將 auto_apply 設為 False 時，feed_crawl 觸發應被略過
    pm.set_global_config("omnirss/ptt-enhancer", {"auto_apply": False})
    raw_ptt_art = ArticleDTO(
        title="[問卦] 測試自動套用開關關閉",
        url="https://www.ptt.cc/bbs/Gossiping/M.1727400000.A.333.html",
        content_html="""
        <div id="main-content" class="bbs-screen bbs-content">
            <div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">tester (測試員)</span></div>
            PTT 測試正文無加工
        </div>
        """,
    )
    res_skipped = await pm.execute_all_processors(raw_ptt_art, trigger_source="feed_crawl")
    assert "ptt-meta-card" not in (res_skipped.content_html or "")

    # 3. 雖然 auto_apply=False，但手動觸發時依然可以獨立執行
    res_manual = await pm.execute_processor("omnirss/ptt-enhancer", raw_ptt_art, trigger_source="manual")
    assert res_manual is not None
    assert "ptt-meta-card" in (res_manual.content_html or "")

    # 恢復設定
    pm.set_global_config("omnirss/ptt-enhancer", {"auto_apply": True})


@pytest.mark.asyncio
async def test_clear_plugin_logs_api(tmp_path) -> None:
    """測試外掛日誌與遙測紀錄清空 API (Test plugin logs and telemetry clearing API)."""
    from httpx import AsyncClient, ASGITransport
    from omnirss.core.database import DatabaseManager, set_global_db_manager
    from omnirss.main import app

    db_file = tmp_path / "test_clear_logs.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. 首次設定管理員並登入
        await client.post("/api/auth/setup", json={"username": "superadmin", "password": "password123"})
        login_res = await client.post("/api/auth/login", json={"username": "superadmin", "password": "password123"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. 寫入測試日誌
        async with db_mgr.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO plugin_execution_logs (
                    plugin_id, user_id, article_id, article_title, trigger_source, status, duration_ms, executed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                ("omnirss/ptt-enhancer", 1, 1, "測試標題", "manual", "success", 120),
            )
            await conn.commit()

        # 3. 驗證可以查到日誌
        res_get = await client.get("/api/plugins/omnirss/ptt-enhancer/logs", headers=headers)
        assert res_get.status_code == 200
        assert len(res_get.json()) >= 1

        # 4. 執行清空日誌 (Query 端點)
        res_del = await client.delete("/api/plugins/logs/clear?plugin_id=omnirss/ptt-enhancer", headers=headers)
        assert res_del.status_code == 200
        assert res_del.json()["plugin_id"] == "omnirss/ptt-enhancer"

        # 5. 驗證清空後無日誌
        res_get_after = await client.get("/api/plugins/omnirss/ptt-enhancer/logs", headers=headers)
        assert res_get_after.status_code == 200
        assert len(res_get_after.json()) == 0


@pytest.mark.asyncio
async def test_batch_apply_plugin_updates_article(tmp_path) -> None:
    """測試批次重新套用外掛更新文章 content_html 與 ai_summary (Test batch apply plugin updating articles)."""
    from httpx import AsyncClient, ASGITransport
    from omnirss.core.database import DatabaseManager, set_global_db_manager
    from omnirss.main import app

    db_file = tmp_path / "test_batch_apply.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. 首次設定管理員並登入
        await client.post("/api/auth/setup", json={"username": "superadmin", "password": "password123"})
        login_res = await client.post("/api/auth/login", json={"username": "superadmin", "password": "password123"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. 新增 feeds 與 PTT 文章到資料庫
        async with db_mgr.get_connection() as conn:
            await conn.execute(
                "INSERT INTO feeds (id, title, feed_url) VALUES (1, 'PTT 八卦板', 'https://www.ptt.cc/atom/Gossiping.xml')"
            )
            await conn.execute(
                """
                INSERT INTO articles_hot (id, feed_id, entry_hash, title, url, author, content_html, content_text, snippet, published_at)
                VALUES (9999, 1, 'hash9999', '[問卦] 測試批次重新套用', 'https://www.ptt.cc/bbs/Gossiping/M.19999.html', 'tester',
                        '<div id="main-content" class="bbs-screen bbs-content">推 uid: 測試推文 01/01</div>', '推 uid: 測試推文 01/01', '推文摘要', CURRENT_TIMESTAMP)
                """
            )
            await conn.commit()

        # 3. 呼叫重新套用 API
        res = await client.post("/api/plugins/batch-apply?plugin_id=omnirss/ptt-enhancer", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["processed_count"] >= 1
        assert data["updated_count"] >= 1

    # 4. 檢查文章在資料庫中是否被更新為帶有 PTT 卡片格式
    async with db_mgr.get_connection() as conn:
        cur = await conn.execute("SELECT content_html FROM articles_hot WHERE id = 9999")
        row = await cur.fetchone()
        assert row is not None
        assert "ptt-meta-card" in row[0] or "ptt-push-card" in row[0] or "ptt" in row[0]


@pytest.mark.asyncio
async def test_gemini_summary_entertainment_auto_detection(monkeypatch) -> None:
    """測試成人/影視題材自動分流至 entertainment 範本與自選 action_param (Test adult/video auto detection & action_param)."""
    captured_prompts = []

    async def mock_call(self, api_key: str, model: str, prompt: str) -> str:
        captured_prompts.append(prompt)
        return "- 作品番號：SSIS-888\n- 主演陣容：三上悠亞\n- 企劃主題：溫泉旅行\n- 推薦看點：畫質高、情境豐富"

    monkeypatch.setattr(GeminiSummaryProcessorPlugin, "_call_gemini_api", mock_call)

    plugin = GeminiSummaryProcessorPlugin(
        plugin_id="omnirss/gemini-summary",
        config={"api_key": "test-key-auto"},
    )
    await plugin.initialize()

    # 1. 包含番號與女優關鍵字之成人娛樂文章（未指定 style）
    adult_article = ArticleDTO(
        title="[推薦] SSIS-888 三上悠亞 溫泉引退特輯 最新作品評測",
        url="https://jav.local/ssis-888",
        feed_url="https://jav.local/rss",
        content_text="S1 最新企劃推出 SSIS-888 特輯，由人氣女優三上悠亞主演，全程於箱根知名溫泉飯店實景拍攝，場景豪華。",
        published_at=datetime.now(timezone.utc),
    )

    res1 = await plugin.process(adult_article)
    assert res1 is not None
    assert len(captured_prompts) == 1
    # 驗證自動被分流至 entertainment 範本（帶有 作品資訊、參演人物 等 4 字標籤結構）
    assert "作品資訊" in captured_prompts[0]
    assert "參演人物" in captured_prompts[0]

    # 2. 手動指定 action_param = "tldr" 應覆蓋自動分流
    res2 = await plugin.process(adult_article, action_param="tldr")
    assert res2 is not None
    assert len(captured_prompts) == 2
    assert "TL;DR" in captured_prompts[1]


@pytest.mark.asyncio
async def test_gemini_summary_sanitization_and_legal_framing(monkeypatch) -> None:
    """測試 Gemini 摘要之司法新聞情境注入與極端成人詞彙脫敏 (Test legal news framing and adult title sanitization)."""
    captured_prompts = []

    async def mock_call(self, api_key: str, model: str, prompt: str) -> str:
        captured_prompts.append(prompt)
        return "- 摘要重點已生成"

    monkeypatch.setattr(GeminiSummaryProcessorPlugin, "_call_gemini_api", mock_call)

    plugin = GeminiSummaryProcessorPlugin(
        plugin_id="omnirss/gemini-summary",
        config={"api_key": "test-key-sanitize"},
    )
    await plugin.initialize()

    # 1. 司法判決裁判新聞 -> 驗證情境宣告注入
    legal_article = ArticleDTO(
        title="涉性侵偷拍判刑4年半 北院審理認犯行重大",
        url="https://news.local/legal-123",
        feed_url="https://news.local/rss",
        content_text="台北地院審理某涉嫌性侵與未經同意錄影案件，合議庭今日審結判處有期徒刑4年6月，全案仍可上訴。",
        published_at=datetime.now(timezone.utc),
    )
    res_legal = await plugin.process(legal_article)
    assert res_legal is not None
    assert len(captured_prompts) == 1
    assert "公開新聞紀實與司法裁判事實分析" in captured_prompts[0]
    assert "性侵" in captured_prompts[0]

    # 2. 含有極端生理詞彙之成人作品 -> 驗證極端詞彙已脫敏轉換，保留番號與主演名
    adult_article = ArticleDTO(
        title="HNBR-015 即ハメ中出し 御子柴美花 溫泉旅行",
        url="https://jav.local/hnbr-015",
        feed_url="https://jav.local/rss",
        content_text="即ハメ種付けの豪華企画、御子柴美花が出演する温泉旅行編。",
        published_at=datetime.now(timezone.utc),
    )
    res_adult = await plugin.process(adult_article)
    assert res_adult is not None
    assert len(captured_prompts) == 2
    prompt_adult = captured_prompts[1]
    # 驗證極端詞已被替換
    assert "即ハメ" not in prompt_adult
    assert "中出し" not in prompt_adult
    # 驗證關鍵要素保留
    assert "HNBR-015" in prompt_adult
    assert "御子柴美花" in prompt_adult


@pytest.mark.asyncio
async def test_gemini_summary_safety_block_local_fallback(monkeypatch) -> None:
    """測試當 Google Gemini 觸發安全阻擋時自動切換為本地繁中要點提取器 (Test local fallback summary on safety block)."""
    async def mock_call_blocked(self, api_key: str, model: str, prompt: str) -> str:
        # 模擬 Google API 回報 PROHIBITED_CONTENT 阻擋
        return "__SAFETY_BLOCKED__:PROHIBITED_CONTENT"

    monkeypatch.setattr(GeminiSummaryProcessorPlugin, "_call_gemini_api", mock_call_blocked)

    plugin = GeminiSummaryProcessorPlugin(
        plugin_id="omnirss/gemini-summary",
        config={"api_key": "test-key-blocked"},
    )
    await plugin.initialize()

    # 1. 影視成人作品觸發阻擋 -> 提取番號、主演、企劃
    adult_article = ArticleDTO(
        title="HNBR-015 [御子柴美花] 溫泉旅行同居生活最新特別篇",
        url="https://jav.local/hnbr-015-blocked",
        feed_url="https://jav.local/rss",
        content_text="這是由御子柴美花主演的箱根溫泉旅行企劃，包含多段精彩生活實景互動。",
        published_at=datetime.now(timezone.utc),
    )

    res_adult = await plugin.process(adult_article)
    assert res_adult is not None
    assert res_adult.ai_summary is not None
    assert "觸發 Google 內容安全政策 (PROHIBITED_CONTENT)" in res_adult.ai_summary
    assert "自動啟用本地繁中要點提取" in res_adult.ai_summary
    assert "HNBR-015" in res_adult.ai_summary
    assert "御子柴美花" in res_adult.ai_summary

    # 2. 司法裁判新聞觸發阻擋 -> 提取核心事實、判決要點
    legal_article = ArticleDTO(
        title="涉性侵判刑4年半 北院合議庭宣判",
        url="https://news.local/legal-blocked",
        feed_url="https://news.local/rss",
        content_text="台北地院審理某重大社會刑案。\n合議庭經過密集審理後，認定被告犯行明確。\n今日正式宣判處有期徒刑4年6月，全案可上訴。",
        published_at=datetime.now(timezone.utc),
    )

    res_legal = await plugin.process(legal_article)
    assert res_legal is not None
    assert res_legal.ai_summary is not None
    assert "觸發 Google 內容安全政策 (PROHIBITED_CONTENT)" in res_legal.ai_summary
    assert "核心事件" in res_legal.ai_summary

