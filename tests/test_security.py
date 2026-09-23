"""資安與 Anti-SSRF 防禦單元測試 (Security and Anti-SSRF Unit Tests).

Tests Anti-SSRF IP inspection, nh3 HTML static de-fanging, Argon2id password hashing, and token validation.
"""

from datetime import timedelta
import pytest
from omnirss.core.security import (
    AntiSSRFGateway,
    HTMLSanitizer,
    PasswordHasherTool,
    SSRFBlockedException,
    TokenManager,
    get_security_headers,
)


def test_anti_ssrf_ip_blacklist() -> None:
    """測試私有與雲端元數據 IP 阻擋規則 (Test Anti-SSRF subnet filters)."""
    # 私有與本地網段
    assert AntiSSRFGateway.is_ip_forbidden("127.0.0.1") is True
    assert AntiSSRFGateway.is_ip_forbidden("10.0.0.5") is True
    assert AntiSSRFGateway.is_ip_forbidden("172.16.1.1") is True
    assert AntiSSRFGateway.is_ip_forbidden("192.168.1.100") is True

    # OCI / AWS 雲端元數據 IP
    assert AntiSSRFGateway.is_ip_forbidden("169.254.169.254") is True
    assert AntiSSRFGateway.is_ip_forbidden("169.254.0.1") is True

    # 公開合法 IP
    assert AntiSSRFGateway.is_ip_forbidden("8.8.8.8") is False
    assert AntiSSRFGateway.is_ip_forbidden("1.1.1.1") is False
    assert AntiSSRFGateway.is_ip_forbidden("104.26.12.13") is False


def test_anti_ssrf_url_verification() -> None:
    """測試網址安全驗證與例外攔截 (Test URL verification blocking)."""
    with pytest.raises(SSRFBlockedException):
        AntiSSRFGateway.verify_url("http://127.0.0.1:8000/secret")

    with pytest.raises(SSRFBlockedException):
        AntiSSRFGateway.verify_url("http://169.254.169.254/opc/v1/instance")

    with pytest.raises(SSRFBlockedException):
        AntiSSRFGateway.verify_url("ftp://example.com/file.xml")


def test_html_sanitizer_defanging() -> None:
    """測試 nh3 靜態拔牙脫毒與 XSS 防禦 (Test HTML de-fanging)."""
    dirty_html = """
    <div>
        <h1>安全文章標題</h1>
        <p>這是一段正常文字<strong>重要內容</strong>。</p>
        <script>alert('XSS 木馬執行');</script>
        <img src="https://example.com/photo.jpg" onload="maliciousAttack()" alt="圖片" />
        <a href="javascript:stealCookies()">惡意連結</a>
        <iframe src="http://evil.com/subframe"></iframe>
    </div>
    """
    clean_html = HTMLSanitizer.clean(dirty_html)

    # 驗證惡意標籤與屬性徹底消失
    assert "<script" not in clean_html.lower()
    assert "alert(" not in clean_html
    assert "onload" not in clean_html.lower()
    assert "iframe" not in clean_html.lower()
    assert "javascript:" not in clean_html.lower()

    # 驗證正常圖文標籤完整保留
    assert "<h1>安全文章標題</h1>" in clean_html
    assert "<strong>重要內容</strong>" in clean_html
    assert "https://example.com/photo.jpg" in clean_html


def test_html_snippet_and_media_extraction() -> None:
    """測試純文字摘要與多媒體提取 (Test snippet and media extraction)."""
    html_content = """
    <p>第一段文字 <a href="https://link.com">連結</a></p>
    <img src="https://example.com/img1.png" />
    <img src="https://example.com/img2.jpg" />
    <video src="https://example.com/video1.mp4"></video>
    """
    snippet = HTMLSanitizer.extract_snippet(html_content, max_chars=10)
    assert snippet == "第一段文字 連結" or "第一段文字" in snippet

    media = HTMLSanitizer.extract_media(html_content)
    assert len(media.images) == 2
    assert "https://example.com/img1.png" in media.images
    assert len(media.videos) == 1
    assert "https://example.com/video1.mp4" in media.videos


def test_password_hasher_argon2() -> None:
    """測試 Argon2id 密碼雜湊與比對 (Test Argon2id hashing)."""
    hasher = PasswordHasherTool()
    raw_pwd = "SuperSecretPassword123!"

    hashed = hasher.hash_password(raw_pwd)
    assert hashed.startswith("$argon2id$")

    assert hasher.verify_password(hashed, raw_pwd) is True
    assert hasher.verify_password(hashed, "WrongPassword") is False


def test_token_and_api_key_manager() -> None:
    """測試 JWT 與 API Key 簽署及常數時間比對 (Test JWT and API Key manager)."""
    # API Key
    key1 = TokenManager.generate_api_key("omni_")
    assert key1.startswith("omni_")
    assert TokenManager.verify_api_key(key1, key1) is True
    assert TokenManager.verify_api_key(key1, "omni_wrong") is False

    # JWT Token
    secret = "test_super_secret_signing_key_32bytes"
    payload = {"sub": "alice", "user_id": 42, "is_admin": True}

    token = TokenManager.create_jwt_token(payload, secret, expires_delta=timedelta(hours=1))
    decoded = TokenManager.decode_jwt_token(token, secret)

    assert decoded is not None
    assert decoded["sub"] == "alice"
    assert decoded["user_id"] == 42
    assert decoded["is_admin"] is True


def test_security_headers() -> None:
    """測試 6 大安全標頭產出 (Test HTTP security headers)."""
    headers = get_security_headers()
    assert "Content-Security-Policy" in headers
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert "connect-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
