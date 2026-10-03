"""PTT BBS 閱讀體驗增強外掛 (PTT BBS Reading Enhancer Plugin).

This plugin parses PTT Web BBS structure and RSS/Atom feeds using high-performance
lxml and regex, separating BBS header metadata, preserving indentation/newlines, auto-embedding
Imgur/image URLs, and rendering push comments into structured cards with user-defined options.
"""

import html as py_html
import re
from typing import Any, Optional, TYPE_CHECKING
import lxml.html
from loguru import logger
from omnirss.core.security import HTMLSanitizer
from omnirss.sdk.base_plugin import BaseProcessorPlugin
from omnirss.sdk.models import ArticleDTO

if TYPE_CHECKING:
    from omnirss.sdk.context import PluginContext

_PTT_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Cookie": "over18=1",
}


async def _fetch_full_page(url: str, context: Optional["PluginContext"] = None) -> str:
    """抓取完整網頁內容 (優先用 context.http_get，無則用 aiohttp 自建 session).

    :param url: 目標頁面網址
    :param context: 外掛上下文 (可選，提供 http_client)
    :return: 頁面 HTML 字串，失敗時回傳空字串
    """
    try:
        if context and context.http_client is not None:
            resp = await context.http_get(url, headers=_PTT_FETCH_HEADERS)
            if hasattr(resp, "text"):
                return await resp.text() if callable(resp.text) else resp.text
            return str(resp)
        else:
            import aiohttp
            async with aiohttp.ClientSession(headers=_PTT_FETCH_HEADERS) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    return ""
    except Exception as exc:
        logger.debug(f"PttEnhancer _fetch_full_page error for {url}: {exc}")
        return ""


PUSH_PATTERN = re.compile(
    r'^(?:<p[^>]*>)?\s*(推|噓|→|\u2192)\s+([a-zA-Z0-9_\-]+)\s*[:：]\s*(.*?)(?:\s+((?:\d{1,3}\.){3}\d{1,3}))?(?:\s+(\d{1,2}/\d{1,2}(?:\s+\d{1,2}:\d{1,2}(?::\d{1,2})?)?))?(?:</p>)?$',
    re.IGNORECASE,
)

IMG_URL_PATTERN = re.compile(
    r'(https?://(?:i\.)?imgur\.com/[a-zA-Z0-9]+(?:\.[a-zA-Z]{3,4})?|https?://[^\s<>"\']+\.(?:jpg|jpeg|png|gif|webp|bmp|svg)(?:\?[^\s<>"\']*)?)',
    re.IGNORECASE,
)

YT_URL_PATTERN = re.compile(
    r'(https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?(?:[^\s<>"\']*&)?v=|embed/|v/|shorts/|live/)|youtu\.be/)([a-zA-Z0-9_\-]{11})(?:[^\s<>"\']*))',
    re.IGNORECASE,
)

LINK_URL_PATTERN = re.compile(r'(https?://[^\s<>"\']+)', re.IGNORECASE)

BBS_HEADER_PATTERN = re.compile(
    r'^\s*作者\s+([^\s]+(?:\s*\([^\)]*\))?)\s+看板\s+([a-zA-Z0-9_\-]+)'
)


def _build_yt_preview_card(yt_url: str, video_id: str) -> str:
    """生成結構化 YouTube 影片預告與縮圖卡片 (Build YouTube video preview card).

    :param yt_url: 原始 YouTube 影片網址
    :param video_id: 11 碼 YouTube 影片 ID
    :return: 結構化預覽卡片 HTML 字串
    """
    esc_url = py_html.escape(yt_url)
    thumb_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    return (
        f'<div class="ptt-yt-preview" style="margin:14px auto; max-width:600px; border-radius:10px; overflow:hidden; border:1px solid var(--border-color, rgba(0,0,0,0.12)); background:var(--card-bg, #ffffff); box-shadow:0 2px 8px rgba(0,0,0,0.06);">'
        f'<a href="{esc_url}" target="_blank" rel="noopener noreferrer" style="display:block; text-decoration:none; color:inherit;">'
        f'<div style="position:relative; width:100%; aspect-ratio:16/9; background:#000000; overflow:hidden;">'
        f'<img src="{thumb_url}" alt="YouTube Video Preview" style="width:100%; height:100%; object-fit:cover; display:block;" loading="lazy" />'
        f'<div style="position:absolute; top:50%; left:50%; transform:translate(-50%, -50%); width:56px; height:40px; background:rgba(239,68,68,0.92); border-radius:10px; display:flex; align-items:center; justify-content:center; box-shadow:0 4px 12px rgba(0,0,0,0.45);">'
        f'<svg width="20" height="20" viewBox="0 0 24 24" fill="#ffffff" style="margin-left:2px;"><path d="M8 5v14l11-7z"/></svg>'
        f'</div>'
        f'</div>'
        f'<div style="padding:10px 14px; display:flex; align-items:center; justify-content:space-between; font-size:13px; color:var(--text-secondary, #4b5563); background:var(--bg-surface-elevated, rgba(0,0,0,0.02));">'
        f'<span style="font-weight:600; color:#ef4444; display:flex; align-items:center; gap:6px;">'
        f'<svg width="16" height="16" viewBox="0 0 24 24" fill="#ef4444"><path d="M19.615 3.184c-3.604-.246-11.631-.245-15.23 0-3.897.266-4.356 2.62-4.385 8.816.029 6.185.484 8.549 4.385 8.816 3.6.245 11.626.246 15.23 0 3.897-.266 4.356-2.62 4.385-8.816-.029-6.185-.484-8.549-4.385-8.816zm-10.615 12.816v-8l8 3.993-8 4.007z"/></svg>'
        f'YouTube 影片'
        f'</span>'
        f'<span style="color:var(--accent-primary, #3b82f6); text-decoration:underline; font-size:12px;">點擊開啟觀看 ↗</span>'
        f'</div>'
        f'</a>'
        f'</div>'
    )


def normalize_ptt_feed_url(url: str) -> str:
    """將舊版 rss.ptt.cc 網址正規化為官方標準 Atom 訂閱網址 (Normalize legacy rss.ptt.cc URL).

    :param url: 來源訂閱網址
    :return: 正規化後之 PTT Atom 網址
    """
    clean_url = (url or "").strip()
    if "rss.ptt.cc" in clean_url.lower():
        board = clean_url.rstrip("/").split("/")[-1].replace(".xml", "")
        return f"https://www.ptt.cc/atom/{board}.xml"
    return clean_url


def _clean_and_split_raw_lines(raw_lines: list[str]) -> list[str]:
    """將雜亂或粘連的 PTT 文字行分解為乾淨獨立的行清單 (Clean and split messy PTT lines).

    :param raw_lines: 原始文字行清單
    :return: 規範化後的獨立文字行清單
    """
    result: list[str] = []
    nav_pattern = re.compile(
        r'^\s*批踢踢實業坊\s*(?:[›>]\s*)?(?:看板\s+[a-zA-Z0-9_\-]+\s*)?(?:關於我們\s*)?(?:聯絡資訊\s*)?(?:返回看板\s*)?',
        re.IGNORECASE,
    )
    for raw in raw_lines:
        s = raw.strip()
        if not s:
            result.append("")
            continue

        # 移除頂部導航欄殘留文字
        s = nav_pattern.sub("", s).strip()
        if not s:
            continue

        # 處理單行包含的署名與發信站簽名檔
        if "-- ※ 發信站:" in s or "--※ 發信站:" in s or "-- ※發信站:" in s:
            parts = re.split(r'(--\s*※\s*發信站:)', s, maxsplit=1)
            if parts[0].strip():
                result.append(parts[0].strip())
            result.append("--")
            rest = ("※ 發信站:" + parts[2]) if len(parts) > 2 else ""
            if rest:
                if "※ 文章網址:" in rest:
                    sig_parts = re.split(r'(※\s*文章網址:)', rest, maxsplit=1)
                    if sig_parts[0].strip():
                        result.append(sig_parts[0].strip())
                    if len(sig_parts) > 1:
                        result.append("".join(sig_parts[1:]).strip())
                else:
                    result.append(rest.strip())
            continue

        if "※ 文章網址:" in s and not s.startswith("※ 文章網址:"):
            url_parts = re.split(r'(※\s*文章網址:)', s, maxsplit=1)
            if url_parts[0].strip():
                result.append(url_parts[0].strip())
            if len(url_parts) > 1:
                result.append("".join(url_parts[1:]).strip())
            continue

        result.append(s)
    return result


def _format_text_lines(
    lines: list[str],
    auto_embed_images: bool = True,
    auto_embed_videos: bool = True,
    url: str = "",
    board: str = "",
) -> list[str]:
    """格式化純文字或段落列表為結構化 HTML 內文 (Format text lines into structured HTML).

    :param lines: 文字行或段落列表
    :param auto_embed_images: 是否自動將圖片網址轉換為預覽圖
    :param auto_embed_videos: 是否自動將 YouTube 網址轉換為預覽卡片
    :param url: 原文網址
    :param board: 看板名稱
    :return: 格式化後之 HTML 段落清單
    """
    formatted: list[str] = []
    consecutive_empty = 0
    expanded_lines = _clean_and_split_raw_lines(lines)
    seen_img_urls: set[str] = set()
    seen_yt_vids: set[str] = set()

    for line_str in expanded_lines:
        if not line_str:
            consecutive_empty += 1
            if consecutive_empty <= 1 and formatted:
                formatted.append("<br>")
            continue

        consecutive_empty = 0

        if line_str == "--":
            formatted.append(
                '<hr style="border:none; border-top:1px dashed var(--border-color, #ccc); margin:16px 0;" />'
            )
            continue

        if line_str.startswith("※ 發信站:") or line_str.startswith("※ 文章網址:") or line_str.startswith("※ 編輯:"):
            escaped_line = py_html.escape(line_str)
            linked_line = LINK_URL_PATTERN.sub(
                r'<a href="\1" target="_blank" rel="noopener noreferrer" style="color:var(--accent-primary, #3b82f6); text-decoration:underline;">\1</a>',
                escaped_line,
            )
            formatted.append(
                f'<div style="font-size:12px; color:var(--text-muted, #666); margin:4px 0;">{linked_line}</div>'
            )
            continue

        # 1. 檢查整行是否為單一 YouTube 網址 (獨立 YouTube 影片預告卡片)
        yt_match = YT_URL_PATTERN.fullmatch(line_str.strip())
        if auto_embed_videos and yt_match:
            yt_url = yt_match.group(1)
            video_id = yt_match.group(2)
            if video_id in seen_yt_vids:
                formatted.append(
                    f'<p style="margin:6px 0; line-height:1.75; font-size:15px; color:var(--text-primary);"><a href="{py_html.escape(yt_url)}" target="_blank" rel="noopener noreferrer" style="color:var(--accent-primary, #3b82f6); text-decoration:underline;">{py_html.escape(yt_url)}</a></p>'
                )
            else:
                seen_yt_vids.add(video_id)
                formatted.append(_build_yt_preview_card(yt_url, video_id))
            continue

        # 2. 檢查整行是否為單一圖片網址 (獨立圖片區塊)
        img_match = IMG_URL_PATTERN.fullmatch(line_str.strip())
        if auto_embed_images and img_match:
            img_url = img_match.group(1)
            if "imgur.com" in img_url and not any(
                img_url.lower().endswith(ext)
                for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]
            ):
                img_url = img_url.replace("imgur.com", "i.imgur.com") + ".jpg"

            norm_img = img_url.split("?")[0].lower()
            if norm_img in seen_img_urls:
                formatted.append(
                    f'<p style="margin:6px 0; line-height:1.75; font-size:15px; color:var(--text-primary);"><a href="{py_html.escape(img_url)}" target="_blank" rel="noopener noreferrer" style="color:var(--accent-primary, #3b82f6); text-decoration:underline;">{py_html.escape(img_url)}</a></p>'
                )
                continue

            seen_img_urls.add(norm_img)
            formatted.append(
                f'<div style="margin:12px 0; text-align:center;">'
                f'<img src="{py_html.escape(img_url)}" alt="PTT Image" style="max-width:100%; max-height:600px; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,0.1);" loading="lazy" />'
                f"</div>"
            )
            continue

        # 3. 混合文字行：將 URL 安全切割分塊處理
        parts: list[str] = []
        last_idx = 0
        for m in LINK_URL_PATTERN.finditer(line_str):
            start, end = m.span()
            if start > last_idx:
                parts.append(py_html.escape(line_str[last_idx:start]))
            raw_u = m.group(1)

            # 判斷是否為 YouTube 影片
            m_yt = YT_URL_PATTERN.fullmatch(raw_u)
            if auto_embed_videos and m_yt:
                yt_url = m_yt.group(1)
                vid = m_yt.group(2)
                if vid not in seen_yt_vids:
                    seen_yt_vids.add(vid)
                    parts.append(_build_yt_preview_card(yt_url, vid))
                else:
                    parts.append(
                        f'<a href="{py_html.escape(raw_u)}" target="_blank" rel="noopener noreferrer" style="color:var(--accent-primary, #3b82f6); text-decoration:underline;">{py_html.escape(raw_u)}</a>'
                    )
            # 判斷是否為圖片
            elif auto_embed_images and bool(IMG_URL_PATTERN.fullmatch(raw_u)):
                clean_img = raw_u
                if "imgur.com" in clean_img and not any(
                    clean_img.lower().endswith(ext)
                    for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]
                ):
                    clean_img = clean_img.replace("imgur.com", "i.imgur.com") + ".jpg"

                norm_clean_img = clean_img.split("?")[0].lower()
                if norm_clean_img not in seen_img_urls:
                    seen_img_urls.add(norm_clean_img)
                    parts.append(
                        f'<div style="margin:8px 0; text-align:center;"><img src="{py_html.escape(clean_img)}" alt="PTT Image" style="max-width:100%; max-height:550px; border-radius:6px;" loading="lazy" /></div>'
                    )
                else:
                    parts.append(
                        f'<a href="{py_html.escape(raw_u)}" target="_blank" rel="noopener noreferrer" style="color:var(--accent-primary, #3b82f6); text-decoration:underline;">{py_html.escape(raw_u)}</a>'
                    )
            else:
                parts.append(
                    f'<a href="{py_html.escape(raw_u)}" target="_blank" rel="noopener noreferrer" style="color:var(--accent-primary, #3b82f6); text-decoration:underline;">{py_html.escape(raw_u)}</a>'
                )
            last_idx = end
        if last_idx < len(line_str):
            parts.append(py_html.escape(line_str[last_idx:]))

        line_html = "".join(parts)
        formatted.append(
            f'<p style="margin:6px 0; line-height:1.75; font-size:15px; color:var(--text-primary);">{line_html}</p>'
        )

    return formatted


def render_ptt_components(
    meta_items: list[tuple[str, str]],
    body_html_parts: list[str],
    push_items: list[dict[str, str]],
    config: Optional[dict[str, Any]] = None,
) -> str:
    """渲染 PTT 結構化卡片與推文組件 (Render structured PTT components and pushes card).

    :param meta_items: 文章標頭元數據清單 [(欄位名, 值)]
    :param body_html_parts: 文章主體 HTML 片段
    :param push_items: 結構化推文資料清單
    :param config: 外掛設定參數
    :return: 經安全清洗之完整 HTML 字串
    """
    cfg = config or {}
    collapse_pushes = bool(cfg.get("collapse_pushes", False))
    hide_arrow_pushes = bool(cfg.get("hide_arrow_pushes", False))
    max_pushes_display = int(cfg.get("max_pushes_display", 0) or 0)

    # 1. Metadata Block
    meta_block = ""
    if meta_items:
        meta_row_list: list[str] = []
        for k, v in meta_items:
            if not v:
                continue
            if k == "作者":
                m_auth = re.match(r"^([a-zA-Z0-9_\-]+)", v)
                if m_auth:
                    uid = m_auth.group(1)
                    val_html = (
                        f'<a href="https://www.pttweb.cc/user/{py_html.escape(uid)}" target="_blank" rel="noopener noreferrer" '
                        f'style="color:var(--accent-primary, #3b82f6); text-decoration:underline;" title="在 PttWeb 查看 {py_html.escape(uid)} 的文章">'
                        f"{py_html.escape(v)}</a>"
                    )
                else:
                    val_html = py_html.escape(v)
            elif k == "看板":
                val_html = (
                    f'<a href="https://www.pttweb.cc/bbs/{py_html.escape(v)}" target="_blank" rel="noopener noreferrer" '
                    f'style="color:var(--accent-primary, #3b82f6); text-decoration:underline;" title="在 PttWeb 查看 {py_html.escape(v)} 看板">'
                    f"{py_html.escape(v)}</a>"
                )
            else:
                val_html = py_html.escape(v)

            meta_row_list.append(
                f'<div style="display:flex; align-items:center; gap:8px; font-size:13px; margin-bottom:4px;">'
                f'<span style="font-weight:600; color:var(--text-secondary); width:40px; flex-shrink:0;">{py_html.escape(k)}</span>'
                f'<span style="color:var(--text-primary);">{val_html}</span>'
                f"</div>"
            )

        if meta_row_list:
            meta_block = (
                f'<div class="ptt-meta-card" style="margin-bottom:18px; padding:12px 14px; background:var(--bg-surface-elevated, rgba(0,0,0,0.03)); border-left:3px solid var(--accent-primary, #3b82f6); border-radius:4px;">'
                f'{"".join(meta_row_list)}'
                f"</div>"
            )

    # 2. Push Comments Block
    pushes_block = ""
    push_items_html: list[str] = []
    push_up_count = 0
    push_down_count = 0
    push_arrow_count = 0

    for p in push_items:
        tag_text = p.get("tag", "").strip()
        user_text = p.get("user", "").strip()
        content_text = p.get("content", "").strip()
        time_text = p.get("time", "").strip()

        if "推" in tag_text:
            push_up_count += 1
        elif "噓" in tag_text:
            push_down_count += 1
        else:
            push_arrow_count += 1

        if hide_arrow_pushes and ("推" not in tag_text and "噓" not in tag_text):
            continue

        if max_pushes_display > 0 and len(push_items_html) >= max_pushes_display:
            continue

        tag_color = (
            "#10b981"
            if "推" in tag_text
            else "#ef4444"
            if "噓" in tag_text
            else "#6b7280"
        )
        clean_user = user_text.split()[0].strip() if user_text else ""
        if clean_user:
            user_markup = (
                f'<a href="https://www.pttweb.cc/user/{py_html.escape(clean_user)}" target="_blank" rel="noopener noreferrer" '
                f'style="font-weight:600; color:var(--text-secondary, #4b5563); width:110px; flex-shrink:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; text-decoration:none;" '
                f'title="在 PttWeb 查看 {py_html.escape(clean_user)} 的發文與推文" '
                f'onmouseover="this.style.textDecoration=\'underline\'" onmouseout="this.style.textDecoration=\'none\'">'
                f"{py_html.escape(user_text)}</a>"
            )
        else:
            user_markup = f'<span style="font-weight:600; color:var(--text-secondary, #4b5563); width:110px; flex-shrink:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{py_html.escape(user_text)}</span>'

        esc_content = py_html.escape(content_text)
        linked_content = LINK_URL_PATTERN.sub(
            r'<a href="\1" target="_blank" rel="noopener noreferrer" style="color:var(--accent-primary, #3b82f6); text-decoration:underline;">\1</a>',
            esc_content,
        )

        push_items_html.append(
            f'<div style="display:flex; align-items:baseline; gap:8px; padding:4px 0; border-bottom:1px solid var(--border-color, rgba(0,0,0,0.05)); font-size:13px;">'
            f'<span style="font-weight:bold; color:{tag_color}; width:24px; flex-shrink:0;">{py_html.escape(tag_text)}</span>'
            f"{user_markup}"
            f'<span style="flex:1; color:var(--text-primary, #111827); word-break:break-word;">{linked_content}</span>'
            f'<span style="font-size:11px; color:var(--text-muted, #9ca3af); flex-shrink:0;">{py_html.escape(time_text)}</span>'
            f"</div>"
        )

    if push_items_html:
        stats_badge = (
            f'<span style="font-size:12px; font-weight:normal; margin-left:8px; color:var(--text-muted);">'
            f'<span style="color:#10b981; font-weight:600;">{push_up_count} 推</span> / '
            f'<span style="color:#ef4444; font-weight:600;">{push_down_count} 噓</span> / '
            f'<span style="color:#6b7280; font-weight:600;">{push_arrow_count} →</span>'
            f"</span>"
        )

        if collapse_pushes:
            pushes_block = (
                f'<details style="margin-top:28px; padding:12px 16px; background:var(--card-bg, rgba(0,0,0,0.02)); border-radius:10px; border:1px solid var(--border-color, rgba(0,0,0,0.08));">'
                f'<summary style="font-size:14px; font-weight:600; cursor:pointer; color:var(--text-primary, #111827);">'
                f"💬 PTT 鄉民推文 ({len(push_items_html)}) {stats_badge}"
                f"</summary>"
                f'<div style="margin-top:12px;">{"".join(push_items_html)}</div>'
                f"</details>"
            )
        else:
            pushes_block = (
                f'<div class="ptt-pushes-card" style="margin-top:28px; padding:16px; background:var(--card-bg, rgba(0,0,0,0.02)); border-radius:10px; border:1px solid var(--border-color, rgba(0,0,0,0.08));">'
                f'<h4 style="margin:0 0 12px 0; font-size:14px; font-weight:600; color:var(--text-primary, #111827);">'
                f"💬 PTT 鄉民推文 ({len(push_items_html)}) {stats_badge}"
                f"</h4>"
                f'{"".join(push_items_html)}'
                f"</div>"
            )

    body_html = meta_block + "".join(body_html_parts) + pushes_block
    return HTMLSanitizer.clean(body_html)


def parse_ptt_html(
    html_str: str,
    config: Optional[dict[str, Any]] = None,
    url: str = "",
    title: str = "",
    author: str = "",
    snippet: str = "",
) -> Optional[str]:
    """解析 PTT HTML/Feed 內容並轉換為結構化閱讀排版 (Parse and Enhance PTT HTML & Feed Content).

    :param html_str: PTT 原始 HTML 或文字字串
    :param config: 外掛設定參數 (如 auto_embed_images, collapse_pushes 等)
    :param url: 原文網址
    :param title: 文章標題
    :param author: 文章作者
    :param snippet: 文章簡介備用文字
    :return: 清洗與美化後之 HTML 內文或 None
    """
    if not html_str:
        return None

    # 若已經美化過，不重複處理
    if "ptt-meta-card" in html_str and "ptt-pushes-card" in html_str:
        return html_str

    cfg = config or {}
    auto_embed_images = bool(cfg.get("auto_embed_images", True))
    auto_embed_videos = bool(cfg.get("auto_embed_videos", True))

    # 抽取看板名稱
    board = ""
    if url:
        m_board = re.search(r"ptt(?:\.cc|web\.cc)/bbs/([^/]+)", url, re.IGNORECASE)
        if m_board:
            board = m_board.group(1)

    # 判斷是否為 Web DOM 模式 (含有 id="main-content" 或 class="bbs-screen")
    is_web_dom = (
        'id="main-content"' in html_str
        or "main-content" in html_str
        or "bbs-screen" in html_str
    )

    if is_web_dom:
        try:
            doc = lxml.html.fromstring(html_str)
            main_content = doc.get_element_by_id("main-content", None)
            if main_content is None:
                matches = doc.xpath(
                    '//div[contains(@class, "bbs-screen") and contains(@class, "bbs-content")]'
                )
                if matches:
                    main_content = matches[0]

            if main_content is not None:
                def _strip_element_preserve_tail(elem: Any) -> None:
                    p_node = elem.getparent()
                    if p_node is None:
                        return
                    if elem.tail:
                        prev = elem.getprevious()
                        if prev is not None:
                            prev.tail = (prev.tail or "") + elem.tail
                        else:
                            p_node.text = (p_node.text or "") + elem.tail
                    p_node.remove(elem)

                # 移除導航欄位、官方重複預覽圖 (richcontent) 或無效控制條
                for nav_elem in main_content.xpath(
                    './/*[contains(@class, "bbs-header") or contains(@class, "bbs-custom") or contains(@class, "richcontent")]'
                ):
                    _strip_element_preserve_tail(nav_elem)


                # 抽取推文 (支援 div, p 或任意 class 包含 push 之節點)
                pushes = main_content.xpath('.//*[contains(@class, "push")]')
                push_items: list[dict[str, str]] = []
                for p in pushes:
                    tag_nodes = p.xpath('.//span[contains(@class, "push-tag")]/text()')
                    user_nodes = p.xpath(
                        './/span[contains(@class, "push-userid")]/text()'
                    )
                    content_nodes = p.xpath(
                        './/span[contains(@class, "push-content")]/text()'
                    )
                    time_nodes = p.xpath(
                        './/span[contains(@class, "push-ipdatetime")]/text()'
                    )

                    tag_text = tag_nodes[0].strip() if tag_nodes else ""
                    user_text = user_nodes[0].strip() if user_nodes else ""
                    content_text = (
                        content_nodes[0].strip().lstrip(": ") if content_nodes else ""
                    )
                    time_text = time_nodes[0].strip() if time_nodes else ""

                    # 若無 span 標籤，嘗試純文字正則解析
                    if not tag_text and not user_text:
                        p_text = p.text_content().strip()
                        m_push = PUSH_PATTERN.match(p_text)
                        if m_push:
                            ptag, puid, pcontent, pip, pdt = m_push.groups()
                            tag_text = ptag or ""
                            user_text = puid or ""
                            content_text = pcontent or ""
                            time_text = f"{pip or ''} {pdt or ''}".strip()

                    if tag_text or user_text:
                        push_items.append(
                            {
                                "tag": tag_text,
                                "user": user_text,
                                "content": content_text,
                                "time": time_text,
                            }
                        )
                    _strip_element_preserve_tail(p)

                # 抽取 metadata (支援 div, p 或任意 class 包含 article-metaline 之節點)
                meta_items: list[tuple[str, str]] = []
                for meta in main_content.xpath(
                    './/*[contains(@class, "article-metaline") or contains(@class, "article-metaline-right")]'
                ):
                    tag_nodes = meta.xpath(
                        './/span[contains(@class, "article-meta-tag")]/text()'
                    )
                    val_nodes = meta.xpath(
                        './/span[contains(@class, "article-meta-value")]/text()'
                    )
                    if tag_nodes and val_nodes:
                        meta_items.append((tag_nodes[0].strip(), val_nodes[0].strip()))
                    else:
                        m_text = meta.text_content().strip()
                        for prefix in ("作者", "看板", "標題", "時間"):
                            if m_text.startswith(prefix):
                                meta_items.append((prefix, m_text[len(prefix):].strip()))
                                break
                    _strip_element_preserve_tail(meta)

                # 若 DOM 中未能解析出作者/看板/標題，使用 fallback 補充元數據
                has_keys = {k for k, _ in meta_items}
                if "作者" not in has_keys and author:
                    meta_items.insert(0, ("作者", author))
                if "看板" not in has_keys and board:
                    meta_items.append(("看板", board))
                if "標題" not in has_keys and title:
                    meta_items.append(("標題", title))

                raw_text = main_content.text_content()
                formatted_paragraphs = _format_text_lines(
                    raw_text.splitlines(),
                    auto_embed_images=auto_embed_images,
                    auto_embed_videos=auto_embed_videos,
                    url=url,
                    board=board,
                )
                return render_ptt_components(
                    meta_items, formatted_paragraphs, push_items, config=cfg
                )
        except Exception as exc:
            logger.debug(f"PttEnhancer DOM parsing fallback to text mode: {exc}")

    # 軌道 B：Feed / Text / Paragraph 模式
    try:
        try:
            doc = lxml.html.fromstring(f"<div>{html_str}</div>")
        except Exception:
            doc = lxml.html.fromstring("<div></div>")

        pres = doc.xpath(".//pre")
        ps = doc.xpath(".//p")

        lines: list[str] = []
        if pres:
            for pre in pres:
                lines.extend(pre.text_content().splitlines())
        elif ps:
            for p in ps:
                p_text = p.text_content().strip()
                if p_text:
                    lines.extend(p_text.splitlines())
        else:
            lines = doc.text_content().splitlines()

        # 展開並過濾行
        cleaned_input_lines = _clean_and_split_raw_lines(lines)

        meta_items = []
        if author:
            meta_items.append(("作者", author))
        if board:
            meta_items.append(("看板", board))
        if title:
            meta_items.append(("標題", title))

        push_items = []
        body_lines: list[str] = []

        inline_header_pattern = re.compile(
            r'^\s*作者\s+([^\s]+(?:\s*\([^\)]*\))?)\s+看板\s+([a-zA-Z0-9_\-]+)\s+標題\s+(.*?)\s+時間\s+([a-zA-Z0-9 :]+(?:20\d{2})?)\s*',
            re.IGNORECASE,
        )

        for line in cleaned_input_lines:
            if not line:
                body_lines.append("")
                continue

            # 略過重複的文章連結
            if url and (
                line == url
                or line == f"https://www.ptt.cc/bbs/{board}/"
                or (
                    line.startswith("https://www.ptt.cc/bbs/")
                    and line.endswith(".html")
                )
            ):
                continue

            # 單行或多行內嵌 BBS 標頭辨識
            m_inline = inline_header_pattern.match(line)
            if m_inline:
                b_auth, b_board, b_title, b_dt = m_inline.groups()
                meta_items = [
                    ("作者", b_auth.strip()),
                    ("看板", b_board.strip()),
                    ("標題", b_title.strip()),
                    ("時間", b_dt.strip()),
                ]
                rest_text = line[m_inline.end():].strip()
                if rest_text:
                    body_lines.append(rest_text)
                continue

            # 推文辨識
            m_push = PUSH_PATTERN.match(line)
            if m_push:
                tag, uid, content, ip, dt = m_push.groups()
                ip_time = f"{ip or ''} {dt or ''}".strip()
                push_items.append(
                    {
                        "tag": tag,
                        "user": uid,
                        "content": content,
                        "time": ip_time,
                    }
                )
                continue

            # 標準多行 BBS 標頭辨識
            m_bbs = BBS_HEADER_PATTERN.match(line)
            if m_bbs:
                b_auth, b_board = m_bbs.groups()
                meta_items = [("作者", b_auth), ("看板", b_board)]
                if title:
                    meta_items.append(("標題", title))
                continue

            # 獨立標題與時間行辨識 (若在頂部前幾行)
            if len(body_lines) < 4:
                if line.startswith("標題 ") or line.startswith("標題:"):
                    continue
                if line.startswith("時間 ") or line.startswith("時間:"):
                    continue

            body_lines.append(line)

        # 若 body_lines 為空但有備用 snippet，填入備用內文以防空洞
        if not any(b.strip() for b in body_lines) and snippet and snippet.strip():
            body_lines = [snippet.strip()]

        formatted_paragraphs = _format_text_lines(
            body_lines,
            auto_embed_images=auto_embed_images,
            auto_embed_videos=auto_embed_videos,
            url=url,
            board=board,
        )
        return render_ptt_components(
            meta_items, formatted_paragraphs, push_items, config=cfg
        )
    except Exception as exc:
        logger.warning(f"PttEnhancer parsing error: {exc}")
        return None


class PttEnhancerProcessorPlugin(BaseProcessorPlugin):
    """PTT BBS 閱讀體驗增強外掛 (PTT BBS Reading Enhancer Processor Plugin)."""

    async def process(
        self, article: ArticleDTO, context: Optional["PluginContext"] = None
    ) -> Optional[ArticleDTO]:
        """為 PTT 文章提供結構化 BBS 標頭、排版整理、圖片自動預覽與推文美化.

        若 RSS 內容不含 Web DOM 結構（無推文），外掛會自動抓取 ptt.cc 完整頁面以取得推文，
        無需使用者手動開啟 auto_full_text。

        :param article: 待處理文章資料
        :param context: 微核心注入之安全上下文
        :return: 增強後之文章物件
        """
        article_url = getattr(article, "url", "") or ""
        url_lower = article_url.lower()
        content = (
            getattr(article, "content_html", "")
            or getattr(article, "content_text", "")
            or ""
        )

        # 判定是否為 PTT 相關內容 (嚴格網址與內容特徵雙重辨識)
        is_ptt = (
            "ptt.cc" in url_lower
            or "pttweb.cc" in url_lower
            or "※ 發信站: 批踢踢實業坊" in content
            or 'class="article-metaline"' in content
            or 'id="main-content"' in content
        )

        if not is_ptt:
            return article

        merged_cfg = dict(self.config)
        if context and context.config:
            merged_cfg.update(context.config)

        # 若已完整增強（有 meta + pushes），直接回傳
        if "ptt-meta-card" in content and "ptt-pushes-card" in content:
            return article

        # 偵測是否為 RSS 簡短格式 (無 Web DOM，無推文)
        # PTT Atom RSS 的 <content> 只有 <pre> 本文，不含推文
        # 專屬外掛自動觸發全文抓取，取得 ptt.cc 完整頁面以解析推文
        has_pushes_in_content = bool(PUSH_PATTERN.search(content))
        is_rss_short = (
            'id="main-content"' not in content
            and "bbs-screen" not in content
            and "ptt-pushes-card" not in content
            and not has_pushes_in_content
            and article_url.startswith("https://www.ptt.cc/bbs/")
        )

        working_content = content
        if is_rss_short and context is not None:
            logger.debug(f"PttEnhancer: RSS content detected for {article_url}, fetching full page...")
            full_html = await _fetch_full_page(article_url, context)
            if full_html and ('id="main-content"' in full_html or "bbs-screen" in full_html):
                working_content = full_html
                logger.debug(f"PttEnhancer: Full page fetched successfully ({len(full_html)} bytes)")
            else:
                logger.debug("PttEnhancer: Full page fetch failed or empty, using RSS content")

        # 結構化解析與增強 PTT 內容 (傳入 url, title, author, snippet 輔助元數據抽取)
        enhanced_html = parse_ptt_html(
            working_content,
            config=merged_cfg,
            url=article_url,
            title=getattr(article, "title", "") or "",
            author=getattr(article, "author", "") or "",
            snippet=getattr(article, "snippet", "") or "",
        )
        if enhanced_html and len(enhanced_html.strip()) > 30:
            article.content_html = enhanced_html
            article.content_text = HTMLSanitizer.extract_text(enhanced_html)
            article.snippet = HTMLSanitizer.extract_snippet(
                enhanced_html, max_chars=200
            )
            logger.debug(
                f"PttEnhancer successfully enhanced article: {article.title}"
            )

        return article

