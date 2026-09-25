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
    "Connection": "close",
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
        timeout: float = 8.0,
        flaresolverr_url: Optional[str] = None,
    ) -> None:
        """初始化爬蟲引擎 (Initialize crawler engine).

        :param timeout: 單次連線與讀取逾時秒數 (Socket timeout in seconds)
        :param flaresolverr_url: 可選之 FlareSolverr 代理網址 (Optional FlareSolverr endpoint)
        """
        self.timeout = timeout
        self.flaresolverr_url = flaresolverr_url

    async def _single_hop_http_get(
        self,
        url: str,
        headers: dict[str, str],
    ) -> tuple[int, dict[str, str], bytes]:
        """執行單跳底層非同步 HTTP GET (Single hop async HTTP GET)."""
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
            content_length: Optional[int] = None
            if "content-length" in resp_headers:
                try:
                    content_length = int(resp_headers["content-length"])
                except ValueError:
                    content_length = None

            is_chunked = (
                resp_headers.get("transfer-encoding", "").lower() == "chunked"
            )

            # 若 body_initial 已經滿足 Content-Length 或 Chunked 結束，無需再讀取
            can_finish = False
            if content_length is not None and total_bytes >= content_length:
                can_finish = True
            elif is_chunked and (b"\r\n0\r\n\r\n" in body_initial or body_initial.endswith(b"0\r\n\r\n") or body_initial == b"0\r\n\r\n"):
                can_finish = True

            while not can_finish:
                try:
                    chunk = await asyncio.wait_for(
                        reader.read(8192), timeout=self.timeout
                    )
                except (asyncio.TimeoutError, ConnectionResetError):
                    break

                if not chunk:
                    break
                total_bytes += len(chunk)
                body_chunks.append(chunk)

                if content_length is not None and total_bytes >= content_length:
                    break

                if is_chunked:
                    tail = b"".join(body_chunks[-3:])
                    if b"\r\n0\r\n\r\n" in tail or tail.endswith(b"0\r\n\r\n"):
                        break

                if total_bytes > MAX_RESPONSE_SIZE:
                    logger.warning(
                        f"Stream cutoff triggered: payload from '{url}' exceeded 10MB"
                    )
                    break

            raw_body = b"".join(body_chunks)
            if content_length is not None and len(raw_body) > content_length:
                raw_body = raw_body[:content_length]

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

    async def _safe_http_get(
        self,
        url: str,
        headers: dict[str, str],
        max_redirects: int = 5,
    ) -> tuple[int, dict[str, str], bytes]:
        """執行具備 Anti-SSRF、自動轉址追蹤與防 DoS 串流讀取之非同步 HTTP GET (Safe async HTTP GET with redirects).

        :param url: 目標網址 (Target URL)
        :param headers: HTTP 標頭字典 (HTTP headers dictionary)
        :param max_redirects: 最大允許跳轉次數 (Maximum redirect hops)
        :return: (狀態碼, 響應標頭字典, 原始位元組內容)
        :raises SSRFBlockedException: 命中私有 IP 或非法協議
        :raises asyncio.TimeoutError: 連線或讀取逾時
        :raises Exception: 網路與傳輸例外
        """
        current_url = url
        current_headers = dict(headers)

        for hop in range(max_redirects + 1):
            status_code, resp_headers, raw_body = await self._single_hop_http_get(
                current_url, current_headers
            )

            # 處理 301, 302, 303, 307, 308 重新導向 (Follow HTTP redirects)
            if status_code in (301, 302, 303, 307, 308) and "location" in resp_headers:
                loc = resp_headers["location"]
                next_url = urllib.parse.urljoin(current_url, loc)
                logger.debug(f"HTTP {status_code} Redirect ({hop+1}/{max_redirects}): {current_url} -> {next_url}")
                current_url = next_url
                current_headers["Referer"] = get_origin_referer(current_url)
                continue

            return status_code, resp_headers, raw_body

        return status_code, resp_headers, raw_body

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
        force_refresh: bool = False,
        auth: Optional[tuple[str, str]] = None,
    ) -> CrawlResult:
        """非同步抓取並解析 RSS/Atom 頻道 (Fetch and parse feed with 3-stage fallback).

        :param url: 目標訂閱網址 (Target feed URL)
        :param etag: 前次暫存之 ETag 標頭 (Cached ETag header)
        :param last_modified: 前次暫存之 Last-Modified 標頭 (Cached Last-Modified header)
        :param requires_flaresolverr: 是否強制透過 FlareSolverr 側邊欄 (Force FlareSolverr sidecar)
        :param force_refresh: 是否強制繞過 304 快取標頭 (Force fresh fetch without ETag/Last-Modified)
        :param auth: HTTP 認證 (username, password) 序對 (HTTP Basic Auth tuple)
        :return: 抓取與解析結果 CrawlResult 實例
        """
        current_url = url
        # 智慧 PTT URL 正規化 (自動升級舊版 rss.ptt.cc 至官方 https://www.ptt.cc/atom/*.xml)
        if "rss.ptt.cc" in current_url.lower():
            board = current_url.rstrip("/").split("/")[-1].replace(".xml", "")
            current_url = f"https://www.ptt.cc/atom/{board}.xml"

        # 準備基礎標頭組與 Auto-Referer
        base_headers = dict(CHROME_HEADERS)
        base_headers["Referer"] = get_origin_referer(current_url)
        if "ptt.cc" in current_url.lower():
            base_headers["Cookie"] = "over18=1"
        if auth and auth[0]:
            import base64
            auth_str = f"{auth[0]}:{auth[1] or ''}"
            encoded = base64.b64encode(auth_str.encode("utf-8")).decode("ascii")
            base_headers["Authorization"] = f"Basic {encoded}"
        if not force_refresh:
            if etag:
                base_headers["If-None-Match"] = etag
            if last_modified:
                base_headers["If-Modified-Since"] = last_modified

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

    async def fetch_web_page(
        self,
        url: str,
        requires_flaresolverr: bool = False,
        auth: Optional[tuple[str, str]] = None,
    ) -> tuple[int, str]:
        """抓取目標網頁之原始 HTML 內容 (Fetch raw web page HTML with Anti-SSRF and Chrome headers).

        :param url: 目標網址 (Target Web Page URL)
        :param requires_flaresolverr: 是否使用 FlareSolverr 側邊欄 (Use FlareSolverr sidecar)
        :param auth: 可選之 HTTP 基本認證 (Optional HTTP Basic Auth)
        :return: (HTTP 狀態碼, 解碼後之 HTML 字串)
        """
        current_url = url
        base_headers = dict(CHROME_HEADERS)
        base_headers["Referer"] = get_origin_referer(current_url)
        if "ptt.cc" in current_url.lower():
            base_headers["Cookie"] = "over18=1"
        if auth and auth[0]:
            import base64
            auth_str = f"{auth[0]}:{auth[1] or ''}"
            encoded = base64.b64encode(auth_str.encode("utf-8")).decode("ascii")
            base_headers["Authorization"] = f"Basic {encoded}"

        try:
            status, resp_headers, body = await self._safe_http_get(
                current_url, base_headers
            )
            # 智能偵測編碼 (Smart charset decoding)
            content_type = resp_headers.get("content-type", "").lower()
            encoding = "utf-8"
            if "charset=" in content_type:
                encoding = content_type.split("charset=")[-1].split(";")[0].strip()
            
            try:
                html_text = body.decode(encoding, errors="replace")
            except Exception:
                html_text = body.decode("utf-8", errors="replace")

            return status, html_text
        except Exception as e:
            logger.warning(f"Failed to fetch web page '{url}': {e}")
            return 500, ""

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
    def _extract_ptt(html_str: str) -> Optional[str]:
        """PTT Web 版 BBS 結構、文章內文排版與推文專屬解析器 (PTT BBS Fulltext Parser)."""
        try:
            import html as py_html
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html_str, "html.parser")
            main_content = soup.find(id="main-content")
            if not main_content:
                return None

            # 1. 抽取推文區塊並轉換為結構化卡片 HTML
            pushes = main_content.find_all("div", class_="push")
            push_items_html = []
            for p in pushes:
                tag_span = p.find("span", class_="push-tag")
                user_span = p.find("span", class_="push-userid")
                content_span = p.find("span", class_="push-content")
                time_span = p.find("span", class_="push-ipdatetime")

                tag_text = tag_span.get_text(strip=True) if tag_span else ""
                user_text = user_span.get_text(strip=True) if user_span else ""
                content_text = content_span.get_text(strip=True) if content_span else ""
                time_text = time_span.get_text(strip=True) if time_span else ""

                tag_color = "#10b981" if "推" in tag_text else "#ef4444" if "噓" in tag_text else "#6b7280"
                push_items_html.append(
                    f'<div style="display:flex; align-items:baseline; gap:8px; padding:4px 0; border-bottom:1px solid var(--border-color, rgba(0,0,0,0.05)); font-size:13px;">'
                    f'<span style="font-weight:bold; color:{tag_color}; width:20px; flex-shrink:0;">{py_html.escape(tag_text)}</span>'
                    f'<span style="font-weight:600; color:var(--text-secondary, #4b5563); width:100px; flex-shrink:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{py_html.escape(user_text)}</span>'
                    f'<span style="flex:1; color:var(--text-primary, #111827); word-break:break-word;">{py_html.escape(content_text)}</span>'
                    f'<span style="font-size:11px; color:var(--text-muted, #9ca3af); flex-shrink:0;">{py_html.escape(time_text)}</span>'
                    f'</div>'
                )
                p.decompose()

            # 2. 抽取頂部 BBS metadata (作者、看板、標題、時間)
            meta_items = []
            for meta in main_content.find_all("div", class_="article-metaline"):
                tag = meta.find("span", class_="article-meta-tag")
                val = meta.find("span", class_="article-meta-value")
                if tag and val:
                    meta_items.append((tag.get_text(strip=True), val.get_text(strip=True)))
                meta.decompose()

            for meta in main_content.find_all("div", class_="article-metaline-right"):
                tag = meta.find("span", class_="article-meta-tag")
                val = meta.find("span", class_="article-meta-value")
                if tag and val:
                    meta_items.append((tag.get_text(strip=True), val.get_text(strip=True)))
                meta.decompose()

            # 3. 取得主內文文字並做智慧排版與換行處理
            raw_text = main_content.get_text()

            # 圖片網址偵測 Regex
            img_url_pattern = re.compile(
                r'(https?://(?:i\.)?imgur\.com/[a-zA-Z0-9]+(?:\.[a-zA-Z]{3,4})?|https?://[^\s<>"\']+\.(?:jpg|jpeg|png|gif|webp|bmp))',
                re.IGNORECASE,
            )

            # 一般網址偵測 Regex
            link_url_pattern = re.compile(
                r'(https?://[^\s<>"\']+)',
                re.IGNORECASE,
            )

            # 將文字依換行分割，保留所有行距與縮排
            paragraphs = raw_text.split('\n')
            formatted_paragraphs = []

            for line in paragraphs:
                line_str = line.strip()
                if not line_str:
                    formatted_paragraphs.append('<br>')
                    continue

                # 簽名檔分界線與發信站美化
                if line_str == '--':
                    formatted_paragraphs.append('<hr style="border:none; border-top:1px dashed var(--border-color, #ccc); margin:16px 0;" />')
                    continue
                if line_str.startswith('※ 發信站:') or line_str.startswith('※ 文章網址:'):
                    escaped_line = py_html.escape(line_str)
                    linked_line = link_url_pattern.sub(r'<a href="\1" target="_blank" rel="noopener noreferrer" style="color:var(--accent-primary, #3b82f6); text-decoration:underline;">\1</a>', escaped_line)
                    formatted_paragraphs.append(f'<div style="font-size:12px; color:var(--text-muted, #666); margin:4px 0;">{linked_line}</div>')
                    continue

                # 檢查整行是否為圖片網址
                img_match = img_url_pattern.search(line_str)
                if img_match and len(line_str) == len(img_match.group(0)):
                    img_url = img_match.group(0)
                    if "imgur.com" in img_url and not any(img_url.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]):
                        img_url = img_url.replace("imgur.com", "i.imgur.com") + ".jpg"
                    formatted_paragraphs.append(f'<div style="margin:12px 0; text-align:center;"><img src="{img_url}" alt="PTT Image" style="max-width:100%; max-height:600px; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,0.1);" loading="lazy" /></div>')
                    continue

                # 一般內文行：轉義 HTML、替換圖片與超連結
                escaped = py_html.escape(line_str)

                def _img_sub(m):
                    u = m.group(1)
                    if "imgur.com" in u and not any(u.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]):
                        u = u.replace("imgur.com", "i.imgur.com") + ".jpg"
                    return f'<div style="margin:8px 0; text-align:center;"><img src="{u}" alt="PTT Image" style="max-width:100%; border-radius:6px;" loading="lazy" /></div>'

                with_imgs = img_url_pattern.sub(_img_sub, escaped)
                with_links = link_url_pattern.sub(r'<a href="\1" target="_blank" rel="noopener noreferrer" style="color:var(--accent-primary, #3b82f6); text-decoration:underline;">\1</a>', with_imgs)

                formatted_paragraphs.append(f'<p style="margin:6px 0; line-height:1.75; font-size:15px; color:var(--text-primary);">{with_links}</p>')

            # 4. 組合 BBS Metadata Header
            meta_block = ""
            if meta_items:
                meta_rows = "".join(
                    f'<div style="display:flex; align-items:center; gap:8px; font-size:13px; margin-bottom:4px;">'
                    f'<span style="font-weight:600; color:var(--text-secondary); width:40px; flex-shrink:0;">{py_html.escape(k)}</span>'
                    f'<span style="color:var(--text-primary);">{py_html.escape(v)}</span>'
                    f'</div>'
                    for k, v in meta_items
                )
                meta_block = (
                    '<div class="ptt-meta-card" style="margin-bottom:18px; padding:12px 14px; background:var(--bg-surface-elevated, rgba(0,0,0,0.03)); border-left:3px solid var(--accent-primary, #3b82f6); border-radius:4px;">'
                    + meta_rows
                    + '</div>'
                )

            # 5. 組合推文區塊
            pushes_block = ""
            if push_items_html:
                pushes_block = (
                    '<div style="margin-top:28px; padding:16px; background:var(--card-bg, rgba(0,0,0,0.02)); border-radius:10px; border:1px solid var(--border-color, rgba(0,0,0,0.08));">'
                    f'<h4 style="margin:0 0 12px 0; font-size:14px; font-weight:600; color:var(--text-primary, #111827);">💬 PTT 鄉民推文 ({len(push_items_html)})</h4>'
                    + "".join(push_items_html)
                    + '</div>'
                )

            body_html = meta_block + "".join(formatted_paragraphs) + pushes_block
            return HTMLSanitizer.clean(body_html)
        except Exception as exc:
            logger.debug(f"PTT custom extraction error: {exc}")
            return None

    @staticmethod
    def _extract_yahoo(html_str: str) -> Optional[str]:
        """Yahoo 新聞與影音內文專屬解析器 (Yahoo News .caas-body Fulltext Parser)."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html_str, "html.parser")
            body_container = (
                soup.find(class_=re.compile(r"caas-body|story-body|article-body"))
                or soup.find("article")
            )
            if not body_container:
                return None

            # 移除廣告、社群分享與無關推薦區塊
            for noise in body_container.find_all(
                class_=re.compile(r"caas-readmore|caas-share|ad-container|advertisement|inline-ad")
            ):
                noise.decompose()

            # 修正圖片來源
            for img in body_container.find_all("img"):
                real_src = img.get("data-src") or img.get("src") or img.get("data-original")
                if real_src and real_src.startswith("http"):
                    img["src"] = real_src
                    img["style"] = "max-width:100%; height:auto; border-radius:8px; margin:12px 0;"
                else:
                    img.decompose()

            paragraphs = body_container.find_all(["p", "img", "blockquote", "h2", "h3"])
            if not paragraphs:
                return None

            out_html = "".join(str(p) for p in paragraphs if p.get_text(strip=True) or p.name == "img")
            return HTMLSanitizer.clean(out_html) if len(out_html) > 50 else None
        except Exception as exc:
            logger.debug(f"Yahoo News custom extraction error: {exc}")
            return None

    @staticmethod
    def _extract_semantic_fallback(html_str: str) -> Optional[str]:
        """語意標籤與閱讀器啟發式回退抽取器 (Semantic HTML & Readability Heuristic Fallback)."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html_str, "html.parser")
            # 移除 script, style, nav, footer, header
            for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "aside"]):
                tag.decompose()

            main_elem = (
                soup.find("article")
                or soup.find("main")
                or soup.find(class_=re.compile(r"content|post-content|article-content|entry-content"))
                or soup.find(id=re.compile(r"content|main|article"))
            )

            if not main_elem:
                main_elem = soup.body

            if not main_elem:
                return None

            # 取得所有實質段落
            paragraphs = main_elem.find_all(["p", "img", "blockquote", "h2", "h3"])
            if not paragraphs:
                return None

            out_parts = []
            for p in paragraphs:
                if p.name == "img":
                    src = p.get("data-src") or p.get("src")
                    if src and src.startswith("http"):
                        out_parts.append(f'<p><img src="{src}" style="max-width:100%; border-radius:8px;" /></p>')
                else:
                    text = p.get_text(strip=True)
                    if len(text) > 5:
                        out_parts.append(f"<p>{text}</p>")

            if out_parts:
                combined = "".join(out_parts)
                return HTMLSanitizer.clean(combined) if len(combined) > 30 else None
            return None
        except Exception as exc:
            logger.debug(f"Semantic fallback error: {exc}")
            return None

    @classmethod
    def extract_full_text_from_html(
        cls, html_str: str, base_url: str = ""
    ) -> Optional[str]:
        """三階梯高韌性全文萃取引擎 (Multi-Tier High-Resilience Fulltext Extractor).

        階梯一：特定平台專屬語意解析 (PTT BBS + 推文 / Yahoo 新聞 .caas-body)
        階梯二：Trafilatura 機器學習智能正文抽取
        階梯三：Semantic HTML 與 Readability 啟發式段落回退

        :param html_str: 原始 HTML 標記字串 (Raw HTML markup)
        :param base_url: 基準來源網址 (Base URL)
        :return: 脫毒與格式化後的結構化 HTML 內文或 None
        """
        if not html_str:
            return None

        url_lower = (base_url or "").lower()

        # 階梯一 (Tier 1): 專屬平台抽取
        if "ptt.cc" in url_lower or 'id="main-content"' in html_str:
            ptt_res = cls._extract_ptt(html_str)
            if ptt_res and len(ptt_res) > 30:
                return ptt_res

        if "yahoo.com" in url_lower or "caas-body" in html_str:
            yahoo_res = cls._extract_yahoo(html_str)
            if yahoo_res and len(yahoo_res) > 50:
                return yahoo_res

        # 階梯二 (Tier 2): Trafilatura 機器學習正文萃取
        try:
            import trafilatura

            extracted = trafilatura.extract(
                html_str,
                url=base_url,
                include_links=True,
                include_images=True,
                output_format="html",
            )
            if extracted and len(extracted.strip()) > 50:
                clean_res = HTMLSanitizer.clean(extracted)
                if clean_res:
                    return clean_res
        except Exception as e:
            logger.debug(f"Trafilatura extraction failed for {base_url}: {e}")

        # 階梯三 (Tier 3): 語意 HTML 與 Readability 啟發式回退
        fallback_res = cls._extract_semantic_fallback(html_str)
        if fallback_res:
            return fallback_res

        return None

