"""外掛安全執行上下文 (Plugin Secure Execution Context).

This module provides the PluginContext class injected into all plugin invocations,
offering safe HTTP access with Anti-SSRF protection, structured logging, and sandboxed helper utilities.
"""

from typing import Any, Optional
from loguru import logger


class PluginContext:
    """外掛執行上下文封裝 (Plugin Execution Context).

    Provides isolated and secure runtime facilities to plugins, preventing unmonitored external access.
    """

    def __init__(
        self,
        plugin_id: str,
        config: dict[str, Any],
        user_id: Optional[int] = None,
        http_client: Optional[Any] = None,
    ) -> None:
        """初始化外掛上下文 (Initialize plugin context).

        :param plugin_id: 外掛識別碼 (Plugin ID)
        :param config: 生效之完整設定 (Effective merged configuration)
        :param user_id: 觸發此任務的使用者 ID (Triggering user ID if any)
        :param http_client: 注入之安全 HTTP 客戶端 (Injected Anti-SSRF HTTP client)
        """
        self.plugin_id = plugin_id
        self.config = config
        self.user_id = user_id
        self._http_client = http_client
        self.logger = logger.bind(plugin_id=plugin_id, user_id=user_id)

    def get_config(self, key: str, default: Any = None) -> Any:
        """獲取指定設定鍵值 (Retrieve a specific configuration key).

        :param key: 設定鍵名稱 (Config key name)
        :param default: 鍵不存在時之預設值 (Fallback value)
        :return: 設定值 (Config value)
        """
        return self.config.get(key, default)

    async def http_get(
        self, url: str, headers: Optional[dict[str, str]] = None, **kwargs: Any
    ) -> Any:
        """透過安全網關發送 HTTP GET 請求 (Execute secure HTTP GET request).

        :param url: 目標網址 (Target URL)
        :param headers: 自訂標頭 (Request headers)
        :return: HTTP 響應物件 (Response object)
        """
        if self._http_client is None:
            raise RuntimeError(
                f"Plugin '{self.plugin_id}' has no active HTTP client attached."
            )
        return await self._http_client.get(url, headers=headers, **kwargs)

    async def http_post(
        self,
        url: str,
        data: Optional[Any] = None,
        json: Optional[Any] = None,
        headers: Optional[dict[str, str]] = None,
        **kwargs: Any,
    ) -> Any:
        """透過安全網關發送 HTTP POST 請求 (Execute secure HTTP POST request).

        :param url: 目標網址 (Target URL)
        :param data: 表單資料 (Form data)
        :param json: JSON 資料 (JSON payload)
        :param headers: 自訂標頭 (Request headers)
        :return: HTTP 響應物件 (Response object)
        """
        if self._http_client is None:
            raise RuntimeError(
                f"Plugin '{self.plugin_id}' has no active HTTP client attached."
            )
        return await self._http_client.post(
            url, data=data, json=json, headers=headers, **kwargs
        )
