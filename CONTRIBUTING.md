# OmniRSS 開源外掛開發與貢獻指南 (Contributor & Plugin Developer Guide)

感謝您對 **OmniRSS** 開源專案的關注與支持！OmniRSS 致力於打造現代、極致緊湊、高擴充性且資料主權完全自主的萬能 RSS 聚合閱讀器。

---

## 1. 架構核心原則 (Core Philosophy)

1. **微核心純粹 (Clean Microkernel)**：核心只負責非同步排程調度、SQLite WAL 高效儲存與基礎防禦。
2. **4 大插件槽解耦 (4-Slot Architecture)**：所有擴充功能均透過標準插件槽實現。
3. **安全第一 (Defense-in-Depth)**：所有外部資料嚴格通過 `AntiSSRFGuard` 與 `nh3` Rust 級脫毒過濾。
4. **Context7 上游標準**：嚴格遵守現代 Python 3.12+、FastAPI、Pydantic v2 與 PEP-257 雙語註解規範。

---

## 2. 如何開發一個新外掛 (How to Build a Plugin)

每個外掛存放於 `plugins/<slot_type>/<author>_<plugin_name>/` 目錄下：

### 2.1 建立外掛宣告檔 (`plugin.json`)
```json
{
  "$schema": "https://omnirss.local/schemas/plugin-manifest.v1.json",
  "id": "yourname/custom-plugin",
  "name": "我的客製外掛",
  "version": "1.0.0",
  "slot_type": "processor",
  "author": "Your Name",
  "description": "說明此插件的功能與用途",
  "entry_point": "plugin:MyCustomPlugin",
  "default_config": {
    "api_key": ""
  }
}
```

### 2.2 選擇對應的 SDK 基礎類別繼承

#### A. 來源槽插件 (`Source Plugin`) —— 網站/社群爬蟲
```python
from omnirss.sdk.base_source import BaseSourcePlugin
from omnirss.sdk.models import ArticleDTO

class MySourcePlugin(BaseSourcePlugin):
    async def fetch(self, feed_url: str, session) -> list[ArticleDTO]:
        # 使用注入的安全 session (自帶 Anti-SSRF 防護) 發送請求
        resp = await session.get(feed_url)
        # 解析並回傳 ArticleDTO 清單
        return [ArticleDTO(...)]
```

#### B. 處理槽插件 (`Processor Plugin`) —— 管線加工/去重/AI
```python
from omnirss.sdk.base_processor import BaseProcessorPlugin
from omnirss.sdk.models import ArticleDTO
from typing import Optional

class MyProcessorPlugin(BaseProcessorPlugin):
    async def process(self, article: ArticleDTO) -> Optional[ArticleDTO]:
        # 進行正文加工、過濾或打標
        article.extra_tags.append("精選")
        return article
```

#### C. 動作槽插件 (`Action Plugin`) —— 收藏/標籤外部連動
```python
from omnirss.sdk.base_action import BaseActionPlugin
from omnirss.sdk.models import ArticleDTO

class MyActionPlugin(BaseActionPlugin):
    async def on_article_starred(self, article: ArticleDTO) -> bool:
        # 當使用者加星時，自動發送 Webhook
        return True
```

---

## 3. 代碼風格與品質要求 (Quality Standards)

- **Docstring 規範**：所有類別與公開函式必須提供符合 **PEP-257** 規範的繁體中文或雙語說明。
- **型別提示**：100% 採用 Python 3.12 現代 Type Hints (`list[str]`, `str | None`)。
- **無阻塞 I/O**：所有網路與資料庫操作必須採用 `async` / `await` 非同步語法。
- **單一職責**：外掛程式碼應盡可能自包含，外部第三方相依套件請宣告於 `plugin.json` 的 `dependencies` 欄位中。

---

## 4. Pull Request 提交清單 (PR Checklist)

- [ ] 新增或修改的功能已在本地完成測試。
- [ ] 若新增外掛，已提供完整的 `plugin.json` 與測試用例。
- [ ] 程式碼無未捕獲的嚴重例外，符合安全防護規範。
- [ ] 繁體中文與英文語系檔 (`locales/*.json`) 已對齊新增的 UI 鍵名。
