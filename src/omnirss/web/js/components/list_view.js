/**
 * OmniRSS 24px 極限緊湊文章列表元件 (List View Component).
 *
 * Implements:
 * - QuiteRSS 24px single-line zero-wrap table
 * - Native HTML5 drag-and-drop column header reordering with live row updates
 * - Dynamic columns via PluginRegistry & columnOrder state
 * - Quick Actions Column ([↑ Top] [↓ Bottom] [✓ Mark Read])
 * - 4-state visual indicators (Skeleton, Empty, Error)
 * - Two-way star & read state synchronization
 */

import { store } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";
import { parseUtcDate, formatSmartDate } from "../date_utils.js";
import { pluginRegistry } from "../plugin_registry.js";

export class ListView {
  constructor(headerEl, bodyEl) {
    this.headerEl = headerEl;
    this.bodyEl = bodyEl;
    this.draggedColKey = null;

    this.applyColumnWidthsStyle();
    this.renderHeaders();
    this.initListeners();
    this.initDragAndDrop();
    this.initColumnResizing();
    this.initContextMenu();
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

  applyColumnWidthsStyle() {
    let styleEl = document.getElementById("omnirss-column-widths-style");
    if (!styleEl) {
      styleEl = document.createElement("style");
      styleEl.id = "omnirss-column-widths-style";
      document.head.appendChild(styleEl);
    }

    const widths = store.get("columnWidths") || {};
    const rules = [];

    for (const [colKey, width] of Object.entries(widths)) {
      if (colKey === "title") {
        if (width && width > 0) {
          rules.push(`.col-title { flex: 0 0 ${width}px !important; width: ${width}px !important; }`);
        } else {
          rules.push(`.col-title { flex: 1 1 0px !important; min-width: 150px !important; }`);
        }
      } else if (width && width > 0) {
        rules.push(`.col-${colKey} { width: ${width}px !important; min-width: ${Math.min(width, 20)}px; }`);
      }
    }

    styleEl.textContent = rules.join("\n");
  }

  initListeners() {
    store.subscribe("articles", () => this.render());
    store.subscribe("listState", () => this.render());
    store.subscribe("columnWidths", () => this.applyColumnWidthsStyle());
    store.subscribe("columnOrder", () => {
      this.renderHeaders();
      this.render();
    });
    store.subscribe("columns", () => {
      this.renderHeaders();
      this.render();
    });
    store.subscribe("selectedArticleId", (id) => this.updateSelection(id));
    store.subscribe("sortField", () => this.renderHeaders());
    store.subscribe("sortAsc", () => this.renderHeaders());

    // Header sorting click & quick action buttons
    this.headerEl.addEventListener("click", (e) => {
      // Ignore click if clicking column resizer
      if (e.target.closest(".col-resizer")) return;

      // 1. Column Picker button
      const pickerBtn = e.target.closest("#btn-col-picker");
      if (pickerBtn) return; // Handled by ColumnPicker

      // 2. Header Quick Actions (Scroll Top / Bottom / Mark Read View)
      const actionBtn = e.target.closest(".btn-col-action");
      if (actionBtn) {
        e.stopPropagation();
        const id = actionBtn.id;
        if (id === "btn-col-scroll-top") {
          this.bodyEl.scrollTo({ top: 0, behavior: "smooth" });
        } else if (id === "btn-col-scroll-bottom") {
          this.bodyEl.scrollTo({ top: this.bodyEl.scrollHeight, behavior: "smooth" });
        } else if (id === "btn-col-mark-read-view") {
          const btnMarkAll = document.getElementById("btn-mark-all-read");
          if (btnMarkAll) btnMarkAll.click();
        }
        return;
      }

      // 3. Header Sorting click
      const headerCell = e.target.closest(".col-header");
      if (!headerCell) return;

      const field = headerCell.dataset.field;
      if (!field) return;

      const currentField = store.get("sortField");
      const currentAsc = store.get("sortAsc");

      if (currentField === field) {
        store.set("sortAsc", !currentAsc);
      } else {
        store.update({ sortField: field, sortAsc: false });
      }

      this.sortArticles();
    });

    // Row clicks: Star click, Row Action clicks, Tag clicks, Feed Filter clicks, Selection
    this.bodyEl.addEventListener("click", async (e) => {
      // 1. Error / Empty State Action Buttons
      const retryBtn = e.target.closest("#btn-state-retry");
      if (retryBtn) {
        window.dispatchEvent(new CustomEvent("omnirss:filter-changed"));
        return;
      }

      const addFeedBtn = e.target.closest("#btn-state-add-feed");
      if (addFeedBtn) {
        window.dispatchEvent(new CustomEvent("omnirss:open-modal", { detail: { modalId: "modal-add-feed" } }));
        return;
      }

      // 2. Row Actions Capsule (Fetch full, Open URL, Trash, Read, Top, Bottom)
      const rowActionBtn = e.target.closest(".btn-row-action");
      if (rowActionBtn) {
        e.stopPropagation();
        const action = rowActionBtn.dataset.action;
        const row = rowActionBtn.closest(".article-row");
        const articleId = row ? parseInt(row.dataset.id, 10) : null;
        if (!articleId && !["top", "bottom"].includes(action)) return;

        if (action === "tag") {
          window.dispatchEvent(new CustomEvent("omnirss:open-tag-modal", { detail: { articleId } }));
        } else if (action === "fetch-full") {
          window.dispatchEvent(new CustomEvent("omnirss:fetch-full-text", { detail: { id: articleId, articleId } }));
        } else if (action === "open-url") {
          const articles = store.get("articles") || [];
          const art = articles.find((a) => a.id === articleId);
          if (art && art.url) {
            window.open(art.url, "_blank", "noopener,noreferrer");
          }
        } else if (action === "trash") {
          window.dispatchEvent(new CustomEvent("omnirss:trash-article", { detail: { articleId } }));
        } else if (action === "toggle-read") {
          await this.toggleArticleRead(articleId);
        } else if (action === "top") {
          this.bodyEl.scrollTo({ top: 0, behavior: "smooth" });
        } else if (action === "bottom") {
          this.bodyEl.scrollTo({ top: this.bodyEl.scrollHeight, behavior: "smooth" });
        }
        return;
      }

      // 3. Star Button Click (Instant 2-way UI & State Sync)
      const starBtn = e.target.closest(".star-btn");
      if (starBtn) {
        e.stopPropagation();
        const row = starBtn.closest(".article-row");
        if (!row) return;
        const articleId = parseInt(row.dataset.id, 10);
        await this.toggleArticleStar(articleId, starBtn);
        return;
      }

      // 4. Tag Badge Click
      const tagBadge = e.target.closest(".clickable-tag");
      if (tagBadge) {
        e.stopPropagation();
        const tagId = tagBadge.dataset.tagId;
        const tagName = tagBadge.dataset.tagName;
        if (tagId) {
          window.dispatchEvent(new CustomEvent("omnirss:select-tag", { detail: { id: parseInt(tagId, 10), name: tagName } }));
        }
        return;
      }

      // 5. Feed Link Click (方案 A: 列表點擊來源頻道聚焦)
      const feedLink = e.target.closest(".clickable-feed-filter");
      if (feedLink) {
        e.stopPropagation();
        const feedId = parseInt(feedLink.dataset.feedId, 10);
        if (feedId) {
          window.dispatchEvent(new CustomEvent("omnirss:select-feed", { detail: { id: feedId } }));
        }
        return;
      }

      // 6. Normal Row Selection
      const row = e.target.closest(".article-row");
      if (row) {
        const articleId = parseInt(row.dataset.id, 10);
        window.dispatchEvent(new CustomEvent("omnirss:select-article", { detail: { id: articleId } }));
      }
    });

    // Double click to fetch full text (QuiteRSS Alignment)
    this.bodyEl.addEventListener("dblclick", (e) => {
      const row = e.target.closest(".article-row");
      if (!row) return;
      const articleId = parseInt(row.dataset.id, 10);
      if (articleId) {
        window.dispatchEvent(new CustomEvent("omnirss:fetch-full-text", { detail: { id: articleId, articleId } }));
      }
    });
  }

  /**
   * 初始化表頭拖曳欄寬 (QuiteRSS-style Column Width Resizing)
   */
  initColumnResizing() {
    let isResizing = false;
    let currentResizer = null;
    let currentColKey = null;
    let startX = 0;
    let startWidth = 0;

    const minWidthMap = {
      status: 20,
      star: 20,
      actions: 50,
      title: 100,
      feed: 60,
      date: 60,
      author: 50,
      tags: 50,
    };

    const defaultWidthMap = {
      status: 28,
      star: 28,
      title: 0,
      actions: 80,
      feed: 140,
      date: 120,
      author: 100,
      tags: 100,
    };

    this.headerEl.addEventListener("mousedown", (e) => {
      const resizer = e.target.closest(".col-resizer");
      if (!resizer) return;

      e.stopPropagation();
      e.preventDefault();

      isResizing = true;
      currentResizer = resizer;
      currentColKey = resizer.dataset.colKey;
      const headerCell = resizer.closest(".col-header");
      startX = e.clientX;
      startWidth = headerCell.getBoundingClientRect().width;

      resizer.classList.add("resizing");
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    });

    // 雙擊欄寬調整把手：自動恢復預設寬度
    this.headerEl.addEventListener("dblclick", (e) => {
      const resizer = e.target.closest(".col-resizer");
      if (!resizer) return;

      e.stopPropagation();
      const colKey = resizer.dataset.colKey;
      const widths = { ...(store.get("columnWidths") || defaultWidthMap) };
      widths[colKey] = defaultWidthMap[colKey] ?? 100;
      store.set("columnWidths", widths);
      this.applyColumnWidthsStyle();
      window.dispatchEvent(new CustomEvent("omnirss:column-widths-changed"));
    });

    window.addEventListener("mousemove", (e) => {
      if (!isResizing || !currentColKey) return;
      e.preventDefault();

      const delta = e.clientX - startX;
      const minW = minWidthMap[currentColKey] || 40;
      const newWidth = Math.max(minW, Math.round(startWidth + delta));

      const widths = { ...(store.get("columnWidths") || defaultWidthMap) };
      widths[currentColKey] = newWidth;

      // 即時套用 Style 節點，維持 60fps 絲滑拖曳
      store.state.columnWidths = widths;
      this.applyColumnWidthsStyle();
    });

    window.addEventListener("mouseup", () => {
      if (!isResizing) return;
      isResizing = false;
      if (currentResizer) {
        currentResizer.classList.remove("resizing");
        currentResizer = null;
      }
      document.body.style.cursor = "";
      document.body.style.userSelect = "";

      if (currentColKey) {
        const widths = store.state.columnWidths;
        store.set("columnWidths", { ...widths });
        window.dispatchEvent(new CustomEvent("omnirss:column-widths-changed"));
        currentColKey = null;
      }
    });
  }

  /**
   * 初始化文章列表右鍵選單 (Right-Click Context Menu)
   */
  initContextMenu() {
    const removeMenu = () => {
      const existing = document.querySelector(".article-context-menu");
      if (existing) existing.remove();
    };

    document.addEventListener("click", removeMenu);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") removeMenu();
    });

    this.bodyEl.addEventListener("contextmenu", (e) => {
      const row = e.target.closest(".article-row");
      if (!row) return;

      e.preventDefault();
      e.stopPropagation();
      removeMenu();

      const articleId = parseInt(row.dataset.id, 10);
      const articles = store.get("articles") || [];
      const artIdx = articles.findIndex((a) => a.id === articleId);
      const art = articles[artIdx];
      if (!art) return;

      const isStarred = Boolean(art.is_starred);
      const isUnread = art.is_read === false || art.is_read === 0 || art.is_unread === true;
      const isTrash = Boolean(art.is_trash) || store.get("activeFilter") === "trash";

      const menu = document.createElement("div");
      menu.className = "article-context-menu";

      menu.innerHTML = `
        <div class="context-menu-item" data-action="mark-above-read">
          <span>⬆</span>
          <span>${t("list.mark_above_read")}</span>
        </div>
        <div class="context-menu-item" data-action="mark-below-read">
          <span>⬇</span>
          <span>${t("list.mark_below_read")}</span>
        </div>
        <div class="context-menu-divider"></div>
        <div class="context-menu-item" data-action="toggle-read">
          <span>${isUnread ? "✓" : "●"}</span>
          <span>${isUnread ? t("list.mark_read") : t("list.mark_unread")}</span>
        </div>
        <div class="context-menu-item" data-action="toggle-star">
          <span>★</span>
          <span>${isStarred ? t("list.unstar") : t("list.star")}</span>
        </div>
        <div class="context-menu-item" data-action="open-tags">
          <span>🏷️</span>
          <span>${t("list.set_tags")}</span>
        </div>
        <div class="context-menu-divider"></div>
        ${
          isTrash
            ? `
          <div class="context-menu-item" data-action="restore-article">
            <span>♻️</span>
            <span>${t("list.restore")}</span>
          </div>
          <div class="context-menu-item" data-action="delete-permanent" style="color: var(--accent-red, #f87171);">
            <span>❌</span>
            <span>${t("list.delete_perm")}</span>
          </div>
        `
            : `
          <div class="context-menu-item" data-action="trash-article" style="color: var(--accent-red, #f87171);">
            <span>🗑️</span>
            <span>${t("list.trash")}</span>
          </div>
        `
        }
        <div class="context-menu-divider"></div>
        <div class="context-menu-item" data-action="copy-link">
          <span>🔗</span>
          <span>${t("list.copy_link")}</span>
        </div>
        <div class="context-menu-item" data-action="open-url">
          <span>🌐</span>
          <span>${t("list.open_browser")}</span>
        </div>
      `;

      document.body.appendChild(menu);
      const menuWidth = 220;
      const menuHeight = 290;
      let x = e.clientX;
      let y = e.clientY;
      if (x + menuWidth > window.innerWidth) x = window.innerWidth - menuWidth - 8;
      if (y + menuHeight > window.innerHeight) y = window.innerHeight - menuHeight - 8;
      menu.style.left = `${Math.max(8, x)}px`;
      menu.style.top = `${Math.max(8, y)}px`;

      menu.addEventListener("click", async (menuEvt) => {
        menuEvt.stopPropagation();
        const item = menuEvt.target.closest(".context-menu-item");
        if (!item) return;
        const action = item.dataset.action;
        removeMenu();

        if (action === "mark-above-read") {
          await this.markRangeRead(0, artIdx);
        } else if (action === "mark-below-read") {
          await this.markRangeRead(artIdx, articles.length - 1);
        } else if (action === "toggle-read") {
          await this.toggleArticleRead(articleId);
        } else if (action === "toggle-star") {
          const starBtn = row.querySelector(".star-btn");
          await this.toggleArticleStar(articleId, starBtn);
        } else if (action === "open-tags") {
          window.dispatchEvent(new CustomEvent("omnirss:open-article-tags", { detail: { article: art } }));
        } else if (action === "trash-article" || action === "restore-article") {
          window.dispatchEvent(new CustomEvent("omnirss:trash-article", { detail: { articleId } }));
        } else if (action === "delete-permanent") {
          window.dispatchEvent(new CustomEvent("omnirss:delete-article-permanent", { detail: { articleId } }));
        } else if (action === "copy-link") {
          if (art.url) {
            try {
              await navigator.clipboard.writeText(art.url);
              window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("list.link_copied"), type: "success" } }));
            } catch (_) {}
          }
        } else if (action === "open-url") {
          if (art.url) window.open(art.url, "_blank", "noopener,noreferrer");
        }
      });
    });
  }

  async markRangeRead(startIndex, endIndex) {
    try {
      const articles = [...(store.get("articles") || [])];
      const start = Math.max(0, Math.min(startIndex, endIndex));
      const end = Math.min(articles.length - 1, Math.max(startIndex, endIndex));
      const targetArticles = articles.slice(start, end + 1);
      const unreadTargets = targetArticles.filter((a) => a.is_read === false || a.is_read === 0 || a.is_unread === true);

      if (unreadTargets.length === 0) {
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("list.all_in_scope_read"), type: "info" } }));
        return;
      }

      const targetIds = unreadTargets.map((a) => a.id);

      // Optimistic state update
      targetArticles.forEach((a) => {
        a.is_read = 1;
        a.is_unread = false;
      });
      store.set("articles", articles);

      await api.markAllRead(null, null, targetIds);
      window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
      window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("list.marked_count_read", { count: targetIds.length }), type: "success" } }));
    } catch (err) {
      console.error("Failed to mark range read:", err);
      window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("list.batch_mark_failed", { error: err.message }), type: "error" } }));
    }
  }

  /**
   * 初始化表頭拖曳換位 (HTML5 Drag & Drop Column Reordering)
   */
  initDragAndDrop() {
    this.headerEl.addEventListener("dragstart", (e) => {
      if (e.target.closest(".col-resizer")) {
        e.preventDefault();
        return;
      }
      const header = e.target.closest(".col-header-drag");
      if (!header) return;
      this.draggedColKey = header.dataset.colKey;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", this.draggedColKey);
      header.classList.add("dragging");
    });

    this.headerEl.addEventListener("dragover", (e) => {
      const header = e.target.closest(".col-header-drag");
      if (!header || !this.draggedColKey) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";

      const targetColKey = header.dataset.colKey;
      if (targetColKey === this.draggedColKey) return;

      const rect = header.getBoundingClientRect();
      const midPoint = rect.left + rect.width / 2;
      const isLeft = e.clientX < midPoint;

      this.headerEl.querySelectorAll(".col-header-drag").forEach((el) => {
        el.classList.remove("drag-over-left", "drag-over-right");
      });

      if (isLeft) {
        header.classList.add("drag-over-left");
      } else {
        header.classList.add("drag-over-right");
      }
    });

    this.headerEl.addEventListener("dragleave", (e) => {
      const header = e.target.closest(".col-header-drag");
      if (header) {
        header.classList.remove("drag-over-left", "drag-over-right");
      }
    });

    this.headerEl.addEventListener("drop", (e) => {
      const header = e.target.closest(".col-header-drag");
      if (!header || !this.draggedColKey) return;
      e.preventDefault();

      const targetColKey = header.dataset.colKey;
      const rect = header.getBoundingClientRect();
      const isLeft = e.clientX < rect.left + rect.width / 2;

      this.headerEl.querySelectorAll(".col-header-drag").forEach((el) => {
        el.classList.remove("drag-over-left", "drag-over-right", "dragging");
      });

      if (targetColKey !== this.draggedColKey) {
        const order = [...(store.get("columnOrder") || [])];
        const srcIdx = order.indexOf(this.draggedColKey);
        if (srcIdx !== -1) {
          order.splice(srcIdx, 1);
          let targetIdx = order.indexOf(targetColKey);
          if (!isLeft) targetIdx += 1;
          order.splice(targetIdx, 0, this.draggedColKey);
          store.set("columnOrder", order);
          window.dispatchEvent(new CustomEvent("omnirss:column-order-changed"));
        }
      }

      this.draggedColKey = null;
    });

    this.headerEl.addEventListener("dragend", () => {
      this.headerEl.querySelectorAll(".col-header-drag").forEach((el) => {
        el.classList.remove("drag-over-left", "drag-over-right", "dragging");
      });
      this.draggedColKey = null;
    });
  }

  async toggleArticleStar(articleId, starBtnEl) {
    try {
      const articles = store.get("articles") || [];
      const art = articles.find((a) => a.id === articleId);
      const isStarred = art ? Boolean(art.is_starred) : starBtnEl.classList.contains("starred");
      const nextStarred = !isStarred;

      // 1. Optimistic UI update
      if (starBtnEl) {
        starBtnEl.classList.toggle("starred", nextStarred);
        const svg = starBtnEl.querySelector("svg");
        if (svg) svg.setAttribute("fill", nextStarred ? "currentColor" : "none");
      }

      if (art) art.is_starred = nextStarred;
      store.set("articles", [...articles]);

      // 2. Sync with selectedArticle in reader
      const selected = store.get("selectedArticle");
      if (selected && selected.id === articleId) {
        selected.is_starred = nextStarred;
        store.set("selectedArticle", { ...selected });
      }

      // 2.5 Update dynamic starredCount
      store.set("starredCount", Math.max(0, (store.get("starredCount") || 0) + (nextStarred ? 1 : -1)));

      // 3. Backend persistence
      await api.updateArticleState(articleId, { is_starred: nextStarred });
      window.dispatchEvent(
        new CustomEvent("omnirss:toast", {
          detail: { message: nextStarred ? t("list.starred_toast") : t("list.unstarred_toast"), type: "success" },
        })
      );
    } catch (err) {
      console.error("Failed to toggle star:", err);
    }
  }

  async toggleArticleRead(articleId) {
    try {
      const articles = store.get("articles") || [];
      const art = articles.find((a) => a.id === articleId);
      if (!art) return;

      const isUnread = art.is_read === false || art.is_read === 0 || art.is_unread === true;
      const nextRead = isUnread;

      art.is_read = nextRead ? 1 : 0;
      art.is_unread = !nextRead;
      store.set("articles", [...articles]);

      const selected = store.get("selectedArticle");
      if (selected && selected.id === articleId) {
        selected.is_read = nextRead;
        selected.is_unread = !nextRead;
        store.set("selectedArticle", { ...selected });
      }

      await api.updateArticleState(articleId, { is_read: nextRead, is_unread: !nextRead });
    } catch (err) {
      console.error("Failed to toggle read state:", err);
    }
  }

  renderHeaders() {
    const cols = store.get("columns") || {};
    const columnOrder = store.get("columnOrder") || ["status", "star", "title", "feed", "date", "author", "tags"];
    const sortField = store.get("sortField");
    const sortAsc = store.get("sortAsc");

    const getSortIcon = (field) => {
      if (sortField !== field) return "";
      return `<span class="sort-icon">${sortAsc ? "▲" : "▼"}</span>`;
    };

    const headerCells = columnOrder
      .filter((colKey) => cols[colKey] !== false)
      .map((colKey) => {
        const colDef = pluginRegistry.getListColumn(colKey);
        if (!colDef) return "";

        const label = t(colDef.label || `columns.${colKey}`);
        const sortIcon = colDef.sortField ? getSortIcon(colDef.sortField) : "";
        const content = colDef.renderHeader ? colDef.renderHeader(label, sortIcon) : label;
        const sortAttr = colDef.sortField ? `data-field="${colDef.sortField}"` : "";

        return `
          <div class="col-cell col-${colKey} col-header col-header-drag" draggable="true" data-col-key="${colKey}" ${sortAttr} title="${t("list.header_drag_hint", { label })}">
            ${content}
            <div class="col-resizer" data-col-key="${colKey}" title="${t("list.resizer_hint")}"></div>
          </div>
        `;
      })
      .join("");

    this.headerEl.innerHTML = `
      ${headerCells}
      <div class="col-cell col-picker-trigger" id="btn-col-picker" title="${t("columns.picker_title")}">⊞</div>
    `;
  }

  sortArticles() {
    const articles = [...(store.get("articles") || [])];
    const field = store.get("sortField");
    const asc = store.get("sortAsc");

    articles.sort((a, b) => {
      let valA = a[field] || "";
      let valB = b[field] || "";
      if (field === "published_at") {
        valA = parseUtcDate(valA).getTime() || 0;
        valB = parseUtcDate(valB).getTime() || 0;
      }
      if (valA < valB) return asc ? -1 : 1;
      if (valA > valB) return asc ? 1 : -1;
      return 0;
    });

    store.set("articles", articles);
  }

  renderSkeleton() {
    const rows = Array.from({ length: 6 })
      .map(
        () => `
      <div class="skeleton-row">
        <div class="skeleton-block" style="width: 14px; height: 14px; border-radius: 50%;"></div>
        <div class="skeleton-block" style="width: 14px; height: 14px;"></div>
        <div class="skeleton-block" style="flex: 1; max-width: 45%;"></div>
        <div class="skeleton-block" style="width: 80px;"></div>
        <div class="skeleton-block" style="width: 120px;"></div>
      </div>
    `
      )
      .join("");
    this.bodyEl.innerHTML = rows;
  }

  render() {
    const state = store.get("listState") || "ready";
    const rawArticles = store.get("articles") || [];
    // Defensive deduplication by article ID
    const seenIds = new Set();
    const articles = rawArticles.filter((a) => {
      if (!a || a.id === undefined || seenIds.has(a.id)) return false;
      seenIds.add(a.id);
      return true;
    });
    const feeds = store.get("feeds") || [];
    const activeFilter = store.get("activeFilter");
    const selectedId = store.get("selectedArticleId");
    const cols = store.get("columns") || {};
    const columnOrder = store.get("columnOrder") || ["status", "star", "title", "feed", "date", "author", "tags"];

    // 1. Loading State
    if (state === "loading") {
      this.renderSkeleton();
      return;
    }

    // 2. Error State
    if (state === "error") {
      const errorMsg = store.get("listErrorMsg") || t("error.title");
      this.bodyEl.innerHTML = `
        <div class="state-card">
          <div class="state-card-icon error">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          </div>
          <div class="state-card-title">${errorMsg}</div>
          <button class="state-card-btn" id="btn-state-retry">${t("error.retry_btn")}</button>
        </div>
      `;
      return;
    }

    // 3. Empty States
    if (articles.length === 0) {
      const search = store.get("searchQuery");
      if (search && search.trim()) {
        this.bodyEl.innerHTML = `
          <div class="state-card">
            <div class="state-card-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            </div>
            <div class="state-card-title">${t("empty.search_title", { keyword: this.escape(search.trim()) })}</div>
            <div class="state-card-desc">${t("empty.search_desc")}</div>
            <button class="state-card-btn" id="btn-clear-search">${t("empty.search_clear_btn")}</button>
          </div>
        `;
        const btnClear = this.bodyEl.querySelector("#btn-clear-search");
        if (btnClear) {
          btnClear.addEventListener("click", () => {
            const searchInput = document.getElementById("global-search");
            if (searchInput) searchInput.value = "";
            store.set("searchQuery", "");
            window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
          });
        }
        return;
      }

      if (feeds.length === 0) {
        this.bodyEl.innerHTML = `
          <div class="state-card">
            <div class="state-card-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1"/></svg>
            </div>
            <div class="state-card-title">${t("empty.no_feeds_title")}</div>
            <div class="state-card-desc">${t("empty.no_feeds_desc")}</div>
            <button class="state-card-btn" id="btn-state-add-feed">${t("empty.no_feeds_btn")}</button>
          </div>
        `;
      } else if (activeFilter === "unread") {
        this.bodyEl.innerHTML = `
          <div class="state-card">
            <div class="state-card-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            </div>
            <div class="state-card-title">${t("empty.all_read_title")}</div>
            <div class="state-card-desc">${t("empty.all_read_desc")}</div>
          </div>
        `;
      } else if (activeFilter === "category") {
        this.bodyEl.innerHTML = `
          <div class="state-card">
            <div class="state-card-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
            </div>
            <div class="state-card-title">${t("empty.category_title")}</div>
            <div class="state-card-desc">${t("empty.category_desc")}</div>
          </div>
        `;
      } else if (activeFilter === "tag") {
        this.bodyEl.innerHTML = `
          <div class="state-card">
            <div class="state-card-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>
            </div>
            <div class="state-card-title">${t("empty.tag_title")}</div>
            <div class="state-card-desc">${t("empty.tag_desc")}</div>
          </div>
        `;
      } else if (activeFilter === "starred") {
        this.bodyEl.innerHTML = `
          <div class="state-card">
            <div class="state-card-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
            </div>
            <div class="state-card-title">${t("empty.starred_title")}</div>
            <div class="state-card-desc">${t("empty.starred_desc")}</div>
          </div>
        `;
      } else if (activeFilter === "trash") {
        this.bodyEl.innerHTML = `
          <div class="state-card">
            <div class="state-card-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            </div>
            <div class="state-card-title">${t("empty.trash_title")}</div>
            <div class="state-card-desc">${t("empty.trash_desc")}</div>
          </div>
        `;
      } else {
        this.bodyEl.innerHTML = `
          <div class="state-card">
            <div class="state-card-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
            </div>
            <div class="state-card-title">${t("empty.feed_title")}</div>
            <div class="state-card-desc">${t("empty.feed_desc")}</div>
          </div>
        `;
      }
      return;
    }

    // 4. Normal Rows Rendering (Driven by columnOrder)
    const visibleColKeys = columnOrder.filter((k) => cols[k] !== false);

    const html = articles.map((art) => {
      const isSelected = art.id === selectedId;
      const isUnread = art.is_read === false || art.is_read === 0 || art.is_unread === true;
      const formattedDate = this.formatDate(art.published_at);

      const cellHtmls = visibleColKeys.map((colKey) => {
        const colDef = pluginRegistry.getListColumn(colKey);
        if (!colDef || !colDef.renderCell) return "";
        return colDef.renderCell(art, this.escape, formattedDate);
      }).join("");

      return `
        <div class="article-row ${isSelected ? "selected" : ""} ${isUnread ? "unread" : ""}" data-id="${art.id}">
          ${cellHtmls}
          <div class="col-cell col-picker-trigger" style="visibility:hidden"></div>
        </div>
      `;
    }).join("");

    this.bodyEl.innerHTML = html;
  }

  updateSelection(selectedId) {
    this.bodyEl.querySelectorAll(".article-row").forEach((row) => {
      const id = parseInt(row.dataset.id, 10);
      const isSelected = id === selectedId;
      row.classList.toggle("selected", isSelected);
      if (isSelected) {
        row.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    });
  }

  formatDate(dateStr) {
    const formatMode = store.get("dateFormat") || "smart";
    return formatSmartDate(dateStr, formatMode);
  }

  escape(str) {
    if (str === null || str === undefined || str === "null" || str === "undefined" || !str) return "";
    return String(str).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }
}
