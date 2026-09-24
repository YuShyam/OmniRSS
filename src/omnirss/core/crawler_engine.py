"""高韌性非同步爬蟲引擎 (High-Resilience Asynchronous Crawler Engine).

This module implements an asynchronous RSS/Atom/JSON feed crawler with Anti-SSRF protection,
Auto-Referer hotlink bypassing, 3-stage fallback fingerprint rotation, ETag/304 conditional polling,
streaming 10MB DoS cutoff, and safe feed parsing into ArticleDTO objects.
"""

import asyncio
import hashlib
import ipaddress
import logging
import random
import re
import socket
import ssl
import urllib.parse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
import feedparser
from pydantic import BaseModel, Field

from omnirss.core.security import AntiSSRFClient, HTMLSanitizer, SSRFBlockedException
from omnirss.sdk.models import ArticleDTO, FeedDTO

logger = logging.getLogger("omnirss.crawler")

# 最大允許串流讀取位元組數 (10MB) (Max streaming payload cutoff)
MAX_RESPONSE_SIZE = 10 * 1024 * 1024

# 預設現代桌面 Chrome 128 標頭 (Default Modern Chrome 128 Request Headers)
CHROME_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# QuiteRSS 桌面客戶端 Qt 指紋 (QuiteRSS Desktop Client Qt Fingerprint Headers)
QUITERSS_HEADERS: dict[str, str] = {
    "User-Agent": "QuiteRSS/0.19.4 (Qt/5.15.2; Windows NT 10.0; Win64; x64)",
    "Accept": "application/xml,text/xml,application/rss+xml,application/atom+xml,*/*;q=0.1",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "close",
}


def get_origin_referer(url: str) -> str:
    """自動提取目標網址之根網域作為 Referer 標頭 (Extract root origin as Referer).

    :param url: 目標連線網址 (Target URL)
    :return: 根網域 Referer 字串 (Root origin URL)
    """
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"


def calculate_next_check_time(
    interval_minutes: int,
    error_count: int,
    base_time: Optional[datetime] = None,
) -> datetime:
    """計算錯誤指數退避後的下次抓取時間 (Compute next crawl time with exponential backoff and jitter).

    公式：delay = min(1440, interval * 2^min(errors, 5)) +/- 10% Jitter
    :param interval_minutes: 基礎排程間隔分鐘數 (Base check interval in minutes)
    :param error_count: 連續失敗次數 (Consecutive error counter)
    :param base_time: 計算基準時間 (Base time, defaults to current UTC)
    :return: 下次執行之 UTC 時間 (Next scheduled UTC timestamp)
    """
    now = base_time or datetime.now(timezone.utc)
    clamped_errors = max(0, min(error_count, 5))
    backoff_factor = 2**clamped_errors
    nominal_delay = min(1440, max(1, interval_minutes) * backoff_factor)

    # 引入 +/- 10% 隨機擾動 (Apply 10% random jitter)
    jitter = nominal_delay * random.uniform(-0.1, 0.1)
    effective_delay = max(1.0, nominal_delay + jitter)

    from datetime import timedelta

    return now + timedelta(minutes=effective_delay)


class CrawlResult(BaseModel):
    """爬取結果傳輸模型 (Crawl Result DTO)."""

    url: str
    status_code: int
    is_modified: bool = True
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    content_bytes: bytes = b""
    content_text: str = ""
    articles: list[ArticleDTO] = Field(default_factory=list)
    feed_metadata: Optional[FeedDTO] = None
    error_message: Optional[str] = None
    used_stage: str = "stage1_chrome"


class CrawlerEngine:
    """高韌性非同步爬蟲引擎 (High-Resilience Asynchronous Crawler Engine).

    Provides safe HTTP fetching, 3-stage fallback fingerprint rotation,
    streaming 10MB limits, and feed parsing.
    """

    def __init__(
        self,
        timeout: float = 15.0,
        flaresolverr_url: Optional[str] = None,
    ) -> None:
        """初始化爬蟲引擎 (Initialize crawler engine).

        :param timeout: 單次連線與讀取逾時秒數 (Socket timeout in seconds)
        :param flaresolverr_url: 可選之 FlareSolverr 代理網址 (Optional FlareSolverr endpoint)
        """
        self.timeout = timeout
        self.flaresolverr_url = flaresolverr_url

    async def _safe_http_get(
        self,
        url: str,
        headers: dict[str, str],
    ) -> tuple[int, dict[str, str], bytes]:
        """執行具備 Anti-SSRF 與防 DoS 串流讀取之底層非同步 HTTP GET (Safe async HTTP GET).

        :param url: 目標網址 (Target URL)
        :param headers: HTTP 標頭字典 (HTTP headers dictionary)
        :return: (狀態碼, 響應標頭字典, 原始位元組內容)
        :raises SSRFBlockedException: 命中私有 IP 或非法協議
        :raises asyncio.TimeoutError: 連線或讀取逾時
        :raises Exception: 網路與傳輸例外
        """
        # 第一道防線：Anti-SSRF 網址安全檢驗與 DNS 解析
        resolved_ips = AntiSSRFClient.verify_url(url)
        parsed = urllib.parse.urlparse(url)
        is_ssl = parsed.scheme.lower() == "https"
        port = parsed.port or (443 if is_ssl else 80)
        target_ip = resolved_ips[0]

        # 構建 HTTP 請求報文
        path_and_query = parsed.path or "/"
        if parsed.query:
            path_and_query += f"?{parsed.query}"

        host_header = parsed.netloc
        req_lines = [f"GET {path_and_query} HTTP/1.1", f"Host: {host_header}"]
        for k, v in headers.items():
            if k.lower() != "host":
                req_lines.append(f"{k}: {v}")
        req_lines.append("\r\n")
        req_payload = "\r\n".join(req_lines).encode("latin-1")

        # 建立非同步 Socket 連線 (Async TCP connection)
        ssl_ctx: Optional[ssl.SSLContext] = None
        if is_ssl:
            ssl_ctx = ssl.create_default_context()
            # 保持 SNI 伺服器名稱指示正確 (Preserve SNI hostname)
            server_hostname = parsed.hostname
        else:
            server_hostname = None

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                host=target_ip,
                port=port,
                ssl=ssl_ctx,
                server_hostname=server_hostname,
            ),
            timeout=self.timeout,
        )

        try:
            writer.write(req_payload)
            await asyncio.wait_for(writer.drain(), timeout=self.timeout)

            # 讀取 HTTP 響應標頭 (Read response headers)
            header_bytes = b""
            while b"\r\n\r\n" not in header_bytes:
                chunk = await asyncio.wait_for(
                    reader.read(4096), timeout=self.timeout
                )
                if not chunk:
                    break
                header_bytes += chunk
                if len(header_bytes) > 65536:
                    raise ValueError("HTTP response headers exceeded 64KB")

            header_part, body_initial = header_bytes.split(b"\r\n\r\n", 1)
            header_text = header_part.decode("latin-1", errors="replace")
            lines = header_text.split("\r\n")

            # 解析狀態列 (Parse status line)
            status_line = lines[0] if lines else ""
            status_parts = status_line.split(" ", 2)
            status_code = (
                int(status_parts[1])
                if len(status_parts) >= 2 and status_parts[1].isdigit()
                else 500
            )

            # 解析標頭欄位 (Parse headers)
            resp_headers: dict[str, str] = {}
            for line in lines[1:]:
                if ": " in line:
                    hk, hv = line.split(": ", 1)
                    resp_headers[hk.lower()] = hv.strip()

            # 若為 304 Not Modified，無須讀取內文 (Return immediately on 304)
            if status_code == 304:
                return status_code, resp_headers, b""

            # 讀取內文並落實 10MB 硬切斷 (Read body with 10MB cutoff)
            body_chunks = [body_initial]
            total_bytes = len(body_initial)

            # 檢查 Content-Length 或 Chunked
            is_chunked = (
                resp_headers.get("transfer-encoding", "").lower() == "chunked"
            )

            while True:
                chunk = await asyncio.wait_for(
                    reader.read(8192), timeout=self.timeout
                )
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_RESPONSE_SIZE:
                    logger.warning(
                        f"Stream cutoff triggered: payload from '{url}' exceeded 10MB"
                    )
                    break
                body_chunks.append(chunk)

            raw_body = b"".join(body_chunks)

            # 若為 chunked 編碼，簡易解包 (Unpack chunked if needed)
            if is_chunked and raw_body:
                raw_body = self._decode_chunked(raw_body)

            # 處理 gzip 解壓縮 (Handle Gzip decompress)
            encoding = resp_headers.get("content-encoding", "").lower()
            if "gzip" in encoding:
                import gzip

                try:
                    raw_body = gzip.decompress(raw_body)
                except Exception:
                    pass
            elif "deflate" in encoding:
                import zlib

                try:
                    raw_body = zlib.decompress(raw_body)
                except Exception:
                    pass

            return status_code, resp_headers, raw_body

        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _decode_chunked(self, chunked_bytes: bytes) -> bytes:
        """解碼 HTTP Chunked 傳輸位元組 (Decode chunked transfer payload)."""
        output = bytearray()
        pos = 0
        length = len(chunked_bytes)
        while pos < length:
            crlf = chunked_bytes.find(b"\r\n", pos)
            if crlf == -1:
                break
            hex_str = chunked_bytes[pos:crlf].decode(
                "latin-1", errors="replace"
            )
            # 移除 chunk extension
            hex_str = hex_str.split(";")[0].strip()
            try:
                chunk_len = int(hex_str, 16)
            except ValueError:
                break
            if chunk_len == 0:
                break
            chunk_start = crlf + 2
            chunk_end = chunk_start + chunk_len
            output.extend(chunked_bytes[chunk_start:chunk_end])
            pos = chunk_end + 2
        return bytes(output) if output else chunked_bytes

    async def fetch_feed(
        self,
        url: str,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        requires_flaresolverr: bool = False,
    ) -> CrawlResult:
        """非同步抓取並解析 RSS/Atom 頻道 (Fetch and parse feed with 3-stage fallback).

        :param url: 目標訂閱網址 (Target feed URL)
        :param etag: 前次暫存之 ETag 標頭 (Cached ETag header)
        :param last_modified: 前次暫存之 Last-Modified 標頭 (Cached Last-Modified header)
        :param requires_flaresolverr: 是否強制透過 FlareSolverr 側邊欄 (Force FlareSolverr sidecar)
        :return: 抓取與解析結果 CrawlResult 實例
        """
        # 準備基礎標頭組與 Auto-Referer
        base_headers = dict(CHROME_HEADERS)
        base_headers["Referer"] = get_origin_referer(url)
        if etag:
            base_headers["If-None-Match"] = etag
        if last_modified:
            base_headers["If-Modified-Since"] = last_modified

        current_url = url
        last_error = ""

        # =====================================================================
        # Stage 1: 現代 Chrome 128 + Auto-Referer 主力攻堅
        # =====================================================================
        try:
            status, resp_headers, body = await self._safe_http_get(
                current_url, base_headers
            )
            if status == 304:
                return CrawlResult(
                    url=current_url,
                    status_code=304,
                    is_modified=False,
                    used_stage="stage1_chrome_304",
                )
            if 200 <= status < 300:
                articles, feed_meta = self.parse_feed_content(
                    body, current_url
                )
                return CrawlResult(
                    url=current_url,
                    status_code=status,
                    is_modified=True,
                    etag=resp_headers.get("etag"),
                    last_modified=resp_headers.get("last-modified"),
                    content_bytes=body,
                    articles=articles,
                    feed_metadata=feed_meta,
                    used_stage="stage1_chrome",
                )
            last_error = f"HTTP {status}"
        except Exception as e:
            last_error = str(e)
            logger.debug(f"Stage 1 failed for '{current_url}': {e}")

        # =====================================================================
        # Stage 2: 協定升級救援 (若原為 http:// 且失敗，升級為 https://)
        # =====================================================================
        if current_url.startswith("http://"):
            https_url = "https://" + current_url[7:]
            try:
                base_headers["Referer"] = get_origin_referer(https_url)
                status, resp_headers, body = await self._safe_http_get(
                    https_url, base_headers
                )
                if status == 304:
                    return CrawlResult(
                        url=https_url,
                        status_code=304,
                        is_modified=False,
                        used_stage="stage2_https_304",
                    )
                if 200 <= status < 300:
                    articles, feed_meta = self.parse_feed_content(
                        body, https_url
                    )
                    return CrawlResult(
                        url=https_url,
                        status_code=status,
                        is_modified=True,
                        etag=resp_headers.get("etag"),
                        last_modified=resp_headers.get("last-modified"),
                        content_bytes=body,
                        articles=articles,
                        feed_metadata=feed_meta,
                        used_stage="stage2_https_upgrade",
                    )
                last_error = f"Stage 2 HTTP {status}"
            except Exception as e:
                last_error = str(e)
                logger.debug(f"Stage 2 failed for '{https_url}': {e}")

        # =====================================================================
        # Stage 3: QuiteRSS Qt 指紋救援 (針對白名單/舊型 CMS 站點)
        # =====================================================================
        try:
            qr_headers = dict(QUITERSS_HEADERS)
            qr_headers["Referer"] = get_origin_referer(current_url)
            if etag:
                qr_headers["If-None-Match"] = etag
            if last_modified:
                qr_headers["If-Modified-Since"] = last_modified

            status, resp_headers, body = await self._safe_http_get(
                current_url, qr_headers
            )
            if status == 304:
                return CrawlResult(
                    url=current_url,
                    status_code=304,
                    is_modified=False,
                    used_stage="stage3_quiterss_304",
                )
            if 200 <= status < 300:
                articles, feed_meta = self.parse_feed_content(
                    body, current_url
                )
                return CrawlResult(
                    url=current_url,
                    status_code=status,
                    is_modified=True,
                    etag=resp_headers.get("etag"),
                    last_modified=resp_headers.get("last-modified"),
                    content_bytes=body,
                    articles=articles,
                    feed_metadata=feed_meta,
                    used_stage="stage3_quiterss_fingerprint",
                )
            last_error = f"Stage 3 HTTP {status}"
        except Exception as e:
            last_error = str(e)
            logger.debug(f"Stage 3 failed for '{current_url}': {e}")

        # =====================================================================
        # Stage 4: FlareSolverr 側邊欄智能調度 (若已配置且有需求)
        # =====================================================================
        if (
            requires_flaresolverr or "403" in last_error
        ) and self.flaresolverr_url:
            try:
                flare_result = await self._fetch_via_flaresolverr(current_url)
                if flare_result:
                    return flare_result
            except Exception as e:
                logger.debug(f"Stage 4 FlareSolverr failed: {e}")

        # 所有降級手段皆告失敗
        return CrawlResult(
            url=current_url,
            status_code=500,
            is_modified=False,
            error_message=f"All crawl stages failed. Last error: {last_error}",
            used_stage="failed",
        )

    async def _fetch_via_flaresolverr(
        self, target_url: str
    ) -> Optional[CrawlResult]:
        """透過 FlareSolverr 代理抓取 Cloudflare 頑強站點 (Fetch via FlareSolverr sidecar)."""
        import json

        if not self.flaresolverr_url:
            return None

        payload = {
            "cmd": "request.get",
            "url": target_url,
            "maxTimeout": int(self.timeout * 1000),
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body_bytes)),
        }

        # 呼叫 FlareSolverr API
        status, _, resp_body = await self._safe_http_get(
            f"{self.flaresolverr_url}/v1", headers
        )
        if status == 200:
            data = json.loads(resp_body.decode("utf-8", errors="replace"))
            solution = data.get("solution", {})
            html_text = solution.get("response", "")
            raw_bytes = html_text.encode("utf-8")
            articles, feed_meta = self.parse_feed_content(
                raw_bytes, target_url
            )
            return CrawlResult(
                url=target_url,
                status_code=solution.get("status", 200),
                is_modified=True,
                content_bytes=raw_bytes,
                articles=articles,
                feed_metadata=feed_meta,
                used_stage="stage4_flaresolverr",
            )
        return None

    def parse_feed_content(
        self, content_bytes: bytes, source_url: str
    ) -> tuple[list[ArticleDTO], Optional[FeedDTO]]:
        """安全解析 XML / Feed 位元組為 ArticleDTO 清單與頻道詮釋資料 (Parse feed content).

        :param content_bytes: 原始 XML 或 JSONFeed 位元組 (Raw feed bytes)
        :param source_url: 來源網址 (Source URL)
        :return: (ArticleDTO 清單, FeedDTO 頻道中繼資料)
        """
        # 使用 feedparser 安全解析 (Feedparser internally defuses XML entities)
        parsed = feedparser.parse(content_bytes)

        # 抽取頻道詮釋資料 (Extract Feed Metadata)
        feed_title = parsed.feed.get("title", "").strip() or source_url
        feed_site_url = parsed.feed.get("link") or get_origin_referer(
            source_url
        )
        feed_description = parsed.feed.get("description", "")
        feed_icon_url = (
            parsed.feed.get("icon")
            or parsed.feed.get("logo")
            or f"{get_origin_referer(source_url)}favicon.ico"
        )

        feed_dto = FeedDTO(
            title=feed_title,
            feed_url=source_url,
            site_url=feed_site_url,
            icon_url=feed_icon_url,
            description=feed_description,
        )

        articles: list[ArticleDTO] = []
        for entry in parsed.entries:
            # 抽取 GUID 與 URL (Extract GUID & URL)
            url = entry.get("link", "").strip()
            guid = entry.get("id", "").strip()
            if not guid:
                guid = (
                    url
                    if url
                    else hashlib.sha256(
                        (entry.get("title", "") + source_url).encode("utf-8")
                    ).hexdigest()
                )

            title = entry.get("title", "Untitled").strip()
            author = entry.get("author") or entry.get("author_detail", {}).get(
                "name"
            )

            # 解析發布時間 (Parse published timestamp)
            published_dt = datetime.now(timezone.utc)
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                import calendar

                ts = calendar.timegm(entry.published_parsed)
                published_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                import calendar

                ts = calendar.timegm(entry.updated_parsed)
                published_dt = datetime.fromtimestamp(ts, tz=timezone.utc)

            # 抽取內文 HTML (Extract HTML content)
            content_html = ""
            if hasattr(entry, "content") and entry.content:
                content_html = entry.content[0].get("value", "")
            elif hasattr(entry, "summary_detail") and entry.summary_detail:
                content_html = entry.summary_detail.get("value", "")
            elif hasattr(entry, "summary") and entry.summary:
                content_html = entry.summary

            # 透過 HTMLSanitizer 脫毒與抽取純文字/預覽
            clean_html = HTMLSanitizer.clean(content_html)
            clean_text = HTMLSanitizer.extract_text(clean_html)
            snippet = HTMLSanitizer.extract_snippet(clean_html, max_chars=200)
            media = HTMLSanitizer.extract_media(clean_html)
            cover_image = media.images[0] if media.images else None

            # 若內文僅為孤立圖片網址，自動升級為 <img> 標籤 (Auto-upgrade raw image URL to <img>)
            raw_stripped = content_html.strip()
            if raw_stripped and re.match(r"^https?://[^\s<>\"']+\.(?:jpg|jpeg|png|gif|webp|svg|bmp|avif)(?:\?[^\s<>\"']*)?$", raw_stripped, re.IGNORECASE):
                clean_html = f'<p><img src="{raw_stripped}" alt="{title}" style="max-width: 100%; height: auto; border-radius: 6px;" /></p>'
                clean_text = ""
                snippet = f"[圖片] {title}"
                if not cover_image:
                    cover_image = raw_stripped

            # 附加標籤 (Extra tags)
            tags: list[str] = []
            if hasattr(entry, "tags") and entry.tags:
                for t in entry.tags:
                    term = t.get("term")
                    if term and term not in tags:
                        tags.append(term)

            article_dto = ArticleDTO(
                guid=guid,
                url=url or source_url,
                title=title,
                author=author,
                published_at=published_dt,
                content_html=clean_html,
                content_text=clean_text,
                snippet=snippet,
                cover_image_url=cover_image,
                extra_tags=tags,
            )
            articles.append(article_dto)

        return articles, feed_dto

    @staticmethod
    def extract_full_text_from_html(
        html_str: str, base_url: str = ""
    ) -> Optional[str]:
        """使用 Trafilatura 從原始 HTML 萃取結構化去噪內文 (Extract clean article content using Trafilatura).

        :param html_str: 原始 HTML 字串 (Raw HTML markup)
        :param base_url: 基準網址 (Base URL)
        :return: 脫毒與去噪後的 HTML 內文或 None
        """
        try:
            import trafilatura

            extracted = trafilatura.extract(
                html_str,
                url=base_url,
                include_links=True,
                include_images=True,
                output_format="html",
            )
            return HTMLSanitizer.clean(extracted) if extracted else None
        except Exception as e:
            logger.debug(f"Trafilatura extraction skipped or failed: {e}")
            return None

