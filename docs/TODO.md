# OmniRSS 施工任務清單與漸進式驗收藍圖 (Execution Checklist & Milestones)

> **專案名稱**：OmniRSS  
> **當前狀態**：Phase 4 完成 (QuiteRSS 24px 緊湊三欄、雙軸 Splitters、動態欄位 [ ⊞ ]、Vim 快捷鍵與 PWA 100% 綠燈驗收) ➔ 進入 Phase 5 (官方外掛生態與 Chrome 擴充套件)  
> **規格書文件路徑**：`docs/TODO.md`

---

## 📦 里程碑 Commit 總覽 (Bilingual Git Milestones Strategy)

| 里程碑階段 | 建議 Commit 訊息 (中英雙顯 Conventional Commits) | 驗收核心標的 |
| :---: | :--- | :--- |
| **Commit #0** | `docs(architecture): 封裝 OmniRSS 系統架構藍圖、資安規範與部署配置 / seal complete omnirss system blueprints, security specs, and deployment configs` | 8 大架構藍圖、外掛清單、部署配置、多國語系封裝 |
| **Commit #1** | `feat(core): 實作微核心 SDK、多租戶 SQLite WAL 地基、Anti-SSRF 網關與外掛管理器 / implement microkernel sdk, multi-tenant sqlite wal ddl, security gateway, and plugin manager` | Phase 1 地基工程、Anti-SSRF 網關、外掛管理器、單元測試全綠燈 |
| **Commit #2** | `feat(crawler): 實作 304 條件爬蟲、Auto-Referer、三階降級排程與 QuiteRSS 規則過濾引擎 / implement 304 conditional crawler, auto-referer, 3-stage fallback, and rule engine` | Phase 2 爬蟲引擎、QuiteRSS 條件過濾器、備份引擎、排程器 |
| **Commit #3** | `feat(api): 實作 FastAPI 路由、JWT/金鑰鑑權、金鑰脫敏備份與邊緣中繼端點 / implement fastAPI routes, jwt auth, edge relay endpoints, and opml handlers` | Phase 3 RESTful API 路由、Swagger 互動驗收、金鑰脫敏、中繼端點 |
| **Commit #4** | `feat(web): 建構 QuiteRSS 24px 緊湊三欄、雙軸 Splitters、動態欄位 [ ⊞ ] 與 PWA 支援 / build quiteRSS 24px compact reader, css grid splitters, column picker, and pwa` | Phase 4 QuiteRSS 24px 經典三欄、鍵盤流、動態欄位 [ ⊞ ]、PWA |
| **Commit #5** | `feat(ecosystem): 實作官方 4 大外掛 (Gemini 摘要、SimHash 去重、爬蟲) 與 Chrome MV3 擴充套件 / add official plugins and chrome companion extension` | Phase 5 官方 4 大外掛、Chrome MV3 擴充套件、端對端全生態閉環 |

---

## 🚀 階段一：微核心底座、Plugin SDK 與安全防護 (Phase 1)

### 1.1 專案骨架與環境初始化
- [x] 建立 `requirements.txt`（包含 `fastapi`, `uvicorn`, `pydantic`, `aiosqlite`, `nh3`, `apscheduler`, `feedparser`, `trafilatura`, `google-genai`, `argon2-cffi`, `pyjwt`, `pytest`, `pytest-asyncio`）
- [x] 建立 `config.example.json` 與 `omnirss/core/config.py` 設定讀取模組（UPPERCASE_SNAKE_CASE 規範）
- [x] 建立完整模組目錄結構：`omnirss/sdk/`, `omnirss/core/`, `omnirss/api/`, `omnirss/web/`, `locales/`, `plugins/`, `layouts/`, `data/`

### 1.2 Plugin SDK 介面定義 (`omnirss/sdk/`)
- [x] `models.py`：定義 `ArticleDTO`、`FeedDTO`、`MediaManifestDTO`、`PluginManifest`（嚴格型別驗證）
- [x] `base_plugin.py`：實作 `BasePlugin`、`BaseSourcePlugin`、`BaseProcessorPlugin`、`BaseActionPlugin`
- [x] `context.py`：注入外掛的安全 HTTP Client（內建 Anti-SSRF）與獨立 Logger

### 1.3 核心儲存層與 DDL 遷移 (`omnirss/core/database.py`)
- [x] 實作 SQLite 連線池、PRAGMA 極速調優與 WAL 模式初始化（`PRAGMA journal_mode = WAL`）
- [x] 自動建表：`users`, `categories`, `feeds`, `user_feeds`, `articles_hot`, `user_article_states`, `archives_cold`, `tags`, `article_tags`, `user_rules`, `plugins_telemetry`, `plugin_configs_global`, `user_plugin_configs`
- [x] 實作未讀計數自動維護觸發器 (`trg_articles_unread_inc`, `trg_articles_read_dec`, `trg_user_states_read_revert`)
- [x] 實作 `image_vault.py`（SHA-256 圖片去重轉 WebP 存檔）
- [x] 實作 `i18n.py`（後端多國語系翻譯器）

### 1.4 安全防護、身份認證與脫毒器 (`omnirss/core/security.py`)
- [x] 實作 `PasswordHasher` (Argon2id 密碼雜湊) 與常數時間比對 (`hmac.compare_digest`)
- [x] 實作 **四重防禦 Anti-SSRF 網路網關**（強制 DNS 解析真實 IP、攔截 OCI 元數據 `169.254.169.254`、逐跳重導向重審、Socket Pinning 連線直接綁定）
- [x] 實作 `HTMLSanitizer`（基於 `nh3` 嚴格移除 `<script>`, `<iframe>`, `on*` 事件）
- [x] 實作 Zero-Script CSP 標頭中間件與 `X-API-Key` 隨機金鑰產生器

### 1.5 插件管理器與可觀測性 (`omnirss/core/plugin_manager.py`)
- [x] 實作動態掃描 `plugins/` 目錄並解析 `plugin.json`
- [x] 實作 **三層外掛設定覆蓋合併** ($\text{ManifestDefault} \oplus \text{GlobalConfig} \oplus \text{UserConfig}$)
- [x] 實作 **雙層防衛性逾時鉗制**：$\text{effective\_timeout} = \max(1, \min(\text{int}(\text{manifest\_declared}), 45))$，異常負數自動防禦回退 15s
- [x] 實作 `circuit_breaker.py`（單次耗時監控、獨立例外隔離、連續 5 次錯誤自動熔斷 `is_tripped=1`）

### 🔍 Phase 1 驗收標準 (Acceptance Gate)
* **驗收指令**：`pytest tests/`
* **驗收指標**：
  1. ✅ SQLite WAL 連線池建立成功，觸發器精準增減未讀數。
  2. ✅ Anti-SSRF 網關成功攔截 `169.254.169.254`、`127.0.0.1` 與指向私有 IP 的惡意網域。
  3. ✅ 外掛管理器成功鉗制異常逾時數值（如 `-30` 秒），連續 5 次失敗自動觸發熔斷。
  4. ✅ 全部單元測試 100% 綠燈通過 (14/14 Passed in 0.62s)。
* **Commit 執行**：`git commit -m "feat(core): 實作微核心 SDK、多租戶 SQLite WAL 地基、Anti-SSRF 網關與外掛管理器 / implement microkernel sdk, multi-tenant sqlite wal ddl, security gateway, and plugin manager"`

---

## 📡 階段二：爬蟲引擎、過濾器與排程器 (Phase 2)

### 2.1 高韌性爬蟲引擎 (`omnirss/core/crawler_engine.py`)
- [x] 實作 **Auto-Referer 自動防盜鏈注入** (攻破 Mobile01 等論壇防禦)
- [x] 實作 **三階自適應指紋輪替狀態機** (Chrome 128 ➔ HTTPS 自動升級 ➔ QuiteRSS Qt 指紋)
- [x] 實作 **ETag / Last-Modified 304 零流量快取** 與 Gzip/Brotli 雙向解壓
- [x] 實作 **錯誤指數退避排程** (Exponential Backoff with Jitter)
- [x] 實作 10MB 串流讀取硬切斷 (防巨型檔案 DoS) 與 `defusedxml` 安全解析 (防 XML 炸彈)
- [x] 支援 **FlareSolverr 側邊欄智能路由** (針對 OCI 頑強 Cloudflare 站點)

### 2.2 智慧過濾與規則引擎 (`omnirss/core/rule_engine.py`)
- [x] 實作 QuiteRSS 條件比對器（支援 `AND` / `OR` 邏輯，比對標題、作者、內文、網址、正則 Regex）
- [x] 實作動作分發器（自動執行：`mark_read`、`trash`、`star`、`add_tag`、`notify`、`ai_summary`）

### 2.3 資料便攜備份與排程器 (`omnirss/core/backup_engine.py` & `scheduler.py`)
- [x] 實作 OPML 2.0 雙向匯出與匯入解析器（完整保留目錄階層樹與自訂別名）
- [x] 實作個人設定脫敏備份與還原（自動過濾 `[REDACTED]` 機敏金鑰）
- [x] 實作基於 APScheduler 的非同步定時排程引擎

### 🔍 Phase 2 驗收標準 (Acceptance Gate)
* **驗收指令**：`python scripts/verify_crawler.py`
* **驗收指標**：
  1. ✅ 成功抓取真實 Sample RSS 頻道並寫入 `articles_hot`，終端機顯示清晰抓取日誌。
  2. ✅ 第二次抓取時命中 304 快取，消耗頻寬為 0。
  3. ✅ 建立測試規則（標題包含「廣告」自動標記已讀），驗證入庫時自動觸發過濾。
  4. ✅ 匯入與匯出 OPML 測試，資料夾目錄與頻道名稱 100% 還原。
* **Commit 執行**：`git commit -m "feat(crawler): 實作 304 條件爬蟲、Auto-Referer、三階降級排程與 QuiteRSS 規則過濾引擎 / implement 304 conditional crawler, auto-referer, 3-stage fallback, and rule engine"`

---

## 🔌 階段三：RESTful API 路由與 Swagger 互動驗收 (Phase 3)

### 3.1 認證、依賴與錯誤處理 (`omnirss/api/`)
- [x] `dependencies.py`：JWT 登入認證、`X-API-Key` 鑑權（常數時間比對 `hmac.compare_digest`）、Rate Limiter（5 次失敗鎖定 15 分鐘）
- [x] `schemas.py`：嚴格對齊 [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) 的 Pydantic v2 DTO
- [x] 實作 RFC 7807 錯誤處理中介軟體

### 3.2 領域路由模組分拆 (`omnirss/api/routers/`)
- [x] `auth_router.py`：`/api/auth/login`, `/api/auth/logout`, `/api/auth/me`
- [x] `feeds_router.py`：`/api/feeds`, `/api/categories`, `/api/feeds/{id}/refresh`
- [x] `articles_router.py`：`/api/articles` (分頁/搜尋/排序), `/api/articles/{id}` (已讀/星標/標籤)
- [x] `rules_router.py`：`/api/rules` (過濾規則 CRUD 與優先權排序)
- [x] `plugins_router.py`：`/api/plugins` (外掛清單、開關、配置與遙測)
- [x] `edge_router.py`：`/api/feeds/edge-tasks` (個人頻道隔離), `/api/feeds/{id}/ingest`, `/api/articles/push` (Web Clipper 接收)
- [x] `backup_router.py`：`/api/opml/export`, `/api/opml/import`, `/api/user/backup`, `/api/user/restore`
- [x] `omnirss/main.py`：Lifespan 啟動健檢 (`PRAGMA quick_check`) 與關機 WAL 刷盤 (`PRAGMA wal_checkpoint(TRUNCATE)`)

### 🔍 Phase 3 驗收標準 (Acceptance Gate)
* **驗收指令**：啟動 `python -m omnirss.main` 並在瀏覽器開啟 `http://localhost:8000/docs`
* **驗收指標**：
  1. ✅ 在 Swagger UI 上執行 `/api/auth/login` 成功獲取 Token。
  2. ✅ 呼叫 `/api/feeds` 與 `/api/articles` 能以視覺化方式檢視真實 JSON 回傳。
  3. ✅ 呼叫 `/api/user/backup` 驗證機敏金鑰是否已自動脫敏為 `[REDACTED]`。
  4. ✅ 呼叫 `/api/feeds/edge-tasks` 驗證是否只回傳該使用者自己訂閱的 403 受阻頻道。
* **Commit 執行**：`git commit -m "feat(api): 實作 FastAPI 路由、JWT/金鑰鑑權、金鑰脫敏備份與邊緣中繼端點 / implement fastAPI routes, jwt auth, edge relay endpoints, and opml handlers"`

---

## 🎨 階段四：QuiteRSS 24px 經典前端與 PWA (Phase 4)

### 4.1 核心介面與零件化 CSS (`omnirss/web/`)
- [x] `index.html`：現代語意化結構，載入 Google Fonts、PWA Meta
- [x] `css/tokens.css`：24px 行高密度、QuiteRSS 暗黑與自訂主題色彩變數
- [x] `css/layout.css`：CSS Grid 三欄佈局與滑鼠/觸控多軸 Splitter 拖曳
- [x] `css/list.css`：單行零折行 (`nowrap` + `ellipsis`)、[ ⊞ ] 欄位自選彈窗、寧靜模式浮動通知
- [x] `css/reader.css`：文章排版美化、影音 Responsive Embed 播放器、AI 摘要抽屜

### 4.2 模組化 ES6 元件 (`omnirss/web/js/`)
- [x] `app.js` & `state.js`：應用程式啟動與響應式狀態管理
- [x] `api_client.js`：封裝 Fetch API、Token 自動附加與錯誤攔截
- [x] `i18n.js`：無重載即時多國語系切換 (zh-TW / en-US)
- [x] `keybindings.js`：全套 QuiteRSS / Vim 鍵盤流監聽器 (`j`/`k`, `v`, `m`, `s`, `Shift+A`, `/`, `b`)
- [x] `components/`：
  - [x] `tree_view.js`：分類目錄樹展開折疊、未讀計數平滑更新
  - [x] `list_view.js`：24px 虛擬滾動列表、全欄位點擊排序、寧靜模式 (Quiet Mode)
  - [x] `reader_view.js`：脫毒內容呈現、影音播放、外鏈在新分頁開啟
  - [x] `column_picker.js`：`[ ⊞ ]` 動態欄位顯示/隱藏與寬度記憶
  - [x] `rule_modal.js`：條件過濾器視覺化設定面板
- [x] `manifest.webmanifest` & `sw.js`：PWA 離線靜態快取與手機端自適應

### 🔍 Phase 4 驗收標準 (Acceptance Gate)
* **驗收指令**：在瀏覽器打開 `http://localhost:8000/`
* **驗收指標**：
  1. ✅ 介面達到 QuiteRSS 24px 高密度單行零折行視覺效果。
  2. ✅ 雙手不離鍵盤，利用 `j`/`k`、`v`、`m`、`s`、`Shift+A` 順暢操作。
  3. ✅ 點擊 `[ ⊞ ]` 勾選欄位可即時隱藏/顯示「作者」、「標籤」或「圖」欄位。
  4. ✅ 拖曳雙軸 Splitter 分割線可自由調整側邊欄與閱讀窗比例並自動記憶。
  5. ✅ 縮小視窗至手機寬度時，自動平滑自適應為單欄卡片視圖。
* **Commit 執行**：`git commit -m "feat(web): 建構 QuiteRSS 24px 緊湊三欄、雙軸 Splitters、動態欄位 [ ⊞ ] 與 PWA 支援 / build quiteRSS 24px compact reader, css grid splitters, column picker, and pwa"`

---

## 🧩 階段五：官方外掛生態與 Chrome 擴充套件 (Phase 5)

### 5.1 官方 4 大標準外掛實作 (`plugins/`)
- [ ] 來源外掛：`plugins/sources/generic_scraper/`（通用 Web 轉 RSS 爬蟲）
- [ ] 來源外掛：`plugins/sources/gomaji/`（Gomaji 折價券情報）
- [ ] 處理外掛：`plugins/processors/gemini_summary/`（Gemini Flash 動態探測、配額瀑布與繁中摘要）
- [ ] 處理外掛：`plugins/processors/simhash_dedup/`（SimHash 64-bit 漢明距離轉貼去重）

### 5.2 Chrome MV3 擴充套件 (`extensions/chrome/`)
- [ ] `manifest.json`：MV3 最小權限宣告
- [ ] `popup/`：伺服器網址配對、`X-API-Key` 驗證、快剪一鍵存入視圖
- [ ] `options/`：右鍵選單開關 (`enable_context_menu: false` 預設)、邊緣中繼排程 (15~120m)
- [ ] `content_scripts/extractor.js`：13 項完整中繼資料、去廣告 HTML、圖片清冊、影片嵌入代碼提取
- [ ] `background.js`：動態右鍵選單管理、個人頻道隔離邊緣中繼 Cron

### 🔍 Phase 5 驗收標準 (Acceptance Gate)
* **驗收指令**：在 Chrome 載入未封裝擴充套件並瀏覽外部新聞/部落格
* **驗收指標**：
  1. ✅ 點擊「📌 存入 OmniRSS」，後台冷存庫即時收納全文、去重圖檔與影片嵌入。
  2. ✅ 後台自動觸發 Gemini Flash 生成繁體中文重點摘要並呈現在閱讀窗。
  3. ✅ 擴充套件成功中繼抓取 OCI 受阻之 403 頻道並注入回庫。
  4. ✅ 端對端生態系統完整閉環驗收！
* **Commit 執行**：`git commit -m "feat(ecosystem): 實作官方 4 大外掛 (Gemini 摘要、SimHash 去重、爬蟲) 與 Chrome MV3 擴充套件 / add official plugins and chrome companion extension"`
