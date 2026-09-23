"""零信任資安防禦與安全網關 (Zero-Trust Security Gateway & Anti-SSRF Firewall).

This module provides 4-layer Anti-SSRF protection, nh3 static HTML sanitization,
Argon2id password hashing, constant-time token verification, and Zero-Script CSP generation.
"""

from datetime import datetime, timedelta, timezone
import hmac
import html
import ipaddress
import re
import secrets
import socket
from typing import Any, Optional
import urllib.parse
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import jwt
from loguru import logger
from omnirss.sdk.models import MediaManifestDTO

try:
    import nh3
except ImportError:
    nh3 = None  # Fallback for environments before nh3 install finishes


# 私有與保留網段黑名單 (Blacklisted Private and Reserved IP Subnets)
FORBIDDEN_SUBNETS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local & OCI metadata (169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),  # Multicast
    ipaddress.ip_network("240.0.0.0/4"),  # Reserved
    ipaddress.ip_network("255.255.255.255/32"),
    # IPv6
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fc00::/7"),  # Unique Local
    ipaddress.ip_network("fe80::/10"),  # Link-local
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
]


class SSRFBlockedException(Exception):
    """SSRF 網關攔截例外 (SSRF Gateway Blocked Exception).

    Raised when a requested URL resolves to a forbidden or private network IP.
    """

    def __init__(self, message: str, host: str, resolved_ips: list[str]) -> None:
        super().__init__(message)
        self.host = host
        self.resolved_ips = resolved_ips


class AntiSSRFGateway:
    """四重防禦 Anti-SSRF 網路網關 (The 4-Layer Anti-SSRF Network Gateway).

    Validates URL safety by pre-resolving hostnames, blocking private/cloud metadata IPs,
    and preventing DNS rebinding attacks.
    """

    @staticmethod
    def is_ip_forbidden(ip_str: str) -> bool:
        """檢驗 IP 是否屬於私有或受限制網段 (Check if IP address is blacklisted).

        :param ip_str: 待檢驗之 IP 字串 (IP address string)
        :return: 若屬於受限制網段則回傳 True
        """
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            return True

        # 若為 IPv4-mapped IPv6，解包為原生 IPv4 檢驗
        if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
            ip_obj = ip_obj.ipv4_mapped

        for net in FORBIDDEN_SUBNETS:
            if ip_obj in net:
                return True

        return False

    @classmethod
    def verify_url(cls, url: str) -> list[str]:
        """驗證目標 URL 之網路連線安全性 (Verify URL safety and resolve valid public IPs).

        :param url: 目標連線網址 (Target connection URL)
        :return: 通過檢驗之解析實體 IP 清單 (List of verified public IPs)
        :raises SSRFBlockedException: 命中私有網段或非法協議時拋出
        """
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() not in ("http", "https"):
            raise SSRFBlockedException(
                f"Unsupported URL scheme: {parsed.scheme}",
                host=parsed.netloc,
                resolved_ips=[],
            )

        hostname = parsed.hostname
        if not hostname:
            raise SSRFBlockedException(
                "Invalid URL with empty hostname", host="", resolved_ips=[]
            )

        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)

        # 執行 DNS 解析，獲取所有 A 與 AAAA 記錄
        try:
            addr_info = socket.getaddrinfo(
                hostname, port, type=socket.SOCK_STREAM
            )
        except socket.gaierror as e:
            raise SSRFBlockedException(
                f"DNS resolution failed for host '{hostname}': {e}",
                host=hostname,
                resolved_ips=[],
            )

        resolved_ips: list[str] = []
        for family, _, _, _, sockaddr in addr_info:
            ip_candidate = sockaddr[0]
            if ip_candidate not in resolved_ips:
                resolved_ips.append(ip_candidate)

        if not resolved_ips:
            raise SSRFBlockedException(
                f"No IP addresses resolved for host '{hostname}'",
                host=hostname,
                resolved_ips=[],
            )

        # 逐一檢查所有解析出的 IP
        for ip_str in resolved_ips:
            if cls.is_ip_forbidden(ip_str):
                logger.warning(
                    f"Anti-SSRF Blocked: Host '{hostname}' resolved to forbidden IP '{ip_str}'"
                )
                raise SSRFBlockedException(
                    f"Access to host '{hostname}' is blocked due to private/restricted IP ({ip_str})",
                    host=hostname,
                    resolved_ips=resolved_ips,
                )

        return resolved_ips


class HTMLSanitizer:
    """HTML 靜態脫毒與清洗器 (HTML Sanitizer & De-fanger).

    Strips executable scripts, iframes, and malicious attributes from external content using nh3.
    """

    ALLOWED_TAGS = {
        "a",
        "b",
        "blockquote",
        "br",
        "code",
        "div",
        "em",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "s",
        "span",
        "strike",
        "strong",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
        "video",
        "audio",
        "source",
    }

    ALLOWED_ATTRIBUTES = {
        "a": {"href", "title", "target"},
        "img": {"src", "alt", "title", "width", "height", "loading"},
        "video": {"src", "controls", "poster", "width", "height"},
        "audio": {"src", "controls"},
        "source": {"src", "type"},
        "*": {"class", "id", "style"},
    }

    @classmethod
    def clean(cls, raw_html: str) -> str:
        """清洗並拔除所有惡意腳本 (Sanitize and de-fang raw HTML content).

        :param raw_html: 原始外部 HTML 字串 (Raw untrusted HTML)
        :return: 脫毒後的乾淨 HTML 字串 (Safe de-fanged HTML)
        """
        if not raw_html:
            return ""

        if nh3 is not None:
            clean_html = nh3.clean(
                raw_html,
                tags=cls.ALLOWED_TAGS,
                attributes=cls.ALLOWED_ATTRIBUTES,
                url_schemes={"http", "https", "mailto", "data"},
                link_rel="noopener noreferrer",
                strip_comments=True,
            )
            return clean_html

        # 基本正則備援防禦 (若 nh3 未載入)
        cleaned = re.sub(
            r"<(script|iframe|object|embed|applet)[^>]*>.*?</\1>",
            "",
            raw_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        cleaned = re.sub(r"on\w+\s*=\s*['\"][^'\"]*['\"]", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"javascript:[^\s'\"]*", "", cleaned, flags=re.IGNORECASE)
        return cleaned

    @classmethod
    def extract_snippet(cls, html_text: str, max_chars: int = 200) -> str:
        """提取純文字摘要 (Extract plain text preview snippet from HTML).

        :param html_text: HTML 文章內文 (Article HTML body)
        :param max_chars: 摘要最大字元數 (Maximum characters to keep)
        :return: 清理後的純文字預覽 (Clean plain text snippet)
        """
        if not html_text:
            return ""

        # 移除標籤並轉義實體
        text = re.sub(r"<[^>]+>", " ", html_text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > max_chars:
            return text[:max_chars] + "..."
        return text

    @classmethod
    def extract_media(cls, html_text: str) -> MediaManifestDTO:
        """提取內文所有多媒體 URL 清單 (Extract all media URLs from HTML).

        :param html_text: HTML 文章內文 (Article HTML body)
        :return: MediaManifestDTO 實例
        """
        manifest = MediaManifestDTO()
        if not html_text:
            return manifest

        # 圖片
        img_srcs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_text, re.IGNORECASE)
        manifest.images = [src for src in img_srcs if src.startswith(("http://", "https://", "data:"))]

        # 影片
        video_srcs = re.findall(r'<video[^>]+src=["\']([^"\']+)["\']', html_text, re.IGNORECASE)
        source_video_srcs = re.findall(r'<source[^>]+src=["\']([^"\']+)["\'][^>]+type=["\']video/', html_text, re.IGNORECASE)
        manifest.videos = list(set(video_srcs + source_video_srcs))

        # 音訊
        audio_srcs = re.findall(r'<audio[^>]+src=["\']([^"\']+)["\']', html_text, re.IGNORECASE)
        source_audio_srcs = re.findall(r'<source[^>]+src=["\']([^"\']+)["\'][^>]+type=["\']audio/', html_text, re.IGNORECASE)
        manifest.audios = list(set(audio_srcs + source_audio_srcs))

        return manifest


class PasswordHasherTool:
    """Argon2id 密碼雜湊與驗證工具 (Argon2id Password Security Tool)."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=2,
            memory_cost=65536,
            parallelism=2,
            hash_len=32,
            salt_len=16,
        )

    def hash_password(self, password: str) -> str:
        """生成 Argon2id 密碼雜湊 (Generate Argon2id password hash).

        :param password: 明文密碼 (Plaintext password)
        :return: 雜湊字串 (Argon2id hash string)
        """
        return self._hasher.hash(password)

    def verify_password(self, password_hash: str, password: str) -> bool:
        """驗證密碼是否正確 (Verify password against Argon2id hash).

        :param password_hash: 資料庫存儲之雜湊 (Stored password hash)
        :param password: 使用者輸入之明文 (Input plaintext password)
        :return: 驗證成功回傳 True，否則回傳 False
        """
        try:
            return self._hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False
        except Exception:
            return False


class TokenManager:
    """安全 Token 與 API Key 管理工具 (Security Token and API Key Manager)."""

    ALGORITHM = "HS256"

    @classmethod
    def generate_api_key(cls, prefix: str = "omni_") -> str:
        """生成隨機安全 API Key (Generate high-entropy API key).

        :param prefix: 識別前綴 (Key prefix)
        :return: 格式化之 API Key 字串 (e.g. 'omni_aBc123...')
        """
        return f"{prefix}{secrets.token_urlsafe(32)}"

    @classmethod
    def verify_api_key(cls, provided_key: str, actual_key: str) -> bool:
        """常數時間比對 API Key 防範側信道攻擊 (Constant-time API Key verification).

        :param provided_key: 客戶端提供之金鑰 (Key provided by client)
        :param actual_key: 資料庫存儲之真實金鑰 (True key stored in DB)
        :return: 若完全相符則回傳 True
        """
        return hmac.compare_digest(provided_key, actual_key)

    @classmethod
    def create_jwt_token(
        cls,
        payload: dict[str, Any],
        secret_key: str,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """簽發 JWT 存取權杖 (Issue signed JWT access token).

        :param payload: 載荷資料 (Data payload)
        :param secret_key: 簽章密鑰 (HMAC secret key)
        :param expires_delta: 有效時長 (Token expiration duration)
        :return: 簽名之 JWT 字串
        """
        to_encode = payload.copy()
        expire = datetime.now(timezone.utc) + (
            expires_delta or timedelta(days=7)
        )
        to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
        return jwt.encode(to_encode, secret_key, algorithm=cls.ALGORITHM)

    @classmethod
    def decode_jwt_token(
        cls, token: str, secret_key: str
    ) -> Optional[dict[str, Any]]:
        """解碼並校驗 JWT 權杖 (Decode and validate JWT access token).

        :param token: JWT 字串 (Token string)
        :param secret_key: 簽章密鑰 (HMAC secret key)
        :return: 解碼之載荷字典；若無效或過期回傳 None
        """
        try:
            return jwt.decode(token, secret_key, algorithms=[cls.ALGORITHM])
        except jwt.PyJWTError as e:
            logger.debug(f"JWT verification error: {e}")
            return None


def get_security_headers() -> dict[str, str]:
    """產出微核心 6 大安全防禦標頭 (Generate the 6 Core HTTP Security Headers).

    :return: 標頭字典 (Security headers dictionary)
    """
    return {
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'none'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src * data:; "
            "media-src *; "
            "frame-src 'none'; "
            "object-src 'none';"
        ),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "X-XSS-Protection": "0",
        "Cross-Origin-Opener-Policy": "same-origin",
    }
