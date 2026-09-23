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
            self.plugins_dir = (
                Path(__file__).resolve().parents[3] / "plugins"
            )
        else:
            self.plugins_dir = Path(plugins_dir)

        self._plugins: dict[str, BasePlugin] = {}
        self._manifests: dict[str, PluginManifest] = {}
        self._global_configs: dict[str, dict[str, Any]] = {}
        self._user_configs: dict[tuple[int, str], dict[str, Any]] = {}

    @property
    def loaded_plugins(self) -> dict[str, BasePlugin]:
        """已成功載入之外掛字典 (Dictionary of loaded plugin instances)."""
        return self._plugins

    @property
    def loaded_manifests(self) -> dict[str, PluginManifest]:
        """已成功載入之資訊清單字典 (Dictionary of loaded manifests)."""
        return self._manifests

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
        """計算三層外掛設定覆蓋結果 (Compute 3-tier merged effective configuration).

        Formula: ManifestDefault ⊕ GlobalConfig ⊕ UserConfig

        :param plugin_id: 外掛識別碼
        :param user_id: 使用者 ID (若有)
        :return: 最終生效之設定字典
        """
        manifest = self._manifests.get(plugin_id)
        default_cfg = manifest.default_config if manifest else {}
        global_cfg = self._global_configs.get(plugin_id, {})
        user_cfg = (
            self._user_configs.get((user_id, plugin_id), {})
            if user_id is not None
            else {}
        )

        merged = {}
        merged.update(default_cfg)
        merged.update(global_cfg)
        merged.update(user_cfg)
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

        manifest = self._manifests[plugin_id]
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
        )

    async def execute_processor(
        self,
        plugin_id: str,
        article: ArticleDTO,
        user_id: Optional[int] = None,
        http_client: Optional[Any] = None,
    ) -> Optional[ArticleDTO]:
        """執行處理外掛加工文章 (Execute processor plugin under supervision).

        :param plugin_id: 處理外掛 ID
        :param article: 待處理文章
        :param user_id: 觸發用戶 ID
        :param http_client: 注入之安全 HTTP 客戶端
        :return: 處理後之 ArticleDTO (若為 None 則拋棄)
        """
        plugin = self._plugins.get(plugin_id)
        if not isinstance(plugin, BaseProcessorPlugin):
            raise ValueError(
                f"Plugin '{plugin_id}' is not an active BaseProcessorPlugin"
            )

        manifest = self._manifests[plugin_id]
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
            coro_fn=lambda: plugin.process(article, context),
            declared_timeout=manifest.timeout_seconds,
        )


_PLUGIN_MANAGER: Optional[PluginManager] = None


def get_plugin_manager(
    plugins_dir: Optional[Union[str, Path]] = None
) -> PluginManager:
    """取得外掛管理器單例 (Get singleton plugin manager).

    :param plugins_dir: 自訂外掛目錄
    :return: PluginManager 實例
    """
    global _PLUGIN_MANAGER
    if _PLUGIN_MANAGER is None or plugins_dir is not None:
        _PLUGIN_MANAGER = PluginManager(plugins_dir)
    return _PLUGIN_MANAGER
