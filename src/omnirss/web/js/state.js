/**
 * OmniRSS 響應式狀態管理模組 (Centralized Reactive State Store).
 *
 * Manages global application state, active selections, filter modes,
 * column visibility, and in-memory preferences (SSOT backed by DB).
 */

export const DEFAULT_STATE = {
  // Authentication & Session
  user: null,
  token: null,
  theme: "dark",
  lang: "zh-TW",
  timezone: "auto",
  quietMode: false,

  // Reading Behavior & Preferences (Default to un-intrusive safe values)
  readDelaySec: 3,
  hideEmptyFeeds: false, // 預設不隱藏無文章頻道 (Never hide empty feeds by default)
  hideRead: false,
  markReadOnFeedSwitch: false,
  allExpanded: true,
  autoNextCategory: false, // 預設不自動跳轉下一未讀分類 (Do not auto-jump by default)
  refreshOnStartup: true,
  autoFullText: false,
  fontSize: "medium",
  readerFontSize: 15,
  listFontSize: 13,
  treeFontSize: 12,
  fontFamily: "system",
  customShortcuts: {}, // 預設原生空物件 (No custom key overrides by default)
  retentionDays: 60,
  pollIntervalMinutes: 30,
  imageVaultEnabled: true,
  minPublishDate: "",
  forceMinDate: false,

  // Pagination & Article Streaming
  articlePage: 1,
  hasMoreArticles: true,

  // Navigation & Selections
  activeFilter: "all", // "all", "unread", "starred", "trash", "category", "feed", "tag"
  activeCategoryId: null,
  activeFeedId: null,
  activeTag: null,
  activeTagId: null,
  searchQuery: "",

  // Data Collections
  categories: [],
  feeds: [],
  tags: [],
  articles: [],
  selectedArticleId: null,
  selectedArticle: null,

  // 4-State Visual Indicators ("loading" | "ready" | "empty_unread" | "empty_feed" | "error")
  listState: "ready",
  listErrorMsg: "",

  // List View Options, Column Widths & Column Ordering
  sortField: "published_at",
  sortAsc: false,
  columnWidths: {
    status: 28,
    star: 28,
    title: 0,
    feed: 140,
    date: 120,
    author: 100,
    tags: 100,
  },
  columnOrder: [
    "status",
    "star",
    "title",
    "feed",
    "date",
    "author",
    "tags",
  ],
  columns: {
    status: true,
    star: true,
    title: true,
    feed: true,
    date: true,
    author: true,
    tags: false,
  },

  // Reader Toolbar Options & Action Ordering
  readerToolbarOrder: [
    "star",
    "toggle_read",
    "ai_summary",
    "tag",
    "trash",
    "fetch_full",
    "copy_link",
    "open_url",
    "font_dec",
    "font_inc",
  ],

  // Reader Toolbar Visibility Map & Mode (both | icon_only)
  readerToolbarMode: "both",
  readerToolbarVisible: {
    star: true,
    toggle_read: true,
    ai_summary: true,
    tag: true,
    trash: true,
    fetch_full: true,
    copy_link: true,
    open_url: true,
    font_dec: true,
    font_inc: true,
  },

  // Tree & Sidebar Options
  tagsPosition: "bottom",
  tagsPaneHeight: 140,
  starredCount: 0,
  totalArticlesCount: 0,
  trashCount: 0,
  collapsedCategories: [],

  // Layout Sizes
  treeWidth: 240,
  listHeight: 45,

  // Loading Indicators
  isSyncing: false,
  isAiGenerating: false,
};

class StateStore {
  constructor() {
    this.state = this._createDefaultState();
    // 僅讀取客戶端必需的憑證與初始視覺主題
    const cachedToken = localStorage.getItem("omnirss_token");
    if (cachedToken) this.state.token = cachedToken;

    const cachedTheme = localStorage.getItem("omnirss_theme");
    if (cachedTheme) this.state.theme = cachedTheme;

    this.listeners = new Map();
  }

  _createDefaultState() {
    return JSON.parse(JSON.stringify(DEFAULT_STATE));
  }

  /**
   * 重置狀態為乾淨預設值 (Reset state to zero-state defaults).
   * @param {boolean} preserveAuth - 是否保留目前登入憑證與主題
   */
  resetToDefaults(preserveAuth = true) {
    const currentToken = preserveAuth ? this.state.token : null;
    const currentTheme = preserveAuth ? (this.state.theme || "dark") : "dark";
    const currentLang = preserveAuth ? (this.state.lang || "zh-TW") : "zh-TW";

    this.state = this._createDefaultState();
    if (preserveAuth) {
      this.state.token = currentToken;
      this.state.theme = currentTheme;
      this.state.lang = currentLang;
    } else {
      this.state.token = null;
      this.state.user = null;
      localStorage.removeItem("omnirss_token");
    }

    this.emit("*", this.state);
  }

  get(key) {
    const val = this.state[key];
    if (key === "searchQuery") {
      return (val && typeof val === "string" && val !== "null" && val !== "undefined") ? val : "";
    }
    return val;
  }

  set(key, value) {
    if (key === "searchQuery") {
      if (value === null || value === undefined || value === "null" || value === "undefined") {
        value = "";
      }
    }
    const oldValue = this.state[key];
    this.state[key] = value;

    // 僅對 Token 與全域 Theme 進行客戶端存儲，其餘偏好一律由後端 DB 派發
    if (key === "token") {
      if (value) localStorage.setItem("omnirss_token", value);
      else localStorage.removeItem("omnirss_token");
    }
    if (key === "theme") {
      if (value) localStorage.setItem("omnirss_theme", value);
    }

    this.emit(key, value, oldValue);
    this.emit("*", this.state);
  }

  update(patch) {
    for (const [k, v] of Object.entries(patch)) {
      this.set(k, v);
    }
  }

  subscribe(key, callback) {
    if (!this.listeners.has(key)) {
      this.listeners.set(key, new Set());
    }
    this.listeners.get(key).add(callback);

    // Return unsubscribe function
    return () => {
      const set = this.listeners.get(key);
      if (set) set.delete(callback);
    };
  }

  emit(key, value, oldValue) {
    const set = this.listeners.get(key);
    if (set) {
      for (const cb of set) {
        try {
          cb(value, oldValue);
        } catch (err) {
          console.error(`State listener error on [${key}]:`, err);
        }
      }
    }
  }
}

export function safeInputVal(v) {
  if (v === null || v === undefined || v === "null" || v === "undefined") return "";
  return String(v).trim();
}

export const store = new StateStore();
