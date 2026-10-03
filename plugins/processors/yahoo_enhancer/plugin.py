"""Yahoo 新聞文章排版與廣告淨化外掛 (Yahoo News Enhancer Plugin).

This plugin parses Yahoo News article structure using high-performance lxml,
extracts .caas-body containers, strips intrusive ads/promos, and restores HD images.
Also handles short RSS snippet content (image + snippet only) by wrapping in yh-article card.
"""

from typing import Any, Optional, TYPE_CHECKING
import html as py_html
import lxml.html
from loguru import logger
from omnirss.core.security import HTMLSanitizer
from omnirss.sdk.base_plugin import BaseProcessorPlugin
from omnirss.sdk.models import ArticleDTO

if TYPE_CHECKING:
    from omnirss.sdk.context import PluginContext

_YAHOO_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": "https://tw.yahoo.com/",
}


async def _fetch_yahoo_full_page(url: str, context: Optional["PluginContext"] = None) -> str:
    """抓取 Yahoo 新聞完整頁面內容 (Fetch full Yahoo article HTML).

    :param url: Yahoo 文章網址
    :param context: 外掛上下文
    :return: 頁面 HTML 字串，失敗時回傳空字串
    """
    try:
        if context and context.http_client is not None:
            resp = await context.http_get(url, headers=_YAHOO_FETCH_HEADERS)
            if hasattr(resp, "text"):
                return await resp.text() if callable(resp.text) else resp.text
            return str(resp)
        else:
            import aiohttp
            async with aiohttp.ClientSession(headers=_YAHOO_FETCH_HEADERS) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15),
                                       allow_redirects=True) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    return ""
    except Exception as exc:
        logger.debug(f"YahooEnhancer _fetch_yahoo_full_page error for {url}: {exc}")
        return ""


def _build_rss_fallback_card(html_str: str, article_title: str = "", article_snippet: str = "") -> Optional[str]:
    """為 RSS 縮圖型 Yahoo 文章建立基礎 yh-article 卡片 (Build yh-article card from RSS snippet content).

    :param html_str: RSS 提供的簡短 HTML (通常只有 <p><img/></p>)
    :param article_title: 文章標題
    :param article_snippet: 文章摘要
    :return: yh-article 卡片 HTML 或 None
    """
    try:
        doc = lxml.html.fromstring(html_str) if html_str.strip() else None
        parts: list[str] = []

        # 封面圖片
        if doc is not None:
            imgs = doc.xpath('.//img')
            if imgs:
                img = imgs[0]
                src = img.get("src") or ""
                alt = img.get("alt") or article_title or ""
                if src and src.startswith("http"):
                    parts.append(
                        f'<img src="{py_html.escape(src)}" alt="{py_html.escape(alt)}" '
                        f'style="max-width:100%; height:auto; border-radius:8px; margin:0 0 14px 0; display:block;" />'
                    )

        # 摘要文字
        if article_snippet and article_snippet.strip():
            parts.append(
                f'<p style="margin:0; line-height:1.75; font-size:15px; color:var(--text-primary);">'
                f'{py_html.escape(article_snippet.strip())}</p>'
            )

        if not parts:
            return None

        out_html = f'<div class="yh-article">{"".join(parts)}</div>'
        return out_html if len(out_html) > 50 else None

    except Exception as exc:
        logger.debug(f"Yahoo RSS fallback card error: {exc}")
        return None


import re
import urllib.parse


def _extract_img_fingerprint(url: str) -> str:
    """從 Yahoo 圖片 URL 中萃取圖片特徵指紋 (Extract stable image fingerprint from Yahoo CDN URL).

    無論外層封裝了多少層 Mysterio API、Lightyear 或 Ny Proxy Hash，
    只要底層檔名相同即視為同一張圖片。

    :param url: 圖片原始 URL
    :return: 圖片特徵指紋字串
    """
    if not url or not url.strip():
        return ""
    u = url.strip()
    for _ in range(3):
        if "%" in u:
            try:
                u = urllib.parse.unquote(u)
            except Exception:
                break
        else:
            break

    # 1. 尋找 32~64 位元之 Hex Hash (Yahoo Zenfs / Creatr 常見特徵)
    m = re.search(r'([a-f0-9]{32,64}(?:\.[a-zA-Z0-9]+)?)', u, re.IGNORECASE)
    if m:
        return m.group(1).lower()

    # 2. 若無 Hex Hash，取出去除 query 參數後的最後一段路徑檔名
    parsed = urllib.parse.urlparse(u)
    path = parsed.path.rstrip("/")
    if "/" in path:
        return path.split("/")[-1].lower()
    return u.split("?")[0].lower()


def _is_noise_image(url: str) -> bool:
    """判斷是否為無效雜訊、Logo、追蹤像素或推薦新聞縮圖 (Check if image is noise/ad/icon/thumbnail).

    :param url: 圖片 URL
    :return: True 若為雜訊圖片
    """
    if not url or not url.startswith("http"):
        return True
    u_lower = url.lower()
    noise_keywords = [
        "google-prefered",
        "illustration",
        "icon",
        "logo",
        "resizefill_h48",
        "smartcrop_w184",
        "1x1",
        "pixel",
        "avatar",
        "advertisement",
        "badge",
    ]
    return any(k in u_lower for k in noise_keywords)


def parse_yahoo_html(html_str: str, config: Optional[dict[str, Any]] = None,
                     article_title: str = "", article_snippet: str = "") -> Optional[str]:
    """解析 Yahoo 新聞 HTML 並進行正文萃取與廣告淨化 (Parse and enhance Yahoo News HTML).

    :param html_str: Yahoo 新聞原始 HTML 字串 (全文頁面或 RSS 摘要片段皆可)
    :param config: 外掛設定參數 (如 strip_inline_ads, restore_hd_images 等)
    :param article_title: 文章標題 (供 RSS 簡短內容備用卡片使用)
    :param article_snippet: 文章摘要 (供 RSS 簡短內容備用卡片使用)
    :return: 清洗與美化後之 HTML 內文或 None
    """
    if not html_str:
        return None

    # 快速判斷：若為 RSS 簡短內容 (無全文頁面結構)，走備用卡片路徑
    has_full_page_structure = (
        "caas-body" in html_str
        or "atoms" in html_str
        or "story-body" in html_str
        or "article-body" in html_str
        or "<article" in html_str
    )
    if not has_full_page_structure:
        return _build_rss_fallback_card(html_str, article_title, article_snippet)

    cfg = config or {}
    strip_inline_ads = bool(cfg.get("strip_inline_ads", True))
    strip_read_more = bool(cfg.get("strip_read_more", True))
    restore_hd_images = bool(cfg.get("restore_hd_images", True))

    try:
        doc = lxml.html.fromstring(html_str)
        body_container = None

        # 精準定位正文容器 (優先搜尋最具特異性的正文容器，避免包含側欄推薦)
        candidate_selectors = [
            '//div[contains(@class, "atoms")]',
            '//div[contains(@class, "caas-body")]',
            '//div[contains(@class, "story-body")]',
            '//div[contains(@class, "article-body")]',
            '//article',
        ]
        for sel in candidate_selectors:
            matches = doc.xpath(sel)
            if matches:
                body_container = matches[0]
                break

        if body_container is None:
            return _build_rss_fallback_card(html_str, article_title, article_snippet)

        seen_fingerprints: set[str] = set()

        # 1. 移除廣告、社群分享、側欄與延伸閱讀推薦等各類雜訊
        noise_selectors = [
            './/header',
            './/dialog',
            './/script',
            './/style',
            './/*[contains(@class, "google-ps")]',
            './/*[contains(@class, "toast-background")]',
            './/*[contains(@class, "lg:w-article-aside")]',
            './/*[contains(@class, "sidebar")]',
            './/*[contains(@class, "atomic-stream-item")]',
            './/*[contains(@class, "story-cluster")]',
            './/*[contains(@class, "recommendation-contents")]',
            './/*[contains(@class, "caas-readmore")]',
            './/*[contains(@class, "caas-share")]',
            './/*[contains(@class, "caas-follow")]',
            './/*[contains(@class, "read-more-vendor")]',
            './/*[contains(@class, "related-articles")]',
            './/*[contains(@class, "smartcrop")]',
        ]
        if strip_inline_ads:
            noise_selectors.extend([
                './/*[contains(@class, "ad-container")]',
                './/*[contains(@class, "advertisement")]',
                './/*[contains(@class, "inline-ad")]',
                './/*[contains(@class, "caas-ad")]',
                './/*[contains(@class, "canvas-ad")]',
            ])

        for noise in body_container.xpath(" | ".join(noise_selectors)):
            parent = noise.getparent()
            if parent is not None:
                parent.remove(noise)

        # 2. 修正並還原高畫質圖片來源，同時標記並剔除重複與雜訊圖片
        for img in body_container.xpath('.//img'):
            real_src = (
                img.get("data-src")
                or img.get("data-original")
                or img.get("src")
                or ""
            ).strip()
            fp = _extract_img_fingerprint(real_src)

            if restore_hd_images and real_src and not _is_noise_image(real_src) and fp and fp not in seen_fingerprints:
                seen_fingerprints.add(fp)
                img.set("src", real_src)
                img.set("style", "max-width:100%; height:auto; border-radius:8px; margin:12px auto; display:block;")
            else:
                parent = img.getparent()
                if parent is not None:
                    # 若 parent 是 figure 且無其他有效 img，移除整個 figure；否則移除 img
                    if parent.tag == "figure" and len(parent.xpath('.//img')) <= 1:
                        fig_parent = parent.getparent()
                        if fig_parent is not None:
                            fig_parent.remove(parent)
                    else:
                        parent.remove(img)

        # 3. 抽取正文段落 (排除已被包含在 figure 內部的孤立 img，杜絕父子節點重複)
        paragraphs = body_container.xpath('.//p | .//figure | .//img[not(ancestor::figure) and not(ancestor::p)] | .//blockquote | .//h2 | .//h3')
        if not paragraphs:
            return _build_rss_fallback_card(html_str, article_title, article_snippet)

        out_parts: list[str] = []
        rendered_fps: set[str] = set()

        for p in paragraphs:
            if p.tag == "img":
                img_src = (p.get("src") or p.get("data-src") or "").strip()
                fp = _extract_img_fingerprint(img_src)
                if img_src and not _is_noise_image(img_src) and fp and fp not in rendered_fps:
                    rendered_fps.add(fp)
                    out_parts.append(
                        f'<div style="margin:12px 0; text-align:center;">'
                        f'<img src="{py_html.escape(img_src)}" alt="{py_html.escape(article_title)}" '
                        f'style="max-width:100%; height:auto; border-radius:8px; display:block; margin:0 auto;" />'
                        f'</div>'
                    )
            elif p.tag == "figure":
                fig_imgs = p.xpath('.//img')
                if fig_imgs:
                    img_src = (fig_imgs[0].get("src") or fig_imgs[0].get("data-src") or "").strip()
                    fp = _extract_img_fingerprint(img_src)
                    if img_src and not _is_noise_image(img_src) and fp and fp not in rendered_fps:
                        rendered_fps.add(fp)
                        p.set("style", "margin:14px 0; padding:0; text-align:center;")
                        out_parts.append(lxml.html.tostring(p, encoding="unicode"))
            else:
                text = p.text_content().strip()
                # 過濾 Google 偏好來源等純廣告或推薦段落
                if text and "加入為 Google 偏好來源" not in text and "將 Yahoo 設為首選來源" not in text and "更多新聞報導" not in text:
                    out_parts.append(lxml.html.tostring(p, encoding="unicode"))

        # 若內文中完全沒有任何圖片，嘗試以 og:image 補一張封面圖
        if not rendered_fps:
            og_imgs = doc.xpath('//meta[@property="og:image"]/@content | //meta[@name="twitter:image"]/@content')
            if og_imgs:
                og_img_src = og_imgs[0].strip()
                og_fp = _extract_img_fingerprint(og_img_src)
                if og_img_src and not _is_noise_image(og_img_src) and og_fp and og_fp not in rendered_fps:
                    rendered_fps.add(og_fp)
                    out_parts.insert(
                        0,
                        f'<figure style="margin:0 0 16px 0; padding:0; text-align:center;">'
                        f'<img src="{py_html.escape(og_img_src)}" alt="{py_html.escape(article_title)}" '
                        f'style="max-width:100%; height:auto; border-radius:8px; display:block; margin:0 auto;" />'
                        f'</figure>'
                    )

        out_html = f'<div class="yh-article">{"".join(out_parts)}</div>'
        return HTMLSanitizer.clean(out_html) if len(out_html) > 50 else None

    except Exception as exc:
        logger.debug(f"Yahoo News parsing error: {exc}")
        return None


class YahooEnhancerProcessorPlugin(BaseProcessorPlugin):
    """Yahoo 新聞排版與廣告淨化外掛 (Yahoo News Processor Plugin)."""

    async def process(
        self, article: ArticleDTO, context: Optional["PluginContext"] = None
    ) -> Optional[ArticleDTO]:
        """淨化 Yahoo 新聞內文、移除雜訊廣告並還原高清大圖.

        若 RSS 內容為簡短片段 (無完整正文)，外掛會自動抓取 Yahoo 完整頁面內容，
        無需使用者手動開啟 auto_full_text。

        :param article: 待處理文章資料
        :param context: 微核心注入之安全上下文
        :return: 淨化後之文章物件
        """
        content = (
            getattr(article, "content_html", "")
            or getattr(article, "content_text", "")
            or ""
        )

        merged_cfg = dict(self.config)
        if context and context.config:
            merged_cfg.update(context.config)

        title = getattr(article, "title", "") or ""
        snippet = getattr(article, "snippet", "") or ""
        article_url = getattr(article, "url", "") or ""

        # 判斷是否需要抓取 Yahoo 原始頁面全文：
        # 1. 無完整結構 (caas-body / atoms / <article)
        # 2. 或是雖然有 yh-article 但純文字長度極短 (< 300 字) 且帶有省略號 (說明先前只是 RSS fallback 縮圖卡片)
        plain_len = len(HTMLSanitizer.extract_text(content))
        is_short_fallback = "yh-article" in content and (plain_len < 300 or content.endswith("...</p></div>") or "..." in snippet)
        needs_full_page = ("atoms" not in content and "caas-body" not in content and "<article" not in content) or is_short_fallback

        working_content = content
        if needs_full_page and article_url:
            logger.debug(f"YahooEnhancer: Fetching full page for {article_url} (current plain len: {plain_len})...")
            full_html = await _fetch_yahoo_full_page(article_url, context)
            if full_html and ("atoms" in full_html or "caas-body" in full_html or "story-body" in full_html or "<article" in full_html):
                working_content = full_html
                logger.debug(f"YahooEnhancer: Full page fetched ({len(full_html)} bytes)")
            else:
                logger.debug("YahooEnhancer: Full page unavailable, using RSS fallback card")

        enhanced_html = parse_yahoo_html(working_content, config=merged_cfg,
                                          article_title=title, article_snippet=snippet)
        if enhanced_html and len(enhanced_html.strip()) > 50:
            article.content_html = enhanced_html
            article.content_text = HTMLSanitizer.extract_text(enhanced_html)
            article.snippet = HTMLSanitizer.extract_snippet(enhanced_html, max_chars=200)
            logger.debug(f"YahooEnhancer successfully enhanced article: {article.title}")

        return article
