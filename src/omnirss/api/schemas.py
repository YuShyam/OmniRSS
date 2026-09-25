"""API 資料傳輸模型定義 (API Schemas & Pydantic v2 DTOs).

This module defines standard Pydantic v2 request/response models for all RESTful API endpoints,
strictly aligning with the API Contract in docs/API_CONTRACT.md.
"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# 1. 身分認證與用戶相關模型 (Authentication & User Models)
# =============================================================================

class UserSetupRequest(BaseModel):
    """首次啟動建立管理員請求 (First-time Admin Setup Request)."""

    username: str = Field(min_length=3, max_length=50, description="管理員帳號名稱")
    password: str = Field(min_length=6, description="登入密碼")


class LoginRequest(BaseModel):
    """使用者登入請求 (User Login Request)."""

    username: str = Field(description="使用者帳號名稱")
    password: str = Field(description="使用者登入密碼")


class TokenResponse(BaseModel):
    """登入成功 Token 回應 (Token Response)."""

    access_token: str = Field(description="JWT Access Token")
    token_type: str = Field(default="bearer", description="Token 類型")
    expires_in: int = Field(description="有效秒數")


class UserDTO(BaseModel):
    """用戶個人資料模型 (User DTO)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_admin: bool
    api_key: str
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class UserSettingsDTO(BaseModel):
    """用戶偏好設定模型 (User Settings DTO)."""

    settings: dict[str, Any] = Field(default_factory=dict, description="用戶偏好與介面狀態設定")


class UserSettingsUpdateRequest(BaseModel):
    """更新用戶偏好設定請求 (Update User Settings Request)."""

    settings: dict[str, Any] = Field(description="用戶偏好設定字典")



# =============================================================================
# 2. 分類與訂閱源相關模型 (Categories & Feeds Models)
# =============================================================================

class CategoryDTO(BaseModel):
    """分類目錄資料模型 (Category DTO)."""

    id: int
    name: str
    sort_order: int = 0
    unread_count: int = 0
    custom_retention_days: Optional[int] = None
    custom_interval_minutes: Optional[int] = None
    custom_min_date: Optional[str] = None
    force_min_date: bool = False
    is_paused: bool = False
    filter_rules: Optional[str] = None
    view_preferences: Optional[dict[str, Any]] = None


class CategoryStatsDTO(BaseModel):
    """分類即時健康度與統計模型 (Category Real-time Stats DTO)."""

    category_id: int
    name: str
    feed_count: int = 0
    article_count: int = 0
    unread_count: int = 0
    custom_interval_minutes: Optional[int] = None
    last_updated_at: Optional[str] = None
    is_paused: bool = False


class CategoryCreateRequest(BaseModel):
    """建立分類目錄請求 (Create Category Request)."""

    name: str = Field(min_length=1, max_length=100, description="分類名稱")
    sort_order: int = Field(default=0, description="排序權重")
    custom_retention_days: Optional[int] = Field(default=None, ge=0, description="自訂保留天數")
    custom_interval_minutes: Optional[int] = Field(default=None, ge=5, le=10080, description="分類專屬更新頻率 (分鐘)")
    custom_min_date: Optional[str] = Field(default=None, description="文章收錄起始時間 (YYYY-MM-DD 或 ISO 格式)")
    force_min_date: bool = Field(default=False, description="是否強制向下套用至該分類下所有來源")


class CategoryUpdateRequest(BaseModel):
    """更新分類目錄請求 (Update Category Request)."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    sort_order: Optional[int] = None
    custom_retention_days: Optional[int] = None
    custom_interval_minutes: Optional[int] = None
    custom_min_date: Optional[str] = None
    force_min_date: Optional[bool] = None
    is_paused: Optional[bool] = None
    filter_rules: Optional[str] = None
    view_preferences: Optional[dict[str, Any]] = None


class RefreshProgressDTO(BaseModel):
    """即時全量更新進度模型 (Real-time Refresh Progress DTO)."""

    is_running: bool = False
    total_feeds: int = 0
    completed_feeds: int = 0
    current_feed_name: Optional[str] = None
    new_articles_count: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None



class FeedTestRequest(BaseModel):
    """測試訂閱網址請求 (Test Feed URL Request)."""

    feed_url: str = Field(description="欲測試的 RSS/Atom 網址")
    requires_flaresolverr: bool = Field(default=False, description="是否透過 FlareSolverr 測試")
    auth_username: Optional[str] = Field(default=None, description="HTTP 認證帳號")
    auth_password: Optional[str] = Field(default=None, description="HTTP 認證密碼")


class FeedTestResponse(BaseModel):
    """測試訂閱網址回應 (Test Feed URL Response)."""

    status: str = Field(description="測試結果狀態 ('ok' | 'error')")
    http_status: Optional[int] = Field(default=None, description="HTTP 狀態碼")
    title: Optional[str] = Field(default=None, description="解析所得頻道名稱")
    site_url: Optional[str] = Field(default=None, description="解析所得官方首頁")
    item_count: int = Field(default=0, description="目前 Feed 內包含的文章數量")
    error_detail: Optional[str] = Field(default=None, description="錯誤詳細訊息")


class FeedCreateRequest(BaseModel):
    """新增訂閱頻道請求 (Subscribe Feed Request)."""

    feed_url: str = Field(description="訂閱源網址 (RSS/Atom URL)")
    title: Optional[str] = Field(default=None, description="自訂頻道別名")
    custom_title: Optional[str] = Field(default=None, description="自訂頻道別名 (前端別名)")
    category_id: Optional[int] = Field(default=None, description="所屬分類 ID")
    check_interval_minutes: int = Field(default=30, ge=5, le=1440, description="抓取間隔分鐘數")
    custom_retention_days: Optional[int] = Field(default=None, ge=0, description="自訂保留天數")
    min_publish_date: Optional[str] = Field(default=None, description="文章收錄起始時間 (YYYY-MM-DD 或 ISO 格式)")
    force_min_date: bool = Field(default=False, description="是否強制依此來源（特許穿透全域與分類限制）")
    requires_flaresolverr: bool = Field(default=False, description="是否強制調度 FlareSolverr 繞過 Cloudflare")
    auto_full_text: bool = Field(default=False, description="是否自動抓取全文與展開推文/圖片")
    auth_username: Optional[str] = Field(default=None, description="HTTP 認證帳號")
    auth_password: Optional[str] = Field(default=None, description="HTTP 認證密碼")


class FeedUpdateRequest(BaseModel):
    """更新訂閱頻道請求 (Update Feed Request)."""

    custom_title: Optional[str] = None
    category_id: Optional[int] = None
    feed_url: Optional[str] = None
    site_url: Optional[str] = None
    check_interval_minutes: Optional[int] = Field(default=None, ge=5, le=1440)
    custom_retention_days: Optional[int] = None
    min_publish_date: Optional[str] = None
    force_min_date: Optional[bool] = None
    is_paused: Optional[bool] = None
    requires_flaresolverr: Optional[bool] = None
    auto_full_text: Optional[bool] = None
    auth_username: Optional[str] = None
    auth_password: Optional[str] = None




class FeedTreeItemDTO(BaseModel):
    """訂閱目錄樹中的單一頻道 (Feed Item in Tree)."""

    id: int
    title: str
    feed_url: str
    site_url: Optional[str] = None
    icon_hash: Optional[str] = None
    unread_count: int = 0
    error_count: int = 0
    last_error_message: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    is_paused: bool = False
    auto_full_text: bool = False
    min_publish_date: Optional[str] = None
    force_min_date: bool = False


class FeedTreeCategoryDTO(BaseModel):
    """訂閱目錄樹中的分類節點 (Category Node in Tree)."""

    id: Optional[int] = None  # None 代表未分類 (Uncategorized)
    name: str
    sort_order: int = 0
    unread_count: int = 0
    feeds: list[FeedTreeItemDTO] = Field(default_factory=list)


class FeedTreeResponseDTO(BaseModel):
    """完整階層式訂閱樹回應 (Hierarchical Feed Tree Response with Global Stats)."""

    total_unread: int = 0
    total_articles: int = 0
    starred_count: int = 0
    trash_count: int = 0
    categories: list[FeedTreeCategoryDTO] = Field(default_factory=list)


# =============================================================================
# 3. 文章相關模型 (Articles Models)
# =============================================================================

class ArticleListItemDTO(BaseModel):
    """文章列表精簡資料傳輸模型 (Article List Item DTO)."""

    id: int
    feed_id: int
    feed_title: str
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    title: str
    url: str
    author: Optional[str] = None
    snippet: str
    cover_image_url: Optional[str] = None
    published_at: datetime
    is_read: bool
    is_unread: bool = False
    is_starred: bool
    tags: list[dict[str, Any]] = Field(default_factory=list)


class ArticleDetailDTO(ArticleListItemDTO):
    """單一文章完整詳情模型 (Article Detail DTO with Full HTML)."""

    content_html: str
    content_text: str
    ai_summary: Optional[str] = None


class ArticleListResponseDTO(BaseModel):
    """文章列表分頁回應模型 (Paginated Article List Response)."""

    total: int
    page: int
    page_size: int
    items: list[ArticleListItemDTO] = Field(default_factory=list)


class MarkReadBatchRequest(BaseModel):
    """批次標記已讀請求 (Batch Mark Read Request)."""

    scope: str = Field(default="all", description="'all', 'category', 或 'feed'")
    target_id: Optional[int] = Field(default=None, description="分類 ID 或頻道 ID")


# =============================================================================
# 4. 規則過濾器相關模型 (Filter Rules Models)
# =============================================================================

class RuleCreateRequest(BaseModel):
    """建立過濾規則請求 (Create Filter Rule Request)."""

    name: str = Field(min_length=1, max_length=100, description="規則名稱")
    sort_order: int = Field(default=0, description="優先權排序")
    is_enabled: bool = Field(default=True, description="是否啟用")
    conditions: list[dict[str, Any]] | dict[str, Any] = Field(description="比對條件清單或物件")
    actions: list[dict[str, Any]] = Field(description="執行動作清單")


class RuleUpdateRequest(BaseModel):
    """更新過濾規則請求 (Update Filter Rule Request)."""

    name: Optional[str] = None
    sort_order: Optional[int] = None
    is_enabled: Optional[bool] = None
    conditions: Optional[list[dict[str, Any]] | dict[str, Any]] = None
    actions: Optional[list[dict[str, Any]]] = None


class RuleResponseDTO(BaseModel):
    """過濾規則資料傳輸模型 (Filter Rule Response DTO)."""

    id: int
    name: str
    sort_order: int
    is_enabled: bool
    conditions: list[dict[str, Any]] | dict[str, Any]
    actions: list[dict[str, Any]]
    hit_count: int
    created_at: datetime


# =============================================================================
# 5. 邊緣中繼與快剪相關模型 (Edge Relay & Web Clipper Models)
# =============================================================================

class EdgeTaskFeedDTO(BaseModel):
    """Edge Relay 待抓取頻道任務條目 (Edge Relay Due Feed Task)."""

    feed_id: int
    feed_url: str
    title: str
    last_error_message: Optional[str] = None


class EdgeRelayIngestRequest(BaseModel):
    """Edge Relay 中繼 RSS XML 回傳請求 (Edge Relay Ingest Payload)."""

    feed_id: int
    raw_xml: str = Field(description="本地抓取的原始 RSS/Atom XML")


class WebClipperPushRequest(BaseModel):
    """Web Clipper 網頁一鍵剪藏請求 (Web Clipper Push Article Payload)."""

    url: str = Field(description="剪藏目標網址")
    title: str = Field(description="剪藏文章標題")
    html_content: str = Field(description="原始或清理後之 HTML 內容")
    author: Optional[str] = None
    cover_image_url: Optional[str] = None


# =============================================================================
# 6. 外掛與遙測相關模型 (Plugin & Telemetry Models)
# =============================================================================

class PluginTelemetryDTO(BaseModel):
    """外掛遙測與監控資料模型 (Plugin Telemetry DTO)."""

    plugin_id: str
    name: str
    version: str
    slot_type: str
    is_enabled: bool
    is_tripped: bool
    total_runs: int
    success_runs: int
    error_runs: int
    consecutive_errors: int
    avg_duration_ms: int
    last_error_message: Optional[str] = None


class PluginConfigUpdateRequest(BaseModel):
    """更新外掛私有設定請求 (Update Plugin Private Config)."""

    config: dict[str, Any] = Field(description="外掛私有配置字典")


# =============================================================================
# 7. 標籤與色票模型 (Tags & Labels Models - QuiteRSS Alignment)
# =============================================================================

class TagDTO(BaseModel):
    """標籤資料傳輸模型 (Tag DTO)."""

    id: int
    name: str
    color_hex: str = "#3b82f6"
    sort_order: int = 0
    unread_count: int = 0
    article_count: int = 0
    created_at: Optional[datetime] = None


class TagCreateRequest(BaseModel):
    """建立標籤請求 (Create Tag Request)."""

    name: str = Field(min_length=1, max_length=50, description="標籤名稱")
    color_hex: str = Field(default="#3b82f6", max_length=20, description="16 進位色票碼")
    sort_order: int = Field(default=0, description="排序權重")


class TagUpdateRequest(BaseModel):
    """更新標籤請求 (Update Tag Request)."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    color_hex: Optional[str] = Field(default=None, max_length=20)
    sort_order: Optional[int] = None


class ArticleTagBindingRequest(BaseModel):
    """文章標籤綁定請求 (Article Tag Binding Request)."""

    tag_ids: list[int] = Field(description="標籤 ID 清單")


class ArticleTagToggleRequest(BaseModel):
    """文章單一標籤切換請求 (Article Tag Toggle Request)."""

    tag_id: int = Field(description="標籤 ID")
    action: Optional[str] = Field(default="toggle", description="'toggle', 'add', 或 'remove'")


class BatchArticleTagRequest(BaseModel):
    """批次文章標籤操作請求 (Batch Article Tag Request)."""

    article_ids: list[int] = Field(description="文章 ID 清單")
    tag_id: int = Field(description="標籤 ID")
    action: str = Field(default="add", description="'add', 'remove', 或 'toggle'")

