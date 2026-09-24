/**
 * OmniRSS 24px 極限緊湊文章列表元件 (List View Component).
 *
 * Implements QuiteRSS 24px single-line zero-wrap table, sortable column headers,
 * read/unread indicator, star toggling, 4-state visual indicators (Skeleton, Empty, Error),
 * and fast DOM rendering.
 */

import { store } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";

export class ListView {
  constructor(headerEl, bodyEl) {
    this.headerEl = headerEl;
    this.bodyEl = bodyEl;
    this.renderHeaders();
    this.initListeners();
  }

  initListeners() {
    store.subscribe("articles", () => this.render());
    store.subscribe("listState", () => this.render());
    store.subscribe("columns", () => {
      this.renderHeaders();
      this.render();
    });
    store.subscribe("selectedArticleId", (id) => this.updateSelection(id));
    store.subscribe("sortField", () => this.renderHeaders());
    store.subscribe("sortAsc", () => this.renderHeaders());

    // Header sorting click
    this.headerEl.addEventListener("click", (e) => {
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

    // Row selection, star click, or state card button click
    this.bodyEl.addEventListener("click", async (e) => {
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

      const starBtn = e.target.closest(".star-btn");
      if (starBtn) {
        e.stopPropagation();
        const row = starBtn.closest(".article-row");
        if (!row) return;
        const articleId = parseInt(row.dataset.id, 10);
        const isStarred = starBtn.classList.contains("starred");

        await api.updateArticleState(articleId, { is_starred: !isStarred });
        starBtn.classList.toggle("starred", !isStarred);

        const articles = store.get("articles") || [];
        const targetArt = articles.find((a) => a.id === articleId);
        if (targetArt) targetArt.is_starred = !isStarred;
        return;
      }

      const row = e.target.closest(".article-row");
      if (row) {
        const articleId = parseInt(row.dataset.id, 10);
        window.dispatchEvent(new CustomEvent("omnirss:select-article", { detail: { id: articleId } }));
      }
    });
  }

  renderHeaders() {
    const cols = store.get("columns");
    const sortField = store.get("sortField");
    const sortAsc = store.get("sortAsc");

    const getSortIcon = (field) => {
      if (sortField !== field) return "";
      return `<span class="sort-icon">${sortAsc ? "▲" : "▼"}</span>`;
    };

    let html = `
      ${cols.status ? `<div class="col-cell col-status" title="${t("columns.status")}">●</div>` : ""}
      ${cols.star ? `<div class="col-cell col-star" title="${t("columns.star")}">★</div>` : ""}
      ${cols.title ? `<div class="col-cell col-title col-header" data-field="title">${t("columns.title")} ${getSortIcon("title")}</div>` : ""}
      ${cols.feed ? `<div class="col-cell col-feed col-header" data-field="feed_title">${t("columns.feed")} ${getSortIcon("feed_title")}</div>` : ""}
      ${cols.date ? `<div class="col-cell col-date col-header" data-field="published_at">${t("columns.date")} ${getSortIcon("published_at")}</div>` : ""}
      ${cols.author ? `<div class="col-cell col-author col-header" data-field="author">${t("columns.author")} ${getSortIcon("author")}</div>` : ""}
      ${cols.tags ? `<div class="col-cell col-tags">${t("columns.tags")}</div>` : ""}
      <div class="col-cell col-picker-trigger" id="btn-col-picker" title="${t("columns.picker_title")}">⊞</div>
    `;

    this.headerEl.innerHTML = html;
  }

  sortArticles() {
    const articles = [...(store.get("articles") || [])];
    const field = store.get("sortField");
    const asc = store.get("sortAsc");

    articles.sort((a, b) => {
      let valA = a[field] || "";
      let valB = b[field] || "";
      if (field === "published_at") {
        valA = new Date(valA).getTime() || 0;
        valB = new Date(valB).getTime() || 0;
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
        <div class="skeleton-block" style="width: 120px;"></div>
        <div class="skeleton-block" style="width: 80px;"></div>
      </div>
    `
      )
      .join("");
    this.bodyEl.innerHTML = rows;
  }

  render() {
    const state = store.get("listState") || "ready";
    const articles = store.get("articles") || [];
    const feeds = store.get("feeds") || [];
    const activeFilter = store.get("activeFilter");
    const selectedId = store.get("selectedArticleId");
    const cols = store.get("columns");

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
      if (feeds.length === 0) {
        this.bodyEl.innerHTML = `
          <div class="state-card">
            <div class="state-card-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1"/></svg>
            </div>
            <div class="state-card-title">${t("empty.no_feeds_title")}</div>
            <div class="state-card-desc">${t("empty.no_feeds_desc")}</div>
            <button class="state-card-btn" id="btn-state-add-feed">${t("tree.add_feed")}</button>
          </div>
        `;
      } else if (activeFilter === "unread") {
        this.bodyEl.innerHTML = `
          <div class="state-card">
            <div class="state-card-icon success">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            </div>
            <div class="state-card-title">${t("empty.unread_title")}</div>
            <div class="state-card-desc">${t("empty.unread_desc")}</div>
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

    // 4. Normal Rows Rendering
    const html = articles.map((art) => {
      const isSelected = art.id === selectedId;
      const isUnread = art.is_read === false || art.is_read === 0 || art.is_unread === true;
      const isStarred = art.is_starred === true;
      const formattedDate = this.formatDate(art.published_at);

      return `
        <div class="article-row ${isSelected ? "selected" : ""} ${isUnread ? "unread" : ""}" data-id="${art.id}">
          ${cols.status ? `<div class="col-cell col-status">${isUnread ? '<span class="unread-dot"></span>' : ""}</div>` : ""}
          ${
            cols.star
              ? `<div class="col-cell col-star">
                  <button class="star-btn ${isStarred ? "starred" : ""}" title="★">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="${isStarred ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                  </button>
                </div>`
              : ""
          }
          ${cols.title ? `<div class="col-cell col-title" title="${this.escape(art.title)}">${this.escape(art.title || "無標題")}</div>` : ""}
          ${cols.feed ? `<div class="col-cell col-feed feed-name" title="${this.escape(art.feed_title)}">${this.escape(art.feed_title || "")}</div>` : ""}
          ${cols.date ? `<div class="col-cell col-date text-muted">${formattedDate}</div>` : ""}
          ${cols.author ? `<div class="col-cell col-author text-muted">${this.escape(art.author || "")}</div>` : ""}
          ${
            cols.tags
              ? `<div class="col-cell col-tags">
                  ${(art.tags || []).map((t) => `<span class="tag-badge-sm">${this.escape(t)}</span>`).join("")}
                </div>`
              : ""
          }
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
    if (!dateStr) return "";
    try {
      const d = new Date(dateStr);
      const now = new Date();
      const formatMode = store.get("dateFormat") || "smart";

      if (formatMode === "iso") {
        return d.toISOString().replace("T", " ").substring(0, 19);
      }
      if (formatMode === "relative") {
        const diffSec = Math.floor((now.getTime() - d.getTime()) / 1000);
        if (diffSec < 60) return "剛剛";
        if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分鐘前`;
        if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} 小時前`;
        if (diffSec < 2592000) return `${Math.floor(diffSec / 86400)} 天前`;
      }

      // 智慧跨年格式 (Smart format)
      const isToday = d.toDateString() === now.toDateString();
      const timePart = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      if (isToday) {
        return timePart;
      }
      const isCurrentYear = d.getFullYear() === now.getFullYear();
      if (isCurrentYear) {
        return `${d.getMonth() + 1}/${d.getDate()} ${timePart}`;
      }
      return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${timePart}`;
    } catch (_) {
      return dateStr;
    }
  }

  escape(str) {
    if (!str) return "";
    return str.replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }
}
