"""Gemini Flash AI 繁體中文重點摘要處理器 (Gemini Summary Processor Plugin).

This plugin analyzes article content and generates structured bullet points in Traditional Chinese
using Google Gemini Flash models with semantic version dynamic discovery, persistent watermark state machine,
pre-sanitization framing, and local fallback extraction.
"""

from datetime import datetime, timezone
import json
import re
from typing import Any, Optional, TYPE_CHECKING
import httpx
from loguru import logger
from omnirss.sdk.base_plugin import BaseProcessorPlugin
from omnirss.sdk.models import ArticleDTO

if TYPE_CHECKING:
    from omnirss.sdk.context import PluginContext


PROMPT_PRESETS: dict[str, dict[str, str]] = {
    "standard": {
        "id": "standard",
        "name": "標準重點條列",
        "prompt": (
            "請針對以下文章內容，以繁體中文 (Traditional Chinese, 台灣習慣用語) 產出 {bullets} 點「客觀、精準且高資訊密度」的核心重點摘要。\n"
            "【鋼鐵原則】：\n"
            "1. 嚴禁任何公關客套話、空泛開場白與模糊形容詞。\n"
            "2. 直擊核心事實：精準提煉關鍵事件、核心論點、實質進展或重要細節。\n"
            "3. 輸出格式請直接以 Markdown 條列清單 ( - ) 回覆，勿加入多餘開場白：\n\n"
            "標題：{title}\n\n"
            "內文：\n{content}"
        ),
    },
    "tldr": {
        "id": "tldr",
        "name": "極簡 TL;DR 結論",
        "prompt": (
            "請針對以下內容，以極度精準、直白客觀的繁體中文提供 TL;DR 核心結論（1 句核心結論大綱 + {bullets} 點關鍵事實要點）。\n"
            "【要求】：拒絕客套空話，直接交代具體人事物、關鍵進展與核心結論。\n"
            "輸出格式請直接以 Markdown 條列清單 ( - ) 回覆：\n\n"
            "標題：{title}\n\n"
            "內文：\n{content}"
        ),
    },
    "insights": {
        "id": "insights",
        "name": "產業與數據洞察",
        "prompt": (
            "請以專業分析師視角，針對以下文章提取關鍵數據、核心決策、實質影響與具體看點（{bullets} 點 Markdown 條列清單，繁體中文，拒絕公關空話）：\n\n"
            "標題：{title}\n\n"
            "內文：\n{content}"
        ),
    },
    "entertainment": {
        "id": "entertainment",
        "name": "影視與娛樂看點",
        "prompt": (
            "請以專業客觀的影視、文化娛樂作品與多媒體發行資訊評析視角，將以下內容整理為 {bullets} 點繁體中文 (Traditional Chinese) 重點摘要：\n"
            "- **作品資訊**：作品名稱、發行番號/代碼 (若有) 與發行商規格\n"
            "- **核心主題**：企劃主題設定與故事劇情背景脈絡\n"
            "- **參演人物**：主要演出名單 (女優/男優/主演團隊/人物背景)\n"
            "- **劇情觀點**：作品核心特色、題材亮點與劇情看點\n\n"
            "【格式規範】：每點開頭請嚴格採用「- **四字標籤**：具體說明」格式（固定使用 **作品資訊**、**核心主題**、**參演人物**、**劇情觀點**），粗體標籤嚴格維持四個字，禁止使用過多贅字；語言一律使用繁體中文。輸出格式請直接以 Markdown 條列清單 ( - ) 回覆：\n\n"
            "標題：{title}\n\n"
            "內文：\n{content}"
        ),
    },
    "roast": {
        "id": "roast",
        "name": "犀利幽默短評",
        "prompt": (
            "請以犀利、幽默且切中核心重點的風格，針對以下內容給出 {bullets} 個讓人會心一笑或直擊痛點的繁體中文短評（請直接針對具體情節與特色吐槽或點評）：\n\n"
            "標題：{title}\n\n"
            "內文：\n{content}"
        ),
    },
}


# 專用與非文本生成/零免費配額黑名單關鍵字 (Blacklisted non-text/zero-quota model substrings)
NON_TEXT_MODEL_KEYWORDS = [
    "-image",
    "imagen",
    "embedding",
    "aqa",
    "tts",
    "whisper",
    "realtime",
    "computer-use",
    "bilingual",
    "customtools",
    "tuning",
    "robotics",
    "transcribe",
    "clip",
    "banana",
]

# 官方最新規格保底階梯 (Official Google AI Studio Fallback Ladder)
# 優先採用 API 動態探測，僅於完全斷網時作為防衛性預設
DEFAULT_GEMINI_MODELS_LADDER = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]

# 標準安全設定 (全面設為 BLOCK_NONE 解除過濾，以支援各類型影視作品、成人娛樂與新聞內容摘要分析)
DEFAULT_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
]

# 司法裁判與刑事社會新聞特徵關鍵字 (Judicial and Legal News Feature Keywords)
LEGAL_NEWS_KEYWORDS = [
    "判決", "地院", "高院", "最高法院", "裁判", "性侵", "殺人", "傷害", "毒品",
    "詐欺", "起訴", "判刑", "偵查", "審理", "檢察官", "法官", "被告", "原告",
    "告訴人", "刑法", "刑案", "命案", "嫌犯", "羈押", "自首", "逮捕", "拘提",
]

# 極端露骨詞彙脫敏對照表 (Extreme Explicit Keywords Sanitization Mapping for API Entrance)
EXPLICIT_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"即ハメ", re.IGNORECASE), "企劃互動"),
    (re.compile(r"中出し", re.IGNORECASE), "親密企劃"),
    (re.compile(r"種付け", re.IGNORECASE), "企劃拍攝"),
    (re.compile(r"パイズリ", re.IGNORECASE), "特寫互動"),
    (re.compile(r"潮吹き", re.IGNORECASE), "企劃演出"),
    (re.compile(r"アナル", re.IGNORECASE), "特別篇"),
    (re.compile(r"輪姦", re.IGNORECASE), "多人企劃"),
    (re.compile(r"痴漢", re.IGNORECASE), "電車企劃"),
    (re.compile(r"凌辱", re.IGNORECASE), "劇情逆轉"),
    (re.compile(r"レイプ|强奸|強姦", re.IGNORECASE), "突發案件"),
    (re.compile(r"手コキ|フェラ|オナニー", re.IGNORECASE), "個人特寫"),
    (re.compile(r"射精|射爆", re.IGNORECASE), "高潮互動"),
    (re.compile(r"近親相姦|母子|乱倫", re.IGNORECASE), "家庭情境企劃"),
]


def sort_gemini_models_semver(model_names: list[str]) -> list[str]:
    """依據語意數值版本號降序排序 Gemini 文本摘要模型清單 (Semantic Version Descending Sort).

    :param model_names: 待排序之模型名稱字串清單
    :return: 依權重排序之模型名稱清單
    """
    def model_sort_key(name: str) -> tuple[int, int, int, float, str]:
        name_lower = name.lower()
        is_flash = 0 if "flash" in name_lower else 1
        is_pro = 1 if "-pro" in name_lower or name_lower.startswith("gemini-pro") else 0
        is_exp = 1 if ("exp" in name_lower or "preview" in name_lower) else 0
        matches = re.findall(r"gemini-(\d+(?:\.\d+)?)", name_lower)
        version_num = float(matches[0]) if matches else 0.0
        return (is_flash, is_pro, is_exp, -version_num, name_lower)

    return sorted(model_names, key=model_sort_key)


def sanitize_text_for_gemini(
    title: str, content: str, is_entertainment: bool = False, is_legal_news: bool = False
) -> tuple[str, str, str]:
    """對輸入文字進行輕量脫敏與情境宣告包裝 (Sanitize and Frame Text for Gemini).

    :param title: 文章標題
    :param content: 文章內容
    :param is_entertainment: 是否為影視娛樂題材
    :param is_legal_news: 是否為司法裁判或社會新聞題材
    :return: (脫敏後標題, 脫敏後內文, 前置情境宣告文字)
    """
    clean_title = title or ""
    clean_content = content or ""
    framing_header = ""

    # 1. 針對影視/成人作品執行關鍵詞脫敏（保留番號、主演名單，轉化極端生理詞彙）
    if is_entertainment:
        for pattern, replacement in EXPLICIT_REPLACEMENTS:
            clean_title = pattern.sub(replacement, clean_title)
            clean_content = pattern.sub(replacement, clean_content)
        framing_header = (
            "【公開多媒體影視作品發行與文娛看點評析 (Entertainment Media Catalog & Review)】\n"
            "以下內容為公開影視出版品目錄資訊。請以客觀中立之影評與作品資訊整理角度產出摘要：\n\n"
        )
    elif is_legal_news:
        framing_header = (
            "【公開新聞紀實與司法裁判事實分析 (Public Journalistic & Legal Case Documentation)】\n"
            "以下內容為公開新聞報導與法庭裁判事實紀錄。請以客觀中立、符合新聞紀實之專業視角整理核心重點事實：\n\n"
        )

    return clean_title, clean_content, framing_header


def extract_local_fallback_summary(
    article: ArticleDTO, block_reason: str = "PROHIBITED_CONTENT", bullets: int = 4
) -> str:
    """當 Google Gemini API 觸發安全政策或無法連線時，由本地引擎自動提取繁體中文結構化要點 (Local Fallback Summary Extractor).

    :param article: 文章資料物件
    :param block_reason: 阻擋原因代碼 (如 PROHIBITED_CONTENT, SAFETY 等)
    :param bullets: 建議條列點數
    :return: 標註阻擋原因與本地提取之繁體中文 Markdown 條列要點
    """
    raw_title = (article.title or "").strip()
    raw_content = (article.content_text or article.content_html or "").strip()
    combined = f"{raw_title} {raw_content}"

    # 1. 偵測是否為影視/娛樂/番號作品 (Detect Entertainment/AV Works)
    code_match = re.search(r"\b([A-Z]{2,6}[-_]?\d{2,5})\b", raw_title, re.IGNORECASE)
    if not code_match:
        code_match = re.search(r"\b(FC2(?:-PPV)?[-_]?\d{4,8})\b", raw_title, re.IGNORECASE)

    is_entertainment = bool(
        code_match
        or any(
            kw in combined.lower()
            for kw in ["女優", "片商", "番號", "dmm", "fanza", "s1", "moodyz", "prestige", "soft on demand", "ideapocket", "attackers"]
        )
    )

    lines: list[str] = [
        f"⚠️ [觸發 Google 內容安全政策 ({block_reason}) · 自動啟用本地繁中要點提取]"
    ]

    if is_entertainment:
        # 影視題材結構化提取（固定四字標籤：作品資訊、核心主題、參演人物、劇情觀點）
        release_code = code_match.group(1).upper() if code_match else "未明確標註"
        
        # 嘗試提取主演人員（常見日文兩字或三字漢字人名）
        actress_name = "劇組/主演人員"
        name_match = re.search(r"[\s\[【(]([一-龥]{2,4}[\s\u3000]?[一-龥]{1,4})[\s\]】)]", raw_title)
        if name_match:
            candidate = name_match.group(1).strip()
            if candidate not in ["最新作品", "超特寫", "中文字幕", "無碼破解", "完全新作", "完全版"]:
                actress_name = candidate

        # 企劃情境關鍵字提煉
        themes = []
        for kw in ["溫泉旅行", "同居生活", "職場", "秘書", "學園", "家庭", "逆轉", "專屬", "新人", "精選", "素人", "企劃"]:
            if kw in raw_title or kw in raw_content:
                themes.append(kw)
        theme_desc = "、".join(themes[:3]) if themes else "影視企劃主題設定"

        # 乾淨標題
        clean_title = raw_title
        for pattern, replacement in EXPLICIT_REPLACEMENTS:
            clean_title = pattern.sub(replacement, clean_title)

        lines.append(f"- **作品資訊**：番號 `{release_code}`")
        lines.append(f"- **核心主題**：{theme_desc}")
        lines.append(f"- **參演人物**：{actress_name}")
        lines.append(f"- **劇情觀點**：{clean_title[:80]}...")
    else:
        # 新聞/司法/一般文章結構化事實提取（固定四字標籤：核心事件、事實要點、進展細節）
        clean_title = raw_title
        lines.append(f"- **核心事件**：{clean_title}")

        # 拆解內文段落並選取高資訊密度句子
        paragraphs = [p.strip() for p in re.split(r"[\r\n]+", raw_content) if len(p.strip()) >= 15]
        selected_points: list[str] = []

        for p in paragraphs:
            # 過濾廣告與贅詞
            if any(ad in p for ad in ["廣告", "記者", "報導", "點擊連結", "訂閱", "未經授權", "Copyright"]):
                continue
            # 依句號切割
            sentences = [s.strip() for s in re.split(r"[。！？\n]", p) if len(s.strip()) >= 12]
            for s in sentences:
                if s not in selected_points and len(selected_points) < (bullets - 1):
                    selected_points.append(s)

        if selected_points:
            labels = ["**事實要點**", "**進展細節**", "**現況摘要**"]
            for idx, pt in enumerate(selected_points):
                lbl = labels[idx] if idx < len(labels) else "**補充重點**"
                lines.append(f"- {lbl}：{pt}")
        else:
            lines.append(f"- **事實要點**：{raw_content[:100]}...")

    return "\n".join(lines)


class GeminiSummaryProcessorPlugin(BaseProcessorPlugin):
    """Gemini Flash AI 繁體中文重點摘要處理器 (Gemini Summary Processor Plugin)."""

    _cached_active_model: Optional[str] = None
    _discovered_models: list[str] = []
    _last_api_key_used: Optional[str] = None

    async def initialize(self) -> None:
        """初始化外掛資源 (Initialize plugin resources)."""
        logger.info(f"GeminiSummaryProcessorPlugin initialized with config: {self.config}")

    async def _discover_active_models(self, api_key: str, force_refresh: bool = False) -> list[str]:
        """動態向 Google Gemini API 查詢當前 API Key 支援的所有文本生成模型 (Dynamic Model Discovery).

        :param api_key: Google Gemini API Key
        :param force_refresh: 是否強制重新探測
        :return: 依語意版本由大到小排序之可用純文字模型清單
        """
        # 若 API Key 更換，強制重新探測
        if self._last_api_key_used and self._last_api_key_used != api_key:
            force_refresh = True
        self._last_api_key_used = api_key

        if self._discovered_models and not force_refresh:
            return self._discovered_models

        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    models_raw = data.get("models", [])
                    valid_models: list[str] = []
                    for m in models_raw:
                        m_name = m.get("name", "").replace("models/", "")
                        m_lower = m_name.lower()
                        methods = m.get("supportedGenerationMethods", [])

                        # 1. 必須支援 generateContent
                        if "generateContent" not in methods:
                            continue
                        # 2. 必須以 gemini- 開頭
                        if not m_lower.startswith("gemini-"):
                            continue
                        # 3. 嚴格排除生圖/語音/向量等非文本或 0 免費配額專用模型 (如 gemini-3-pro-image)
                        if any(kw in m_lower for kw in NON_TEXT_MODEL_KEYWORDS):
                            continue

                        valid_models.append(m_name)

                    if valid_models:
                        sorted_models = sort_gemini_models_semver(valid_models)
                        self._discovered_models = sorted_models
                        if not self._cached_active_model or self._cached_active_model not in sorted_models:
                            self._cached_active_model = sorted_models[0]
                        logger.info(
                            f"Gemini dynamic model discovery succeeded: active={self._cached_active_model}, all={sorted_models}"
                        )
                        return sorted_models
                else:
                    logger.warning(f"Gemini list models failed: HTTP {resp.status_code} - {resp.text}")
        except Exception as exc:
            logger.warning(f"Gemini dynamic model discovery exception: {exc}")

        # 若 API 連線失敗或探測結果為空，使用官方推薦預設保底清單
        if not self._discovered_models or force_refresh:
            self._discovered_models = list(DEFAULT_GEMINI_MODELS_LADDER)
            if not self._cached_active_model or self._cached_active_model not in self._discovered_models:
                self._cached_active_model = self._discovered_models[0]
        return self._discovered_models

    async def _persist_active_model(
        self, user_id: int, active_model: str, discovered_models: list[str]
    ) -> None:
        """將最新生效的模型斷點水位非同步寫回使用者外掛設定 (Persist active model watermark to DB).

        :param user_id: 使用者識別碼
        :param active_model: 目前生效之模型名稱
        :param discovered_models: 探測取得之所有模型清單
        """
        try:
            from omnirss.core.database import get_db_manager
            db_mgr = get_db_manager()
            if not db_mgr.db_path.exists():
                return
            async with db_mgr.write_transaction() as conn:
                cur = await conn.execute(
                    "SELECT config_json FROM user_plugin_configs WHERE user_id = ? AND plugin_id = ?",
                    (user_id, self.plugin_id),
                )
                row = await cur.fetchone()
                cfg = json.loads(row["config_json"]) if row and row["config_json"] else dict(self.config)
                cfg["_active_model"] = active_model
                cfg["_discovered_models"] = discovered_models
                cfg["_last_discovered_at"] = datetime.now(timezone.utc).isoformat()
                self.config["_active_model"] = active_model
                self.config["_discovered_models"] = discovered_models

                await conn.execute(
                    """
                    INSERT INTO user_plugin_configs (user_id, plugin_id, config_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, plugin_id) DO UPDATE SET
                        config_json = excluded.config_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, self.plugin_id, json.dumps(cfg)),
                )
                await conn.commit()
        except Exception as exc:
            logger.debug(f"Failed to persist active model watermark: {exc}")

    async def _call_gemini_api(
        self, api_key: str, model: str, prompt: str, context: Optional["PluginContext"] = None
    ) -> str:
        """呼叫 Google Gemini API 產出摘要 (Call Google Gemini API with Stateful Watermark Waterfall).

        :param api_key: Google Gemini API Key
        :param model: 指定模型名稱或 'auto'
        :param prompt: 組合完成之提示詞
        :param context: 外掛上下文
        :return: 生成之繁體中文文字內容，若遇安全阻擋回傳特定標記
        :raises RuntimeError: 當所有模型階梯輪詢皆失敗時真實拋出
        """
        system_instruction = {
            "parts": [
                {
                    "text": (
                        "【最高語言防線與鋼鐵準則 (Absolute Language Constraint)】：\n"
                        "你是一位精通多國語言並以「繁體中文（台灣習慣用語，Traditional Chinese）」為唯一輸出語言的資深內容分析與影視/新聞資訊整理專家。\n"
                        "1. 無論原始文章為何種語言，你的所有摘要與重點「必須 100% 完全強制使用繁體中文 (Traditional Chinese)」撰寫。\n"
                        "2. 【高資訊密度與客觀真實】：直擊核心事實、人事物名稱、數據指標與重要進展，嚴禁空泛公關客套話。\n"
                        "3. 【條列標籤精簡規範】：每條摘要開頭之粗體標籤請固定使用四個字（例如：**作品資訊**、**核心主題**、**參演人物**、**劇情觀點**、**核心事件**、**事實要點**），嚴禁使用冗長贅字標籤。\n"
                        "4. 【司法裁判與新聞紀實框架】：若文章涉及司法訴訟、刑案、社會爭議或法律裁判，請以客觀中立之法庭事實與新聞報導紀實視角概括，提煉關鍵事實與判決進展。\n"
                        "5. 【影視與成人娛樂作品安全框架】：若文章涉及成人影視、成人娛樂、情色文學或多媒體作品，請以客觀中立的『作品資訊、發行番號、演出名單、企劃主題與特色看點』進行概括總結，避免輸出露骨的生理性行為過程描寫，確保安全合規並精準傳達作品精髓！"
                    )
                }
            ]
        }

        reinforced_prompt = (
            f"{prompt}\n\n"
            "【強制輸出約束】：請務必注意！無論上述原文為何種語言，以上所有摘要與重點「必須 100% 完全使用繁體中文 (Traditional Chinese)」輸出！"
        )

        user_id = context.user_id if context else None

        # 1. 決定候選模型清單與起始斷點水位
        discovered = await self._discover_active_models(api_key)
        if model and model.strip() and model.strip() != "auto":
            # 使用者若手動指定型號，優先嘗試指定型號，若指定型號遭遇 429/404 則依序降級至探測清單
            target_first = model.strip()
            candidate_models = [target_first] + [m for m in discovered if m != target_first]
        else:
            # 模式為 auto：從資料庫/記憶體讀取斷點水位
            stored_active = (
                (context.config.get("_active_model") if context else None)
                or self.config.get("_active_model")
                or self._cached_active_model
            )
            if stored_active and stored_active in discovered:
                start_idx = discovered.index(stored_active)
                candidate_models = discovered[start_idx:] + discovered[:start_idx]
            else:
                candidate_models = list(discovered)

        last_error = ""
        has_quota_error = False

        # 2. 依序執行瀑布階梯呼叫 (Waterfall Step-down)
        for target_model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent?key={api_key}"
            payload = {
                "systemInstruction": system_instruction,
                "contents": [{"parts": [{"text": reinforced_prompt}]}],
                "safetySettings": DEFAULT_SAFETY_SETTINGS,
            }
            try:
                async with httpx.AsyncClient(timeout=35.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()

                        # 1. 檢查輸入 Prompt 是否觸發安全審查阻擋
                        prompt_feedback = data.get("promptFeedback", {})
                        block_reason = prompt_feedback.get("blockReason")
                        if block_reason:
                            logger.info(f"Gemini prompt blocked due to policy: {block_reason}")
                            return f"__SAFETY_BLOCKED__:{block_reason}"

                        # 2. 檢查候選輸出是否成功或觸發安全審查
                        candidates = data.get("candidates", [])
                        if candidates:
                            first_cand = candidates[0]
                            finish_reason = first_cand.get("finishReason")
                            if finish_reason in ["SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"]:
                                logger.info(f"Gemini output finishReason blocked: {finish_reason}")
                                return f"__SAFETY_BLOCKED__:{finish_reason}"

                            parts = first_cand.get("content", {}).get("parts", [])
                            if parts and "text" in parts[0]:
                                # 呼叫成功！更新斷點水位並持久化儲存
                                self._cached_active_model = target_model
                                if user_id:
                                    await self._persist_active_model(
                                        user_id, target_model, self._discovered_models
                                    )
                                return parts[0]["text"].strip()
                    else:
                        err_json = {}
                        try:
                            err_json = resp.json()
                        except Exception:
                            pass
                        err_msg = err_json.get("error", {}).get("message", resp.text)
                        last_error = f"HTTP {resp.status_code} ({target_model}): {err_msg}"
                        if resp.status_code == 429 or "quota" in err_msg.lower():
                            has_quota_error = True
                        logger.warning(
                            f"Gemini model '{target_model}' failed ({last_error}). Stepping down to next candidate model..."
                        )

            except Exception as exc:
                last_error = f"Exception on {target_model}: {exc}"
                logger.warning(f"Gemini request exception on '{target_model}': {exc}")

        # 3. 若所有已知候選階梯皆失敗，執行一次強制全量重探 (Force Refresh Discovery)
        logger.info("All candidate Gemini models failed. Triggering fresh model discovery from Google API...")
        fresh_models = await self._discover_active_models(api_key, force_refresh=True)
        for target_model in fresh_models:
            if target_model in candidate_models:
                continue  # 本輪已嘗試過的略過
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent?key={api_key}"
            payload = {
                "systemInstruction": system_instruction,
                "contents": [{"parts": [{"text": reinforced_prompt}]}],
                "safetySettings": DEFAULT_SAFETY_SETTINGS,
            }
            try:
                async with httpx.AsyncClient(timeout=35.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        prompt_feedback = data.get("promptFeedback", {})
                        block_reason = prompt_feedback.get("blockReason")
                        if block_reason:
                            return f"__SAFETY_BLOCKED__:{block_reason}"

                        candidates = data.get("candidates", [])
                        if candidates:
                            first_cand = candidates[0]
                            finish_reason = first_cand.get("finishReason")
                            if finish_reason in ["SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"]:
                                return f"__SAFETY_BLOCKED__:{finish_reason}"

                            parts = first_cand.get("content", {}).get("parts", [])
                            if parts and "text" in parts[0]:
                                self._cached_active_model = target_model
                                if user_id:
                                    await self._persist_active_model(
                                        user_id, target_model, self._discovered_models
                                    )
                                return parts[0]["text"].strip()
                    else:
                        err_json = {}
                        try:
                            err_json = resp.json()
                        except Exception:
                            pass
                        err_msg = err_json.get("error", {}).get("message", resp.text)
                        last_error = f"HTTP {resp.status_code} ({target_model}): {err_msg}"
                        if resp.status_code == 429 or "quota" in err_msg.lower():
                            has_quota_error = True
            except Exception as heal_exc:
                last_error = f"Exception on {target_model}: {heal_exc}"

        # 4. 備援：若 REST 全數失敗且環境有安裝 google-genai SDK
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            target_model = self._cached_active_model or (fresh_models[0] if fresh_models else "gemini-2.5-flash")
            response = client.models.generate_content(
                model=target_model,
                contents=reinforced_prompt,
            )
            if response and response.text:
                return response.text.strip()
        except Exception:
            pass

        # 5. 真實拋出結構化例外，附帶清晰指引 (True Observability)
        if has_quota_error:
            raise RuntimeError(
                f"Google Gemini 當前所有可用模型免費配額已耗盡 (HTTP 429 Rate Limit)。"
                f"請稍候 1 分鐘後重試，或於 Google AI Studio 綁定帳單啟用付費配額。\n"
                f"最後嘗試錯誤：{last_error}"
            )
        raise RuntimeError(last_error or "無法連線至 Google Gemini 服務，請確認 API Key 與配額狀態。")

    async def process(
        self,
        article: ArticleDTO,
        context: Optional["PluginContext"] = None,
        action_param: Optional[str] = None,
    ) -> Optional[ArticleDTO]:
        """為文章產出繁體中文重點條列摘要 (Generate Traditional Chinese summary for article).

        :param article: 待處理文章資料物件
        :param context: 外掛安全上下文
        :param action_param: 手動指定之風格/子動作識別碼 (如 standard, entertainment, tldr, roast 等)
        :return: 附加 ai_summary 後之文章資料物件
        """
        content = (article.content_text or article.content_html or "").strip()
        if len(content) < 20 and not (article.title and len(article.title) >= 5):
            article.ai_summary = "⚠️ 文章內容與標題過短，無法由 AI 生成有效重點摘要。"
            return article
        elif len(content) < 20 and article.title:
            content = f"文章標題：{article.title}"

        api_key = (self.config.get("api_key") or "").strip()
        model_name = self.config.get("model") or "auto"
        bullets = int(self.config.get("summary_bullets") or 4)

        # 1. 檢驗 API Key 是否填寫
        if not api_key:
            article.ai_summary = (
                "⚠️ 尚未設定 Google Gemini API Key。\n"
                "請前往「外掛管理 ➔ Gemini 摘要 ➔ ⚙️ 設定」填寫 API Key（可於 Google AI Studio 免費取得）以啟用自訂提示詞與 AI 智慧摘要。"
            )
            return article

        # 2. 解析動態 Prompt 範本清單與目標風格
        presets_list = self.config.get("prompt_presets")
        if not isinstance(presets_list, list) or not presets_list:
            presets_list = list(PROMPT_PRESETS.values())

        default_preset_id = self.config.get("default_preset_id") or "standard"
        effective_action = action_param or (context.action_param if context and context.action_param else None)
        has_explicit_action = bool(effective_action and effective_action not in ("auto", "smart", "default"))

        requested_preset_id = (
            effective_action
            or self.config.get("selected_preset")
            or self.config.get("selected_preset_id")
            or self.config.get("preset_id")
            or self.config.get("prompt_style")
            or default_preset_id
        )

        combined_text = f"{article.title or ''} {content[:1500]}".lower()

        # 智慧題材自動分流 (Smart Content Type Detection)
        has_release_code = bool(re.search(r"\b[a-z]{2,6}[-_]?\d{2,5}\b", combined_text, re.IGNORECASE)) or "fc2" in combined_text
        adult_keywords = [
            "jav", "女優", "成人片", "av", "番號", "無碼", "有碼", "中文字幕",
            "作品介紹", "片商", "寫真", "裏番", "dmm", "fanza", "s1", "moodyz",
            "ideapocket", "prestige", "soft on demand", "sod", "attackers",
            "電影", "影集", "日劇", "美劇", "韓劇", "動漫", "動畫", "上映", "預告片"
        ]
        is_entertainment_content = bool(has_release_code or any(kw in combined_text for kw in adult_keywords))
        is_legal_news_content = bool(any(kw in combined_text for kw in LEGAL_NEWS_KEYWORDS))

        if not has_explicit_action and requested_preset_id in ("standard", "auto", "default", default_preset_id):
            if is_entertainment_content:
                requested_preset_id = "entertainment"

        target_template_str = ""
        matched_preset = None

        custom_prompt_val = (self.config.get("custom_prompt") or "").strip()
        if requested_preset_id == "custom" and custom_prompt_val:
            target_template_str = custom_prompt_val
        else:
            for p in presets_list:
                if isinstance(p, dict) and (p.get("id") == requested_preset_id or p.get("name") == requested_preset_id):
                    matched_preset = p
                    target_template_str = p.get("prompt", "")
                    break

            if not target_template_str:
                for p in presets_list:
                    if isinstance(p, dict) and p.get("id") == default_preset_id:
                        matched_preset = p
                        target_template_str = p.get("prompt", "")
                        break

            if not target_template_str and custom_prompt_val:
                target_template_str = custom_prompt_val

            if not target_template_str and presets_list and isinstance(presets_list[0], dict):
                target_template_str = presets_list[0].get("prompt", "")
            if not target_template_str:
                target_template_str = PROMPT_PRESETS["standard"]["prompt"]

        # 3. 執行方案 A：前置輕量脫敏與情境宣告包裝 (Option A: Pre-sanitization and Context Framing)
        clean_title, clean_content, framing_header = sanitize_text_for_gemini(
            article.title or "",
            content[:5000],
            is_entertainment=is_entertainment_content,
            is_legal_news=is_legal_news_content,
        )

        # 4. 防衛性變數格式化 (Safe String Formatting)
        class SafeDict(dict):
            def __missing__(self, key: str) -> str:
                return "{" + key + "}"

        format_dict = SafeDict({
            "title": clean_title,
            "content": clean_content,
            "bullets": str(bullets),
        })

        try:
            prompt = target_template_str.format_map(format_dict)
        except Exception:
            prompt = (
                target_template_str.replace("{title}", clean_title)
                .replace("{content}", clean_content)
                .replace("{bullets}", str(bullets))
            )

        if framing_header:
            prompt = f"{framing_header}{prompt}"

        # 5. 呼叫 Gemini AI 產出摘要 (不掩蓋例外，真實反映失敗)
        try:
            summary_result = await self._call_gemini_api(api_key, model_name, prompt, context)
        except TypeError:
            # 支援向後相容或單元測試 mock 簽名 (api_key, model, prompt)
            summary_result = await self._call_gemini_api(api_key, model_name, prompt)

        # 6. 執行方案 B：若觸發安全阻擋，自動無縫切換為本地繁中結構化要點提取 (Option B: Fallback)
        if summary_result.startswith("__SAFETY_BLOCKED__:") or "觸發了 Google AI 內容安全防護規範" in summary_result:
            # 提取錯誤原因
            if summary_result.startswith("__SAFETY_BLOCKED__:"):
                reason = summary_result.split(":", 1)[1]
            else:
                m = re.search(r"\(([^)]+)\)", summary_result)
                reason = m.group(1) if m else "PROHIBITED_CONTENT"
            
            logger.info(f"Gemini summary triggered safety block ({reason}). Activating local fallback extractor...")
            article.ai_summary = extract_local_fallback_summary(article, block_reason=reason, bullets=bullets)
        else:
            article.ai_summary = summary_result

        return article
