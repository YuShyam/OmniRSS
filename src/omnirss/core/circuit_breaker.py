"""外掛效能取樣器與自動熔斷器 (Plugin Telemetry Profiler & Circuit Breaker).

This module manages execution timing, timeout clamping, exception isolation,
and 5-consecutive-error auto-tripping for OmniRSS plugins.
"""

import asyncio
from datetime import datetime, timezone
import time
import traceback
from typing import Any, Callable, Coroutine, Optional
from loguru import logger
from omnirss.core.config import get_settings


class CircuitBreakerTrippedException(Exception):
    """外掛已熔斷例外 (Circuit Breaker Tripped Exception).

    Raised when attempting to execute a plugin that has been tripped due to excessive errors.
    """

    def __init__(self, plugin_id: str, message: str) -> None:
        super().__init__(message)
        self.plugin_id = plugin_id


class PluginTelemetryRecord:
    """單一外掛遙測紀錄 (In-Memory Plugin Telemetry & Health Record)."""

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        self.is_enabled: bool = True
        self.is_tripped: bool = False
        self.total_runs: int = 0
        self.success_runs: int = 0
        self.error_runs: int = 0
        self.consecutive_errors: int = 0
        self.last_duration_ms: int = 0
        self.avg_duration_ms: int = 0
        self.last_error_message: Optional[str] = None
        self.last_error_traceback: Optional[str] = None
        self.last_run_at: Optional[datetime] = None

    def record_success(self, duration_ms: int) -> None:
        """紀錄執行成功指標 (Record successful execution metrics).

        :param duration_ms: 執行耗時毫秒數
        """
        self.total_runs += 1
        self.success_runs += 1
        self.consecutive_errors = 0
        self.last_duration_ms = duration_ms
        self.last_run_at = datetime.now(timezone.utc)

        # 動態計算平滑平均耗時
        if self.total_runs == 1:
            self.avg_duration_ms = duration_ms
        else:
            self.avg_duration_ms = int(
                (self.avg_duration_ms * (self.total_runs - 1) + duration_ms)
                / self.total_runs
            )

    def record_failure(
        self,
        duration_ms: int,
        error_msg: str,
        tb_str: Optional[str] = None,
        max_consecutive_errors: int = 5,
    ) -> None:
        """紀錄執行失敗指標 (Record failed execution metrics and check trip threshold).

        :param duration_ms: 執行耗時毫秒數
        :param error_msg: 錯誤訊息
        :param tb_str: 例外堆疊字串
        :param max_consecutive_errors: 連續錯誤熔斷門檻
        """
        self.total_runs += 1
        self.error_runs += 1
        self.consecutive_errors += 1
        self.last_duration_ms = duration_ms
        self.last_error_message = error_msg
        self.last_error_traceback = tb_str
        self.last_run_at = datetime.now(timezone.utc)

        if self.consecutive_errors >= max_consecutive_errors:
            self.is_tripped = True
            logger.warning(
                f"Circuit Breaker Tripped: Plugin '{self.plugin_id}' reached {self.consecutive_errors} consecutive failures and is now tripped."
            )

    def reset(self) -> None:
        """重置熔斷狀態與連續錯誤計數 (Reset tripped status)."""
        self.is_tripped = False
        self.consecutive_errors = 0
        self.last_error_message = None
        self.last_error_traceback = None


class CircuitBreakerManager:
    """自動熔斷管理器 (Circuit Breaker Manager)."""

    CONSECUTIVE_ERRORS_THRESHOLD = 5
    DEFAULT_TIMEOUT_SEC = 15

    def __init__(self) -> None:
        self._records: dict[str, PluginTelemetryRecord] = {}

    def get_or_create_record(self, plugin_id: str) -> PluginTelemetryRecord:
        """取得或初始化指定外掛之遙測記錄 (Get or create telemetry record for plugin).

        :param plugin_id: 外掛識別碼
        :return: PluginTelemetryRecord 實例
        """
        if plugin_id not in self._records:
            self._records[plugin_id] = PluginTelemetryRecord(plugin_id)
        return self._records[plugin_id]

    def clamp_timeout(self, declared_timeout: Optional[int]) -> int:
        """防衛性逾時秒數鉗制 (Defensively clamp declared timeout to valid boundaries).

        Formula: max(1, min(int(declared_timeout), global_max_cap))

        :param declared_timeout: 外掛宣告之逾時秒數
        :return: 鉗制後之有效逾時秒數
        """
        settings = get_settings()
        global_cap = settings.security.global_max_plugin_timeout_sec

        if declared_timeout is None:
            return self.DEFAULT_TIMEOUT_SEC

        try:
            val = int(declared_timeout)
            if val <= 0:
                logger.warning(
                    f"Invalid declared timeout ({declared_timeout}s). Falling back to default {self.DEFAULT_TIMEOUT_SEC}s."
                )
                return self.DEFAULT_TIMEOUT_SEC
            return max(1, min(val, global_cap))
        except (ValueError, TypeError):
            return self.DEFAULT_TIMEOUT_SEC

    async def execute(
        self,
        plugin_id: str,
        coro_fn: Callable[[], Coroutine[Any, Any, Any]],
        declared_timeout: Optional[int] = None,
    ) -> Any:
        """包裹逾時控制與自動熔斷執行外掛協程 (Execute coroutine under circuit breaker protection).

        :param plugin_id: 外掛識別碼
        :param coro_fn: 待執行之無參數協程函式
        :param declared_timeout: 宣告逾時秒數
        :return: 協程回傳值
        :raises CircuitBreakerTrippedException: 若該外掛處於熔斷狀態時拋出
        """
        record = self.get_or_create_record(plugin_id)
        if not record.is_enabled:
            raise CircuitBreakerTrippedException(
                plugin_id, f"Plugin '{plugin_id}' is manually disabled."
            )
        if record.is_tripped:
            raise CircuitBreakerTrippedException(
                plugin_id,
                f"Plugin '{plugin_id}' is tripped due to {record.consecutive_errors} consecutive errors.",
            )

        effective_timeout = self.clamp_timeout(declared_timeout)
        start_time = time.perf_counter()

        try:
            result = await asyncio.wait_for(coro_fn(), timeout=effective_timeout)
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            record.record_success(duration_ms)
            return result
        except asyncio.TimeoutError:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            msg = f"Execution timed out after {effective_timeout}s"
            record.record_failure(
                duration_ms,
                msg,
                "TimeoutError",
                self.CONSECUTIVE_ERRORS_THRESHOLD,
            )
            raise TimeoutError(f"Plugin '{plugin_id}' {msg}")
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            tb = traceback.format_exc()
            record.record_failure(
                duration_ms,
                str(e),
                tb,
                self.CONSECUTIVE_ERRORS_THRESHOLD,
            )
            raise e

    def reset_plugin(self, plugin_id: str) -> None:
        """手動重置指定外掛之熔斷狀態 (Manually reset tripped status).

        :param plugin_id: 外掛識別碼
        """
        record = self.get_or_create_record(plugin_id)
        record.reset()


_CIRCUIT_BREAKER_MANAGER: Optional[CircuitBreakerManager] = None


def get_circuit_breaker() -> CircuitBreakerManager:
    """取得全域熔斷管理器單例 (Get singleton circuit breaker manager).

    :return: CircuitBreakerManager 實例
    """
    global _CIRCUIT_BREAKER_MANAGER
    if _CIRCUIT_BREAKER_MANAGER is None:
        _CIRCUIT_BREAKER_MANAGER = CircuitBreakerManager()
    return _CIRCUIT_BREAKER_MANAGER
