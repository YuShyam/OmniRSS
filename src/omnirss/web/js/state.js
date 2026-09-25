/**
 * OmniRSS 響應式狀態管理模組 (Centralized Reactive State Store).
 *
 * Manages global application state, active selections, filter modes,
 * column visibility, and persisted user preferences.
 */

class StateStore {
  constructor() {
    this.state = {
      user: null,
      token: localStorage.getItem("omnirss_token") || null,
      theme: localStorage.getItem("omnirss_theme") || "dark",
      lang: localStorage.getItem("omnirss_lang") || "zh-TW",
      quietMode: localStorage.getItem("omnirss_quiet_mode") === "true",

      // Reading Behavior & Preferences
      readDelaySec: parseInt(localStorage.getItem("omnirss_read_delay") || "3", 10),
      hideEmptyFeeds: localStorage.getItem("omnirss_hide_empty_feeds") === "true",
      hideRead: localStorage.getItem("omnirss_hide_read") === "true",
      markReadOnFeedSwitch: localStorage.getItem("omnirss_mark_read_on_feed_switch") === "true",
      allExpanded: localStorage.getItem("omnirss_all_expanded") !== "false",
      autoNextCategory: localStorage.getItem("omnirss_auto_next_category") !== "false",
      refreshOnStartup: localStorage.getItem("omnirss_refresh_on_startup") !== "false",
      autoFullText: localStorage.getItem("omnirss_auto_full_text") === "true",
      fontSize: localStorage.getItem("omnirss_font_size") || "medium",
      readerFontSize: parseInt(localStorage.getItem("omnirss_reader_font_size") || "15", 10),
      listFontSize: parseInt(localStorage.getItem("omnirss_list_font_size") || "13", 10),
      treeFontSize: parseInt(localStorage.getItem("omnirss_tree_font_size") || "12", 10),
      fontFamily: localStorage.getItem("omnirss_font_family") || "system",
      customShortcuts: JSON.parse(localStorage.getItem("omnirss_custom_shortcuts") || "{}"),
      retentionDays: parseInt(localStorage.getItem("omnirss_retention_days") || "60", 10),
      pollIntervalMinutes: parseInt(localStorage.getItem("omnirss_poll_interval") || "30", 10),
      imageVaultEnabled: localStorage.getItem("omnirss_image_vault") !== "false",

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

      // List View Options, Column Widths & Column Ordering (Removed non-standard actions column)
      sortField: "published_at",
      sortAsc: false,
      columnWidths: JSON.parse(localStorage.getItem("omnirss_column_widths") || JSON.stringify({
        status: 28,
        star: 28,
        title: 0,
        feed: 140,
        date: 120,
        author: 100,
        tags: 100,
      })),
      columnOrder: JSON.parse(localStorage.getItem("omnirss_column_order") || JSON.stringify([
        "status",
        "star",
        "title",
        "feed",
        "date",
        "author",
        "tags",
      ])),
      columns: JSON.parse(localStorage.getItem("omnirss_columns") || JSON.stringify({
        status: true,
        star: true,
        title: true,
        feed: true,
        date: true,
        author: true,
        tags: false,
      })),

      // Reader Toolbar Options & Action Ordering (Including trash/delete)
      readerToolbarOrder: JSON.parse(localStorage.getItem("omnirss_reader_toolbar_order") || JSON.stringify([
        "star",
        "toggle_read",
        "trash",
        "fetch_full",
        "copy_link",
        "open_url",
      ])),

      // Tree & Sidebar Options
      tagsPosition: localStorage.getItem("omnirss_tags_position") || "bottom",
      tagsPaneHeight: parseInt(localStorage.getItem("omnirss_tags_pane_height") || "140", 10),
      starredCount: 0,
      totalArticlesCount: 0,
      trashCount: 0,

      // Layout Sizes
      treeWidth: parseInt(localStorage.getItem("omnirss_tree_width") || "240", 10),
      listHeight: parseInt(localStorage.getItem("omnirss_list_height") || "45", 10),

      // Loading Indicators
      isSyncing: false,
      isAiGenerating: false,
    };

    this.listeners = new Map();
  }

  get(key) {
    return this.state[key];
  }

  set(key, value) {
    if (key === "searchQuery") {
      if (value === null || value === undefined || value === "null") value = "";
    }
    const oldValue = this.state[key];
    this.state[key] = value;

    // Persist specific keys to localStorage
    if (key === "theme") localStorage.setItem("omnirss_theme", value);
    if (key === "lang") localStorage.setItem("omnirss_lang", value);
    if (key === "token") {
      if (value) localStorage.setItem("omnirss_token", value);
      else localStorage.removeItem("omnirss_token");
    }
    if (key === "quietMode") localStorage.setItem("omnirss_quiet_mode", String(value));
    if (key === "readDelaySec") localStorage.setItem("omnirss_read_delay", String(value));
    if (key === "hideEmptyFeeds") localStorage.setItem("omnirss_hide_empty_feeds", String(value));
    if (key === "markReadOnFeedSwitch") localStorage.setItem("omnirss_mark_read_on_feed_switch", String(value));
    if (key === "hideRead") localStorage.setItem("omnirss_hide_read", String(value));
    if (key === "allExpanded") localStorage.setItem("omnirss_all_expanded", String(value));
    if (key === "autoNextCategory") localStorage.setItem("omnirss_auto_next_category", String(value));
    if (key === "autoFullText") localStorage.setItem("omnirss_auto_full_text", String(value));
    if (key === "refreshOnStartup") localStorage.setItem("omnirss_refresh_on_startup", String(value));
    if (key === "customShortcuts") localStorage.setItem("omnirss_custom_shortcuts", JSON.stringify(value));
    if (key === "fontSize") localStorage.setItem("omnirss_font_size", String(value));
    if (key === "readerFontSize") localStorage.setItem("omnirss_reader_font_size", String(value));
    if (key === "listFontSize") localStorage.setItem("omnirss_list_font_size", String(value));
    if (key === "treeFontSize") localStorage.setItem("omnirss_tree_font_size", String(value));
    if (key === "fontFamily") localStorage.setItem("omnirss_font_family", String(value));
    if (key === "columnOrder") localStorage.setItem("omnirss_column_order", JSON.stringify(value));
    if (key === "columnWidths") localStorage.setItem("omnirss_column_widths", JSON.stringify(value));
    if (key === "columns") localStorage.setItem("omnirss_columns", JSON.stringify(value));
    if (key === "readerToolbarOrder") localStorage.setItem("omnirss_reader_toolbar_order", JSON.stringify(value));
    if (key === "tagsPosition") localStorage.setItem("omnirss_tags_position", String(value));
    if (key === "tagsPaneHeight") localStorage.setItem("omnirss_tags_pane_height", String(value));
    if (key === "treeWidth") localStorage.setItem("omnirss_tree_width", String(value));
    if (key === "listHeight") localStorage.setItem("omnirss_list_height", String(value));
    if (key === "retentionDays") localStorage.setItem("omnirss_retention_days", String(value));
    if (key === "pollIntervalMinutes") localStorage.setItem("omnirss_poll_interval", String(value));
    if (key === "imageVaultEnabled") localStorage.setItem("omnirss_image_vault", String(value));

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

export const store = new StateStore();
