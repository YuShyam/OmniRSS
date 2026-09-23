/**
 * OmniRSS 前端多國語系引擎 (Client-side i18n Engine).
 *
 * Supports instant language switching between Traditional Chinese and English
 * without requiring a full page refresh.
 */

import { store } from "./state.js";

const TRANSLATIONS = {
  "zh-TW": {
    "app.title": "OmniRSS",
    "app.tagline": "高密度現代微核心 RSS 閱讀器",
    "nav.all_feeds": "所有訂閱",
    "nav.starred": "星號收藏",
    "nav.unread": "未讀文章",
    "nav.trash": "垃圾桶",
    "nav.plugins": "外掛中心",
    "nav.rules": "過濾規則",
    "nav.settings": "系統設定",
    "nav.logout": "登出",
    "nav.quiet_mode": "寧靜模式",
    "tree.subscriptions": "訂閱目錄樹",
    "tree.add_feed": "新增訂閱",
    "tree.add_category": "新增分類",
    "tree.refresh_all": "全部重新整理",
    "tree.mark_all_read": "標為已讀",
    "tree.import_export": "OPML 匯出/匯入",
    "tree.uncategorized": "未分類訂閱",
    "columns.status": "狀態",
    "columns.star": "★",
    "columns.title": "標題",
    "columns.feed": "來源頻道",
    "columns.date": "發布時間",
    "columns.author": "作者",
    "columns.tags": "標籤",
    "columns.picker_title": "自選欄位顯示",
    "reader.no_selection": "請從上方列表選擇文章開始閱讀",
    "reader.open_original": "在新分頁開啟原文",
    "reader.copy_link": "複製文章連結",
    "reader.mark_read": "標為已讀",
    "reader.mark_unread": "標為未讀",
    "reader.star": "星號收藏",
    "reader.ai_summary": "Gemini AI 繁中重點摘要",
    "reader.ai_generating": "AI 深度摘要生成中...",
    "plugins.title": "外掛管理與效能監控儀表板",
    "plugins.active": "正常運行中",
    "plugins.tripped": "⚠️ 自動熔斷 (Tripped)",
    "plugins.reset_circuit": "重置熔斷",
    "rules.title": "QuiteRSS 智慧過濾與規則引擎",
    "rules.add": "新增過濾規則",
    "settings.title": "偏好與中繼金鑰設定",
    "settings.theme": "外觀主題",
    "settings.theme_dark": "暗黑模式 (QuiteRSS Dark)",
    "settings.theme_light": "明亮模式 (Modern Light)",
    "settings.theme_midnight": "午夜藍 (Midnight Blue)",
    "settings.api_key": "個人專屬 API Key (中繼與剪藏鑑權)",
    "settings.regen_key": "重新生成金鑰",
    "settings.copied": "已複製至剪貼簿",
    "hotkeys.title": "QuiteRSS / Vim 鍵盤快捷鍵指南",
  },
  "en-US": {
    "app.title": "OmniRSS",
    "app.tagline": "High-Density Modern Microkernel RSS Reader",
    "nav.all_feeds": "All Feeds",
    "nav.starred": "Starred",
    "nav.unread": "Unread",
    "nav.trash": "Trash",
    "nav.plugins": "Plugins",
    "nav.rules": "Rules",
    "nav.settings": "Settings",
    "nav.logout": "Logout",
    "nav.quiet_mode": "Quiet Mode",
    "tree.subscriptions": "Subscriptions Tree",
    "tree.add_feed": "Add Feed",
    "tree.add_category": "New Folder",
    "tree.refresh_all": "Refresh All",
    "tree.mark_all_read": "Mark All as Read",
    "tree.import_export": "OPML Import/Export",
    "tree.uncategorized": "Uncategorized",
    "columns.status": "Status",
    "columns.star": "★",
    "columns.title": "Title",
    "columns.feed": "Feed",
    "columns.date": "Date",
    "columns.author": "Author",
    "columns.tags": "Tags",
    "columns.picker_title": "Column Selection",
    "reader.no_selection": "Select an article from the list above to start reading",
    "reader.open_original": "Open Original in New Tab",
    "reader.copy_link": "Copy Article URL",
    "reader.mark_read": "Mark Read",
    "reader.mark_unread": "Mark Unread",
    "reader.star": "Star Article",
    "reader.ai_summary": "Gemini AI Summary",
    "reader.ai_generating": "Generating AI summary...",
    "plugins.title": "Plugin Center & Observability Dashboard",
    "plugins.active": "Active & Healthy",
    "plugins.tripped": "⚠️ Tripped",
    "plugins.reset_circuit": "Reset Circuit",
    "rules.title": "QuiteRSS Filter Rules Engine",
    "rules.add": "Add Rule",
    "settings.title": "Preferences & API Keys",
    "settings.theme": "Appearance Theme",
    "settings.theme_dark": "QuiteRSS Dark",
    "settings.theme_light": "Modern Light",
    "settings.theme_midnight": "Midnight Blue",
    "settings.api_key": "Personal API Key (Edge Relay & Web Clipper)",
    "settings.regen_key": "Regenerate Key",
    "settings.copied": "Copied to clipboard",
    "hotkeys.title": "Keyboard Shortcuts Cheatsheet",
  },
};

export function t(key, fallback = "") {
  const currentLang = store.get("lang") || "zh-TW";
  const dict = TRANSLATIONS[currentLang] || TRANSLATIONS["zh-TW"];
  return dict[key] || fallback || key;
}

export function updateDomTranslations() {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    if (key) {
      el.textContent = t(key);
    }
  });

  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    if (key) {
      el.setAttribute("placeholder", t(key));
    }
  });

  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    const key = el.getAttribute("data-i18n-title");
    if (key) {
      el.setAttribute("title", t(key));
    }
  });
}
