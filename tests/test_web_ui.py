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
        # 1. 測試根路徑 index.html 與 CSP 標頭
        res = await ac.get("/")
        assert res.status_code == 200
        assert "OmniRSS" in res.text
        assert "tokens.css" in res.text
        assert "app.js" in res.text

        csp = res.headers.get("Content-Security-Policy", "")
        assert "script-src 'self'" in csp, "CSP 必須放行同源 script-src 'self'"
        assert "script-src 'none'" not in csp, "CSP 嚴禁誤殺 script-src 'none'"
        assert "connect-src 'self'" in csp, "CSP 必須放行 connect-src 'self'"

        # 2. 測試 JavaScript 模組靜態載入與非空性
        js_files = [
            "/js/app.js",
            "/js/api_client.js",
            "/js/state.js",
            "/js/i18n.js",
            "/js/keybindings.js",
            "/js/components/tree_view.js",
            "/js/components/list_view.js",
            "/js/components/reader_view.js",
            "/js/components/column_picker.js",
            "/js/components/modals.js",
        ]
        for js_path in js_files:
            js_res = await ac.get(js_path)
            assert js_res.status_code == 200, f"{js_path} 載入失敗: {js_res.status_code}"
            assert len(js_res.text) > 50, f"{js_path} 內容異常為空"

        # 3. 測試 CSS 樣式表靜態載入
        css_files = [
            "/css/tokens.css",
            "/css/layout.css",
            "/css/tree.css",
            "/css/list.css",
            "/css/reader.css",
            "/css/modals.css",
        ]
        for css_path in css_files:
            css_res = await ac.get(css_path)
            assert css_res.status_code == 200, f"{css_path} 載入失敗: {css_res.status_code}"

        # 4. 測試 PWA 清單與圖標
        pwa_res = await ac.get("/manifest.webmanifest")
        assert pwa_res.status_code == 200
        assert "OmniRSS" in pwa_res.text

        fav_res = await ac.get("/favicon.ico")
        assert fav_res.status_code == 200
