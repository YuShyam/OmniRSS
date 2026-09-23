"""前端靜態介面測試套件 (Web UI & Static Files Integration Tests).

Tests index.html, static assets mounting, and status headers.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from omnirss.core.database import DatabaseManager, set_global_db_manager
from omnirss.main import app


@pytest.mark.asyncio
async def test_web_ui_and_static_files(tmp_path):
    """測試前端 SPA 頁面與靜態樣式表正常讀取 (Test static files and index.html)."""
    db_file = tmp_path / "test_web_ui.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. 測試根路徑 index.html
        res = await ac.get("/")
        assert res.status_code == 200
        assert "OmniRSS" in res.text
        assert "tokens.css" in res.text
        assert "app.js" in res.text

        # 2. 測試 CSS 樣式表靜態載入
        css_res = await ac.get("/css/tokens.css")
        assert css_res.status_code == 200
        assert "--row-height: 24px;" in css_res.text

        # 3. 測試 PWA 清單
        pwa_res = await ac.get("/manifest.webmanifest")
        assert pwa_res.status_code == 200
        assert "OmniRSS" in pwa_res.text
