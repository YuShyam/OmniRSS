/**
 * OmniRSS 24px 極限緊湊文章列表元件 (List View Component).
 *
 * Implements QuiteRSS 24px single-line zero-wrap table, sortable column headers,
 * read/unread indicator, star toggling, and fast DOM rendering.
 */

import { store } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";

export class ListView {
  constructor(headerEl, bodyEl) {
    this.headerEl = headerEl;
    this.bodyEl = bodyEl;
    this.initListeners();
  }

  initListeners() {
    store.subscribe("articles", () => this.render());
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

    // Row selection and star click
    this.bodyEl.addEventListener("click", async (e) => {
      const starBtn = e.target.closest(".star-btn");
      if (starBtn) {
        e.stopPropagation();
        const row = starBtn.closest(".article-row");
        if (!row) return;
        const articleId = parseInt(row.dataset.id, 10);
        const isStarred = starBtn.classList.contains("starred");

        await api.updateArticleState(articleId, { is_starred: !isStarred });
        starBtn.classList.toggle("starred", !isStarred);

        const articles = store.get("articles");
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

  render() {
    const articles = store.get("articles") || [];
    const cols = store.get("columns");
    const selectedId = store.get("selectedArticleId");

    if (articles.length === 0) {
      this.bodyEl.innerHTML = `
        <div class="empty-state">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
          <div>尚無文章或當前視圖為空</div>
        </div>
      `;
      return;
    }

    const html = articles.map((art) => {
      const isSelected = art.id === selectedId;
      const isUnread = art.is_unread !== false;
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
        // Scroll into view if needed
        row.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    });
  }

  formatDate(dateStr) {
    if (!dateStr) return "";
    try {
      const d = new Date(dateStr);
      const now = new Date();
      const isToday = d.toDateString() === now.toDateString();
      if (isToday) {
        return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      }
      return `${d.getMonth() + 1}/${d.getDate()} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    } catch (_) {
      return dateStr;
    }
  }

  escape(str) {
    if (!str) return "";
    return str.replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }
}
