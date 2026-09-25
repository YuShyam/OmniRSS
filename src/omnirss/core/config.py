"""全域設定管理模組 (Global Configuration Manager).

This module loads, validates, and provides structured access to OmniRSS server settings
from JSON configuration files and environment variables using Pydantic v2.
"""

import json
import os
from pathlib import Path
import secrets
from typing import Optional
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerConfig(BaseModel):
    """伺服器基礎連線設定 (Server Base Configuration)."""

    host: str = "0.0.0.0"
    port: int = 8000
    secret_key: str = ""
    timezone: str = "Asia/Taipei"
    log_level: str = "INFO"


class DatabaseConfig(BaseModel):
    """SQLite 資料庫調優設定 (Database Performance Configuration)."""

    path: str = "data/omnirss.db"
    wal_mode: bool = True
    busy_timeout_ms: int = 5000
    cache_size_kb: int = 64000
    auto_vacuum: str = "incremental"


class SecurityConfig(BaseModel):
    """資安與存取限制設定 (Security & Access Configuration)."""

    allow_registration: bool = False
    allow_external_ingest: bool = True
    rate_limit_per_minute: int = 120
    global_max_plugin_timeout_sec: int = 45
    jwt_secret: Optional[str] = None


class CrawlerConfig(BaseModel):
    """爬蟲與排程參數設定 (Crawler Engine Configuration)."""

    default_polling_interval_minutes: int = 30
    request_timeout_seconds: int = 15
    max_concurrent_workers: int = 25
    auto_referer_injection: bool = True
    enable_3stage_fallback: bool = True


class SidecarsConfig(BaseModel):
    """邊車服務整合設定 (Sidecar Services Configuration)."""

    flaresolverr_enabled: bool = False
    flaresolverr_url: str = "http://flaresolverr:8191/v1"


class RetentionConfig(BaseModel):
    """資料庫修剪與保留策略 (Data Retention Policy)."""

    global_retention_days: int = 60
    max_articles_per_feed: int = 0
    keep_starred_forever: bool = True
    keep_tagged_forever: bool = True
    min_publish_date: Optional[str] = None
    force_min_date: bool = False


class AppSettings(BaseSettings):
    """應用程式全域設定聚合類別 (Global Application Settings Aggregate)."""

    model_config = SettingsConfigDict(
        env_prefix="OMNIRSS_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    crawler: CrawlerConfig = Field(default_factory=CrawlerConfig)
    sidecars: SidecarsConfig = Field(default_factory=SidecarsConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)


_GLOBAL_SETTINGS: Optional[AppSettings] = None


def load_settings(config_path: Optional[str | Path] = None) -> AppSettings:
    """載入並初始化設定檔 (Load and parse JSON settings file).

    :param config_path: 自訂設定檔路徑；若為 None 則按順序探測 config.json 與 config.example.json
    :return: 驗證完成之 AppSettings 實例
    """
    global _GLOBAL_SETTINGS

    base_dir = Path(__file__).resolve().parents[3]

    if config_path is None:
        cand_paths = [
            base_dir / "config.json",
            base_dir / "config.example.json",
        ]
        chosen_path: Optional[Path] = None
        for p in cand_paths:
            if p.is_file():
                chosen_path = p
                break
    else:
        chosen_path = Path(config_path)

    raw_data: dict = {}
    if chosen_path and chosen_path.is_file():
        try:
            with open(chosen_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except Exception:
            raw_data = {}

    settings = AppSettings.model_validate(raw_data)

    # 若 secret_key 為空，自動由 data/.jwt_secret 載入或生成安全密鑰 (Persist secret key across server restarts)
    if not settings.server.secret_key:
        secret_file = base_dir / "data" / ".jwt_secret"
        if secret_file.is_file():
            try:
                loaded_key = secret_file.read_text("utf-8").strip()
                if loaded_key:
                    settings.server.secret_key = loaded_key
            except Exception:
                pass
        if not settings.server.secret_key:
            new_key = secrets.token_urlsafe(32)
            settings.server.secret_key = new_key
            try:
                secret_file.parent.mkdir(parents=True, exist_ok=True)
                secret_file.write_text(new_key, "utf-8")
            except Exception:
                pass

    _GLOBAL_SETTINGS = settings
    return settings


def get_settings() -> AppSettings:
    """取得當前全域設定單例 (Get active singleton settings instance).

    :return: AppSettings 實例
    """
    global _GLOBAL_SETTINGS
    if _GLOBAL_SETTINGS is None:
        _GLOBAL_SETTINGS = load_settings()
    return _GLOBAL_SETTINGS
