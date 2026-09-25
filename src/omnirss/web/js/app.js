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

    // 1. Apply Initial Theme, Font Size & Language
    this.applyTheme(store.get("theme") || "dark");
    this.applyTypography();
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

    // 3. Initialize Keybindings, Splitters, Buttons, and Infinite Scroll
    initKeybindings();
    this.initSplitters();
    this.initHeaderButtons();
    this.initTreeToolbars();
    this.initToastNotifications();
    this.initGlobalEvents();

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
    await this.checkAuthAndLoad();

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
      if (searchInput.value === "null" || !searchInput.value) {
        searchInput.value = store.get("searchQuery") || "";
      }
      const triggerSearch = (immediate = false) => {
        clearTimeout(timeout);
        let val = searchInput.value;
        if (val === "null") {
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
          searchInput.value = "";
          triggerSearch(true);
          searchInput.blur();
        }
      });
      searchInput.addEventListener("focus", () => {
        if (searchInput.value === "null") searchInput.value = "";
      });
      searchInput.addEventListener("blur", () => {
        if (searchInput.value === "null") searchInput.value = "";
      });
    }

    // Toggle Hide Read Button
    const btnHideRead = document.getElementById("btn-toggle-hide-read");
    if (btnHideRead) {
      const isHide = store.get("hideRead") || false;
      btnHideRead.classList.toggle("active", isHide);
      btnHideRead.addEventListener("click", () => {
        const next = !store.get("hideRead");
        store.set("hideRead", next);
        btnHideRead.classList.toggle("active", next);
        this.loadArticles();
      });
    }

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

        // 啟動即時進度輪詢定時器 (120ms 高頻靈敏刷新)
        let pollTimer = setInterval(async () => {
          try {
            const prog = await api.getRefreshProgress();
            if (prog && prog.is_running) {
              const total = Math.max(1, prog.total_feeds || 1);
              const done = prog.completed_feeds || 0;
              const pct = Math.min(100, Math.max(0, Math.round((done / total) * 100)));
              let currentName = prog.current_feed_name || t("status.connecting");
              if (currentName.length > 25) {
                currentName = currentName.slice(0, 22) + "...";
              }

              if (progressFill) progressFill.style.width = `${pct}%`;
              if (progressPercent) progressPercent.textContent = `${pct}%`;
              if (progressMsg) progressMsg.textContent = `[${done}/${total}] ${currentName} (+${prog.new_articles_count || 0})`;
            }
          } catch (_) {}
        }, 120);

        try {
          const res = await api.refreshAllFeeds();
          clearInterval(pollTimer);

          // 獲取最終進度統計
          let finalNewCount = 0;
          try {
            const finalProg = await api.getRefreshProgress();
            if (finalProg) finalNewCount = finalProg.new_articles_count || 0;
          } catch (_) {}

          await this.reloadFeedsAndCounts();
          await this.loadArticles();

          const refreshedCount = (res && typeof res.updated_feeds === "number") ? res.updated_feeds : (store.get("feeds") || []).length;
          const msg = finalNewCount > 0
            ? t("status.refresh_complete_new", { feeds: refreshedCount, new: finalNewCount })
            : t("status.refresh_complete_latest", { feeds: refreshedCount });

          if (progressPill && progressMsg) {
            progressPill.classList.add("finished");
            if (progressFill) progressFill.style.width = "100%";
            if (progressPercent) progressPercent.textContent = "100%";
            progressMsg.textContent = `✓ ${msg}`;
            setTimeout(() => {
              if (progressPill.classList.contains("finished")) {
                progressPill.style.display = "none";
                progressPill.classList.remove("finished");
              }
            }, 5000);
          }
        } catch (err) {
          clearInterval(pollTimer);
          if (progressPill && progressMsg) {
            progressMsg.textContent = t("status.update_failed", { error: (err && (err.detail || err.message)) || t("status.conn_error") });
          }
          if (indicatorEl) indicatorEl.style.backgroundColor = "var(--accent-red, #ef4444)";
        } finally {
          clearInterval(pollTimer);
          btnRefresh.classList.remove("busy");
          if (svgIcon) svgIcon.classList.remove("animate-spin");
          this.updateStatusBar();
        }
      });
    }


    // Mark All Read Button (Scope Aware)
    const btnMarkAll = document.getElementById("btn-mark-all-read");
    if (btnMarkAll) {
      btnMarkAll.addEventListener("click", async () => {
        const feedId = store.get("activeFeedId");
        const catId = store.get("activeCategoryId");
        await api.markAllRead(feedId, catId);
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
    const btnClearFilter = document.getElementById("btn-clear-active-filter");
    if (btnClearFilter) {
      btnClearFilter.addEventListener("click", () => {
        this.resetFilterToAll();
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
      const name = feed ? (feed.title || t("status.feed_scope_label")) : t("status.feed_scope_label");
      labelEl.textContent = t("nav.mark_read_scope", { name });
    } else if (filter === "category") {
      if (catId) {
        const cat = categories.find((c) => c.id === catId);
        const name = cat ? cat.name : t("status.cat_scope_label");
        labelEl.textContent = t("nav.mark_read_scope", { name });
      } else {
        labelEl.textContent = t("status.read_uncat");
      }
    } else if (filter === "tag") {
      const tagId = store.get("activeTagId");
      const tags = store.get("tags") || [];
      const tag = tags.find((tagItem) => tagItem.id === tagId);
      const name = tag ? tag.name : t("status.tag_scope_label");
      labelEl.textContent = t("nav.mark_read_scope", { name });
    } else {
      labelEl.textContent = t("tree.mark_all_read");
    }
    this.updateFilterBar();
  }

  updateFilterBar() {
    const bar = document.getElementById("active-filter-bar");
    const titleEl = document.getElementById("active-filter-title");
    if (!bar || !titleEl) return;

    const filter = store.get("activeFilter");
    const feedId = store.get("activeFeedId");
    const catId = store.get("activeCategoryId");
    const tagId = store.get("activeTagId");
    const search = store.get("searchQuery");
    const feeds = store.get("feeds") || [];
    const categories = store.get("categories") || [];
    const tags = store.get("tags") || [];

    const searchPart = search && search.trim() ? ` · ${t("filter_bar.search", { keyword: this.escape(search.trim()) })}` : "";

    if (filter === "feed" && feedId) {
      const feed = feeds.find((f) => f.id === feedId);
      const name = feed ? (feed.title || t("status.feed_scope_label")) : t("status.feed_scope_label");
      titleEl.innerHTML = `${t("filter_bar.lock_feed", { name })}${searchPart}`;
      bar.style.display = "flex";
    } else if (filter === "category") {
      let name = t("tree.uncategorized");
      if (catId) {
        const cat = categories.find((c) => c.id === catId);
        if (cat) name = cat.name;
      }
      titleEl.innerHTML = `${t("filter_bar.category", { name })}${searchPart}`;
      bar.style.display = "flex";
    } else if (filter === "tag" && tagId) {
      const tag = tags.find((tagItem) => tagItem.id === tagId);
      const name = tag ? tag.name : t("status.tag_scope_label");
      titleEl.innerHTML = `${t("filter_bar.tag", { name })}${searchPart}`;
      bar.style.display = "flex";
    } else if (filter === "starred") {
      titleEl.innerHTML = `${t("filter_bar.starred")}${searchPart}`;
      bar.style.display = "flex";
    } else if (filter === "trash") {
      titleEl.innerHTML = `${t("filter_bar.trash")}${searchPart}`;
      bar.style.display = "flex";
    } else if (search && search.trim()) {
      titleEl.innerHTML = t("filter_bar.search", { keyword: this.escape(search.trim()) });
      bar.style.display = "flex";
    } else {
      bar.style.display = "none";
    }
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
    if (searchInput) searchInput.value = "";
    this.treeView.updateActiveHighlight();
    this.updateMarkReadScopeLabel();
    this.updateFilterBar();
    this.loadArticles();
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
    // Typography change event
    window.addEventListener("omnirss:typography-changed", () => {
      this.applyTypography();
    });
    window.addEventListener("omnirss:font-size-changed", () => {
      this.applyTypography();
    });

    // Select article event with configurable auto-read timer
    window.addEventListener("omnirss:select-article", async (e) => {
      const articleId = e.detail.id;
      store.set("selectedArticleId", articleId);

      // Clear any pending auto-read timer from previously viewed article
      if (this.readTimer) {
        clearTimeout(this.readTimer);
        this.readTimer = null;
      }

      try {
        const fullArticle = await api.getArticle(articleId);
        store.set("selectedArticle", fullArticle);

        // Auto Full-Text Detection & Fetch (Dual-track: feed level or global setting)
        const feeds = store.get("feeds") || [];
        const currentFeed = feeds.find((f) => f.id === fullArticle.feed_id);
        const isFeedAutoFullText = Boolean(currentFeed?.auto_full_text);
        const isGlobalAutoFullText = Boolean(store.get("autoFullText"));
        const textOnly = (fullArticle.content || "").replace(/<[^>]*>/g, "").trim();

        if ((isFeedAutoFullText || isGlobalAutoFullText) && textOnly.length < 200 && fullArticle.url) {
          api.fetchFullContent(articleId).then((updated) => {
            if (store.get("selectedArticleId") === articleId && updated) {
              store.set("selectedArticle", updated);
            }
          }).catch((err) => {
            console.warn("Auto full-text background fetch failed:", err);
          });
        }

        // Delayed Auto Mark as Read Behavior
        const isUnread = fullArticle.is_read === false || fullArticle.is_read === 0 || fullArticle.is_unread === true;
        if (isUnread) {
          const delaySec = store.get("readDelaySec") ?? 3;

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

              const articles = store.get("articles") || [];
              const a = articles.find((item) => item.id === articleId);
              if (a) {
                a.is_read = 1;
                a.is_unread = false;
              }
              store.set("articles", [...articles]);

              // Update feed counters
              const feeds = store.get("feeds") || [];
              const f = feeds.find((feed) => feed.id === fullArticle.feed_id);
              if (f && f.unread_count > 0) {
                f.unread_count = Math.max(0, f.unread_count - 1);
                store.set("feeds", [...feeds]);
              }
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
        console.error("Failed to load article details:", err);
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
          await api.markAllRead(parseInt(id, 10), null);
        } else if (type === "category") {
          const catId = id === "uncategorized" ? null : parseInt(id, 10);
          await api.markAllRead(null, catId);
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

      let pollTimer = setInterval(async () => {
        try {
          const prog = await api.getRefreshProgress();
          if (prog && prog.is_running) {
            const total = Math.max(1, prog.total_feeds || 1);
            const done = prog.completed_feeds || 0;
            const pct = Math.min(100, Math.max(0, Math.round((done / total) * 100)));
            let currentName = prog.current_feed_name || t("status.connecting");
            if (currentName.length > 20) currentName = currentName.slice(0, 18) + "...";
            if (progressFill) progressFill.style.width = `${pct}%`;
            if (progressPercent) progressPercent.textContent = `${pct}%`;
            if (progressMsg) progressMsg.textContent = `[${done}/${total}] ${currentName} (+${prog.new_articles_count || 0})`;
          }
        } catch (_) {}
      }, 120);

      try {
        let res = null;
        if (type === "feed") {
          res = await api.refreshFeed(parseInt(id, 10));
        } else if (type === "category") {
          if (id === "uncategorized") {
            res = await api.refreshFeeds(null, null);
          } else {
            res = await api.refreshCategory(parseInt(id, 10));
          }
        }
        clearInterval(pollTimer);
        await this.reloadFeedsAndCounts();
        await this.loadArticles();

        const updated = (res && typeof res.updated_feeds === "number") ? res.updated_feeds : 1;
        const newArts = (res && typeof res.new_articles === "number") ? res.new_articles : 0;
        const targetLabel = name || (type === "category" ? t("status.cat_channels") : t("status.feed_source"));
        const msg = newArts > 0
          ? t("status.scope_refresh_new", { label: targetLabel, updated, new: newArts })
          : t("status.scope_refresh_latest", { label: targetLabel, updated });

        if (progressPill && progressMsg) {
          progressPill.classList.add("finished");
          if (progressFill) progressFill.style.width = "100%";
          if (progressPercent) progressPercent.textContent = "100%";
          progressMsg.textContent = `✓ ${msg}`;
          setTimeout(() => {
            if (progressPill.classList.contains("finished")) {
              progressPill.style.display = "none";
              progressPill.classList.remove("finished");
            }
          }, 5000);
        }
      } catch (err) {
        clearInterval(pollTimer);
        const errText = (err && (err.detail || err.message)) || String(err || t("status.unknown_error"));
        if (progressPill && progressMsg) {
          progressMsg.textContent = t("status.refresh_failed", { error: errText });
        }
        if (indicatorEl) indicatorEl.style.backgroundColor = "var(--accent-red, #ef4444)";
      } finally {
        clearInterval(pollTimer);
        if (buttonEl) buttonEl.classList.remove("spinning");
        this.updateStatusBar();
      }
    });

    // Escape Key to Reset Filter / Clear Lock
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        const hasOpenModal = document.querySelector(".modal-overlay.open");
        if (!hasOpenModal && store.get("activeFilter") !== "all") {
          this.resetFilterToAll();
        }
      }
    });
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
      const me = await api.getMe();
      store.set("user", me);
      const userBadge = document.getElementById("user-status-name");
      if (userBadge) userBadge.textContent = me.username;

      // Hydrate settings from user profile if available
      if (me.settings && typeof me.settings === "object" && Object.keys(me.settings).length > 0) {
        if (me.settings.theme) {
          store.set("theme", me.settings.theme);
          this.applyTheme(me.settings.theme);
        }
        if (me.settings.fontSize) {
          store.set("fontSize", me.settings.fontSize);
        }
        if (me.settings.fontFamily) {
          store.set("fontFamily", me.settings.fontFamily);
        }
        if (me.settings.readerFontSize !== undefined) {
          store.set("readerFontSize", me.settings.readerFontSize);
        }
        if (me.settings.listFontSize !== undefined) {
          store.set("listFontSize", me.settings.listFontSize);
        }
        if (me.settings.treeFontSize !== undefined) {
          store.set("treeFontSize", me.settings.treeFontSize);
        }
        this.applyTypography();
        if (me.settings.readDelaySec !== undefined) {
          store.set("readDelaySec", me.settings.readDelaySec);
        }
        if (me.settings.autoNextCategory !== undefined) {
          store.set("autoNextCategory", me.settings.autoNextCategory);
        }
        if (me.settings.customKeybindings) {
          store.set("customKeybindings", me.settings.customKeybindings);
        }
        if (me.settings.hideEmptyFeeds !== undefined) {
          store.set("hideEmptyFeeds", me.settings.hideEmptyFeeds);
        }
        if (me.settings.markReadOnFeedSwitch !== undefined) {
          store.set("markReadOnFeedSwitch", me.settings.markReadOnFeedSwitch);
        }
        if (me.settings.refreshOnStartup !== undefined) {
          store.set("refreshOnStartup", me.settings.refreshOnStartup);
        }
        if (me.settings.retentionDays !== undefined) {
          store.set("retentionDays", me.settings.retentionDays);
        }
        if (me.settings.pollIntervalMinutes !== undefined) {
          store.set("pollIntervalMinutes", me.settings.pollIntervalMinutes);
        }
        if (me.settings.imageVaultEnabled !== undefined) {
          store.set("imageVaultEnabled", me.settings.imageVaultEnabled);
        }
        if (me.settings.columnOrder && Array.isArray(me.settings.columnOrder)) {
          store.set("columnOrder", me.settings.columnOrder);
        }
        if (me.settings.columnWidths && typeof me.settings.columnWidths === "object") {
          store.set("columnWidths", me.settings.columnWidths);
        }
        if (me.settings.readerToolbarOrder && Array.isArray(me.settings.readerToolbarOrder)) {
          store.set("readerToolbarOrder", me.settings.readerToolbarOrder);
        }
        if (me.settings.tagsPosition) {
          store.set("tagsPosition", me.settings.tagsPosition);
        }
        if (me.settings.tagsPaneHeight !== undefined) {
          store.set("tagsPaneHeight", me.settings.tagsPaneHeight);
        }
      }

      await this.reloadFeedsAndCounts();
      await this.loadArticles();

      // QuiteRSS Feature: Auto refresh all feeds on startup/login
      if (store.get("refreshOnStartup") !== false) {
        setTimeout(() => {
          const btnRefresh = document.getElementById("btn-refresh-all");
          if (btnRefresh && !btnRefresh.classList.contains("busy")) {
            btnRefresh.click();
          }
        }, 600);
      }
    } catch (_) {
      this.modals.openModal("modal-login");
    }
  }

  async reloadFeedsAndCounts() {
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
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

    // Dynamic Title Unread Badge (QuiteRSS Alignment)
    document.title = totalUnread > 0 ? `(${totalUnread}) OmniRSS` : "OmniRSS";

    connTextEl.textContent = t("status.conn_ready_summary", { count: totalFeeds, time: timeStr });
    if (indicatorEl) {
      indicatorEl.style.backgroundColor = "var(--accent-green, #4ade80)";
    }
  }

  async loadArticles(isAppend = false) {
    const filter = store.get("activeFilter");
    const feedId = store.get("activeFeedId");
    const categoryId = store.get("activeCategoryId");
    const tagId = store.get("activeTagId");
    const search = store.get("searchQuery");
    let hideRead = store.get("hideRead");

    // 獨立分類專屬 hide_read 設定隔離，避免污染全域與其他分類
    if (filter === "category" && categoryId !== null) {
      try {
        const catPrefs = JSON.parse(localStorage.getItem(`omnirss:cat-prefs:${categoryId}`) || "{}");
        if (catPrefs.hide_read !== undefined) {
          hideRead = Boolean(catPrefs.hide_read);
        }
      } catch (_) {}
    }

    // 更新頂部「隱藏已讀」按鈕外觀狀態以匹配當前視圖有效狀態
    const btnHideRead = document.getElementById("btn-toggle-hide-read");
    if (btnHideRead) {
      btnHideRead.classList.toggle("active", Boolean(hideRead));
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
    if (search && search.trim()) {
      params.search = search.trim();
    }
    // 智慧已讀過濾：若 filter 為 "unread" 或 hideRead 為 true 則僅拉取未讀文章
    const shouldFilterUnread = filter === "unread" || Boolean(hideRead);
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
