"""外掛資料傳輸模型 (Plugin Data Transfer Objects).

This module defines standard Pydantic models for articles, feeds, and plugin manifests
exchanged across the OmniRSS microkernel and plugin boundaries.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class PluginType(str, Enum):
    """外掛插槽類型列舉 (Plugin Slot Types).

    Enumeration of supported plugin slot categories in the OmniRSS ecosystem.
    """

    SOURCE = "source"
    PROCESSOR = "processor"
    LAYOUT = "layout"
    ACTION = "action"


class ArticleDTO(BaseModel):
    """文章標準資料傳輸模型 (Standard Article Data Transfer Object).

    Represents an article entity passed through source, processor, and storage pipelines.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    guid: str = Field(
        default="", description="文章原始唯一識別碼 (Original unique GUID)"
    )
    url: str = Field(description="文章原文連結 (Original article URL)")
    title: str = Field(description="文章標題 (Article title)")
    author: Optional[str] = Field(default=None, description="作者名稱 (Author name)")
    published_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="文章發布時間 (Publication timestamp in UTC)",
    )

    # 內文資料 (Content fields)
    content_html: str = Field(default="", description="原始或清洗後的 HTML 正文 (HTML body)")
    content_text: str = Field(default="", description="純文字正文 (Plain text body)")
    snippet: str = Field(default="", description="前 200 字純文字預覽 (Short snippet)")
    cover_image_url: Optional[str] = Field(
        default=None, description="封面圖片網址 (Cover image URL)"
    )

    # 智慧增強中繼資料 (Enriched metadata)
    simhash: Optional[str] = Field(
        default=None, description="64-bit 語意雜湊指紋 (SimHash fingerprint)"
    )
    duplicate_of_guid: Optional[str] = Field(
        default=None, description="轉貼時指向原始母文章之 GUID (Parent GUID if duplicate)"
    )
    ai_summary: Optional[str] = Field(
        default=None, description="AI 產出之條列摘要 (AI-generated summary)"
    )
    extra_tags: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("extra_tags", "custom_tags"),
        description="附加標籤清單 (Additional tag names)",
    )

    # 狀態標記 (State flags)
    is_starred: bool = Field(default=False, description="是否加星收藏 (Starred flag)")
    is_read: bool = Field(default=False, description="是否已讀 (Read flag)")

    @property
    def custom_tags(self) -> list[str]:
        """相容標籤清單屬性 (Compatible custom tags property)."""
        return self.extra_tags

    @custom_tags.setter
    def custom_tags(self, value: list[str]) -> None:
        """設定相容標籤清單 (Set compatible custom tags)."""
        self.extra_tags = value


class FeedDTO(BaseModel):
    """訂閱來源資料傳輸模型 (Feed Data Transfer Object).

    Represents an RSS feed or custom subscription source.
    """

    model_config = ConfigDict(extra="ignore")

    title: str = Field(description="來源預設標題 (Feed title)")
    feed_url: str = Field(description="訂閱目標網址 (Feed URL)")
    site_url: Optional[str] = Field(default=None, description="網站首頁網址 (Site home URL)")
    icon_url: Optional[str] = Field(default=None, description="網站圖示網址 (Favicon URL)")
    description: Optional[str] = Field(default=None, description="頻道說明 (Description)")
    category_name: Optional[str] = Field(
        default=None, description="預設分類名稱 (Category name)"
    )


class MediaManifestDTO(BaseModel):
    """多媒體清單資料傳輸模型 (Media Manifest Data Transfer Object).

    Collects extracted image, video, and audio URLs from an article.
    """

    model_config = ConfigDict(extra="ignore")

    images: list[str] = Field(
        default_factory=list, description="圖片網址清單 (Image URLs)"
    )
    videos: list[str] = Field(
        default_factory=list, description="影片網址清單 (Video URLs)"
    )
    audios: list[str] = Field(
        default_factory=list, description="音訊網址清單 (Audio URLs)"
    )


class PluginManifest(BaseModel):
    """外掛宣告式資訊清單模型 (Plugin Manifest Specification).

    Defines metadata, permissions, configuration schema, and defaults for a plugin.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="外掛唯一 ID，建議格式為 author/plugin_id (Unique plugin ID)")
    name: str = Field(description="外掛人類可讀名稱 (Human-readable name)")
    version: str = Field(default="1.0.0", description="語意化版本號 (Semantic version)")
    slot_type: PluginType = Field(description="外掛插槽分類 (Plugin slot category)")
    author: str = Field(default="Community", description="外掛作者 (Plugin author)")
    description: str = Field(default="", description="外掛功能簡述 (Description)")
    entry_point: str = Field(
        default="plugin:Plugin",
        description="模組載入進入點，格式為 module:ClassName (Entry point)",
    )
    minimum_omnirss_version: str = Field(
        default="1.0.0", description="相容之最低 OmniRSS 版本 (Min required version)"
    )
    dependencies: list[str] = Field(
        default_factory=list, description="Python 套件依賴清單 (Dependencies)"
    )
    permissions: list[str] = Field(
        default_factory=list, description="外掛宣告之權限清單 (Required permissions)"
    )
    default_config: dict[str, Any] = Field(
        default_factory=dict, description="預設設定字典 (Default configuration)"
    )
    config_schema: dict[str, Any] = Field(
        default_factory=dict, description="設定 JSON Schema 結構 (Config schema)"
    )
    timeout_seconds: int = Field(
        default=15, description="單次執行逾時秒數 (Declared execution timeout)"
    )
