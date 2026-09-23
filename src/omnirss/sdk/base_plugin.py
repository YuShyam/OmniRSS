"""外掛基礎抽象介面 (Plugin Abstract Base Classes).

This module provides abstract base classes for the 4 official OmniRSS plugin slots:
Source, Processor, Layout, and Action plugins.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional, TYPE_CHECKING
from omnirss.sdk.models import ArticleDTO, PluginManifest

if TYPE_CHECKING:
    from omnirss.sdk.context import PluginContext


class BasePlugin(ABC):
    """通用外掛抽象基底類別 (Generic Plugin Base Class).

    Provides shared initialization, manifest references, and configuration storage.
    """

    def __init__(
        self,
        plugin_id: str,
        manifest: PluginManifest,
        config: Optional[dict[str, Any]] = None,
    ) -> None:
        """初始化外掛 (Initialize plugin instance).

        :param plugin_id: 外掛唯一識別碼 (Unique plugin ID)
        :param manifest: 外掛宣告之資訊清單 (Loaded plugin manifest)
        :param config: 生效之設定字典 (Merged effective configuration)
        """
        self.plugin_id = plugin_id
        self.manifest = manifest
        self.config = config or {}

    def update_config(self, new_config: dict[str, Any]) -> None:
        """更新外掛執行時設定 (Update active runtime configuration).

        :param new_config: 新的設定字典 (New merged config dictionary)
        """
        self.config = new_config


class BaseSourcePlugin(BasePlugin):
    """來源插槽基礎抽象介面 (Source Plugin Base Interface).

    Responsible for scraping custom websites, APIs, or specialized feeds and returning ArticleDTO lists.
    """

    @abstractmethod
    async def fetch(
        self, feed_url: str, context: "PluginContext"
    ) -> list[ArticleDTO]:
        """執行來源資料擷取 (Fetch and parse articles from external source).

        :param feed_url: 訂閱來源網址或目標 URI (Target feed URL or custom URI)
        :param context: 微核心注入之安全上下文 (Injected secure plugin context)
        :return: 解析完成之 ArticleDTO 清單 (List of parsed ArticleDTO objects)
        """
        raise NotImplementedError


class BaseProcessorPlugin(BasePlugin):
    """處理插槽基礎抽象介面 (Processor Plugin Base Interface).

    Responsible for pipelining, transforming, summarizing, deduplicating, or filtering articles.
    """

    @abstractmethod
    async def process(
        self, article: ArticleDTO, context: "PluginContext"
    ) -> Optional[ArticleDTO]:
        """執行單篇文章加工處理 (Process, enrich, or filter a single article).

        :param article: 當前待處理之文章資料 (Article to process)
        :param context: 微核心注入之安全上下文 (Injected secure plugin context)
        :return: 豐富化後之 ArticleDTO；若回傳 None 則代表拋棄該文章 (Enriched ArticleDTO or None to drop)
        """
        raise NotImplementedError


class BaseActionPlugin(BasePlugin):
    """動作插槽基礎抽象介面 (Action Plugin Base Interface).

    Responds to user interaction events (starring, tagging, export triggers).
    """

    @abstractmethod
    async def on_article_starred(
        self, article: ArticleDTO, context: "PluginContext"
    ) -> bool:
        """文章被加星收藏時觸發 (Triggered when an article is starred).

        :param article: 收藏之文章資料 (Starred article DTO)
        :param context: 微核心注入之安全上下文 (Injected secure plugin context)
        :return: 動作執行成功與否 (True if action succeeded)
        """
        raise NotImplementedError

    @abstractmethod
    async def on_article_tagged(
        self, article: ArticleDTO, tag_name: str, context: "PluginContext"
    ) -> bool:
        """文章被貼上標籤時觸發 (Triggered when an article is tagged).

        :param article: 標記之文章資料 (Tagged article DTO)
        :param tag_name: 貼上之標籤名稱 (Attached tag name)
        :param context: 微核心注入之安全上下文 (Injected secure plugin context)
        :return: 動作執行成功與否 (True if action succeeded)
        """
        raise NotImplementedError
