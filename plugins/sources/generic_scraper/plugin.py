"""通用 Web / JSON API 轉 RSS 來源外掛 (Generic Web & JSON Scraper Source Plugin).

This plugin fetches arbitrary web pages or JSON endpoints, extracting structured article entries
via declarative heuristics, CSS selectors, or JSON parsing into standard ArticleDTO lists.
"""

from datetime import datetime, timezone
import json
import re
from typing import Optional
import httpx
from loguru import logger
from omnirss.sdk.base_plugin import BaseSourcePlugin
from omnirss.sdk.context import PluginContext
from omnirss.sdk.models import ArticleDTO


class GenericScraperPlugin(BaseSourcePlugin):
    """通用網頁與 JSON 轉 RSS 來源外掛 (Generic Web Scraper Source Plugin)."""

    async def initialize(self) -> None:
        """初始化外掛資源 (Initialize plugin resources)."""
        logger.info(f"GenericScraperPlugin initialized with config: {self.config}")

    async def fetch(
        self, feed_url: str, context: Optional[PluginContext] = None
    ) -> list[ArticleDTO]:
        """抓取目標網址並解析為標準 ArticleDTO 清單 (Fetch URL and parse into ArticleDTO items).

        :param feed_url: 目標抓取網址
        :param context: 外掛上下文
        :return: ArticleDTO 清單
        """
        active_client = None
        should_close = False
        if context and context.http_client:
            active_client = context.http_client
        elif self.context and self.context.http_client:
            active_client = self.context.http_client
        else:
            active_client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
            should_close = True

        try:
            response = await active_client.get(feed_url)
            content_type = response.headers.get("content-type", "").lower()
            body_text = response.text
        finally:
            if should_close:
                await active_client.aclose()

        articles: list[ArticleDTO] = []

        # 1. 判斷是否為 JSON API 格式
        if "application/json" in content_type or body_text.strip().startswith(("{", "[")):
            try:
                data = json.loads(body_text)
                items = data if isinstance(data, list) else data.get("items") or data.get("articles") or data.get("data") or []
                if isinstance(items, list):
                    for idx, item in enumerate(items[:30]):
                        if isinstance(item, dict):
                            title = str(item.get("title") or item.get("name") or f"Item #{idx+1}")
                            url = str(item.get("url") or item.get("link") or f"{feed_url}#{idx}")
                            content = str(item.get("content") or item.get("summary") or item.get("description") or title)
                            cover = str(item.get("image") or item.get("cover") or "") or None

                            art = ArticleDTO(
                                title=title,
                                url=url,
                                feed_url=feed_url,
                                author=item.get("author"),
                                content_html=f"<p>{content}</p>",
                                content_text=content,
                                snippet=content[:200],
                                cover_image_url=cover,
                                published_at=datetime.now(timezone.utc),
                            )
                            articles.append(art)
                    return articles
            except Exception as exc:
                logger.warning(f"JSON scraping fallback to HTML: {exc}")

        # 2. HTML 網頁啟發式解析 (Heuristic HTML Scraping)
        try:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(body_text, "html.parser")

                # 移除無關元素
                for unwanted in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    unwanted.decompose()

                # 尋找文章容器 (常見 article, card, list-item, entry)
                candidates = soup.find_all(["article", "li", "div"], class_=re.compile(r"(post|item|article|entry|card|feed)", re.I))
                if not candidates:
                    candidates = soup.find_all("a", href=True)

                seen_urls = set()
                for elem in candidates[:30]:
                    link_el = elem if elem.name == "a" else elem.find("a", href=True)
                    if not link_el or not link_el.get("href"):
                        continue

                    href = link_el.get("href", "").strip()
                    if not href or href.startswith("javascript:") or href in seen_urls:
                        continue

                    if href.startswith("/"):
                        from urllib.parse import urljoin
                        href = urljoin(feed_url, href)

                    title = link_el.get_text(strip=True) or elem.get_text(strip=True)
                    if len(title) < 5:
                        continue

                    seen_urls.add(href)
                    snippet = elem.get_text(strip=True)
                    img_el = elem.find("img", src=True)
                    cover_img = img_el.get("src") if img_el else None
                    if cover_img and cover_img.startswith("/"):
                        from urllib.parse import urljoin
                        cover_img = urljoin(feed_url, cover_img)

                    art = ArticleDTO(
                        title=title[:200],
                        url=href,
                        feed_url=feed_url,
                        content_html=f"<p>{snippet}</p>",
                        content_text=snippet,
                        snippet=snippet[:200],
                        cover_image_url=cover_img,
                        published_at=datetime.now(timezone.utc),
                    )
                    articles.append(art)

            except ImportError:
                # 標準庫正則抽取備援 (Zero external dependency fallback)
                link_pattern = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
                img_pattern = re.compile(r'<img\s+[^>]*(?:src|data-src)=["\']([^"\']+)["\']', re.I)

                seen_urls = set()
                for match in link_pattern.finditer(body_text):
                    href, raw_title = match.groups()
                    clean_title = re.sub(r'<[^>]+>', '', raw_title).strip()
                    if len(clean_title) < 5 or href in seen_urls or href.startswith("javascript:"):
                        continue

                    seen_urls.add(href)
                    if href.startswith("/"):
                        from urllib.parse import urljoin
                        href = urljoin(feed_url, href)

                    img_m = img_pattern.search(body_text)
                    cover_img = img_m.group(1) if img_m else None
                    if cover_img and cover_img.startswith("/"):
                        from urllib.parse import urljoin
                        cover_img = urljoin(feed_url, cover_img)

                    art = ArticleDTO(
                        title=clean_title[:200],
                        url=href,
                        feed_url=feed_url,
                        content_html=f'<p><a href="{href}">{clean_title}</a></p>',
                        content_text=clean_title,
                        snippet=clean_title[:200],
                        cover_image_url=cover_img,
                        published_at=datetime.now(timezone.utc),
                    )
                    articles.append(art)
                    if len(articles) >= 30:
                        break

        except Exception as exc:
            logger.error(f"HTML scraper failed for '{feed_url}': {exc}")

        return articles

    async def fetch_feed(self, feed_url: str) -> list[ArticleDTO]:
        """向後相容之抓取方法 (Backwards compatible fetch_feed alias)."""
        return await self.fetch(feed_url)
