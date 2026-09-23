"""後端多國語系引擎 (Backend Internationalization Engine).

This module manages localized string dictionary loading and translation rendering for error messages and logs.
"""

import json
from pathlib import Path
from typing import Any, Optional
from loguru import logger

_TRANSLATIONS: dict[str, dict[str, str]] = {}
_DEFAULT_LOCALE = "zh-TW"


def load_locales(locales_dir: Optional[str | Path] = None) -> None:
    """載入語系字典檔 (Load translation JSON files from locales directory).

    :param locales_dir: 語系目錄路徑；若為 None 則使用專案內建 locales/
    """
    global _TRANSLATIONS

    if locales_dir is None:
        target_dir = Path(__file__).resolve().parents[3] / "locales"
    else:
        target_dir = Path(locales_dir)

    if not target_dir.is_dir():
        logger.warning(f"Locales directory not found: {target_dir}")
        return

    loaded: dict[str, dict[str, str]] = {}
    for json_file in target_dir.glob("*.json"):
        locale_name = json_file.stem
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                loaded[locale_name] = json.load(f)
        except Exception as exc:
            logger.error(f"Failed to load locale file {json_file}: {exc}")

    _TRANSLATIONS = loaded


def t(key: str, locale: str = _DEFAULT_LOCALE, **kwargs: Any) -> str:
    """取得本地化文字 (Translate key into localized text).

    :param key: 字典鍵值 (Translation key)
    :param locale: 目標語系代碼 (Target locale code, e.g. 'zh-TW', 'en-US')
    :param kwargs: 動態插值參數 (Dynamic string format arguments)
    :return: 渲染後的本地化文字 (Translated and interpolated string)
    """
    if not _TRANSLATIONS:
        load_locales()

    dict_for_locale = _TRANSLATIONS.get(locale) or _TRANSLATIONS.get(_DEFAULT_LOCALE, {})
    text = dict_for_locale.get(key, key)

    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text

    return text
