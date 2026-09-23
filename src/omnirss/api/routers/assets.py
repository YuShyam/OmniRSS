"""圖片金庫與靜態資源路由控制器 (Assets & Image Vault Router).

This module serves deduplicated WebP images from the content-addressable image vault
with HTTP 1-year immutable caching headers.
"""

from fastapi import APIRouter, HTTPException, Response
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
