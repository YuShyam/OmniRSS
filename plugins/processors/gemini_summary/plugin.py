"""Gemini Flash AI 動態模型繁中重點摘要外掛 (Gemini Summary Processor Plugin).

This plugin analyzes article content and generates 3-5 structured bullet points in Traditional Chinese
using Google's official GenAI SDK with graceful fallbacks and cold storage metadata enrichment.
"""

from typing import Optional, TYPE_CHECKING
from loguru import logger
from omnirss.sdk.base_plugin import BaseProcessorPlugin
from omnirss.sdk.models import ArticleDTO

if TYPE_CHECKING:
    from omnirss.sdk.context import PluginContext


class GeminiSummaryProcessorPlugin(BaseProcessorPlugin):
    """Gemini Flash AI 繁體中文重點摘要處理器 (Gemini Summary Processor Plugin)."""

    async def initialize(self) -> None:
        """初始化外掛資源 (Initialize plugin resources)."""
        logger.info(f"GeminiSummaryProcessorPlugin initialized with config: {self.config}")

    async def process(
        self, article: ArticleDTO, context: Optional["PluginContext"] = None
    ) -> Optional[ArticleDTO]:
        """為文章產出繁體中文重點條列摘要 (Generate Traditional Chinese summary for article).

        :param article: 待處理文章資料物件
        :param context: 外掛安全上下文
        :return: 附加 ai_summary 後之文章資料物件
        """
        # 若已有 AI 摘要則略過
        if article.ai_summary and article.ai_summary.strip():
            return article

        content = (article.content_text or "").strip()
        if not content and article.content_html:
            import re
            content = re.sub(r"<[^>]+>", " ", article.content_html).strip()

        if len(content) < 50:
            return article

        api_key = self.config.get("api_key") or ""
        model_name = self.config.get("model") or "auto"
        bullets = int(self.config.get("summary_bullets") or 4)

        summary_text: Optional[str] = None

        if api_key:
            try:
                # 嘗試呼叫 google-genai 官方 SDK
                from google import genai
                client = genai.Client(api_key=api_key)
                target_model = "gemini-1.5-flash" if model_name in ("auto", "") else model_name

                prompt = (
                    f"請針對以下文章內容，以繁體中文 (Traditional Chinese, 台灣習慣用語) 產出 {bullets} 點客觀且高資訊密度的重點摘要。\n"
                    f"輸出格式請直接以 Markdown 條列清單 ( - ) 回覆，勿加入多餘前綴開場白：\n\n"
                    f"標題：{article.title}\n\n"
                    f"內文：\n{content[:4000]}"
                )

                response = client.models.generate_content(
                    model=target_model,
                    contents=prompt,
                )
                if response and response.text:
                    summary_text = response.text.strip()
            except Exception as exc:
                logger.warning(f"Gemini API call failed, falling back to local extractor: {exc}")

        # 若無 API Key 或呼叫失敗，產出智慧型段落摘要 fallback
        if not summary_text:
            sentences = [s.strip() for s in content.replace("\r", "\n").split("\n") if len(s.strip()) > 20]
            if not sentences:
                import re
                sentences = [s.strip() for s in re.split(r"[。！？]", content) if len(s.strip()) > 15]

            selected = sentences[:bullets]
            if selected:
                summary_text = "\n".join([f"- {s}" for s in selected])

        if summary_text:
            article.ai_summary = summary_text

        return article
