/**
 * OmniRSS 訂閱目錄樹元件 (Tree View Component).
 *
 * Renders smart virtual folders (All, Unread, Starred, Trash),
 * hierarchical categories, and individual feeds with unread count badges.
 */

import { store } from "../state.js";
import { t } from "../i18n.js";

export class TreeView {
  constructor(containerEl) {
    this.container = containerEl;
    this.collapsedCategories = new Set();
    this.initListeners();
  }

  initListeners() {
    store.subscribe("categories", () => this.render());
    store.subscribe("feeds", () => this.render());
    store.subscribe("hideEmptyFeeds", () => this.render());
    store.subscribe("activeFilter", () => this.updateActiveHighlight());
    store.subscribe("activeCategoryId", () => this.updateActiveHighlight());
    store.subscribe("activeFeedId", () => this.updateActiveHighlight());

    this.container.addEventListener("click", (e) => {
      // Inline Row Actions (Mark Read & Delete)
      const actionBtn = e.target.closest(".tree-row-btn");
      if (actionBtn) {
        e.stopPropagation();
        const action = actionBtn.dataset.action;
        const targetType = actionBtn.dataset.targetType;
        const targetId = actionBtn.dataset.targetId;
        const targetName = actionBtn.dataset.targetName || "";

        if (action === "mark-read") {
          window.dispatchEvent(
            new CustomEvent("omnirss:mark-read-scope", {
              detail: { type: targetType, id: targetId },
            })
          );
        } else if (action === "category-settings") {
          window.dispatchEvent(
            new CustomEvent("omnirss:open-category-settings", {
              detail: { id: parseInt(targetId, 10), name: targetName },
            })
          );
        } else if (action === "delete") {
          if (targetType === "feed") {
            const confirmMsg = t("tree.confirm_delete_feed").replace("{name}", targetName);
            if (window.confirm(confirmMsg)) {
              window.dispatchEvent(
                new CustomEvent("omnirss:delete-feed", {
                  detail: { id: parseInt(targetId, 10) },
                })
              );
            }
          } else if (targetType === "category") {
            const confirmMsg = t("tree.confirm_delete_category").replace("{name}", targetName);
            if (window.confirm(confirmMsg)) {
              window.dispatchEvent(
                new CustomEvent("omnirss:delete-category", {
                  detail: { id: parseInt(targetId, 10) },
                })
              );
            }
          }
        }
        return;
      }

      // Toggle category fold/unfold
      const toggleBtn = e.target.closest(".category-toggle");
      if (toggleBtn) {
        e.stopPropagation();
        const catId = toggleBtn.dataset.catId;
        if (this.collapsedCategories.has(catId)) {
          this.collapsedCategories.delete(catId);
        } else {
          this.collapsedCategories.add(catId);
        }
        this.render();
        return;
      }

      // Select folder/feed
      const itemEl = e.target.closest(".tree-item, .category-item, .feed-item");
      if (!itemEl) return;

      const type = itemEl.dataset.type;
      if (type === "filter") {
        store.update({
          activeFilter: itemEl.dataset.filter,
          activeCategoryId: null,
          activeFeedId: null,
          activeTag: null,
        });
        window.dispatchEvent(new CustomEvent("omnirss:filter-changed"));
      } else if (type === "category") {
        const idVal = itemEl.dataset.id === "uncategorized" ? null : parseInt(itemEl.dataset.id, 10);
        store.update({
          activeFilter: "category",
          activeCategoryId: idVal,
          activeFeedId: null,
          activeTag: null,
        });
        window.dispatchEvent(new CustomEvent("omnirss:filter-changed"));
      } else if (type === "feed") {
        store.update({
          activeFilter: "feed",
          activeCategoryId: null,
          activeFeedId: parseInt(itemEl.dataset.id, 10),
          activeTag: null,
        });
        window.dispatchEvent(new CustomEvent("omnirss:filter-changed"));
      }
    });
  }

  toggleCollapseAll() {
    const categories = store.get("categories") || [];
    const hasAnyOpen = categories.some((c) => !this.collapsedCategories.has(String(c.id)));

    if (hasAnyOpen) {
      categories.forEach((c) => this.collapsedCategories.add(String(c.id)));
      this.collapsedCategories.add("uncategorized");
      store.set("allExpanded", false);
    } else {
      this.collapsedCategories.clear();
      store.set("allExpanded", true);
    }
    this.render();
  }

  render() {
    const categories = store.get("categories") || [];
    const feeds = store.get("feeds") || [];
    const hideEmpty = store.get("hideEmptyFeeds");

    // Calculate unread statistics
    let totalUnread = 0;
    const catUnreadMap = {};

    feeds.forEach((f) => {
      const unread = f.unread_count || 0;
      totalUnread += unread;
      const catId = f.category_id ? String(f.category_id) : "uncategorized";
      catUnreadMap[catId] = (catUnreadMap[catId] || 0) + unread;
    });

    // Group feeds by category
    const feedsByCat = {};
    feeds.forEach((f) => {
      const catId = f.category_id ? String(f.category_id) : "uncategorized";
      if (!feedsByCat[catId]) feedsByCat[catId] = [];
      feedsByCat[catId].push(f);
    });

    let html = `
      <!-- Smart Virtual Folders -->
      <div class="smart-folders-group">
        <div class="tree-item" data-type="filter" data-filter="all">
          <span class="tree-icon">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1"/></svg>
          </span>
          <span class="tree-label">${t("nav.all_feeds")}</span>
          ${totalUnread > 0 ? `<span class="tree-count has-unread">(${totalUnread})</span>` : ""}
        </div>

        <div class="tree-item" data-type="filter" data-filter="unread">
          <span class="tree-icon">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          </span>
          <span class="tree-label">${t("nav.unread")}</span>
          ${totalUnread > 0 ? `<span class="tree-count has-unread">(${totalUnread})</span>` : ""}
        </div>

        <div class="tree-item" data-type="filter" data-filter="starred">
          <span class="tree-icon" style="color: var(--accent-orange)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
          </span>
          <span class="tree-label">${t("nav.starred")}</span>
        </div>

        <div class="tree-item" data-type="filter" data-filter="trash">
          <span class="tree-icon">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          </span>
          <span class="tree-label">${t("nav.trash")}</span>
        </div>
      </div>

      <!-- Categories & Subscriptions -->
      <div class="categories-group">
    `;

    // Render each category
    categories.forEach((cat) => {
      const catId = String(cat.id);
      const isCollapsed = this.collapsedCategories.has(catId);
      let catFeeds = feedsByCat[cat.id] || [];
      const catUnread = catUnreadMap[catId] || 0;

      if (hideEmpty) {
        catFeeds = catFeeds.filter((f) => (f.unread_count || 0) > 0);
        if (catFeeds.length === 0 && catUnread === 0) return;
      }

      html += `
        <div class="category-block">
          <div class="category-item" data-type="category" data-id="${cat.id}">
            <span class="category-toggle ${isCollapsed ? "collapsed" : ""}" data-cat-id="${cat.id}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
            </span>
            <span class="tree-icon">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
            </span>
            <span class="tree-label">${this.escape(cat.name)}</span>
            ${catUnread > 0 ? `<span class="tree-count has-unread">(${catUnread})</span>` : ""}
            <div class="tree-row-actions">
              ${catUnread > 0 ? `
                <button class="tree-row-btn" data-action="mark-read" data-target-type="category" data-target-id="${cat.id}" title="${t("tree.mark_node_read")}">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
                </button>
              ` : ""}
              <button class="tree-row-btn btn-settings" data-action="category-settings" data-target-type="category" data-target-id="${cat.id}" data-target-name="${this.escape(cat.name)}" title="分類設定">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
              </button>
            </div>
          </div>

          ${
            !isCollapsed
              ? `
            <div class="category-feeds-container">
              ${catFeeds.map((feed) => this.renderFeedItem(feed)).join("")}
            </div>
          `
              : ""
          }
        </div>
      `;
    });

    // Uncategorized Feeds
    let uncatFeeds = feedsByCat["uncategorized"] || [];
    const uncatUnread = catUnreadMap["uncategorized"] || 0;

    if (hideEmpty) {
      uncatFeeds = uncatFeeds.filter((f) => (f.unread_count || 0) > 0);
    }

    if (uncatFeeds.length > 0 || (!hideEmpty && feedsByCat["uncategorized"] && feedsByCat["uncategorized"].length > 0)) {
      const isCollapsed = this.collapsedCategories.has("uncategorized");
      html += `
        <div class="category-block">
          <div class="category-item" data-type="category" data-id="uncategorized">
            <span class="category-toggle ${isCollapsed ? "collapsed" : ""}" data-cat-id="uncategorized">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
            </span>
            <span class="tree-label">${t("tree.uncategorized")}</span>
            ${uncatUnread > 0 ? `<span class="tree-count has-unread">(${uncatUnread})</span>` : ""}
            <div class="tree-row-actions">
              ${uncatUnread > 0 ? `
                <button class="tree-row-btn" data-action="mark-read" data-target-type="category" data-target-id="uncategorized" title="${t("tree.mark_node_read")}">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
                </button>
              ` : ""}
            </div>
          </div>
          ${
            !isCollapsed
              ? `
            <div class="category-feeds-container">
              ${uncatFeeds.map((feed) => this.renderFeedItem(feed)).join("")}
            </div>
          `
              : ""
          }
        </div>
      `;
    }

    html += `</div>`;
    this.container.innerHTML = html;
    this.updateActiveHighlight();
  }

  renderFeedItem(feed) {
    const unread = feed.unread_count || 0;
    const initial = (feed.title || "R").charAt(0).toUpperCase();
    const errorCount = feed.error_count || 0;
    const lastError = feed.last_error_message || "連線異常";

    let errorBadge = "";
    if (errorCount >= 10) {
      errorBadge = `<span class="feed-error-badge dead" style="font-size: 11px; margin-left: 4px; cursor: help;" title="連線失效 (連續失敗 ${errorCount} 次): ${this.escape(lastError)}">💀</span>`;
    } else if (errorCount >= 3) {
      errorBadge = `<span class="feed-error-badge warning" style="font-size: 11px; margin-left: 4px; cursor: help;" title="連線警告 (連續失敗 ${errorCount} 次): ${this.escape(lastError)}">⚠️</span>`;
    }

    return `
      <div class="feed-item" data-type="feed" data-id="${feed.id}">
        ${
          feed.icon_url
            ? `<img class="feed-favicon" src="${feed.icon_url}" alt="" onerror="this.style.display='none'"/>`
            : `<span class="feed-favicon-fallback">${initial}</span>`
        }
        <span class="tree-label">${this.escape(feed.title || feed.feed_url)}</span>
        ${errorBadge}
        ${unread > 0 ? `<span class="tree-count has-unread">(${unread})</span>` : ""}
        <div class="tree-row-actions">
          ${unread > 0 ? `
            <button class="tree-row-btn" data-action="mark-read" data-target-type="feed" data-target-id="${feed.id}" title="${t("tree.mark_node_read")}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
            </button>
          ` : ""}
          <button class="tree-row-btn btn-delete" data-action="delete" data-target-type="feed" data-target-id="${feed.id}" data-target-name="${this.escape(feed.title || feed.feed_url)}" title="${t("tree.delete_feed")}">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          </button>
        </div>
      </div>
    `;
  }

  updateActiveHighlight() {
    const activeFilter = store.get("activeFilter");
    const activeFeedId = store.get("activeFeedId");
    const activeCategoryId = store.get("activeCategoryId");

    this.container.querySelectorAll(".tree-item, .category-item, .feed-item").forEach((el) => {
      el.classList.remove("active");
    });

    if (activeFilter === "feed" && activeFeedId) {
      const feedEl = this.container.querySelector(`.feed-item[data-id="${activeFeedId}"]`);
      if (feedEl) feedEl.classList.add("active");
    } else if (activeFilter === "category") {
      const catVal = activeCategoryId === null ? "uncategorized" : activeCategoryId;
      const catEl = this.container.querySelector(`.category-item[data-id="${catVal}"]`);
      if (catEl) catEl.classList.add("active");
    } else {
      const filterEl = this.container.querySelector(`.tree-item[data-filter="${activeFilter}"]`);
      if (filterEl) filterEl.classList.add("active");
    }
  }

  escape(str) {
    if (!str) return "";
    return str.replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }
}
