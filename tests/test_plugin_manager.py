"""外掛 SDK 與管理器單元測試 (Plugin SDK and Manager Unit Tests).

Tests PluginManifest parsing, 3-tier config cascade merging, timeout clamping, and 5-strike circuit breaker tripping.
"""

import json
from pathlib import Path
import pytest
from omnirss.core.circuit_breaker import (
    CircuitBreakerManager,
    CircuitBreakerTrippedException,
)
from omnirss.core.plugin_manager import PluginManager
from omnirss.sdk.models import ArticleDTO, PluginManifest, PluginType


def test_article_dto_validation() -> None:
    """測試 ArticleDTO 型別校驗與預設值 (Test ArticleDTO validation)."""
    art = ArticleDTO(
        guid="test-guid-001",
        url="https://example.com/item/1",
        title="測試文章標題",
    )
    assert art.guid == "test-guid-001"
    assert art.is_read is False
    assert art.is_starred is False
    assert art.published_at is not None


def test_circuit_breaker_timeout_clamping() -> None:
    """測試雙層防衛性逾時秒數鉗制 (Test timeout clamping boundary rules)."""
    cb = CircuitBreakerManager()

    # 異常負數或零 ➔ 回退預設 15s
    assert cb.clamp_timeout(-30) == 15
    assert cb.clamp_timeout(0) == 15
    assert cb.clamp_timeout(None) == 15

    # 正常範圍 ➔ 採用設定值
    assert cb.clamp_timeout(10) == 10
    assert cb.clamp_timeout(30) == 30

    # 超過全域天花板 (45s) ➔ 鉗制至 45s
    assert cb.clamp_timeout(120) == 45


@pytest.mark.asyncio
async def test_circuit_breaker_tripping() -> None:
    """測試連續 5 次錯誤自動熔斷 (Test 5-strike circuit breaker tripping)."""
    cb = CircuitBreakerManager()
    plugin_id = "test/flaky-plugin"

    async def faulty_task() -> None:
        raise RuntimeError("External API Down")

    # 連續執行 5 次失敗
    for _ in range(5):
        with pytest.raises(RuntimeError):
            await cb.execute(plugin_id, faulty_task, declared_timeout=5)

    record = cb.get_or_create_record(plugin_id)
    assert record.consecutive_errors == 5
    assert record.is_tripped is True

    # 第 6 次嘗試應直接拋出 CircuitBreakerTrippedException
    with pytest.raises(CircuitBreakerTrippedException):
        await cb.execute(plugin_id, faulty_task, declared_timeout=5)

    # 重置熔斷狀態
    cb.reset_plugin(plugin_id)
    assert record.is_tripped is False
    assert record.consecutive_errors == 0


@pytest.mark.asyncio
async def test_plugin_dynamic_load_and_config_cascade(temp_dir: Path) -> None:
    """測試動態外掛載入與三層設定覆蓋合併 (Test dynamic loading and 3-tier config cascade)."""
    plugins_root = temp_dir / "plugins"
    mock_src_dir = plugins_root / "sources" / "mock_weather"
    mock_src_dir.mkdir(parents=True, exist_ok=True)

    # 1. 寫入 plugin.json
    manifest_dict = {
        "id": "official/mock-weather",
        "name": "模擬天氣來源外掛",
        "version": "1.0.0",
        "slot_type": "source",
        "author": "TechLead",
        "entry_point": "main:MockWeatherPlugin",
        "default_config": {
            "city": "Taipei",
            "items_limit": 5,
        },
        "timeout_seconds": 10,
    }
    with open(mock_src_dir / "plugin.json", "w", encoding="utf-8") as f:
        json.dump(manifest_dict, f)

    # 2. 寫入 main.py 實作
    plugin_code = """
from omnirss.sdk.base_plugin import BaseSourcePlugin
from omnirss.sdk.models import ArticleDTO
from omnirss.sdk.context import PluginContext

class MockWeatherPlugin(BaseSourcePlugin):
    async def fetch(self, feed_url: str, context: PluginContext) -> list[ArticleDTO]:
        city = context.get_config("city", "DefaultCity")
        limit = context.get_config("items_limit", 1)
        return [
            ArticleDTO(
                guid=f"weather_{city}_{i}",
                url=f"https://weather.local/{city}/{i}",
                title=f"{city} 今日天氣報 #{i}",
                content_text=f"{city} 晴天",
            )
            for i in range(limit)
        ]
"""
    with open(mock_src_dir / "main.py", "w", encoding="utf-8") as f:
        f.write(plugin_code)

    # 3. 測試動態加載
    pm = PluginManager(plugins_root)
    count = pm.discover_and_load()
    assert count == 1
    assert "official/mock-weather" in pm.loaded_plugins

    # 4. 驗證三層設定繼承:
    # 預設: city=Taipei, limit=5
    # 全域覆蓋: limit=20
    # 用戶覆蓋: city=Kaohsiung
    pm.set_global_config("official/mock-weather", {"items_limit": 20})
    pm.set_user_config(user_id=1, plugin_id="official/mock-weather", config={"city": "Kaohsiung"})

    effective = pm.get_effective_config("official/mock-weather", user_id=1)
    assert effective["city"] == "Kaohsiung"
    assert effective["items_limit"] == 20

    # 5. 執行外掛擷取
    articles = await pm.execute_source(
        plugin_id="official/mock-weather",
        feed_url="mock://feed",
        user_id=1,
    )
    assert len(articles) == 20
    assert articles[0].guid == "weather_Kaohsiung_0"
    assert "Kaohsiung 今日天氣報" in articles[0].title
