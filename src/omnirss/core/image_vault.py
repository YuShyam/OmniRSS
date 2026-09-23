"""圖片雜湊去重與冷存庫 (SHA-256 Content-Addressable Image Vault).

This module manages image content-addressable storage with SHA-256 deduplication,
WebP compression, and two-level directory sharding.
"""

import hashlib
import io
from pathlib import Path
from typing import Optional, Union
from PIL import Image
from loguru import logger


class ImageVault:
    """圖片冷存庫管理器 (Content-Addressable Image Vault Manager)."""

    def __init__(self, base_dir: Optional[Union[str, Path]] = None) -> None:
        if base_dir is None:
            self.base_dir = (
                Path(__file__).resolve().parents[3] / "data" / "images"
            )
        else:
            self.base_dir = Path(base_dir)

    def _get_sharded_path(self, sha256_hash: str) -> Path:
        """根據 SHA-256 雜湊計算二階分片檔案路徑 (Compute two-level sharded filepath).

        Path: base_dir / ab / cd / abcdef...webp

        :param sha256_hash: 64 位元 SHA-256 雜湊字串
        :return: 分片後的完整 Path 物件
        """
        lvl1 = sha256_hash[:2]
        lvl2 = sha256_hash[2:4]
        return self.base_dir / lvl1 / lvl2 / f"{sha256_hash}.webp"

    def store_image(
        self, image_bytes: bytes, quality: int = 80
    ) -> tuple[str, Path, int, int]:
        """儲存並轉碼為 WebP 去重圖檔 (Store, deduplicate, and transcode image to WebP).

        :param image_bytes: 原始圖片二進位數據 (Raw image bytes)
        :param quality: WebP 壓縮品質 (Compression quality, 1-100)
        :return: (sha256_hash, target_path, width, height)
        """
        sha256_hash = hashlib.sha256(image_bytes).hexdigest()
        target_path = self._get_sharded_path(sha256_hash)

        # 若檔案已存在，代表命中去重快取，直接讀取尺寸返回
        if target_path.is_file():
            try:
                with Image.open(target_path) as img:
                    return sha256_hash, target_path, img.width, img.height
            except Exception:
                pass

        target_path.parent.mkdir(parents=True, exist_ok=True)

        # 透過 Pillow 轉碼為 WebP
        with Image.open(io.BytesIO(image_bytes)) as img:
            # 轉換 RGBA/P 等色彩空間為相容格式
            if img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            ):
                converted = img.convert("RGBA")
            else:
                converted = img.convert("RGB")

            width, height = converted.size
            converted.save(str(target_path), format="WEBP", quality=quality)
            logger.debug(
                f"Stored deduplicated WebP image: {sha256_hash[:8]} ({width}x{height})"
            )

        return sha256_hash, target_path, width, height

    def get_image_file(self, sha256_hash: str) -> Optional[Path]:
        """依雜湊取得圖檔實體路徑 (Get image filepath by SHA-256 hash).

        :param sha256_hash: 圖片雜湊
        :return: 圖檔路徑；若不存在回傳 None
        """
        target = self._get_sharded_path(sha256_hash)
        return target if target.is_file() else None


_IMAGE_VAULT: Optional[ImageVault] = None


def get_image_vault(
    base_dir: Optional[Union[str, Path]] = None
) -> ImageVault:
    """取得全域圖片庫單例 (Get singleton image vault).

    :param base_dir: 自訂儲存目錄
    :return: ImageVault 實例
    """
    global _IMAGE_VAULT
    if _IMAGE_VAULT is None or base_dir is not None:
        _IMAGE_VAULT = ImageVault(base_dir)
    return _IMAGE_VAULT
