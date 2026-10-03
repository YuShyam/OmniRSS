"""動態外掛管理器與排程載入器 (Dynamic Plugin Manager & Orchestrator).

This module discovers, validates, and dynamically instantiates OmniRSS plugins,
merging 3-tier configuration layers and orchestrating sandboxed execution.
"""

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Optional, Union
from loguru import logger
from omnirss.core.circuit_breaker import get_circuit_breaker
from omnirss.core.pattern_matcher import match_url_patterns
from omnirss.sdk.base_plugin import (
    BaseActionPlugin,
    BasePlugin,
    BaseProcessorPlugin,
    BaseSourcePlugin,
)
from omnirss.sdk.context import PluginContext
from omnirss.sdk.models import ArticleDTO, PluginManifest, PluginType


class PluginRegistrationError(Exception):
    """外掛註冊異常例外 (Plugin Registration Error)."""


class PluginManager:
    """外掛管理器 (Plugin Manager).

    Discovers plugins in the plugins directory, validates manifests, merges configuration,
    and executes plugins safely under circuit breaker and timeout supervision.
    """

    def __init__(self, plugins_dir: Optional[str | Path] = None) -> None:
        if plugins_dir is None:
            from omnirss.core.config import get_base_dir
            self.plugins_dir = get_base_dir() / "plugins"
        else:
            self.plugins_dir = Path(plugins_dir)

        self._plugins: dict[str, BasePlugin] = {}
        self._manifests: dict[str, PluginManifest] = {}
        self._plugin_dirs: dict[str, Path] = {}
        self._global_configs: dict[str, dict[str, Any]] = {}
        self._user_configs: dict[tuple[int, str], dict[str, Any]] = {}

    @property
    def loaded_plugins(self) -> dict[str, BasePlugin]:
        """已成功載入之外掛字典 (Dictionary of loaded plugin instances)."""
        return self._plugins

    @property
    def loaded_manifests(self) -> dict[str, PluginManifest]:
        """已成功載入之資訊清單字典 (Dictionary of loaded manifests with hot reload)."""
        for p_id in list(self._manifests.keys()):
            self.get_manifest(p_id)
        return self._manifests

    def list_manifests(self) -> dict[str, PluginManifest]:
        """列出所有已載入之外掛資訊清單 (List loaded plugin manifests)."""
        return self.loaded_manifests

    def get_manifest(self, plugin_id: str) -> Optional[PluginManifest]:
        """取得並自動熱同步磁碟上最新之 PluginManifest (Get and auto-refresh manifest)."""
        if plugin_id in self._plugin_dirs:
            manifest_path = self._plugin_dirs[plugin_id] / "plugin.json"
            if manifest_path.is_file():
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    latest_manifest = PluginManifest.model_validate(data)
                    self._manifests[plugin_id] = latest_manifest
                    return latest_manifest
                except Exception:
                    pass
        return self._manifests.get(plugin_id)

    def set_global_config(self, plugin_id: str, config: dict[str, Any]) -> None:
        """設定全域外掛偏好設定 (Set global plugin config).

        :param plugin_id: 外掛識別碼
        :param config: 全域設定字典
        """
        self._global_configs[plugin_id] = config

    def set_user_config(
        self, user_id: int, plugin_id: str, config: dict[str, Any]
    ) -> None:
        """設定個人外掛偏好設定 (Set user-specific plugin config).

        :param user_id: 使用者 ID
        :param plugin_id: 外掛識別碼
        :param config: 個人設定字典
        """
        self._user_configs[(user_id, plugin_id)] = config

    def get_effective_config(
        self, plugin_id: str, user_id: Optional[int] = None
    ) -> dict[str, Any]:
        """計算三層外掛設定覆蓋結果 (Compute 3-tier merged effective configuration with SQLite & Fallback).

        Formula: ManifestDefault ⊕ GlobalConfig ⊕ UserConfig ⊕ SQLiteSync ⊕ EnvFallback

        :param plugin_id: 外掛識別碼
        :param user_id: 使用者 ID (若有)
        :return: 最終生效之設定字典
        """
        import os
        import sqlite3
        from omnirss.core.config import get_settings

        manifest = self.get_manifest(plugin_id) or self._manifests.get(plugin_id)
        default_cfg = dict(manifest.default_config) if manifest and manifest.default_config else {}
        global_cfg = dict(self._global_configs.get(plugin_id, {}))
        user_cfg = (
            dict(self._user_configs.get((user_id, plugin_id), {}))
            if user_id is not None
            else {}
        )

        # 若記憶體中無設定，自 SQLite 資料庫自動同步 (通用條件，不寫死特定外掛 ID)
        if not user_cfg or not global_cfg:
            try:
                settings = get_settings()
                db_path = Path(settings.database.path)
                if db_path.exists() and db_path.is_file():
                    with sqlite3.connect(str(db_path), timeout=0.2) as conn:
                        conn.row_factory = sqlite3.Row
                        cursor = conn.cursor()

                        # 1. 讀取全域設定
                        if not global_cfg:
                            cursor.execute("SELECT config_json FROM plugin_configs_global WHERE plugin_id = ?", (plugin_id,))
                            g_row = cursor.fetchone()
                            if g_row and g_row["config_json"]:
                                global_cfg = json.loads(g_row["config_json"])
                                self._global_configs[plugin_id] = global_cfg

                        # 2. 讀取指定用戶設定
                        if user_id is not None and not user_cfg:
                            cursor.execute("SELECT config_json FROM user_plugin_configs WHERE user_id = ? AND plugin_id = ?", (user_id, plugin_id))
                            u_row = cursor.fetchone()
                            if u_row and u_row["config_json"]:
                                user_cfg = json.loads(u_row["config_json"])
                                self._user_configs[(user_id, plugin_id)] = user_cfg

                        # 3. 智慧保底：若特定金鑰依然為空，查訪系統中既有已設定之有效偏好（避免排程或切換帳號脫節）
                        if not user_cfg.get("api_key") and not global_cfg.get("api_key"):
                            cursor.execute("SELECT config_json FROM user_plugin_configs WHERE plugin_id = ? ORDER BY user_id ASC LIMIT 1", (plugin_id,))
                            any_row = cursor.fetchone()
                            if any_row and any_row["config_json"]:
                                fallback_cfg = json.loads(any_row["config_json"])
                                if fallback_cfg.get("api_key"):
                                    if not user_cfg:
                                        user_cfg = fallback_cfg
                                    else:
                                        user_cfg.setdefault("api_key", fallback_cfg["api_key"])
            except Exception as exc:
                logger.debug(f"SQLite config sync notice for {plugin_id}: {exc}")

        merged = {}
        merged.update(default_cfg)
        merged.update(global_cfg)
        merged.update(user_cfg)

        # 4. 環境變數保底：若外掛 manifest 宣告需要 api_key 欄位且目前尚未設定，則嘗試從環境變數補齊
        # 此邏輯為通用設計，任何宣告了 api_key 欄位的外掛皆受惠，不再寫死特定外掛 ID
        schema_props = (manifest.config_schema or {}).get("properties", {}) if manifest else {}
        if "api_key" in schema_props and not merged.get("api_key"):
            env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("PLUGIN_API_KEY")
            if env_key:
                merged["api_key"] = env_key

        return merged

    def load_plugin_from_dir(self, plugin_dir: Path) -> Optional[BasePlugin]:
        """自指定目錄載入單一外掛 (Load single plugin from directory).

        :param plugin_dir: 外掛目錄路徑 (Plugin directory)
        :return: 實例化之 BasePlugin 物件；若載入失敗則回傳 None
        """
        manifest_path = plugin_dir / "plugin.json"
        if not manifest_path.is_file():
            return None

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            manifest = PluginManifest.model_validate(manifest_data)
        except Exception as exc:
            logger.error(f"Failed to parse manifest in {manifest_path}: {exc}")
            return None

        # 檢驗 ID 唯一性與路徑綁定 (防範身份冒名)
        plugin_id = manifest.id
        if plugin_id in self._plugins:
            logger.warning(
                f"Plugin ID collision: '{plugin_id}' already registered. Skipping {plugin_dir}"
            )
            return None

        entry_point = manifest.entry_point
        if ":" not in entry_point:
            logger.error(
                f"Invalid entry_point '{entry_point}' in {plugin_dir}. Expected 'module:Class'"
            )
            return None

        module_name, class_name = entry_point.split(":", 1)
        module_file = plugin_dir / f"{module_name}.py"
        if not module_file.is_file():
            # 支援 __init__.py 作為進入點
            module_file = plugin_dir / "__init__.py"

        if not module_file.is_file():
            logger.error(
                f"Plugin entrypoint file not found for '{plugin_id}': {module_file}"
            )
            return None

        # 動態載入 Python 模組
        spec_name = f"omnirss_plugin_{plugin_id.replace('/', '_').replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(spec_name, str(module_file))
        if spec is None or spec.loader is None:
            logger.error(f"Failed to create module spec for {module_file}")
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            logger.error(f"Error executing module for plugin '{plugin_id}': {exc}")
            return None

        plugin_class = getattr(module, class_name, None)
        if plugin_class is None:
            logger.error(
                f"Class '{class_name}' not found in module '{module_name}' for plugin '{plugin_id}'"
            )
            return None

        if not issubclass(plugin_class, BasePlugin):
            logger.error(
                f"Class '{class_name}' for plugin '{plugin_id}' must inherit from BasePlugin"
            )
            return None

        effective_config = self.get_effective_config(plugin_id)
        instance = plugin_class(
            plugin_id=plugin_id,
            manifest=manifest,
            config=effective_config,
        )

        self._plugins[plugin_id] = instance
        self._manifests[plugin_id] = manifest
        self._plugin_dirs[plugin_id] = plugin_dir
        logger.info(
            f"Successfully loaded plugin: [{manifest.slot_type.value}] {plugin_id} v{manifest.version}"
        )
        return instance

    def discover_and_load(self) -> int:
        """掃描外掛目錄並載入所有符合規範之外掛 (Scan and load all plugins).

        :return: 成功載入之外掛總數
        """
        if not self.plugins_dir.is_dir():
            logger.warning(f"Plugins directory does not exist: {self.plugins_dir}")
            return 0

        loaded_count = 0
        for slot_dir in self.plugins_dir.iterdir():
            if slot_dir.is_dir():
                # 遍歷各外掛子目錄
                for plugin_candidate in slot_dir.iterdir():
                    if plugin_candidate.is_dir() and (
                        plugin_candidate / "plugin.json"
                    ).is_file():
                        instance = self.load_plugin_from_dir(plugin_candidate)
                        if instance is not None:
                            loaded_count += 1

        logger.info(f"Plugin discovery completed. Total active plugins: {loaded_count}")
        return loaded_count

    async def execute_source(
        self,
        plugin_id: str,
        feed_url: str,
        user_id: Optional[int] = None,
        http_client: Optional[Any] = None,
    ) -> list[ArticleDTO]:
        """執行來源外掛擷取資料 (Execute source plugin under supervision).

        :param plugin_id: 來源外掛 ID
        :param feed_url: 訂閱來源 URL
        :param user_id: 觸發用戶 ID
        :param http_client: 注入之安全 HTTP 客戶端
        :return: 解析完成之 ArticleDTO 清單
        """
        plugin = self._plugins.get(plugin_id)
        if not isinstance(plugin, BaseSourcePlugin):
            raise ValueError(
                f"Plugin '{plugin_id}' is not an active BaseSourcePlugin"
            )

        manifest = self.get_manifest(plugin_id) or self._manifests[plugin_id]
        if manifest.match_patterns and not match_url_patterns(
            feed_url, manifest.match_patterns
        ):
            logger.warning(
                f"Feed URL '{feed_url}' skipped source plugin '{plugin_id}' (match_patterns mismatch)"
            )
            return []

        effective_config = self.get_effective_config(plugin_id, user_id)
        plugin.update_config(effective_config)

        context = PluginContext(
            plugin_id=plugin_id,
            config=effective_config,
            user_id=user_id,
            http_client=http_client,
        )

        cb = get_circuit_breaker()
        return await cb.execute(
            plugin_id=plugin_id,
            coro_fn=lambda: plugin.fetch(feed_url, context),
            declared_timeout=manifest.timeout_seconds,
            user_id=user_id,
            trigger_source="feed_crawl",
            action_param=feed_url,
        )

    async def execute_processor(
        self,
        plugin_id: str,
        article: ArticleDTO,
        user_id: Optional[int] = None,
        http_client: Optional[Any] = None,
        extra_config: Optional[dict[str, Any]] = None,
        action_param: Optional[str] = None,
        trigger_source: str = "manual",
        article_id: Optional[int] = None,
    ) -> Optional[ArticleDTO]:
        """執行處理外掛加工文章 (Execute processor plugin under supervision).

        :param plugin_id: 處理外掛 ID
        :param article: 待處理文章
        :param user_id: 觸發用戶 ID
        :param http_client: 注入之安全 HTTP 客戶端
        :param extra_config: 動態覆蓋或補充之執行期參數 (例如指定 prompt_preset)
        :param action_param: 規則或動作調用時傳入之通用參數
        :param trigger_source: 觸發來源 ('manual', 'rule', 'star')
        :param article_id: 指定文章流水號 ID (預設由 article 物件自動取得)
        :return: 處理後之 ArticleDTO (若為 None 則拋棄)
        """
        plugin = self._plugins.get(plugin_id)
        if not isinstance(plugin, BaseProcessorPlugin):
            raise ValueError(
                f"Plugin '{plugin_id}' is not an active BaseProcessorPlugin"
            )

        manifest = self.get_manifest(plugin_id) or self._manifests[plugin_id]
        # 聲明式網址模式比對檢查 (Declarative match_patterns pre-filter)
        if manifest.match_patterns and not match_url_patterns(
            getattr(article, "url", ""), manifest.match_patterns
        ):
            logger.debug(
                f"Article URL '{getattr(article, 'url', '')}' skipped processor plugin '{plugin_id}' (match_patterns mismatch)"
            )
            return article
        effective_config = dict(self.get_effective_config(plugin_id, user_id))
        if extra_config:
            effective_config.update(extra_config)
        plugin.update_config(effective_config)

        context = PluginContext(
            plugin_id=plugin_id,
            config=effective_config,
            user_id=user_id,
            http_client=http_client,
            action_param=action_param,
        )

        cb = get_circuit_breaker()
        return await cb.execute(
            plugin_id=plugin_id,
            coro_fn=lambda: plugin.process(article, context),
            declared_timeout=manifest.timeout_seconds,
            user_id=user_id,
            article_id=article_id or getattr(article, "id", None),
            article_title=getattr(article, "title", None),
            trigger_source=trigger_source,
            action_param=action_param or (extra_config.get("prompt_style") if extra_config else None),
        )

    async def execute_all_processors(
        self,
        article: ArticleDTO,
        user_id: Optional[int] = None,
        http_client: Optional[Any] = None,
        trigger_source: str = "feed_crawl",
    ) -> ArticleDTO:
        """依序執行所有已啟用之處理外掛 (Pipeline all active processor plugins sequentially).

        :param article: 待處理之 ArticleDTO
        :param user_id: 觸發用戶 ID
        :param http_client: 注入之安全 HTTP 客戶端
        :param trigger_source: 觸發來源 ('feed_crawl', 'rule', 'manual')
        :return: 經所有處理外掛加工後之 ArticleDTO
        """
        current_article = article
        from omnirss.core.circuit_breaker import get_circuit_breaker
        cb = get_circuit_breaker()

        for plugin_id, plugin in self._plugins.items():
            if isinstance(plugin, BaseProcessorPlugin):
                # 若外掛已被手動停用，直接略過 (Bypass disabled plugins)
                rec = cb.get_or_create_record(plugin_id)
                if not rec.is_enabled:
                    continue

                effective_config = self.get_effective_config(plugin_id, user_id)
                # 若為背景爬蟲入庫，且使用者/外掛設定未開啟自動套用，則略過 (Respect auto_apply setting)
                if trigger_source == "feed_crawl" and not effective_config.get("auto_apply", True):
                    continue

                try:
                    res = await self.execute_processor(
                        plugin_id=plugin_id,
                        article=current_article,
                        user_id=user_id,
                        http_client=http_client,
                        trigger_source=trigger_source,
                    )
                    if res is not None:
                        current_article = res
                except Exception as exc:
                    logger.warning(
                        f"Processor plugin '{plugin_id}' execution skipped/failed: {exc}"
                    )
        return current_article


_PLUGIN_MANAGER: Optional[PluginManager] = None


def get_plugin_manager(
    plugins_dir: Optional[Union[str, Path]] = None,
    auto_discover: bool = True,
) -> PluginManager:
    """取得外掛管理器單例並確保已自動掃描 (Get singleton plugin manager with auto-discovery).

    :param plugins_dir: 自訂外掛目錄
    :param auto_discover: 是否自動執行外掛發現
    :return: PluginManager 實例
    """
    global _PLUGIN_MANAGER
    if _PLUGIN_MANAGER is None or plugins_dir is not None:
        _PLUGIN_MANAGER = PluginManager(plugins_dir)
        if auto_discover:
            _PLUGIN_MANAGER.discover_and_load()
    return _PLUGIN_MANAGER

