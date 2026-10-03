/**
 * OmniRSS 全域擴充插槽與前端外掛註冊中心 (Global UI Plugin Slots & Registry).
 *
 * Provides standardized extensibility points across the 4 major UI zones:
 * 1. Tree View (smart folders, custom node badges, context actions)
 * 2. List View (custom columns, header actions, row badges)
 * 3. Reader View (toolbar actions, info panels, content transformers)
 * 4. Status Bar (custom indicator widgets, background tasks)
 */

import { store } from "./state.js";
import { t } from "./i18n.js";

export const OFFICIAL_GEMINI_PRESETS = [
  {
    id: "standard",
    name: "標準重點條列",
    is_builtin: true,
    prompt: "請針對以下文章內容，以繁體中文 (Traditional Chinese, 台灣習慣用語) 產出 {bullets} 點客觀且高資訊密度的重點摘要。\n輸出格式請直接以 Markdown 條列清單 ( - ) 回覆，勿加入多餘前綴開場白：\n\n標題：{title}\n\n內文：\n{content}"
  },
  {
    id: "tldr",
    name: "極簡 TL;DR 結論",
    is_builtin: true,
    prompt: "請針對以下文章，以極度精準、簡明扼要的繁體中文提供 TL;DR 核心結論（1~2 句總結 + {bullets} 點核心事實）：\n輸出格式請直接以 Markdown 條列清單 ( - ) 回覆：\n\n標題：{title}\n\n內文：\n{content}"
  },
  {
    id: "insights",
    name: "產業與數據洞察",
    is_builtin: true,
    prompt: "請以產業分析師視角，針對以下文章提取關鍵數據、核心趨勢與實質影響（{bullets} 點 Markdown 條列清單，繁體中文）：\n\n標題：{title}\n\n內文：\n{content}"
  },
  {
    id: "entertainment",
    name: "影視與娛樂看點",
    is_builtin: true,
    prompt: "請針對以下影視/娛樂作品或介紹文章，以繁體中文 (Traditional Chinese) 提煉出 {bullets} 個核心重點與看點精華（包括作品特色、核心亮點與主要風格）：\n輸出格式請直接以 Markdown 條列清單 ( - ) 回覆：\n\n標題：{title}\n\n內文：\n{content}"
  },
  {
    id: "roast",
    name: "犀利幽默短評",
    is_builtin: true,
    prompt: "請以毒舌、幽默但切中要害的犀利風格，針對以下內容進行繁體中文短評，給出 {bullets} 個讓人會心一笑或直擊痛點的點評：\n\n標題：{title}\n\n內文：\n{content}"
  }
];

class PluginRegistry {
  constructor() {
    this.slots = {
      // 1. Reader Slots
      "reader:toolbar": new Map(),
      "reader:panels": new Map(),
      "reader:transformers": new Map(),

      // 2. List Slots
      "list:columns": new Map(),
      "list:header_actions": new Map(),
      "list:row_badges": new Map(),

      // 3. Tree Slots
      "tree:smart_folders": new Map(),
      "tree:actions": new Map(),

      // 4. Statusbar Slots
      "statusbar:widgets": new Map(),
    };

    this.initDefaultSlots();
  }

  /**
   * 初始化系統預設插槽定義
   */
  initDefaultSlots() {
    // === 預設清單欄位 (Default List Columns) ===
    this.registerListColumn({
      id: "status",
      label: "columns.status",
      defaultVisible: true,
      minWidth: "20px",
      renderHeader: () => "●",
      renderCell: (art) => {
        const isUnread = art.is_read === false || art.is_read === 0 || art.is_unread === true;
        return `<div class="col-cell col-status">${isUnread ? '<span class="unread-dot"></span>' : ""}</div>`;
      },
    });

    this.registerListColumn({
      id: "star",
      label: "columns.star",
      defaultVisible: true,
      minWidth: "24px",
      renderHeader: () => "★",
      renderCell: (art) => {
        const isStarred = art.is_starred === true;
        return `
          <div class="col-cell col-star">
            <button class="star-btn ${isStarred ? "starred" : ""}" title="★">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="${isStarred ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2">
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
              </svg>
            </button>
          </div>`;
      },
    });

    this.registerListColumn({
      id: "title",
      label: "columns.title",
      defaultVisible: true,
      sortField: "title",
      minWidth: "150px",
      renderHeader: (label, sortIcon) => `${label} ${sortIcon}`,
      renderCell: (art, escapeFn) => {
        const titleText = escapeFn(art.title || t("common.untitled"));
        const author = (art.author || "").trim();
        const feedTitle = (art.feed_title || "").trim();
        const cols = store.get("columns") || {};
        const isAuthorColVisible = cols.author !== false;
        // 當獨立作者欄未開啟時，若文章具有作者且不等於頻道名稱，智慧於標題後方附加作者標籤
        const showInlineAuthor = !isAuthorColVisible && author && author.toLowerCase() !== feedTitle.toLowerCase();
        const authorBadge = showInlineAuthor
          ? `<span class="inline-author-badge" title="${t("columns.author_title", { author: escapeFn(author) })}"><span class="author-icon">✍️</span>${escapeFn(author)}</span>`
          : "";

        const applied = art.applied_plugins || [];
        const pluginBadges = applied.length > 0
          ? applied
              .map((pId) => {
                // 從 store 動態查詢外掛的 badge 元資料，完全移除硬編碼字典
                const allPlugins = store.get("plugins") || [];
                const pluginObj = allPlugins.find((p) => (p.plugin_id || p.id) === pId);
                const badge = pluginObj && pluginObj.badge;
                const shortName = badge ? badge.short_name : (pluginObj ? (pluginObj.name && typeof pluginObj.name === "object" ? Object.values(pluginObj.name)[0] : pluginObj.name) : pId.split("/")[1] || pId);
                const icon = badge ? badge.icon : "🧩";
                const color = badge ? badge.color : "#60a5fa";
                return `<span class="inline-plugin-badge" title="已套用 ${escapeFn(shortName)} 外掛增強" style="font-size: 10px; margin-left: 4px; padding: 0 4px; border-radius: 3px; background: rgba(255,255,255,0.08); color: ${color}; font-weight: 600;">${icon}${shortName}</span>`;
              })
              .join("")
          : "";

        return `<div class="col-cell col-title" title="${escapeFn(art.title || "")}"><span class="title-text">${titleText}</span>${pluginBadges}${authorBadge}</div>`;
      },
    });

    this.registerListColumn({
      id: "actions",
      label: "columns.actions",
      defaultVisible: false,
      minWidth: "135px",
      renderHeader: (label) => `<div class="col-cell col-actions" style="font-weight:600; padding: 0 4px;" title="${label}">${label || t("columns.actions")}</div>`,
      renderCell: (art, escapeFn) => {
        const isUnread = art.is_read === false || art.is_read === 0 || art.is_unread === true;
        const isTrash = Boolean(art.is_trash);
        return `
          <div class="col-cell col-actions">
            <div class="row-actions-capsule" style="display: inline-flex; align-items: center; gap: 4px;">
              <button type="button" class="btn-row-action btn-row-tag" data-action="tag" title="${t("actions.set_tags")}" style="padding: 1px 4px; font-size: 11px; border-radius: 3px; border: 1px solid var(--border-color); background: var(--bg-surface); cursor: pointer;">🏷️</button>
              <button type="button" class="btn-row-action btn-row-fetch" data-action="fetch-full" title="${t("actions.fetch_full")}" style="padding: 1px 4px; font-size: 11px; border-radius: 3px; border: 1px solid var(--border-color); background: var(--bg-surface); cursor: pointer;">⚡</button>
              <button type="button" class="btn-row-action btn-row-open" data-action="open-url" title="${t("actions.open_tab")}" style="padding: 1px 4px; font-size: 11px; border-radius: 3px; border: 1px solid var(--border-color); background: var(--bg-surface); cursor: pointer;">🔗</button>
              <button type="button" class="btn-row-action btn-row-trash" data-action="trash" title="${isTrash ? t("actions.restore") : t("actions.trash")}" style="padding: 1px 4px; font-size: 11px; border-radius: 3px; border: 1px solid var(--border-color); background: var(--bg-surface); cursor: pointer;">${isTrash ? '↩️' : '🗑️'}</button>
              <button type="button" class="btn-row-action btn-row-read" data-action="toggle-read" title="${isUnread ? t("actions.mark_read") : t("actions.mark_unread")}" style="padding: 1px 4px; font-size: 11px; border-radius: 3px; border: 1px solid var(--border-color); background: var(--bg-surface); cursor: pointer;">${isUnread ? '✓' : '●'}</button>
            </div>
          </div>`;
      },
    });

    this.registerListColumn({
      id: "feed",
      label: "columns.feed",
      defaultVisible: true,
      sortField: "feed_title",
      minWidth: "100px",
      renderHeader: (label, sortIcon) => `${label} ${sortIcon}`,
      renderCell: (art, escapeFn) => {
        const feedTitle = escapeFn(art.feed_title || "");
        const feedId = art.feed_id || "";
        const dupBadge = art.duplicate_feeds && art.duplicate_feeds.length > 0
          ? `<span class="duplicate-feeds-badge" title="${t("columns.duplicate_feeds_hint", { feeds: escapeFn(art.duplicate_feeds.join(", ")) }) || ("同時來自：" + escapeFn(art.duplicate_feeds.join(", ")))}" style="font-size: 10px; opacity: 0.8; margin-left: 4px; padding: 1px 4px; border-radius: 3px; background: rgba(125,125,125,0.15); font-weight: 500;">+${art.duplicate_feeds.length}</span>`
          : "";
        return `<div class="col-cell col-feed feed-name" title="${feedTitle} (${t("columns.click_filter_feed")})"><span class="feed-name-link clickable-feed-filter" data-feed-id="${feedId}">${feedTitle}</span>${dupBadge}</div>`;
      },
    });

    this.registerListColumn({
      id: "date",
      label: "columns.date",
      defaultVisible: true,
      sortField: "published_at",
      minWidth: "80px",
      renderHeader: (label, sortIcon) => `${label} ${sortIcon}`,
      renderCell: (art, _, dateStr) => {
        return `<div class="col-cell col-date text-muted">${dateStr}</div>`;
      },
    });

    this.registerListColumn({
      id: "author",
      label: "columns.author",
      defaultVisible: true,
      sortField: "author",
      minWidth: "70px",
      renderHeader: (label, sortIcon) => `${label} ${sortIcon}`,
      renderCell: (art, escapeFn) => {
        return `<div class="col-cell col-author text-muted">${escapeFn(art.author || "")}</div>`;
      },
    });

    this.registerListColumn({
      id: "tags",
      label: "columns.tags",
      defaultVisible: false,
      minWidth: "90px",
      renderHeader: (label) => label,
      renderCell: (art, escapeFn) => {
        const badges = (art.tags || [])
          .filter((tagItem) => {
            if (!tagItem) return false;
            const name = typeof tagItem === "object" ? tagItem.name : tagItem;
            return name && name !== "null" && name !== "undefined";
          })
          .map((tagItem) => {
            const isObj = typeof tagItem === "object" && tagItem !== null;
            const name = isObj ? tagItem.name : tagItem;
            const color = isObj && tagItem.color ? tagItem.color : "#3b82f6";
            const id = isObj && tagItem.id ? tagItem.id : "";
            return `<span class="tag-badge-sm clickable-tag" data-tag-id="${id}" data-tag-name="${escapeFn(name)}" style="background-color: ${color}22; border-color: ${color}55; color: ${color};"><span class="tag-dot" style="background-color: ${color};"></span>${escapeFn(name)}</span>`;
          })
          .join("");
        return `<div class="col-cell col-tags">${badges}</div>`;
      },
    });

    // === 預設閱讀器工具列動作 (Default Reader Toolbar Actions) ===
    this.registerReaderAction({
      id: "star",
      label: "reader.star",
      activeLabel: "reader.unstar",
      icon: (isStarred) => `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="${isStarred ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2">
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
        </svg>`,
      isActive: (art) => art.is_starred === true,
      text: (isStarred, t) => isStarred ? t("reader.unstar") : t("reader.star"),
      handler: "toggle-star",
    });

    this.registerReaderAction({
      id: "toggle_read",
      label: "reader.mark_read",
      activeLabel: "reader.mark_unread",
      icon: () => `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="20 6 9 17 4 12"/>
        </svg>`,
      isActive: (art) => !(art.is_read === false || art.is_read === 0 || art.is_unread === true),
      text: (isRead, t) => isRead ? t("reader.mark_unread") : t("reader.mark_read"),
      handler: "toggle-read",
    });

    this.registerReaderAction({
      id: "trash",
      label: "reader.trash",
      activeLabel: "reader.restore",
      icon: (isTrash) => isTrash ? `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>
        </svg>` : `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
        </svg>`,
      isActive: (art) => Boolean(art.is_trash),
      text: (isTrash, t) => isTrash ? t("reader.restore") : t("reader.trash"),
      handler: "trash-article",
    });

    this.registerReaderAction({
      id: "fetch_full",
      label: "reader.fetch_full",
      icon: () => `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
        </svg>`,
      text: (_, t) => t("reader.fetch_full"),
      handler: "fetch-full",
    });

    this.registerReaderAction({
      id: "copy_link",
      label: "reader.copy_link",
      icon: () => `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
        </svg>`,
      text: (_, t) => t("reader.copy_link"),
      handler: "copy-link",
    });

    this.registerReaderAction({
      id: "open_url",
      label: "reader.open_original",
      icon: () => `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
        </svg>`,
      text: (_, t) => t("reader.open_original"),
      handler: "open-url",
    });
  }

  // === List Column Extension API ===
  registerListColumn(def) {
    if (!def.id) throw new Error("List column definition requires 'id'.");
    this.slots["list:columns"].set(def.id, def);
  }

  getListColumn(id) {
    return this.slots["list:columns"].get(id);
  }

  getAllListColumns() {
    return Array.from(this.slots["list:columns"].values());
  }

  // === Reader Action Extension API ===
  registerReaderAction(def) {
    if (!def.id) throw new Error("Reader action definition requires 'id'.");
    this.slots["reader:toolbar"].set(def.id, def);
  }

  getReaderAction(id) {
    return this.slots["reader:toolbar"].get(id);
  }

  getAllReaderActions() {
    return Array.from(this.slots["reader:toolbar"].values());
  }

  // === Reader Info Panel Extension API ===
  registerReaderPanel(def) {
    if (!def.id) throw new Error("Reader panel definition requires 'id'.");
    this.slots["reader:panels"].set(def.id, def);
  }

  getAllReaderPanels() {
    return Array.from(this.slots["reader:panels"].values());
  }
}

export const pluginRegistry = new PluginRegistry();
