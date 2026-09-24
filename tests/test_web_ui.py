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
        assert "cdn.jsdelivr.net" in csp, "CSP 必須放行 cdn.jsdelivr.net 以利 Swagger UI 渲染"
        assert "script-src 'none'" not in csp, "CSP 嚴禁誤殺 script-src 'none'"
        assert "connect-src 'self'" in csp, "CSP 必須放行 connect-src 'self'"

        # 測試 /docs Swagger UI 頁面
        docs_res = await ac.get("/docs")
        assert docs_res.status_code == 200
        assert "swagger-ui" in docs_res.text.lower()
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


@pytest.mark.asyncio
async def test_frontend_button_api_endpoints_flow(tmp_path):
    """測試前端按鈕與對話框所呼叫之所有 API 端點流程 (Test all UI button API endpoints)."""
    db_file = tmp_path / "test_web_buttons.db"
    db_mgr = DatabaseManager(str(db_file))
    await db_mgr.initialize()
    set_global_db_manager(db_mgr)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. 建立管理員並登入
        setup_res = await ac.post("/api/auth/setup", json={"username": "admin", "password": "adminpassword"})
        assert setup_res.status_code == 200

        login_res = await ac.post("/api/auth/login", json={"username": "admin", "password": "adminpassword"})
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. 測試分類建立按鈕 (btn-add-category) 與清單端點
        cat_create = await ac.post("/api/categories", json={"name": "科技新聞", "icon": "folder"}, headers=headers)
        assert cat_create.status_code == 200
        cat_id = cat_create.json()["id"]

        cat_list = await ac.get("/api/categories", headers=headers)
        assert cat_list.status_code == 200
        assert len(cat_list.json()) == 1

        # 3. 測試頻道清單與手動新增訂閱源 (btn-add-feed)
        feed_list = await ac.get("/api/feeds", headers=headers)
        assert feed_list.status_code == 200
        assert isinstance(feed_list.json(), list)

        # 4. 測試文章清單查詢端點 (支援 is_unread, search, limit, offset)
        art_res = await ac.get("/api/articles?is_unread=true&search=test&limit=10&offset=0", headers=headers)
        assert art_res.status_code == 200
        assert "items" in art_res.json()
        assert "total" in art_res.json()

        # 5. 測試全部標記已讀按鈕 (btn-mark-all-read)
        mark_all = await ac.post("/api/articles/mark-all-read", json={"category_id": cat_id}, headers=headers)
        assert mark_all.status_code == 200
        assert "marked_count" in mark_all.json()

        # 6. 測試規則引擎彈窗新增與清單 (modal-rules)
        rule_res = await ac.post(
            "/api/rules",
            json={
                "name": "測試過濾",
                "sort_order": 10,
                "is_enabled": True,
                "conditions": [{"field": "title", "operator": "contains", "value": "廣告"}],
                "actions": [{"action_type": "mark_read", "parameters": {}}],
            },
            headers=headers,
        )
        assert rule_res.status_code == 200
        rule_id = rule_res.json()["id"]

        rules_list = await ac.get("/api/rules", headers=headers)
        assert rules_list.status_code == 200
        assert len(rules_list.json()) >= 1

        del_rule = await ac.delete(f"/api/rules/{rule_id}", headers=headers)
        assert del_rule.status_code == 200

        # 7. 測試外掛中心儀表板 (modal-plugins)
        plugins_res = await ac.get("/api/plugins", headers=headers)
        assert plugins_res.status_code == 200

        # 8. 測試全頻道整理按鈕 (btn-refresh-all)
        refresh_all = await ac.post("/api/feeds/refresh-all", headers=headers)
        assert refresh_all.status_code == 200

        # 9. 測試分類刪除
        del_cat = await ac.delete(f"/api/categories/{cat_id}", headers=headers)
        assert del_cat.status_code == 200
