"""Gomaji 台灣美食與旅宿優惠情報來源外掛 (Gomaji Deals Source Plugin).

This plugin tracks discount food, buffet, and hotel deals from Gomaji Taiwan,
converting deals into rich-formatted RSS ArticleDTO entries with prices and images.
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


class GomajiDealsPlugin(BaseSourcePlugin):
    """Gomaji 特價情報來源外掛 (Gomaji Deals Source Plugin)."""

    async def initialize(self) -> None:
        """初始化外掛資源 (Initialize plugin resources)."""
        logger.info(f"GomajiDealsPlugin initialized with config: {self.config}")

    async def fetch(
        self, feed_url: str, context: Optional[PluginContext] = None
    ) -> list[ArticleDTO]:
        """抓取 Gomaji 優惠活動並解析為 ArticleDTO 清單 (Fetch Gomaji deals and parse into ArticleDTO items).

        :param feed_url: Gomaji 分類頁面或 API 網址
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
            body_text = response.text
        finally:
            if should_close:
                await active_client.aclose()

        articles: list[ArticleDTO] = []

        auto_tag = self.config.get("auto_tag") or "團購特價"
        min_discount = float(self.config.get("min_discount_rate") or 0.0)

        try:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(body_text, "html.parser")

                # 搜尋商品卡片 (Gomaji 卡片結構)
                cards = soup.find_all("div", class_=re.compile(r"(product-card|item-card|card|store-item)", re.I))
                if not cards:
                    cards = soup.find_all("a", href=re.compile(r"(deal|product|store)", re.I))

                for card in cards[:30]:
                    link_el = card if card.name == "a" else card.find("a", href=True)
                    if not link_el:
                        continue

                    href = link_el.get("href", "").strip()
                    if not href:
                        continue

                    if href.startswith("/"):
                        href = f"https://www.gomaji.com{href}"

                    title = link_el.get_text(strip=True) or card.get_text(strip=True)
                    if len(title) < 5:
                        continue

                    # 尋找圖片
                    img_el = card.find("img", src=True) or card.find("img", attrs={"data-src": True})
                    cover_url = None
                    if img_el:
                        cover_url = img_el.get("data-src") or img_el.get("src")
                        if cover_url and cover_url.startswith("//"):
                            cover_url = f"https:{cover_url}"

                    card_text = card.get_text(strip=True)
                    formatted_html = f"""
                    <div class="gomaji-deal-item">
                      <h3><a href="{href}" target="_blank">{title}</a></h3>
                      {f'<p><img src="{cover_url}" alt="{title}" style="max-width: 100%; border-radius: 6px;" /></p>' if cover_url else ''}
                      <p><strong>優惠價格/內容：</strong>{card_text}</p>
                    </div>
                    """

                    art = ArticleDTO(
                        title=f"【Gomaji】{title[:120]}",
                        url=href,
                        feed_url=feed_url,
                        content_html=formatted_html,
                        content_text=card_text,
                        snippet=card_text[:200],
                        cover_image_url=cover_url,
                        custom_tags=[auto_tag],
                        published_at=datetime.now(timezone.utc),
                    )
                    articles.append(art)

            except ImportError:
                # 標準庫正則抽取備援 (Zero external dependency fallback)
                link_pattern = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
                img_pattern = re.compile(r'<img\s+[^>]*(?:src|data-src)=["\']([^"\']+)["\']', re.I)

                seen = set()
                for match in link_pattern.finditer(body_text):
                    href, raw_title = match.groups()
                    clean_title = re.sub(r'<[^>]+>', '', raw_title).strip()
                    if len(clean_title) < 5 or href in seen:
                        continue

                    seen.add(href)
                    if href.startswith("/"):
                        href = f"https://www.gomaji.com{href}"

                    img_m = img_pattern.search(body_text)
                    cover_url = img_m.group(1) if img_m else None
                    if cover_url and cover_url.startswith("//"):
                        cover_url = f"https:{cover_url}"

                    art = ArticleDTO(
                        title=f"【Gomaji】{clean_title[:120]}",
                        url=href,
                        feed_url=feed_url,
                        content_html=f'<p><a href="{href}">{clean_title}</a></p>',
                        content_text=clean_title,
                        snippet=clean_title[:200],
                        cover_image_url=cover_url,
                        custom_tags=[auto_tag],
                        published_at=datetime.now(timezone.utc),
                    )
                    articles.append(art)
                    if len(articles) >= 30:
                        break

        except Exception as exc:
            logger.error(f"Gomaji plugin parsing error: {exc}")

        return articles

    async def fetch_feed(self, feed_url: str) -> list[ArticleDTO]:
        """向後相容之抓取方法 (Backwards compatible fetch_feed alias)."""
        return await self.fetch(feed_url)
