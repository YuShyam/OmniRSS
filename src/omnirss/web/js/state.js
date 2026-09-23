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

      // Navigation & Selections
      activeFilter: "all", // "all", "unread", "starred", "trash", "category", "feed", "tag"
      activeCategoryId: null,
      activeFeedId: null,
      activeTag: null,
      searchQuery: "",

      // Data Collections
      categories: [],
      feeds: [],
      articles: [],
      selectedArticleId: null,
      selectedArticle: null,

      // List View Options
      sortField: "published_at",
      sortAsc: false,
      columns: JSON.parse(localStorage.getItem("omnirss_columns") || JSON.stringify({
        status: true,
        star: true,
        title: true,
        feed: true,
        date: true,
        author: true,
        tags: false,
      })),

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
    if (key === "columns") localStorage.setItem("omnirss_columns", JSON.stringify(value));
    if (key === "treeWidth") localStorage.setItem("omnirss_tree_width", String(value));
    if (key === "listHeight") localStorage.setItem("omnirss_list_height", String(value));

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
