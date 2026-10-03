/**
 * OmniRSS 應用程式進入點與事件協同器 (Main Application Orchestrator).
 *
 * Coordinates state subscriptions, component bootstrapping, draggable splitters,
 * theme switching, delayed auto-read timers, 4-state visual handlers, and data polling loops.
 */

import { store } from "./state.js";
import { api } from "./api_client.js";
import { t, updateDomTranslations } from "./i18n.js";
import { initKeybindings, jumpToNextUnreadCategory } from "./keybindings.js";
import { TreeView } from "./components/tree_view.js";
import { ListView } from "./components/list_view.js";
import { ReaderView } from "./components/reader_view.js";
import { ColumnPicker } from "./components/column_picker.js";
import { ModalController } from "./components/modals.js";

class App {
  constructor() {
    this.readTimer = null;
    this._selectArticleSeq = 0;
  }

  escape(str) {
    if (str === null || str === undefined || str === "null" || str === "undefined") return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  async init() {
    console.log("OmniRSS UI Engine Initializing...");

    try {
      // 1. Apply Initial Theme, Font Size & Language
      this.applyTheme(store.get("theme") || "dark");
      this.applyTypography();
      updateDomTranslations();
    } catch (err) {
      console.error("Theme/Typography init error:", err);
    }

    // 2. Initialize Components with isolated error boundaries
    const treeEl = document.getElementById("tree-scroll-container");
    const listHeaderEl = document.getElementById("list-header-container");
    const listRowsEl = document.getElementById("list-rows-container");
    const readerEl = document.getElementById("reader-container");
    const colPickerEl = document.getElementById("column-picker-dropdown");

    try {
      this.treeView = new TreeView(treeEl);
    } catch (err) {
      console.error("TreeView init error:", err);
    }

    try {
      this.listView = new ListView(listHeaderEl, listRowsEl);
    } catch (err) {
      console.error("ListView init error:", err);
    }

    try {
      this.readerView = new ReaderView(readerEl);
    } catch (err) {
      console.error("ReaderView init error:", err);
    }

    try {
      this.columnPicker = new ColumnPicker(colPickerEl);
    } catch (err) {
      console.error("ColumnPicker init error:", err);
    }

    try {
      this.modals = new ModalController();
    } catch (err) {
      console.error("ModalController init error:", err);
    }

    // 3. Initialize Keybindings, Splitters, Buttons, and Infinite Scroll
    try { initKeybindings(); } catch (err) { console.error("Keybindings init error:", err); }
    try { this.initSplitters(); } catch (err) { console.error("Splitters init error:", err); }
    try { this.initHeaderButtons(); } catch (err) { console.error("HeaderButtons init error:", err); }
    try { this.initTreeToolbars(); } catch (err) { console.error("TreeToolbars init error:", err); }
    try { this.initToastNotifications(); } catch (err) { console.error("ToastNotifications init error:", err); }
    try { this.initGlobalEvents(); } catch (err) { console.error("GlobalEvents init error:", err); }

    // 響應式即時驅動多膠囊指示條 (Reactive Capsule Filter Bar Sync)
    store.subscribe("activeFilter", () => this.updateFilterBar());
    store.subscribe("activeFeedId", () => this.updateFilterBar());
    store.subscribe("activeCategoryId", () => this.updateFilterBar());
    store.subscribe("activeTagId", () => this.updateFilterBar());
    store.subscribe("searchQuery", () => this.updateFilterBar());

    if (listRowsEl) {
      listRowsEl.addEventListener("scroll", async () => {
        if (listRowsEl.scrollTop + listRowsEl.clientHeight >= listRowsEl.scrollHeight - 60) {
          if (store.get("listState") !== "loading" && store.get("hasMoreArticles") && !this.isLoadingMore) {
            this.isLoadingMore = true;
            store.set("articlePage", (store.get("articlePage") || 1) + 1);
            await this.loadArticles(true);
            this.isLoadingMore = false;
          }
        }
      });
    }

    // 4. Initial Authentication & Data Load
    try {
      await this.checkAuthAndLoad();
    } catch (err) {
      console.error("checkAuthAndLoad error:", err);
    }

    // 5. Periodic Background Polling
    setInterval(() => this.reloadFeedsAndCounts(), 60000);
  }

  applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  applyTypography() {
    const root = document.documentElement;
    const fontFamily = store.get("fontFamily") || "system";
    const fontMap = {
      system: 'var(--font-sans)',
      jhenghei: '"Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif',
      serif: 'var(--font-serif)',
      mono: 'var(--font-mono)'
    };
    root.style.setProperty("--custom-font-family", fontMap[fontFamily] || fontMap.system);

    const readerFontSize = store.get("readerFontSize") || 15;
    const listFontSize = store.get("listFontSize") || 13;
    const treeFontSize = store.get("treeFontSize") || 12;

    root.style.setProperty("--reader-font-size", `${readerFontSize}px`);
    root.style.setProperty("--list-font-size", `${listFontSize}px`);
    root.style.setProperty("--tree-font-size", `${treeFontSize}px`);
  }

  applyFontSize(size) {
    // Backwards compatibility shim
    this.applyTypography();
  }

  initSplitters() {
    if (this._splittersInitialized) return;
    this._splittersInitialized = true;

    // Vertical Splitter (Tree <-> Main)
    const splitterV = document.getElementById("splitter-tree");
    const paneTree = document.querySelector(".pane-tree");

    if (splitterV && paneTree) {
      let isDragging = false;
      splitterV.addEventListener("mousedown", () => {
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
          window.dispatchEvent(new CustomEvent("omnirss:layout-changed"));
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
          window.dispatchEvent(new CustomEvent("omnirss:layout-changed"));
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
        this.saveUserSettingsDebounced();
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
        this.updateMarkReadScopeLabel();
        this.updateFilterBar();
        this.updateStatusBar();
        this.treeView.render();
        this.listView.renderHeaders();
        this.listView.render();
        if (this.columnPicker) this.columnPicker.render();
        const selArt = store.get("selectedArticle");
        if (selArt) {
          this.readerView.render(selArt);
        } else {
          this.readerView.render(null);
        }
      });
    }

    // Search Input
    const searchInput = document.getElementById("global-search");
    if (searchInput) {
      let timeout = null;
      const initialQuery = store.get("searchQuery");
      searchInput.value = (initialQuery && typeof initialQuery === "string" && initialQuery !== "null" && initialQuery !== "undefined") ? initialQuery : "";

      const triggerSearch = (immediate = false) => {
        clearTimeout(timeout);
        let val = searchInput.value;
        if (val === "null" || val === "undefined") {
          val = "";
          searchInput.value = "";
        }
        const doSearch = () => {
          store.set("searchQuery", val.trim());
          this.updateFilterBar();
          this.loadArticles();
        };
        if (immediate) {
          doSearch();
        } else {
          timeout = setTimeout(doSearch, 250);
        }
      };

      searchInput.addEventListener("input", () => triggerSearch(false));
      searchInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          triggerSearch(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          this.clearSearchOnly();
          searchInput.blur();
        }
      });
      searchInput.addEventListener("focus", () => {
        if (searchInput.value === "null" || searchInput.value === "undefined") searchInput.value = "";
      });
      searchInput.addEventListener("blur", () => {
        if (searchInput.value === "null" || searchInput.value === "undefined") searchInput.value = "";
      });
    }

    // Toggle Hide Read Button
    const btnHideRead = document.getElementById("btn-toggle-hide-read");
    if (btnHideRead) {
      const isHide = Boolean(store.get("hideRead"));
      btnHideRead.classList.toggle("active", isHide);
      btnHideRead.addEventListener("click", () => {
        const next = !store.get("hideRead");
        store.set("hideRead", next);
        this.saveUserSettingsDebounced();
        this.loadArticles();
      });
    }

    // 響應式同步「隱藏已讀」按鈕外觀狀態
    store.subscribe("hideRead", (val) => {
      const btn = document.getElementById("btn-toggle-hide-read");
      if (btn) btn.classList.toggle("active", Boolean(val));
    });

    // Refresh All Button (Force Immediate Backend Fetch with Real-time Progress Bar)
    const btnRefresh = document.getElementById("btn-refresh-all");
    const progressPill = document.getElementById("status-progress-pill");
    const progressFill = document.getElementById("status-progress-bar-fill");
    const progressPercent = document.getElementById("status-progress-percent");
    const progressMsg = document.getElementById("status-progress-msg");

    if (btnRefresh) {
      btnRefresh.addEventListener("click", async () => {
        if (btnRefresh.classList.contains("busy")) return;
        btnRefresh.classList.add("busy");
        const svgIcon = btnRefresh.querySelector("svg");
        if (svgIcon) svgIcon.classList.add("animate-spin");

        const connTextEl = document.getElementById("status-conn-text");
        const indicatorEl = document.getElementById("status-indicator");
        if (indicatorEl) indicatorEl.style.backgroundColor = "var(--accent-primary, #3b82f6)";
        if (connTextEl) connTextEl.textContent = t("status.updating_feeds");

        if (progressPill) {
          progressPill.classList.remove("finished");
          progressPill.style.display = "inline-flex";
          if (progressFill) progressFill.style.width = "0%";
          if (progressPercent) progressPercent.textContent = "0%";
          if (progressMsg) progressMsg.textContent = t("status.checking_updates");
        }

        // 啟動即時進度輪詢定時器 (200ms 靈敏刷新，後端 is_running 結束時自動結案)
        if (this.currentRefreshPollTimer) clearInterval(this.currentRefreshPollTimer);
        this.currentRefreshPollTimer = setInterval(async () => {
          try {
            const prog = await api.getRefreshProgress();
            if (!prog) return;

            if (prog.is_running) {
              const total = Math.max(1, prog.total_feeds || 1);
              const done = prog.completed_feeds || 0;
              const pct = Math.min(99, Math.max(0, Math.round((done / total) * 100)));
              let currentName = prog.current_feed_name || t("status.connecting");
              if (currentName.length > 25) {
                currentName = currentName.slice(0, 22) + "...";
              }

              if (progressFill) progressFill.style.width = `${pct}%`;
              if (progressPercent) progressPercent.textContent = `${pct}%`;
              if (progressMsg) progressMsg.textContent = `[${done}/${total}] ${currentName} (+${prog.new_articles_count || 0})`;
            } else {
              // 後端已完成抓取 (is_running == false)，自動結案並同步資料
              if (this.currentRefreshPollTimer) {
                clearInterval(this.currentRefreshPollTimer);
                this.currentRefreshPollTimer = null;
              }
              if (progressPill && !progressPill.classList.contains("finished")) {
                progressPill.classList.add("finished");
                if (progressFill) progressFill.style.width = "100%";
                if (progressPercent) progressPercent.textContent = "100%";
                const totalCount = prog.total_feeds || prog.completed_feeds || (store.get("feeds") || []).length;
                const newCount = prog.new_articles_count || 0;
                const completeMsg = newCount > 0
                  ? t("status.refresh_complete_new", { feeds: totalCount, new: newCount })
                  : t("status.refresh_complete_latest", { feeds: totalCount });
                if (progressMsg) progressMsg.textContent = `✓ ${completeMsg}`;

                await this.reloadFeedsAndCounts();
                await this.loadArticles();

                setTimeout(() => {
                  if (progressPill.classList.contains("finished")) {
                    progressPill.style.display = "none";
                    progressPill.classList.remove("finished");
                  }
                }, 3000);
              }
              btnRefresh.classList.remove("busy");
              if (svgIcon) svgIcon.classList.remove("animate-spin");
              this.updateStatusBar();
            }
          } catch (_) {}
        }, 200);

        try {
          await api.refreshAllFeeds();
        } catch (err) {
          if (this.currentRefreshPollTimer) {
            clearInterval(this.currentRefreshPollTimer);
            this.currentRefreshPollTimer = null;
          }
          if (progressPill && progressMsg) {
            progressMsg.textContent = t("status.update_failed", { error: (err && (err.detail || err.message)) || t("status.conn_error") });
          }
          if (indicatorEl) indicatorEl.style.backgroundColor = "var(--accent-red, #ef4444)";
          btnRefresh.classList.remove("busy");
          if (svgIcon) svgIcon.classList.remove("animate-spin");
          this.updateStatusBar();
        }
      });
    }

    // Stop Refresh Button (Emergency Cancel Circuit Breaker)
    const btnStopRefresh = document.getElementById("btn-stop-refresh");
    if (btnStopRefresh) {
      btnStopRefresh.addEventListener("click", async (e) => {
        e.stopPropagation();
        btnStopRefresh.disabled = true;
        const origHtml = btnStopRefresh.innerHTML;
        btnStopRefresh.textContent = t("status.stopping") || "正在停止...";

        if (this.currentRefreshPollTimer) {
          clearInterval(this.currentRefreshPollTimer);
          this.currentRefreshPollTimer = null;
        }

        try {
          const res = await api.stopRefresh();
          window.dispatchEvent(
            new CustomEvent("omnirss:toast", {
              detail: {
                message: (res && res.message) ? res.message : (t("status.refresh_stopped") || "已立即停止更新"),
                type: "info",
              },
            })
          );
        } catch (err) {
          window.dispatchEvent(
            new CustomEvent("omnirss:toast", {
              detail: {
                message: t("status.stop_failed", { error: err.message }) || `停止更新失敗: ${err.message}`,
                type: "error",
              },
            })
          );
        } finally {
          btnStopRefresh.disabled = false;
          btnStopRefresh.innerHTML = origHtml;

          if (progressPill) {
            progressPill.classList.add("finished");
            if (progressMsg) progressMsg.textContent = t("status.refresh_stopped") || "⏹ 已停止更新";
            setTimeout(() => {
              if (progressPill.classList.contains("finished")) {
                progressPill.style.display = "none";
                progressPill.classList.remove("finished");
              }
            }, 2500);
          }

          if (btnRefresh) {
            btnRefresh.classList.remove("busy");
            const svgIcon = btnRefresh.querySelector("svg");
            if (svgIcon) svgIcon.classList.remove("animate-spin");
          }

          document.querySelectorAll(".tree-row-btn.spinning").forEach((b) => b.classList.remove("spinning"));
          await this.reloadFeedsAndCounts();
          this.updateStatusBar();
        }
      });
    }


    // Mark All Read Button (Scope Aware)
    const btnMarkAll = document.getElementById("btn-mark-all-read");
    if (btnMarkAll) {
      btnMarkAll.addEventListener("click", async () => {
        const filter = store.get("activeFilter");
        const feedId = store.get("activeFeedId");
        let catId = store.get("activeCategoryId");
        if (filter === "category" && (catId === null || catId === undefined || catId === "uncategorized")) {
          catId = "uncategorized";
        }
        await api.markAllRead(feedId, catId, null, filter);
        await this.reloadFeedsAndCounts();

        if (store.get("autoNextCategory") && store.get("activeFilter") === "category") {
          const jumped = jumpToNextUnreadCategory();
          if (jumped) {
            return;
          }
        }

        await this.loadArticles();
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("status.marked_as_read"), type: "success" } }));
      });
    }

    // Clear Filter Capsule Bar Button
    const btnClearFilter = document.getElementById("btn-clear-filter") || document.getElementById("btn-clear-active-filter");
    if (btnClearFilter) {
      btnClearFilter.addEventListener("click", () => {
        this.resetFilterToAll();
      });
    }


    // User Account & Management Modal Button
    const btnOpenAccount = document.getElementById("btn-open-account");
    if (btnOpenAccount) {
      btnOpenAccount.addEventListener("click", () => {
        this.modals.openAccountModal("tab-account-security");
      });
    }

    // Logout Button
    const btnLogout = document.getElementById("btn-logout");
    if (btnLogout) {
      btnLogout.addEventListener("click", async () => {
        try {
          await api.logout();
        } catch (_) {}
        store.set("token", null);
        store.resetToDefaults(false);
        const navUserDisplay = document.getElementById("nav-username-display");
        if (navUserDisplay) navUserDisplay.textContent = "User";
        const navAdminBadge = document.getElementById("nav-admin-badge");
        if (navAdminBadge) navAdminBadge.style.display = "none";
        const userBadge = document.getElementById("user-status-name");
        if (userBadge) userBadge.textContent = "Guest";
        this.treeView.render();
        this.listView.render();
        this.readerView.render(null);
        const loginErr = document.getElementById("login-error");
        if (loginErr) loginErr.style.display = "none";
        const loginUser = document.getElementById("login-username");
        const loginPass = document.getElementById("login-password");
        if (loginUser) loginUser.value = "";
        if (loginPass) loginPass.value = "";
        this.modals.openModal("modal-login");
      });
    }
  }

  initTreeToolbars() {
    // Tree: Toggle unread-only
    const btnUnreadOnly = document.getElementById("btn-tree-unread-only");
    if (btnUnreadOnly) {
      if (store.get("hideEmptyFeeds")) btnUnreadOnly.classList.add("active");
      btnUnreadOnly.addEventListener("click", () => {
        const next = !store.get("hideEmptyFeeds");
        store.set("hideEmptyFeeds", next);
        btnUnreadOnly.classList.toggle("active", next);
      });
    }

    // Tree: Toggle expand/collapse all
    const btnCollapseAll = document.getElementById("btn-tree-collapse-all");
    if (btnCollapseAll) {
      btnCollapseAll.addEventListener("click", () => {
        this.treeView.toggleCollapseAll();
      });
    }
  }

  updateMarkReadScopeLabel() {
    const labelEl = document.getElementById("btn-mark-read-label");
    if (!labelEl) return;

    const filter = store.get("activeFilter");
    const feedId = store.get("activeFeedId");
    const feeds = store.get("feeds") || [];
    const categories = store.get("categories") || [];
    const catId = store.get("activeCategoryId");

    if (filter === "feed" && feedId) {
      const feed = feeds.find((f) => f.id === feedId);
      const name = (feed && feed.title && feed.title !== "null" && feed.title !== "undefined") ? feed.title : t("status.feed_scope_label");
      labelEl.textContent = t("nav.mark_read_scope", { name });
    } else if (filter === "category") {
      if (catId) {
        const cat = categories.find((c) => c.id === catId);
        const name = (cat && cat.name && cat.name !== "null" && cat.name !== "undefined") ? cat.name : t("status.cat_scope_label");
        labelEl.textContent = t("nav.mark_read_scope", { name });
      } else {
        labelEl.textContent = t("status.read_uncat");
      }
    } else if (filter === "tag") {
      const tagId = store.get("activeTagId");
      const tags = store.get("tags") || [];
      const tag = tags.find((tagItem) => tagItem.id === tagId);
      const name = (tag && tag.name && tag.name !== "null" && tag.name !== "undefined") ? tag.name : t("status.tag_scope_label");
      labelEl.textContent = t("nav.mark_read_scope", { name });
    } else {
      labelEl.textContent = t("tree.mark_all_read");
    }
    this.updateFilterBar();
  }

  clearSearchOnly() {
    store.set("searchQuery", "");
    const searchInput = document.getElementById("global-search");
    if (searchInput) {
      searchInput.value = "";
      searchInput.placeholder = t("nav.search_placeholder") || "搜尋文章 (/)";
    }
    this.updateFilterBar();
    this.loadArticles();
  }

  clearScopeOnly() {
    store.update({
      activeFilter: "all",
      activeFeedId: null,
      activeCategoryId: null,
      activeTag: null,
      activeTagId: null,
    });
    this.treeView.updateActiveHighlight();
    this.updateMarkReadScopeLabel();
    this.updateFilterBar();
    this.loadArticles();
  }

  resetFilterToAll() {
    store.update({
      activeFilter: "all",
      activeFeedId: null,
      activeCategoryId: null,
      activeTag: null,
      activeTagId: null,
      searchQuery: "",
    });
    const searchInput = document.getElementById("global-search");
    if (searchInput) {
      searchInput.value = "";
      searchInput.placeholder = t("nav.search_placeholder") || "搜尋文章 (/)";
    }
    this.treeView.updateActiveHighlight();
    this.updateMarkReadScopeLabel();
    this.updateFilterBar();
    this.loadArticles();
  }

  updateFilterBar() {
    const bar = document.getElementById("active-filter-bar");
    if (!bar) return;

    const capsulesContainer = document.getElementById("active-filter-capsules");
    const hintEl = document.getElementById("active-filter-hint");

    const filter = store.get("activeFilter");
    const feedId = store.get("activeFeedId");
    const catId = store.get("activeCategoryId");
    const tagId = store.get("activeTagId");
    const search = store.get("searchQuery");
    const feeds = store.get("feeds") || [];
    const categories = store.get("categories") || [];
    const tags = store.get("tags") || [];

    const isValidSearch = (s) => Boolean(s && typeof s === "string" && s.trim() && s.trim() !== "null" && s.trim() !== "undefined");
    const hasSearch = isValidSearch(search);
    const hasScope = filter && filter !== "all";

    if (!hasScope && !hasSearch) {
      bar.style.display = "none";
      bar.classList.remove("active");
      if (capsulesContainer) capsulesContainer.innerHTML = "";
      return;
    }

    let capsulesHtml = "";

    // 1. 範圍膠囊 (Scope Capsule - 鎖定頻道/分類/標籤)
    let scopeLabel = "";
    if (hasScope) {
      if (filter === "feed" && feedId) {
        const feed = feeds.find((f) => f.id === feedId);
        const name = (feed && feed.title && feed.title !== "null" && feed.title !== "undefined") ? feed.title : t("status.feed_scope_label");
        scopeLabel = t("filter_bar.lock_feed", { name: this.escape(name) });
      } else if (filter === "category") {
        let name = t("tree.uncategorized");
        if (catId) {
          const cat = categories.find((c) => c.id === catId);
          if (cat && cat.name && cat.name !== "null" && cat.name !== "undefined") name = cat.name;
        }
        scopeLabel = t("filter_bar.category", { name: this.escape(name) });
      } else if (filter === "tag" && tagId) {
        const tag = tags.find((tagItem) => tagItem.id === tagId);
        const name = (tag && tag.name && tag.name !== "null" && tag.name !== "undefined") ? tag.name : t("status.tag_scope_label");
        scopeLabel = t("filter_bar.tag", { name: this.escape(name) });
      } else if (filter === "starred") {
        scopeLabel = t("filter_bar.starred");
      } else if (filter === "trash") {
        scopeLabel = t("filter_bar.trash");
      } else if (filter === "unread") {
        scopeLabel = t("filter_bar.unread");
      }

      if (scopeLabel) {
        capsulesHtml += `
          <span class="active-filter-pill scope-pill">
            <span class="pill-text">${scopeLabel}</span>
            <button type="button" class="btn-clear-filter btn-clear-scope" title="${t("list.clear_scope", "清除頻道/分類鎖定")}">✕</button>
          </span>
        `;
      }
    }

    // 2. 搜尋關鍵字膠囊 (Search Keyword Capsule)
    if (hasSearch) {
      const searchKeyword = search.trim();
      const searchLabel = t("filter_bar.search", { keyword: this.escape(searchKeyword) });
      capsulesHtml += `
        <span class="active-filter-pill search-pill">
          <span class="pill-text">${searchLabel}</span>
          <button type="button" class="btn-clear-filter btn-clear-search" title="${t("list.clear_search", "清除搜尋關鍵字 (按 Esc)")}">✕</button>
        </span>
      `;
    }

    if (!scopeLabel && !hasSearch) {
      bar.style.display = "none";
      bar.classList.remove("active");
      if (capsulesContainer) capsulesContainer.innerHTML = "";
      return;
    }

    bar.style.display = "flex";
    bar.classList.add("active");

    if (capsulesContainer) {
      capsulesContainer.innerHTML = capsulesHtml;

      // 綁定單獨清除事件
      const btnClearScope = capsulesContainer.querySelector(".btn-clear-scope");
      if (btnClearScope) {
        btnClearScope.addEventListener("click", (e) => {
          e.stopPropagation();
          this.clearScopeOnly();
        });
      }
      const btnClearSearch = capsulesContainer.querySelector(".btn-clear-search");
      if (btnClearSearch) {
        btnClearSearch.addEventListener("click", (e) => {
          e.stopPropagation();
          this.clearSearchOnly();
        });
      }
    }

    // 提示文字動態切換
    if (hintEl) {
      if (hasSearch && hasScope) {
        hintEl.textContent = t("list.filter_clear_dual_esc", "按 Esc 清除搜尋 (再按 Esc 返回全部)");
      } else if (hasSearch) {
        hintEl.textContent = t("list.filter_clear_search_esc", "按 Esc 清除搜尋");
      } else if (hasScope) {
        hintEl.textContent = t("list.filter_clear_esc", "按 Esc 返回全部");
      } else {
        hintEl.textContent = "";
      }
    }
  }

  initToastNotifications() {
    const container = document.getElementById("toast-container");
    window.addEventListener("omnirss:toast", (e) => {
      const rawMsg = e.detail && e.detail.message;
      let message = "";
      if (typeof rawMsg === "string") {
        message = rawMsg;
      } else if (typeof rawMsg === "object" && rawMsg !== null) {
        message = rawMsg.message || rawMsg.detail || JSON.stringify(rawMsg);
      } else {
        message = String(rawMsg || "");
      }
      const type = (e.detail && e.detail.type) || "info";
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
    // Search and Filter Scope event listeners
    window.addEventListener("omnirss:clear-search", () => {
      this.clearSearchOnly();
    });
    window.addEventListener("omnirss:reset-filter-to-all", () => {
      this.resetFilterToAll();
    });

    // Typography change event
    window.addEventListener("omnirss:typography-changed", () => {
      this.applyTypography();
    });
    window.addEventListener("omnirss:font-size-changed", () => {
      this.applyTypography();
    });

    // Select article event with configurable auto-read timer and stale request guard
    window.addEventListener("omnirss:select-article", async (e) => {
      const articleId = e.detail.id;
      const reqSeq = ++this._selectArticleSeq;
      store.set("selectedArticleId", articleId);

      // 0ms 樂觀渲染：立即以列表既有快取文章資料呈現標題與摘要，消除使用者點擊等待感
      const articles = store.get("articles") || [];
      const cachedArt = articles.find((a) => a.id === articleId);
      if (cachedArt) {
        store.set("selectedArticle", cachedArt);
      }

      // Clear any pending auto-read timer from previously viewed article
      if (this.readTimer) {
        clearTimeout(this.readTimer);
        this.readTimer = null;
      }

      try {
        const fullArticle = await api.getArticle(articleId);
        // Stale guard: discard if user has already switched to another article
        if (store.get("selectedArticleId") !== articleId || this._selectArticleSeq !== reqSeq) {
          return;
        }
        store.set("selectedArticle", fullArticle);

        // Auto Full-Text Detection & Fetch (Dual-track: feed level or global setting)
        const feeds = store.get("feeds") || [];
        const currentFeed = feeds.find((f) => f.id === fullArticle.feed_id);
        const isFeedAutoFullText = Boolean(currentFeed?.auto_full_text);
        const isGlobalAutoFullText = Boolean(store.get("autoFullText"));
        const rawContent = fullArticle.content_text || fullArticle.content_html || "";
        const textOnly = rawContent.replace(/<[^>]*>/g, "").trim();

        if ((isFeedAutoFullText || isGlobalAutoFullText) && textOnly.length < 200 && fullArticle.url) {
          api.fetchFullContent(articleId).then((updated) => {
            if (store.get("selectedArticleId") === articleId && this._selectArticleSeq === reqSeq && updated) {
              store.set("selectedArticle", updated);
            }
          }).catch((err) => {
            console.warn("Auto full-text background fetch failed:", err);
          });
        }

        // Delayed Auto Mark as Read Behavior
        const isUnread = fullArticle.is_read === false || fullArticle.is_read === 0 || fullArticle.is_unread === true;
        if (isUnread) {
          const rawDelay = store.get("readDelaySec");
          const delaySec = rawDelay !== undefined && rawDelay !== null ? parseInt(rawDelay, 10) : 3;

          const executeMarkRead = async () => {
            try {
              await api.updateArticleState(articleId, { is_read: true, is_unread: false });

              // 動態取得 store 中的 selectedArticle，避免覆蓋非同步載入的全文
              const currentSelected = store.get("selectedArticle");
              if (currentSelected && currentSelected.id === articleId) {
                store.set("selectedArticle", {
                  ...currentSelected,
                  is_read: true,
                  is_unread: false,
                });
              }

              // 本地精準更新列表列狀態，避免 innerHTML 全表重建造成點擊事件中斷
              if (this.listView) {
                this.listView.updateRowReadState(articleId, true);
              }

              // Update feed counters
              const feeds = store.get("feeds") || [];
              const f = feeds.find((feed) => feed.id === fullArticle.feed_id);
              if (f && f.unread_count > 0) {
                f.unread_count = Math.max(0, f.unread_count - 1);
                store.set("feeds", [...feeds]);
              }

              // 廣播全域文章狀態變更事件
              window.dispatchEvent(
                new CustomEvent("omnirss:article-state-changed", {
                  detail: { articleId, patch: { is_read: true, is_unread: false } },
                })
              );
            } catch (err) {
              console.warn("Auto mark read failed:", err);
            }
          };

          if (delaySec === 0) {
            await executeMarkRead();
          } else if (delaySec > 0) {
            this.readTimer = setTimeout(executeMarkRead, delaySec * 1000);
          }
          // if delaySec === -1, manual only
        }
      } catch (err) {
        if (this._selectArticleSeq === reqSeq) {
          console.error("Failed to load article details:", err);
          window.dispatchEvent(
            new CustomEvent("omnirss:toast", {
              detail: { message: `載入文章失敗: ${err.message}`, type: "error" },
            })
          );
        }
      }
    });

    // Fetch Full Text (Manual / Double Click / Quick Action)
    window.addEventListener("omnirss:fetch-full-text", async (e) => {
      const articleId = e.detail && (e.detail.id ?? e.detail.articleId);
      if (!articleId) return;

      window.dispatchEvent(new CustomEvent("omnirss:toast", {
        detail: { message: t("status.fetching_full"), type: "info" }
      }));

      try {
        const updated = await api.fetchFullContent(articleId);
        if (updated) {
          const articles = store.get("articles") || [];
          const art = articles.find((a) => a.id === articleId);
          if (art) {
            art.content = updated.content;
            art.is_full_text = true;
            store.set("articles", [...articles]);
          }
          if (store.get("selectedArticleId") === articleId) {
            store.set("selectedArticle", updated);
          }
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("status.fetch_full_success"), type: "success" }
          }));
        }
      } catch (err) {
        window.dispatchEvent(new CustomEvent("omnirss:toast", {
          detail: { message: t("status.fetch_full_failed", { error: err.message }), type: "error" }
        }));
      }
    });

    // Open Category Settings Modal
    window.addEventListener("omnirss:open-category-settings", (e) => {
      this.modals.openCategorySettings(e.detail);
    });

    // Open Feed Properties Modal (QuiteRSS Alignment)
    window.addEventListener("omnirss:open-feed-properties", (e) => {
      const feedId = e.detail && (e.detail.id ?? e.detail.feedId);
      if (feedId) {
        this.modals.openFeedPropertiesModal(feedId);
      }
    });

    // Select Feed filter event (Focus Feed - 方案 A + 方案 B)
    window.addEventListener("omnirss:select-feed", (e) => {
      const feedId = e.detail.feedId ?? e.detail.id;
      if (!feedId) return;
      store.update({
        activeFilter: "feed",
        activeFeedId: feedId,
        activeCategoryId: null,
        activeTag: null,
        activeTagId: null,
      });
      this.treeView.updateActiveHighlight();
      this.updateMarkReadScopeLabel();
      this.loadArticles();
    });

    // Select Tag filter event
    window.addEventListener("omnirss:select-tag", (e) => {
      const tagId = e.detail.tagId ?? e.detail.id;
      const tagName = e.detail.tagName ?? e.detail.name;
      store.set("activeFilter", "tag");
      store.set("activeTagId", tagId);
      store.set("activeTagName", tagName);
      store.set("activeFeedId", null);
      store.set("activeCategoryId", null);
      this.updateMarkReadScopeLabel();
      this.loadArticles();
    });

    // Tags updated from modals
    window.addEventListener("omnirss:tags-updated", async () => {
      await this.reloadFeedsAndCounts();
      if (store.get("activeFilter") === "tag") {
        this.loadArticles();
      }
    });

    // Open Tag Settings
    window.addEventListener("omnirss:open-tag-settings", () => {
      this.modals.openSettings();
      const tabTags = document.querySelector(".modal-tab-btn[data-tab='tab-tags']");
      if (tabTags) tabTags.click();
    });

    // Open Tag Modal for Article (🏷️)
    window.addEventListener("omnirss:open-tag-modal", (e) => {
      const articleId = e.detail?.articleId || store.get("selectedArticle")?.id;
      if (articleId && this.modals) {
        this.modals.openArticleTagsModal(articleId);
      }
    });

    // Tag / Untag article
    window.addEventListener("omnirss:tag-article", async (e) => {
      const { articleId, tagId } = e.detail;
      try {
        const res = await api.toggleArticleTag(articleId, tagId);
        await this.reloadFeedsAndCounts();
        const articles = store.get("articles") || [];
        const art = articles.find((a) => a.id === articleId);
        if (art && res.tags) {
          art.tags = res.tags;
          store.set("articles", [...articles]);
        }
        const selectedArticle = store.get("selectedArticle");
        if (selectedArticle && selectedArticle.id === articleId) {
          selectedArticle.tags = res.tags || [];
          store.set("selectedArticle", { ...selectedArticle });
        }
        const tags = store.get("tags") || [];
        const targetTag = tags.find((tagItem) => tagItem.id === tagId);
        const actionName = res.is_tagged ? t("tags.tag_attached") : t("tags.tag_removed");
        const tagName = targetTag ? targetTag.name : "";
        window.dispatchEvent(
          new CustomEvent("omnirss:toast", {
            detail: { message: `${actionName}${tagName ? `：${tagName}` : ""}`, type: "info" },
          })
        );
      } catch (err) {
        console.error("Failed to toggle article tag:", err);
      }
    });

    // Clear article tags
    window.addEventListener("omnirss:clear-article-tags", async (e) => {
      const { articleId } = e.detail;
      try {
        await api.bindArticleTags(articleId, []);
        await this.reloadFeedsAndCounts();
        const articles = store.get("articles") || [];
        const art = articles.find((a) => a.id === articleId);
        if (art) {
          art.tags = [];
          store.set("articles", [...articles]);
        }
        const selectedArticle = store.get("selectedArticle");
        if (selectedArticle && selectedArticle.id === articleId) {
          selectedArticle.tags = [];
          store.set("selectedArticle", { ...selectedArticle });
        }
        window.dispatchEvent(
          new CustomEvent("omnirss:toast", {
            detail: { message: t("tags.clear_all_success"), type: "info" },
          })
        );
      } catch (err) {
        console.error("Failed to clear article tags:", err);
      }
    });

    // Inline Scope Mark Read (from Tree item)
    window.addEventListener("omnirss:mark-read-scope", async (e) => {
      const { type, id } = e.detail;
      try {
        if (type === "feed") {
          await api.markAllRead(parseInt(id, 10), null, null, "feed");
        } else if (type === "category") {
          const catId = id === "uncategorized" ? "uncategorized" : parseInt(id, 10);
          await api.markAllRead(null, catId, null, "category");
        } else if (type === "filter") {
          await api.markAllRead(null, null, null, id || "all");
        }
        await this.reloadFeedsAndCounts();

        if (type === "category" && store.get("autoNextCategory")) {
          const jumped = jumpToNextUnreadCategory();
          if (jumped) {
            return;
          }
        }

        await this.loadArticles();
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("status.marked_as_read"), type: "success" } }));
      } catch (err) {
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("status.mark_read_failed", { error: err.message }), type: "error" } }));
      }
    });

    // Delete Feed event
    window.addEventListener("omnirss:delete-feed", async (e) => {
      try {
        await api.deleteFeed(e.detail.id);
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("tree.delete_feed_success"), type: "success" } }));
        await this.reloadFeedsAndCounts();
        await this.loadArticles();
      } catch (err) {
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("tree.delete_feed_failed", { error: err.message }), type: "error" } }));
      }
    });

    // Delete Category event
    window.addEventListener("omnirss:delete-category", async (e) => {
      try {
        await api.deleteCategory(e.detail.id);
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("tree.delete_cat_success"), type: "success" } }));
        await this.reloadFeedsAndCounts();
        await this.loadArticles();
      } catch (err) {
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("tree.delete_cat_failed", { error: err.message }), type: "error" } }));
      }
    });

    // Trash / Restore Article event
    window.addEventListener("omnirss:trash-article", async (e) => {
      const { articleId } = e.detail || {};
      if (!articleId) return;
      try {
        const articles = store.get("articles") || [];
        const art = articles.find((a) => a.id === articleId) || store.get("selectedArticle");
        const currentTrash = Boolean(art && art.is_trash);
        const nextTrash = !currentTrash;

        await api.trashArticle(articleId, nextTrash);
        window.dispatchEvent(
          new CustomEvent("omnirss:toast", {
            detail: { message: nextTrash ? t("status.moved_to_trash") : t("status.restored_from_trash"), type: "success" },
          })
        );

        if (store.get("activeFilter") === "trash" && !nextTrash) {
          const remaining = articles.filter((a) => a.id !== articleId);
          store.set("articles", remaining);
          if (remaining.length > 0) {
            window.dispatchEvent(new CustomEvent("omnirss:select-article", { detail: { id: remaining[0].id } }));
          } else {
            store.set("selectedArticle", null);
            store.set("selectedArticleId", null);
          }
        } else if (store.get("activeFilter") !== "trash" && nextTrash) {
          const remaining = articles.filter((a) => a.id !== articleId);
          store.set("articles", remaining);
          if (remaining.length > 0) {
            window.dispatchEvent(new CustomEvent("omnirss:select-article", { detail: { id: remaining[0].id } }));
          } else {
            store.set("selectedArticle", null);
            store.set("selectedArticleId", null);
          }
        } else if (art) {
          art.is_trash = nextTrash;
          store.set("articles", [...articles]);
          const sel = store.get("selectedArticle");
          if (sel && sel.id === articleId) {
            sel.is_trash = nextTrash;
            store.set("selectedArticle", { ...sel });
          }
        }

        await this.reloadFeedsAndCounts();
      } catch (err) {
        console.error("Failed to trash article:", err);
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("status.action_failed", { error: err.message }), type: "error" } }));
      }
    });

    // Permanent Delete Article event
    window.addEventListener("omnirss:delete-article-permanent", async (e) => {
      const { articleId } = e.detail || {};
      if (!articleId) return;
      if (!confirm(t("reader.confirm_delete_permanent"))) return;
      try {
        await api.deleteArticle(articleId);
        window.dispatchEvent(
          new CustomEvent("omnirss:toast", {
            detail: { message: t("reader.delete_permanent_success"), type: "success" },
          })
        );

        const articles = store.get("articles") || [];
        const remaining = articles.filter((a) => a.id !== articleId);
        store.set("articles", remaining);
        if (remaining.length > 0) {
          window.dispatchEvent(new CustomEvent("omnirss:select-article", { detail: { id: remaining[0].id } }));
        } else {
          store.set("selectedArticle", null);
          store.set("selectedArticleId", null);
        }

        await this.reloadFeedsAndCounts();
      } catch (err) {
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("reader.delete_permanent_failed", { error: err.message }), type: "error" } }));
      }
    });

    // Empty Trash event
    window.addEventListener("omnirss:empty-trash", async () => {
      if (!confirm(t("trash.confirm_empty"))) return;
      try {
        const res = await api.emptyTrash();
        const count = res.deleted_count || 0;
        window.dispatchEvent(
          new CustomEvent("omnirss:toast", {
            detail: { message: t("trash.empty_success", { count }), type: "success" },
          })
        );
        await this.reloadFeedsAndCounts();
        await this.loadArticles();
      } catch (err) {
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("trash.empty_failed", { error: err.message }), type: "error" } }));
      }
    });

    window.addEventListener("omnirss:filter-changed", () => {
      this.updateMarkReadScopeLabel();
      this.loadArticles();
    });

    window.addEventListener("omnirss:auth-success", async () => {
      await this.checkAuthAndLoad();
    });

    window.addEventListener("omnirss:refresh-all", async () => {
      await this.reloadFeedsAndCounts();
      await this.loadArticles();
    });

    window.addEventListener("omnirss:refresh-scope", async (e) => {
      const { type, id, name, buttonEl } = e.detail || {};
      const progressPill = document.getElementById("status-progress-pill");
      const progressFill = document.getElementById("status-progress-bar-fill");
      const progressPercent = document.getElementById("status-progress-percent");
      const progressMsg = document.getElementById("status-progress-msg");
      const indicatorEl = document.getElementById("status-indicator");

      if (indicatorEl) indicatorEl.style.backgroundColor = "var(--accent-primary, #3b82f6)";
      if (progressPill) {
        progressPill.classList.remove("finished");
        progressPill.style.display = "inline-flex";
        if (progressFill) progressFill.style.width = "0%";
        if (progressPercent) progressPercent.textContent = "0%";
        if (progressMsg) {
          progressMsg.textContent = type === "category"
            ? t("status.refreshing_category", { name: name || id })
            : t("status.refreshing_feed", { name: name || id });
        }
      }

      if (this.currentRefreshPollTimer) clearInterval(this.currentRefreshPollTimer);
      this.currentRefreshPollTimer = setInterval(async () => {
        try {
          const prog = await api.getRefreshProgress();
          if (!prog) return;

          if (prog.is_running) {
            const total = Math.max(1, prog.total_feeds || 1);
            const done = prog.completed_feeds || 0;
            const pct = Math.min(99, Math.max(0, Math.round((done / total) * 100)));
            let currentName = prog.current_feed_name || t("status.connecting");
            if (currentName.length > 20) currentName = currentName.slice(0, 18) + "...";
            if (progressFill) progressFill.style.width = `${pct}%`;
            if (progressPercent) progressPercent.textContent = `${pct}%`;
            if (progressMsg) progressMsg.textContent = `[${done}/${total}] ${currentName} (+${prog.new_articles_count || 0})`;
          } else {
            // 後端抓取已完成
            if (this.currentRefreshPollTimer) {
              clearInterval(this.currentRefreshPollTimer);
              this.currentRefreshPollTimer = null;
            }
            if (progressPill && !progressPill.classList.contains("finished")) {
              progressPill.classList.add("finished");
              if (progressFill) progressFill.style.width = "100%";
              if (progressPercent) progressPercent.textContent = "100%";
              const updated = prog.total_feeds || prog.completed_feeds || 1;
              const newArts = prog.new_articles_count || 0;
              const targetLabel = name || (type === "category" ? t("status.cat_channels") : t("status.feed_source"));
              const msg = newArts > 0
                ? t("status.scope_refresh_new", { label: targetLabel, updated, new: newArts })
                : t("status.scope_refresh_latest", { label: targetLabel, updated });
              if (progressMsg) progressMsg.textContent = `✓ ${msg}`;

              await this.reloadFeedsAndCounts();
              await this.loadArticles();

              setTimeout(() => {
                if (progressPill.classList.contains("finished")) {
                  progressPill.style.display = "none";
                  progressPill.classList.remove("finished");
                }
              }, 3000);
            }
            if (buttonEl) buttonEl.classList.remove("spinning");
            this.updateStatusBar();
          }
        } catch (_) {}
      }, 200);

      try {
        if (type === "feed") {
          await api.refreshFeed(parseInt(id, 10));
        } else if (type === "category") {
          if (id === "uncategorized") {
            await api.refreshFeeds(null, null);
          } else {
            await api.refreshCategory(parseInt(id, 10));
          }
        }
      } catch (err) {
        if (this.currentRefreshPollTimer) {
          clearInterval(this.currentRefreshPollTimer);
          this.currentRefreshPollTimer = null;
        }
        const errText = (err && (err.detail || err.message)) || String(err || t("status.unknown_error"));
        if (progressPill && progressMsg) {
          progressMsg.textContent = t("status.refresh_failed", { error: errText });
        }
        if (indicatorEl) indicatorEl.style.backgroundColor = "var(--accent-red, #ef4444)";
        if (buttonEl) buttonEl.classList.remove("spinning");
        this.updateStatusBar();
      }
    });

    // 監聽所有版面、拖拉、自選欄位變更事件，防抖自動寫入 DB
    window.addEventListener("omnirss:filter-changed", () => this.saveUserSettingsDebounced());
    window.addEventListener("omnirss:layout-changed", () => this.saveUserSettingsDebounced());
    window.addEventListener("omnirss:column-widths-changed", () => this.saveUserSettingsDebounced());
    window.addEventListener("omnirss:column-order-changed", () => this.saveUserSettingsDebounced());
    window.addEventListener("omnirss:columns-changed", () => this.saveUserSettingsDebounced());
    window.addEventListener("omnirss:reader-toolbar-changed", () => this.saveUserSettingsDebounced());
    window.addEventListener("omnirss:reader-toolbar-order-changed", () => this.saveUserSettingsDebounced());
    window.addEventListener("omnirss:save-settings-debounced", () => this.saveUserSettingsDebounced());
  }

  /**
   * 收集目前前端所有版面、欄位與偏好設定 (Collect Full Settings Payload for DB SSOT).
   * @returns {Object} 完整設定 Payload
   */
  collectFullSettingsPayload() {
    return {
      theme: store.get("theme") || "dark",
      activeFilter: store.get("activeFilter") || "all",
      activeCategoryId: store.get("activeCategoryId") ?? null,
      activeFeedId: store.get("activeFeedId") ?? null,
      activeTagId: store.get("activeTagId") ?? null,
      timezone: store.get("timezone") || "auto",
      lang: store.get("lang") || "zh-TW",
      fontSize: store.get("fontSize") || "medium",
      fontFamily: store.get("fontFamily") || "system",
      readerFontSize: store.get("readerFontSize") ?? 15,
      listFontSize: store.get("listFontSize") ?? 13,
      treeFontSize: store.get("treeFontSize") ?? 12,
      readDelaySec: store.get("readDelaySec") ?? 3,
      autoNextCategory: Boolean(store.get("autoNextCategory")),
      customShortcuts: store.get("customShortcuts") || {},
      hideEmptyFeeds: Boolean(store.get("hideEmptyFeeds")),
      hideRead: Boolean(store.get("hideRead")),
      markReadOnFeedSwitch: Boolean(store.get("markReadOnFeedSwitch")),
      refreshOnStartup: store.get("refreshOnStartup") !== false,
      retentionDays: store.get("retentionDays") ?? 60,
      pollIntervalMinutes: store.get("pollIntervalMinutes") ?? 30,
      imageVaultEnabled: store.get("imageVaultEnabled") !== false,
      autoFullText: Boolean(store.get("autoFullText")),
      minPublishDate: store.get("minPublishDate") || null,
      forceMinDate: Boolean(store.get("forceMinDate")),
      columnOrder: store.get("columnOrder") || ["status", "star", "title", "feed", "date", "author", "tags"],
      columnWidths: store.get("columnWidths") || { status: 28, star: 28, title: 0, feed: 140, date: 120, author: 100, tags: 100 },
      columns: store.get("columns") || { status: true, star: true, title: true, feed: true, date: true, author: true, tags: false },
      readerToolbarOrder: store.get("readerToolbarOrder") || ["star", "toggle_read", "run_plugins", "tag", "trash", "fetch_full", "copy_link", "open_url", "font_dec", "font_inc"],
      readerToolbarVisible: store.get("readerToolbarVisible") || { star: true, toggle_read: true, run_plugins: true, tag: true, trash: true, fetch_full: true, copy_link: true, open_url: true, font_dec: true, font_inc: true },
      readerToolbarMode: store.get("readerToolbarMode") || "both",
      tagsPosition: store.get("tagsPosition") || "bottom",
      tagsPaneHeight: store.get("tagsPaneHeight") ?? 140,
      collapsedCategories: store.get("collapsedCategories") || [],
      treeWidth: store.get("treeWidth") ?? 240,
      listHeight: store.get("listHeight") ?? 45,
    };
  }

  /**
   * 防抖自動同步使用者設定至後端資料庫 (Debounced Auto-Persist Settings to DB).
   */
  saveUserSettingsDebounced() {
    clearTimeout(this._saveSettingsTimer);
    this._saveSettingsTimer = setTimeout(async () => {
      if (!store.get("user")) return;
      try {
        const payload = this.collectFullSettingsPayload();
        await api.updateUserSettings(payload);
      } catch (err) {
        console.warn("Auto-persisting settings to DB failed:", err);
      }
    }, 400);
  }

  showToast(message, type = "info") {
    window.dispatchEvent(
      new CustomEvent("omnirss:toast", {
        detail: { message, type },
      })
    );
  }

  async checkAuthAndLoad() {
    try {
      store.resetToDefaults(true);
      const me = await api.getMe();
      store.set("user", me);

      try {
        const pluginsList = await api.getPlugins();
        store.set("plugins", pluginsList || []);
      } catch (e) {
        store.set("plugins", []);
      }

      const userBadge = document.getElementById("user-status-name");
      if (userBadge) userBadge.textContent = me.username;

      const navUserDisplay = document.getElementById("nav-username-display");
      if (navUserDisplay) navUserDisplay.textContent = me.username || "User";

      const navAdminBadge = document.getElementById("nav-admin-badge");
      if (navAdminBadge) {
        navAdminBadge.style.display = me.is_admin ? "inline-block" : "none";
      }

      // Hydrate all settings from user profile (Single Source of Truth from DB - Data-Driven Map)
      if (me.settings && typeof me.settings === "object" && Object.keys(me.settings).length > 0) {
        const SETTINGS_MAP = [
          { key: "theme", action: (val) => { store.set("theme", val); this.applyTheme(val); } },
          {
            key: "activeFilter",
            aliases: ["default_view"],
            action: (val) => {
              if (val && ["all", "unread", "starred", "trash", "category", "feed", "tag"].includes(val)) {
                store.set("activeFilter", val);
              }
            },
          },
          { key: "activeCategoryId" },
          { key: "activeFeedId" },
          { key: "activeTagId" },
          { key: "timezone" },
          {
            key: "lang",
            aliases: ["language"],
            action: (val) => {
              store.set("lang", val);
              const btnLang = document.getElementById("btn-toggle-lang");
              if (btnLang) btnLang.textContent = val === "zh-TW" ? "繁中" : "EN";
              updateDomTranslations();
            },
          },
          { key: "fontSize" },
          { key: "fontFamily" },
          { key: "readerFontSize" },
          { key: "listFontSize" },
          { key: "treeFontSize" },
          { key: "readDelaySec" },
          { key: "autoNextCategory", cast: Boolean },
          { key: "customShortcuts", aliases: ["customKeybindings"], defaultVal: {} },
          { key: "hideEmptyFeeds", cast: Boolean },
          { key: "hideRead", cast: Boolean },
          { key: "markReadOnFeedSwitch", cast: Boolean },
          { key: "refreshOnStartup", cast: (v) => v !== false },
          { key: "autoFullText", cast: Boolean },
          { key: "retentionDays" },
          { key: "pollIntervalMinutes" },
          { key: "imageVaultEnabled", cast: (v) => v !== false },
          { key: "minPublishDate", aliases: ["min_publish_date"], defaultVal: "" },
          { key: "forceMinDate", aliases: ["force_min_date"], cast: Boolean },
          { key: "columnOrder", validate: Array.isArray },
          { key: "columnWidths", validate: (v) => typeof v === "object" && v !== null },
          { key: "columns", validate: (v) => typeof v === "object" && v !== null },
          { key: "readerToolbarOrder", validate: Array.isArray },
          { key: "readerToolbarVisible", validate: (v) => typeof v === "object" && v !== null },
          { key: "readerToolbarMode" },
          { key: "tagsPosition" },
          { key: "tagsPaneHeight" },
          { key: "collapsedCategories", validate: Array.isArray },
          {
            key: "treeWidth",
            action: (val) => {
              store.set("treeWidth", val);
              const paneTree = document.querySelector(".pane-tree");
              if (paneTree) paneTree.style.width = `${val}px`;
            },
          },
          {
            key: "listHeight",
            action: (val) => {
              store.set("listHeight", val);
              const paneList = document.querySelector(".pane-list");
              if (paneList) paneList.style.height = `${val}%`;
            },
          },
        ];

        for (const rule of SETTINGS_MAP) {
          let val = me.settings[rule.key];
          if (val === undefined && rule.aliases) {
            for (const alias of rule.aliases) {
              if (me.settings[alias] !== undefined) {
                val = me.settings[alias];
                break;
              }
            }
          }
          if (val === undefined && rule.defaultVal !== undefined) {
            val = rule.defaultVal;
          }
          if (val !== undefined) {
            if (rule.validate && !rule.validate(val)) continue;
            const finalVal = rule.cast ? rule.cast(val) : val;
            if (rule.action) {
              rule.action(finalVal);
            } else {
              store.set(rule.key, finalVal);
            }
          }
        }
        this.applyTypography();
      }

      // Synchronize component views and styles
      if (this.listView) {
        this.listView.applyColumnWidthsStyle();
        this.listView.renderHeaders();
      }
      if (this.columnPicker) {
        this.columnPicker.render();
      }
      if (this.treeView) {
        this.treeView.render();
      }

      // Synchronize button states
      const btnUnreadOnly = document.getElementById("btn-tree-unread-only");
      if (btnUnreadOnly) {
        btnUnreadOnly.classList.toggle("active", Boolean(store.get("hideEmptyFeeds")));
      }
      const btnHideRead = document.getElementById("btn-toggle-hide-read");
      if (btnHideRead) {
        btnHideRead.classList.toggle("active", Boolean(store.get("hideRead")));
      }

      await this.reloadFeedsAndCounts();
      if (this.treeView) {
        this.treeView.render();
      }
      await this.loadArticles();

      const searchInput = document.getElementById("global-search");
      if (searchInput) {
        const q = store.get("searchQuery");
        searchInput.value = (q && typeof q === "string" && q !== "null" && q !== "undefined") ? q : "";
        searchInput.placeholder = t("nav.search_placeholder") || "搜尋文章 (/)";
      }

      // QuiteRSS Feature: Auto refresh all feeds on startup/login (預設停用，僅在用戶明確開啟時觸發，保障極速載入)
      if (Boolean(store.get("refreshOnStartup"))) {
        setTimeout(() => {
          const btnRefresh = document.getElementById("btn-refresh-all");
          if (btnRefresh && !btnRefresh.classList.contains("busy")) {
            btnRefresh.click();
          }
        }, 1500);
      }
    } catch (_) {
      store.resetToDefaults(false);
      this.treeView.render();
      this.listView.render();
      this.readerView.render(null);
      this.modals.openModal("modal-login");
    }
  }

  async reloadFeedsAndCounts() {
    if (!store.get("user")) return;
    try {
      const [cats, feeds, tags, treeData] = await Promise.all([
        api.getCategories(),
        api.getFeeds(),
        api.getTags ? api.getTags() : Promise.resolve([]),
        api.getFeedTree ? api.getFeedTree() : Promise.resolve(null),
      ]);
      store.set("categories", cats || []);
      store.set("feeds", feeds || []);
      store.set("tags", tags || []);
      if (treeData) {
        if (treeData.starred_count !== undefined) {
          store.set("starredCount", treeData.starred_count);
        }
        if (treeData.total_articles !== undefined) {
          store.set("totalArticlesCount", treeData.total_articles);
        }
        if (treeData.trash_count !== undefined) {
          store.set("trashCount", treeData.trash_count);
        }
      }
      this.updateMarkReadScopeLabel();
      this.updateStatusBar();
    } catch (err) {
      console.warn("Sync feeds error:", err);
      const connTextEl = document.getElementById("status-conn-text");
      if (connTextEl) connTextEl.textContent = t("status.conn_abnormal_retrying");
    }
  }

  updateStatusBar() {
    const connTextEl = document.getElementById("status-conn-text");
    const indicatorEl = document.getElementById("status-indicator");
    if (!connTextEl) return;

    const feeds = store.get("feeds") || [];
    const totalFeeds = feeds.length;
    const totalUnread = feeds.reduce((sum, f) => sum + (f.unread_count || 0), 0);

    // Dynamic Title Unread Badge (QuiteRSS Alignment)
    document.title = totalUnread > 0 ? `(${totalUnread}) OmniRSS` : "OmniRSS";

    if (this.lastRefreshedAt) {
      const timeStr = this.lastRefreshedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      connTextEl.textContent = t("status.conn_ready_summary", { count: totalFeeds, time: timeStr });
    } else {
      connTextEl.textContent = t("status.conn_ready_summary_nosync", { count: totalFeeds });
    }

    if (indicatorEl) {
      indicatorEl.style.backgroundColor = "var(--accent-green, #4ade80)";
    }
  }

  async loadArticles(isAppend = false) {
    if (!store.get("user")) {
      store.set("articles", []);
      this.listView.render();
      return;
    }
    const filter = store.get("activeFilter");
    const feedId = store.get("activeFeedId");
    const categoryId = store.get("activeCategoryId");
    const tagId = store.get("activeTagId");
    const search = store.get("searchQuery");
    const hideRead = Boolean(store.get("hideRead"));
    const btnHideRead = document.getElementById("btn-toggle-hide-read");
    if (btnHideRead) {
      btnHideRead.classList.toggle("active", hideRead);
    }

    if (!isAppend) {
      store.set("listState", "loading");
      store.set("articlePage", 1);
      store.set("hasMoreArticles", true);
      const listRowsEl = document.getElementById("list-rows-container");
      if (listRowsEl) listRowsEl.scrollTop = 0;
    }

    const page = store.get("articlePage") || 1;
    const pageSize = 100;

    const params = {
      page,
      page_size: pageSize,
    };
    if (search && typeof search === "string" && search.trim() && search.trim() !== "null" && search.trim() !== "undefined") {
      params.search = search.trim();
    }
    // 智慧已讀過濾：若 filter 為 "unread" 或 hideRead 為 true（且當前不是標籤視圖）則僅拉取未讀文章
    // 標籤為典藏/知識庫性質，一律顯示全部標籤文章，不隱藏已讀；同時保留頂端狀態供其他分類/來源使用
    const shouldFilterUnread = filter === "unread" || (Boolean(hideRead) && filter !== "tag");
    if (shouldFilterUnread) params.is_unread = true;
    if (filter === "starred") params.is_starred = true;
    if (filter === "trash") params.is_trash = true;
    if (filter === "feed" && feedId) params.feed_id = feedId;
    if (filter === "category") {
      params.category_id = categoryId !== null ? categoryId : 0;
    }
    if (filter === "tag" && tagId) {
      params.tag_id = tagId;
    }

    try {
      const response = await api.getArticles(params);
      const items = Array.isArray(response) ? response : (response && response.items ? response.items : []);
      const total = (response && response.total !== undefined) ? response.total : items.length;

      let newArticles = [];
      if (isAppend) {
        const currentArticles = store.get("articles") || [];
        const seenIds = new Set(currentArticles.map((a) => a.id));
        const uniqueItems = items.filter((a) => !seenIds.has(a.id));
        newArticles = [...currentArticles, ...uniqueItems];
      } else {
        const seenIds = new Set();
        newArticles = items.filter((a) => {
          if (seenIds.has(a.id)) return false;
          seenIds.add(a.id);
          return true;
        });
      }

      store.set("articles", newArticles || []);
      store.set("hasMoreArticles", newArticles.length < total && items.length === pageSize);
      store.set("listState", "ready");
      this.listView.sortArticles();

      // Auto select first article if none selected
      if (newArticles && newArticles.length > 0 && !store.get("selectedArticleId") && !isAppend) {
        window.dispatchEvent(new CustomEvent("omnirss:select-article", { detail: { id: newArticles[0].id } }));
      }
    } catch (err) {
      console.error("Load articles error:", err);
      store.set("listState", "error");
      store.set("listErrorMsg", err.message || t("error.load_articles_failed"));
    }
  }
}

// Bootstrap on DOM Ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    const app = new App();
    app.init();
  });
} else {
  const app = new App();
  app.init();
}
