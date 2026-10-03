from typing import Optional
from urllib.parse import urlparse
import socket
import ipaddress
import aiohttp
from fastapi import APIRouter, HTTPException, Response, Query
from loguru import logger
from omnirss.core.image_vault import get_image_vault

router = APIRouter(prefix="/api/assets", tags=["Assets & Image Vault"])


@router.get("/images/{sha256_hash}")
async def get_cached_image(sha256_hash: str) -> Response:
    """取得去重 WebP 圖片檔案 (Get Cached Deduplicated WebP Image)."""
    vault = get_image_vault()
    data = vault.read_image(sha256_hash)
    if not data:
        raise HTTPException(status_code=404, detail="Image not found in vault")

    return Response(
        content=data,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


@router.get("/proxy")
async def proxy_external_image(url: str = Query(..., description="Target image URL to proxy")) -> Response:
    """代理抓取外部圖片並快取 (Proxy and cache external images to bypass ISP DNS block & hotlink protection).

    :param url: 目標外部圖片 URL (Target Image URL)
    :return: 圖片原始位元組串流與快取標頭
    """
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Invalid image URL schema")

    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="Invalid hostname")

    # Anti-SSRF 私有與本地 IP 阻擋防禦 (Anti-SSRF Protection)
    try:
        ip_list = socket.gethostbyname_ex(hostname)[2]
        for ip_str in ip_list:
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_reserved
                or ip_obj.is_multicast
            ):
                raise HTTPException(status_code=403, detail="Access to internal/private IP address is forbidden")
    except HTTPException:
        raise
    except Exception as exc:
        # 若本地 DNS 解析異常 (例如被 ISP 阻擋)，但此服務在海外 OCI 運作時可連線，記錄除錯日誌後繼續由 aiohttp 嘗試
        logger.debug(f"Image proxy hostname pre-check notice for '{hostname}': {exc}")

    fetch_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": f"{parsed.scheme}://{parsed.netloc}/",
    }

    try:
        async with aiohttp.ClientSession(headers=fetch_headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15), allow_redirects=True) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=resp.status, detail=f"Remote server returned HTTP {resp.status}")
                content_type = resp.headers.get("content-type", "image/jpeg")
                data = await resp.read()
                return Response(
                    content=data,
                    media_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=604800, immutable",
                        "Access-Control-Allow-Origin": "*",
                    },
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(f"Image proxy failed for URL '{url}': {exc}")
        raise HTTPException(status_code=502, detail=f"Failed to proxy external image: {str(exc)}")

