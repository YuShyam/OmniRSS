/**
 * OmniRSS 應用程式進入點與事件協同器 (Main Application Orchestrator).
 *
 * Coordinates state subscriptions, component bootstrapping, draggable splitters,
 * theme switching, and data polling loops.
 */

import { store } from "./state.js";
import { api } from "./api_client.js";
import { t, updateDomTranslations } from "./i18n.js";
import { initKeybindings } from "./keybindings.js";
import { TreeView } from "./components/tree_view.js";
import { ListView } from "./components/list_view.js";
import { ReaderView } from "./components/reader_view.js";
import { ColumnPicker } from "./components/column_picker.js";
import { ModalController } from "./components/modals.js";

class App {
  async init() {
    console.log("OmniRSS UI Engine Initializing...");

    // 1. Apply Initial Theme & Language
    this.applyTheme(store.get("theme"));
    updateDomTranslations();

    // 2. Initialize Components
    const treeEl = document.getElementById("tree-scroll-container");
    const listHeaderEl = document.getElementById("list-header-container");
    const listRowsEl = document.getElementById("list-rows-container");
    const readerEl = document.getElementById("reader-container");
    const colPickerEl = document.getElementById("column-picker-dropdown");

    this.treeView = new TreeView(treeEl);
    this.listView = new ListView(listHeaderEl, listRowsEl);
    this.readerView = new ReaderView(readerEl);
    this.columnPicker = new ColumnPicker(colPickerEl);
    this.modals = new ModalController();

    // 3. Initialize Keybindings & Splitters
    initKeybindings();
    this.initSplitters();
    this.initHeaderButtons();
    this.initToastNotifications();
    this.initGlobalEvents();

    // 4. Initial Authentication & Data Load
    await this.checkAuthAndLoad();

    // 5. Periodic Background Polling
    setInterval(() => this.reloadFeedsAndCounts(), 60000);
  }

  applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  initSplitters() {
    // Vertical Splitter (Tree <-> Main)
    const splitterV = document.getElementById("splitter-tree");
    const paneTree = document.querySelector(".pane-tree");

    if (splitterV && paneTree) {
      let isDragging = false;
      splitterV.addEventListener("mousedown", (e) => {
        isDragging = true;
        splitterV.classList.add("dragging");
        document.body.style.cursor = "col-resize";
      });

      window.addEventListener("mousemove", (e) => {
        if (!isDragging) return;
        const newWidth = Math.max(180, Math.min(e.clientX, 500));
        paneTree.style.width = `${newWidth}px`;
        store.set("treeWidth", newWidth);
      });

      window.addEventListener("mouseup", () => {
        if (isDragging) {
          isDragging = false;
          splitterV.classList.remove("dragging");
          document.body.style.cursor = "";
        }
      });
    }

    // Horizontal Splitter (List <-> Reader)
    const splitterH = document.getElementById("splitter-list");
    const paneList = document.querySelector(".pane-list");
    const paneMain = document.querySelector(".pane-main");

    if (splitterH && paneList && paneMain) {
      let isDragging = false;
      splitterH.addEventListener("mousedown", () => {
        isDragging = true;
        splitterH.classList.add("dragging");
        document.body.style.cursor = "row-resize";
      });

      window.addEventListener("mousemove", (e) => {
        if (!isDragging) return;
        const mainRect = paneMain.getBoundingClientRect();
        const relativeY = e.clientY - mainRect.top;
        const heightPercent = (relativeY / mainRect.height) * 100;
        const clampedPercent = Math.max(20, Math.min(heightPercent, 80));
        paneList.style.height = `${clampedPercent}%`;
        store.set("listHeight", Math.round(clampedPercent));
      });

      window.addEventListener("mouseup", () => {
        if (isDragging) {
          isDragging = false;
          splitterH.classList.remove("dragging");
          document.body.style.cursor = "";
        }
      });
    }
  }

  initHeaderButtons() {
    // Theme Selector Button
    const btnTheme = document.getElementById("btn-toggle-theme");
    if (btnTheme) {
      btnTheme.addEventListener("click", () => {
        const current = store.get("theme");
        const next = current === "dark" ? "light" : current === "light" ? "midnight" : "dark";
        store.set("theme", next);
        this.applyTheme(next);
      });
    }

    // Language Selector Button
    const btnLang = document.getElementById("btn-toggle-lang");
    if (btnLang) {
      btnLang.addEventListener("click", () => {
        const current = store.get("lang");
        const next = current === "zh-TW" ? "en-US" : "zh-TW";
        store.set("lang", next);
        btnLang.textContent = next === "zh-TW" ? "繁中" : "EN";
        updateDomTranslations();
        this.treeView.render();
        this.listView.renderHeaders();
      });
    }

    // Quiet Mode Toggle
    const btnQuiet = document.getElementById("btn-toggle-quiet");
    const quietBanner = document.getElementById("quiet-mode-banner");
    if (btnQuiet) {
      btnQuiet.addEventListener("click", () => {
        const isQuiet = !store.get("quietMode");
        store.set("quietMode", isQuiet);
        btnQuiet.classList.toggle("active", isQuiet);
        if (quietBanner) quietBanner.classList.toggle("active", isQuiet);
        this.loadArticles();
      });
    }

    // Search Input
    const searchInput = document.getElementById("global-search");
    if (searchInput) {
      let timeout = null;
      searchInput.addEventListener("input", (e) => {
        clearTimeout(timeout);
        timeout = setTimeout(() => {
          store.set("searchQuery", e.target.value.trim());
          this.loadArticles();
        }, 250);
      });
    }

    // Add Feed Button
    const btnAddFeed = document.getElementById("btn-add-feed");
    if (btnAddFeed) {
      btnAddFeed.addEventListener("click", () => {
        // Populate category dropdown
        const cats = store.get("categories") || [];
        const select = document.getElementById("select-feed-category");
        if (select) {
          select.innerHTML = `<option value="">未分類</option>` + cats.map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
        }
        this.modals.openModal("modal-add-feed");
      });
    }

    // Add Category Button
    const btnAddCat = document.getElementById("btn-add-category");
    if (btnAddCat) {
      btnAddCat.addEventListener("click", () => {
        this.modals.openModal("modal-add-category");
      });
    }

    // Refresh All Button
    const btnRefresh = document.getElementById("btn-refresh-all");
    if (btnRefresh) {
      btnRefresh.addEventListener("click", async () => {
        btnRefresh.classList.add("busy");
        try {
          await api.refreshAllFeeds();
          await this.reloadFeedsAndCounts();
          await this.loadArticles();
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "全頻道更新完畢", type: "success" } }));
        } finally {
          btnRefresh.classList.remove("busy");
        }
      });
    }

    // Mark All Read Button
    const btnMarkAll = document.getElementById("btn-mark-all-read");
    if (btnMarkAll) {
      btnMarkAll.addEventListener("click", async () => {
        const feedId = store.get("activeFeedId");
        const catId = store.get("activeCategoryId");
        await api.markAllRead(feedId, catId);
        await this.reloadFeedsAndCounts();
        await this.loadArticles();
      });
    }

    // Logout Button
    const btnLogout = document.getElementById("btn-logout");
    if (btnLogout) {
      btnLogout.addEventListener("click", async () => {
        await api.logout();
        store.set("user", null);
        store.set("token", null);
        this.modals.openModal("modal-login");
      });
    }
  }

  initToastNotifications() {
    const container = document.getElementById("toast-container");
    window.addEventListener("omnirss:toast", (e) => {
      const { message, type = "info" } = e.detail;
      const toast = document.createElement("div");
      toast.className = `toast ${type}`;
      toast.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        <span>${message}</span>
      `;
      container.appendChild(toast);
      setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 200);
      }, 3000);
    });
  }

  initGlobalEvents() {
    window.addEventListener("omnirss:select-article", async (e) => {
      const articleId = e.detail.id;
      store.set("selectedArticleId", articleId);
      try {
        const fullArticle = await api.getArticle(articleId);
        store.set("selectedArticle", fullArticle);

        // Mark as read automatically when opened
        if (fullArticle.is_unread) {
          await api.updateArticleState(articleId, { is_unread: false });
          fullArticle.is_unread = false;
          const articles = store.get("articles");
          const a = articles.find((item) => item.id === articleId);
          if (a) a.is_unread = false;
          store.set("articles", [...articles]);
        }
      } catch (err) {
        console.error("Failed to load article details:", err);
      }
    });

    window.addEventListener("omnirss:filter-changed", () => {
      this.loadArticles();
    });

    window.addEventListener("omnirss:refresh-all", async () => {
      await this.reloadFeedsAndCounts();
      await this.loadArticles();
    });
  }

  async checkAuthAndLoad() {
    try {
      const me = await api.getMe();
      store.set("user", me);
      const userBadge = document.getElementById("user-status-name");
      if (userBadge) userBadge.textContent = me.username;

      await this.reloadFeedsAndCounts();
      await this.loadArticles();
    } catch (_) {
      this.modals.openModal("modal-login");
    }
  }

  async reloadFeedsAndCounts() {
    try {
      const [cats, feeds] = await Promise.all([api.getCategories(), api.getFeeds()]);
      store.set("categories", cats || []);
      store.set("feeds", feeds || []);
    } catch (err) {
      console.warn("Sync feeds error:", err);
    }
  }

  async loadArticles() {
    const filter = store.get("activeFilter");
    const feedId = store.get("activeFeedId");
    const categoryId = store.get("activeCategoryId");
    const search = store.get("searchQuery");
    const quiet = store.get("quietMode");

    const params = {};
    if (search) params.search = search;
    if (filter === "unread" || quiet) params.is_unread = true;
    if (filter === "starred") params.is_starred = true;
    if (filter === "trash") params.is_trash = true;
    if (filter === "feed" && feedId) params.feed_id = feedId;
    if (filter === "category" && categoryId) params.category_id = categoryId;

    try {
      const articles = await api.getArticles(params);
      store.set("articles", articles || []);
      this.listView.sortArticles();

      // Auto select first article if none selected
      if (articles && articles.length > 0 && !store.get("selectedArticleId")) {
        window.dispatchEvent(new CustomEvent("omnirss:select-article", { detail: { id: articles[0].id } }));
      }
    } catch (err) {
      console.error("Load articles error:", err);
    }
  }
}

// Bootstrap on DOM Ready
document.addEventListener("DOMContentLoaded", () => {
  const app = new App();
  app.init();
});
