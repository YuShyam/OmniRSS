/**
 * OmniRSS 內容閱讀器元件 (Reader View Component).
 *
 * Implements:
 * - Compact draggable action toolbar with DnD reordering
 * - Dynamic toolbar items via PluginRegistry & readerToolbarOrder
 * - Two-way state sync for star & read operations
 * - Gemini AI summary & extensible panel containers
 * - Sanitized HTML article body rendering
 */

import { store } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";
import { parseUtcDate } from "../date_utils.js";
import { pluginRegistry } from "../plugin_registry.js";

export class ReaderView {
  constructor(containerEl) {
    this.container = containerEl;
    this.draggedActionKey = null;

    this.initListeners();
  }

  initListeners() {
    store.subscribe("selectedArticle", (article) => this.render(article));
    store.subscribe("readerToolbarOrder", () => {
      const article = store.get("selectedArticle");
      if (article) this.render(article);
    });

    // Handle button actions inside reader toolbar & tags
    this.container.addEventListener("click", async (e) => {
      const article = store.get("selectedArticle");
      if (!article) return;

      // 1. Toggle Read
      const toggleReadBtn = e.target.closest("#btn-reader-toggle-read");
      if (toggleReadBtn) {
        const isCurrentUnread = article.is_read === false || article.is_read === 0 || article.is_unread === true;
        const newUnread = !isCurrentUnread;
        article.is_read = !newUnread;
        article.is_unread = newUnread;
        store.set("selectedArticle", { ...article });

        const articles = store.get("articles") || [];
        const a = articles.find((item) => item.id === article.id);
        if (a) {
          a.is_read = newUnread ? 0 : 1;
          a.is_unread = newUnread;
        }
        store.set("articles", [...articles]);

        await api.updateArticleState(article.id, { is_read: !newUnread, is_unread: newUnread });
        return;
      }

      // 2. Toggle Star (Instant 2-way sync)
      const toggleStarBtn = e.target.closest("#btn-reader-toggle-star");
      if (toggleStarBtn) {
        const newStarred = !article.is_starred;
        article.is_starred = newStarred;
        store.set("selectedArticle", { ...article });

        const articles = store.get("articles") || [];
        const a = articles.find((item) => item.id === article.id);
        if (a) a.is_starred = newStarred;
        store.set("articles", [...articles]);

        await api.updateArticleState(article.id, { is_starred: newStarred });
        window.dispatchEvent(
          new CustomEvent("omnirss:toast", {
            detail: { message: newStarred ? t("list.starred_toast") : t("list.unstarred_toast"), type: "success" },
          })
        );
        return;
      }

      // 3. Fetch Full Text
      const fetchFullBtn = e.target.closest("#btn-reader-fetch-full");
      if (fetchFullBtn) {
        fetchFullBtn.classList.add("busy");
        try {
          const updated = await api.fetchFullContent(article.id);
          store.set("selectedArticle", updated);

          const articles = store.get("articles") || [];
          const a = articles.find((item) => item.id === article.id);
          if (a) {
            a.snippet = updated.snippet;
          }
          store.set("articles", [...articles]);
          window.dispatchEvent(
            new CustomEvent("omnirss:toast", {
              detail: { message: t("reader.fetch_success"), type: "success" },
            })
          );
        } catch (err) {
          window.dispatchEvent(
            new CustomEvent("omnirss:toast", {
              detail: { message: t("reader.fetch_failed", { error: err.message }), type: "error" },
            })
          );
        } finally {
          fetchFullBtn.classList.remove("busy");
        }
        return;
      }

      // 3.5 Trash / Restore Article
      const trashBtn = e.target.closest("#btn-reader-trash");
      if (trashBtn) {
        window.dispatchEvent(new CustomEvent("omnirss:trash-article", { detail: { articleId: article.id } }));
        return;
      }

      // 3.6 Tag Article Button
      const tagBtn = e.target.closest("#btn-reader-tag");
      if (tagBtn) {
        window.dispatchEvent(new CustomEvent("omnirss:open-tag-modal", { detail: { articleId: article.id } }));
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

      // 5. Copy Link
      const copyLinkBtn = e.target.closest("#btn-reader-copy-link");
      if (copyLinkBtn) {
        const urlToCopy = article.url || article.link;
        if (urlToCopy) {
          navigator.clipboard.writeText(urlToCopy);
          window.dispatchEvent(
            new CustomEvent("omnirss:toast", {
              detail: { message: t("settings.copied"), type: "success" },
            })
          );
        }
        return;
      }

      // 6. Feed Chip Click -> Focus feed (方案 B)
      const feedChip = e.target.closest(".clickable-feed-filter");
      if (feedChip) {
        const feedId = parseInt(feedChip.dataset.feedId, 10);
        if (feedId) {
          window.dispatchEvent(new CustomEvent("omnirss:select-feed", { detail: { id: feedId } }));
        }
        return;
      }
    });

    // Toolbar Drag and Drop
    this.container.addEventListener("dragstart", (e) => {
      const btn = e.target.closest(".reader-action-drag");
      if (!btn) return;
      this.draggedActionKey = btn.dataset.actionKey;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", this.draggedActionKey);
      btn.classList.add("dragging");
    });

    this.container.addEventListener("dragover", (e) => {
      const btn = e.target.closest(".reader-action-drag");
      if (!btn || !this.draggedActionKey) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";

      const targetKey = btn.dataset.actionKey;
      if (targetKey === this.draggedActionKey) return;

      const rect = btn.getBoundingClientRect();
      const isLeft = e.clientX < rect.left + rect.width / 2;

      this.container.querySelectorAll(".reader-action-drag").forEach((el) => {
        el.classList.remove("drag-over-left", "drag-over-right");
      });

      if (isLeft) {
        btn.classList.add("drag-over-left");
      } else {
        btn.classList.add("drag-over-right");
      }
    });

    this.container.addEventListener("dragleave", (e) => {
      const btn = e.target.closest(".reader-action-drag");
      if (btn) {
        btn.classList.remove("drag-over-left", "drag-over-right");
      }
    });

    this.container.addEventListener("drop", (e) => {
      const btn = e.target.closest(".reader-action-drag");
      if (!btn || !this.draggedActionKey) return;
      e.preventDefault();

      const targetKey = btn.dataset.actionKey;
      const rect = btn.getBoundingClientRect();
      const isLeft = e.clientX < rect.left + rect.width / 2;

      this.container.querySelectorAll(".reader-action-drag").forEach((el) => {
        el.classList.remove("drag-over-left", "drag-over-right", "dragging");
      });

      if (targetKey !== this.draggedActionKey) {
        const order = [...(store.get("readerToolbarOrder") || [])];
        const srcIdx = order.indexOf(this.draggedActionKey);
        if (srcIdx !== -1) {
          order.splice(srcIdx, 1);
          let targetIdx = order.indexOf(targetKey);
          if (!isLeft) targetIdx += 1;
          order.splice(targetIdx, 0, this.draggedActionKey);
          store.set("readerToolbarOrder", order);
        }
      }

      this.draggedActionKey = null;
    });

    this.container.addEventListener("dragend", () => {
      this.container.querySelectorAll(".reader-action-drag").forEach((el) => {
        el.classList.remove("drag-over-left", "drag-over-right", "dragging");
      });
      this.draggedActionKey = null;
    });
  }

  render(article) {
    if (!article) {
      this.container.innerHTML = `
        <div class="empty-state">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
          <div>${t("reader.no_selection")}</div>
        </div>
      `;
      return;
    }

    const isStarred = article.is_starred === true;
    const isUnread = article.is_read === false || article.is_read === 0 || article.is_unread === true;
    const formattedDate = article.published_at ? parseUtcDate(article.published_at).toLocaleString() : "";
    const articleLink = article.url || article.link;

    const toolbarOrder = store.get("readerToolbarOrder") || [
      "star",
      "toggle_read",
      "tag",
      "trash",
      "fetch_full",
      "copy_link",
      "open_url",
    ];

    // Render Draggable Action Buttons from Order
    const dragSuffix = ` ${t("reader.drag_sort_suffix")}`;
    const actionButtonsHtml = toolbarOrder
      .map((actionKey) => {
        if (actionKey === "star") {
          return `
            <button class="icon-btn reader-action-drag ${isStarred ? "active starred" : ""}" id="btn-reader-toggle-star" draggable="true" data-action-key="star" title="${isStarred ? t("reader.unstar") : t("reader.star")}${dragSuffix}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="${isStarred ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
              <span>${isStarred ? t("reader.unstar") : t("reader.star")}</span>
            </button>
          `;
        }
        if (actionKey === "toggle_read") {
          return `
            <button class="icon-btn reader-action-drag" id="btn-reader-toggle-read" draggable="true" data-action-key="toggle_read" title="${isUnread ? t("reader.mark_read") : t("reader.mark_unread")}${dragSuffix}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
              <span>${isUnread ? t("reader.mark_read") : t("reader.mark_unread")}</span>
            </button>
          `;
        }
        if (actionKey === "tag") {
          return `
            <button class="icon-btn reader-action-drag" id="btn-reader-tag" draggable="true" data-action-key="tag" title="${t("reader.tag") || "Tag"}${dragSuffix}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>
              <span>${t("reader.tag") || "Tag"}</span>
            </button>
          `;
        }
        if (actionKey === "trash") {
          const isTrash = Boolean(article.is_trash) || store.get("activeFilter") === "trash";
          return `
            <button class="icon-btn reader-action-drag ${isTrash ? "danger" : ""}" id="btn-reader-trash" draggable="true" data-action-key="trash" title="${isTrash ? t("reader.restore") : t("reader.trash")}${dragSuffix}">
              ${
                isTrash
                  ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg><span>${t("reader.restore")}</span>`
                  : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg><span>${t("reader.trash")}</span>`
              }
            </button>
          `;
        }
        if (actionKey === "fetch_full") {
          return `
            <button class="icon-btn reader-action-drag" id="btn-reader-fetch-full" draggable="true" data-action-key="fetch_full" title="${t("reader.fetch_full_title")}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
              <span>${t("reader.fetch_full")}</span>
            </button>
          `;
        }
        if (actionKey === "copy_link") {
          return `
            <button class="icon-btn reader-action-drag" id="btn-reader-copy-link" draggable="true" data-action-key="copy_link" title="${t("reader.copy_link")}${dragSuffix}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              <span>${t("reader.copy_link")}</span>
            </button>
          `;
        }
        if (actionKey === "open_url") {
          return articleLink
            ? `
            <a class="icon-btn reader-action-drag" href="${articleLink}" target="_blank" rel="noopener noreferrer" draggable="true" data-action-key="open_url" title="${t("reader.open_original")}${dragSuffix}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
              <span>${t("reader.open_original")}</span>
            </a>
          `
            : "";
        }
        return "";
      })
      .join("");

    let html = `
      <!-- Compact Draggable Actions Toolbar -->
      <div class="reader-toolbar">
        <div class="reader-toolbar-group">
          ${actionButtonsHtml}
        </div>
      </div>

      <!-- Scrollable Article Content -->
      <div class="reader-scroll-area">
        <div class="article-header">
          <h1 class="article-title">
            ${articleLink ? `<a href="${articleLink}" target="_blank" rel="noopener noreferrer">${this.escape(article.title)}</a>` : this.escape(article.title)}
          </h1>

          <div class="article-meta">
            ${article.feed_title && article.feed_title !== "null" && article.feed_title !== "undefined" ? `<span class="feed-chip clickable-feed-filter" data-feed-id="${article.feed_id || ""}" title="${this.escape(article.feed_title)} (${t("columns.click_filter_feed")})">${this.escape(article.feed_title)}</span>` : ""}
            ${article.author && article.author !== "null" && article.author !== "undefined" ? `<span class="meta-item">✍️ ${this.escape(article.author)}</span>` : ""}
            ${formattedDate ? `<span class="meta-item">🕒 ${formattedDate}</span>` : ""}
            ${(article.tags || [])
              .filter((tItem) => {
                if (!tItem) return false;
                const name = typeof tItem === "object" ? tItem.name : tItem;
                return name && name !== "null" && name !== "undefined";
              })
              .map((tItem) => {
                const isObj = typeof tItem === "object" && tItem !== null;
                const name = isObj ? tItem.name : tItem;
                const color = isObj && tItem.color ? tItem.color : "#3b82f6";
                const id = isObj && tItem.id ? tItem.id : "";
                return `<span class="tag-badge-sm clickable-tag" data-tag-id="${id}" data-tag-name="${this.escape(name)}" style="background-color: ${color}22; border-color: ${color}55; color: ${color};"><span class="tag-dot" style="background-color: ${color};"></span>${this.escape(name)}</span>`;
              }).join("")}
          </div>
        </div>

        <!-- AI Summary Block (if available) -->
        ${
          article.ai_summary && article.ai_summary !== "null" && article.ai_summary !== "undefined"
            ? `
          <div class="ai-summary-card">
            <div class="ai-summary-header">
              <span class="ai-badge">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg>
                ${t("reader.ai_summary")}
              </span>
            </div>
            <div class="ai-summary-body">
              ${this.escape(article.ai_summary).replace(/\n/g, "<br>")}
            </div>
          </div>
        `
            : ""
        }

        <!-- De-fanged Main Content Body -->
        <div class="article-content">
          ${article.content_html || article.content_text || t("reader.no_content")}
        </div>
      </div>
    `;

    this.container.innerHTML = html;
  }

  escape(str) {
    if (str === null || str === undefined || str === "null" || str === "undefined") return "";
    return String(str).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }
}
