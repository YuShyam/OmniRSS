"""聲明式網址比對器 (Declarative URL Pattern Matcher).

This module implements high-performance, robust URL pattern matching inspired by
Chrome Extension Match Patterns and standard wildcards, with LRU regex compilation caching.
"""

from functools import lru_cache
import re
from typing import Sequence
from urllib.parse import urlparse


@lru_cache(maxsize=512)
def compile_pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """將 Match Pattern 編譯為高效率之正則表達式 (Compile URL match pattern to regex).

    支援規則:
    - '<all_urls>' 或 '*' -> 匹配所有 http/https 網址
    - '*://*.example.com/*' -> scheme 匹配 http/https，host 匹配 example.com 及其子網域
    - 'https://example.com/path/*' -> 精確 scheme 與 host，path 支援萬用字元
    - 任意 wildcard pattern 如 '*ptt.cc*'

    :param pattern: 網址比對樣式字串
    :return: 編譯後之正則表達式 Pattern
    """
    p = pattern.strip()
    if p in ("<all_urls>", "*", "*://*/*", "*://*"):
        return re.compile(r"^https?://.*$", re.IGNORECASE)

    # 處理標準 scheme://host/path 格式
    if "://" in p:
        scheme_part, rest = p.split("://", 1)
        if "/" in rest:
            host_part, path_part = rest.split("/", 1)
            path_part = "/" + path_part
        else:
            host_part = rest
            path_part = "/*"

        # 1. Scheme regex
        if scheme_part == "*":
            scheme_re = r"https?"
        else:
            scheme_re = re.escape(scheme_part)

        # 2. Host regex
        if host_part == "*":
            host_re = r"[^/]+"
        elif host_part.startswith("*."):
            base_domain = host_part[2:]
            host_re = r"(?:[a-zA-Z0-9\-._]+\.)?" + re.escape(base_domain)
        else:
            host_re = re.escape(host_part)

        # 3. Path regex (將 * 轉為 .*)
        if path_part == "/*":
            path_re = r"(?:/.*)?"
        else:
            escaped_path = re.escape(path_part).replace(r"\*", r".*")
            path_re = escaped_path

        pattern_str = f"^{scheme_re}://{host_re}{path_re}$"
        return re.compile(pattern_str, re.IGNORECASE)

    # 一般 Wildcard / Glob pattern
    escaped = re.escape(p).replace(r"\*", r".*")
    return re.compile(f"^{escaped}$", re.IGNORECASE)


def match_url_patterns(url: str, patterns: Sequence[str]) -> bool:
    """檢查指定網址是否命中任一 Match Pattern (Check if URL matches any pattern).

    :param url: 待檢驗之完整網址字串
    :param patterns: 樣式清單 (若清單為空則視為全域相容，回傳 True)
    :return: 是否命中比對
    """
    if not patterns:
        return True

    clean_url = (url or "").strip()
    if not clean_url:
        return False

    for pat in patterns:
        if not pat or pat in ("<all_urls>", "*"):
            return True
        try:
            rgx = compile_pattern_to_regex(pat)
            if rgx.match(clean_url):
                return True
        except Exception:
            # 防衛性忽略非法正則，繼續檢查下一個 pattern
            continue

    return False
