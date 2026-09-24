"""SimHash 智慧語意跨站轉貼去重與聚合外掛 (SimHash Deduplication Processor Plugin).

This plugin calculates 64-bit SimHash fingerprints for articles to detect cross-site duplicates,
content-farm rewrites, and syndicate reporting, applying configurable tags or actions.
"""

import hashlib
import re
from typing import Optional, TYPE_CHECKING
from loguru import logger
from omnirss.sdk.base_plugin import BaseProcessorPlugin
from omnirss.sdk.models import ArticleDTO

if TYPE_CHECKING:
    from omnirss.sdk.context import PluginContext


class SimHashProcessorPlugin(BaseProcessorPlugin):
    """SimHash 64-bit 轉貼去重與聚合處理器 (SimHash Deduplication Processor Plugin)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._recent_hashes: list[int] = []
        self._max_history: int = 500

    async def initialize(self) -> None:
        """初始化外掛資源 (Initialize plugin resources)."""
        logger.info(f"SimHashProcessorPlugin initialized with config: {self.config}")

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """繁體中文與英數分詞 (Tokenize text into tokens / bi-grams)."""
        text = re.sub(r"[^\w\s]", "", text)
        tokens: list[str] = []
        # 嘗試使用 jieba 分詞
        try:
            import jieba
            tokens = list(jieba.cut(text))
        except ImportError:
            # 內建 2-gram / word 分詞備援
            words = text.split()
            for w in words:
                if len(w) <= 2:
                    tokens.append(w)
                else:
                    for i in range(len(w) - 1):
                        tokens.append(w[i : i + 2])
        return [t.strip() for t in tokens if len(t.strip()) > 0]

    @classmethod
    def compute_simhash(cls, text: str) -> int:
        """計算 64 位元 SimHash 特徵雜湊 (Compute 64-bit SimHash).

        :param text: 待分析文字
        :return: 64-bit 整數指紋
        """
        tokens = cls._tokenize(text)
        if not tokens:
            return 0

        v = [0] * 64
        for token in tokens:
            # 64-bit MD5 prefix hash
            token_hash = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:16], 16)
            for i in range(64):
                bit = (token_hash >> i) & 1
                if bit == 1:
                    v[i] += 1
                else:
                    v[i] -= 1

        fingerprint = 0
        for i in range(64):
            if v[i] > 0:
                fingerprint |= 1 << i

        return fingerprint

    @staticmethod
    def hamming_distance(hash1: int, hash2: int) -> int:
        """計算兩 64-bit 整數之漢明距離 (Calculate Hamming Distance)."""
        x = (hash1 ^ hash2) & 0xFFFFFFFFFFFFFFFF
        return bin(x).count("1")

    async def process(
        self, article: ArticleDTO, context: Optional["PluginContext"] = None
    ) -> Optional[ArticleDTO]:
        """檢測文章是否為轉貼或重複報導 (Detect syndicated or duplicate articles).

        :param article: 待處理文章資料物件
        :param context: 外掛安全上下文
        :return: 標記後之文章資料物件
        """
        text = f"{article.title} {article.content_text or ''}"
        if len(text.strip()) < 30:
            return article

        current_hash = self.compute_simhash(text)
        threshold = int(self.config.get("hamming_distance_threshold") or 3)
        action_mode = self.config.get("action_mode") or "cluster"
        tag_name = self.config.get("auto_tag_name") or "轉貼報導"

        is_duplicate = False
        for prev_hash in self._recent_hashes:
            dist = self.hamming_distance(current_hash, prev_hash)
            if dist <= threshold:
                is_duplicate = True
                break

        if is_duplicate:
            if tag_name not in article.custom_tags:
                article.custom_tags.append(tag_name)

            if action_mode == "mark_read":
                article.is_read = True

            logger.info(f"SimHash detected syndicated article: '{article.title}' (Mode: {action_mode})")
        else:
            self._recent_hashes.append(current_hash)
            if len(self._recent_hashes) > self._max_history:
                self._recent_hashes.pop(0)

        return article
