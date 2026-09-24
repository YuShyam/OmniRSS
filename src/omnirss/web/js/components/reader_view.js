/**
 * OmniRSS 內容閱讀器元件 (Reader View Component).
 *
 * Renders the article header, metadata, Gemini AI summary drawer/card,
 * responsive media players, and sanitized HTML article body.
 */

import { store } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";

export class ReaderView {
  constructor(containerEl) {
    this.container = containerEl;
    this.initListeners();
  }

  initListeners() {
    store.subscribe("selectedArticle", (article) => this.render(article));

    // Handle button actions inside reader toolbar
    this.container.addEventListener("click", async (e) => {
      const article = store.get("selectedArticle");
      if (!article) return;

      const toggleReadBtn = e.target.closest("#btn-reader-toggle-read");
      if (toggleReadBtn) {
        const newUnread = !article.is_unread;
        await api.updateArticleState(article.id, { is_unread: newUnread });
        article.is_unread = newUnread;
        store.set("selectedArticle", { ...article });

        const articles = store.get("articles");
        const a = articles.find((item) => item.id === article.id);
        if (a) a.is_unread = newUnread;
        store.set("articles", [...articles]);
        return;
      }

      const toggleStarBtn = e.target.closest("#btn-reader-toggle-star");
      if (toggleStarBtn) {
        const newStarred = !article.is_starred;
        await api.updateArticleState(article.id, { is_starred: newStarred });
        article.is_starred = newStarred;
        store.set("selectedArticle", { ...article });

        const articles = store.get("articles");
        const a = articles.find((item) => item.id === article.id);
        if (a) a.is_starred = newStarred;
        store.set("articles", [...articles]);
        return;
      }

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
      }
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
    const isUnread = article.is_unread !== false;
    const formattedDate = article.published_at ? new Date(article.published_at).toLocaleString() : "";
    const articleLink = article.url || article.link;

    let html = `
      <!-- Actions Toolbar -->
      <div class="reader-toolbar">
        <div class="reader-toolbar-left">
          <button class="icon-btn ${isStarred ? "active" : ""}" id="btn-reader-toggle-star" title="${t("reader.star")}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="${isStarred ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
            <span>${isStarred ? t("reader.star") : t("reader.star")}</span>
          </button>

          <button class="icon-btn" id="btn-reader-toggle-read" title="${isUnread ? t("reader.mark_read") : t("reader.mark_unread")}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
            <span>${isUnread ? t("reader.mark_read") : t("reader.mark_unread")}</span>
          </button>
        </div>

        <div class="reader-toolbar-right">
          <button class="icon-btn" id="btn-reader-copy-link" title="${t("reader.copy_link")}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          </button>

          ${
            articleLink
              ? `
            <a class="icon-btn" href="${articleLink}" target="_blank" rel="noopener noreferrer" title="${t("reader.open_original")}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
              <span>${t("reader.open_original")}</span>
            </a>
          `
              : ""
          }
        </div>
      </div>

      <!-- Scrollable Article Content -->
      <div class="reader-scroll-area">
        <div class="article-header">
          <h1 class="article-title">
            ${articleLink ? `<a href="${articleLink}" target="_blank" rel="noopener noreferrer">${this.escape(article.title)}</a>` : this.escape(article.title)}
          </h1>

          <div class="article-meta">
            ${article.feed_title ? `<span class="feed-chip">${this.escape(article.feed_title)}</span>` : ""}
            ${article.author ? `<span class="meta-item">✍️ ${this.escape(article.author)}</span>` : ""}
            ${formattedDate ? `<span class="meta-item">🕒 ${formattedDate}</span>` : ""}
            ${(article.tags || []).map((t) => `<span class="tag-badge-sm">#${this.escape(t)}</span>`).join("")}
          </div>
        </div>

        <!-- AI Summary Block (if available) -->
        ${
          article.ai_summary
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
          ${article.content_html || article.content_text || "<p>本篇無額外內文</p>"}
        </div>
      </div>
    `;

    this.container.innerHTML = html;
  }

  escape(str) {
    if (!str) return "";
    return str.replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }
}
