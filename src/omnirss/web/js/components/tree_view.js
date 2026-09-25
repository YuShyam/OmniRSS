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
    try {
      const saved = JSON.parse(localStorage.getItem("omnirss_collapsed_categories") || "[]");
      this.collapsedCategories = new Set(saved);
    } catch (_) {
      this.collapsedCategories = new Set();
    }
    this.initListeners();
    this.initSplitter();
    this.initContextMenu();
  }

  saveCollapsedState() {
    try {
      localStorage.setItem("omnirss_collapsed_categories", JSON.stringify(Array.from(this.collapsedCategories)));
    } catch (_) {}
  }

  initListeners() {
    store.subscribe("categories", () => this.render());
    store.subscribe("feeds", () => this.render());
    store.subscribe("tags", () => this.render());
    store.subscribe("hideEmptyFeeds", () => this.render());
    store.subscribe("starredCount", () => this.render());
    store.subscribe("totalArticlesCount", () => this.render());
    store.subscribe("trashCount", () => this.render());
    store.subscribe("tagsPosition", () => this.render());
    store.subscribe("tagsPaneHeight", () => this.render());
    store.subscribe("activeFilter", () => this.updateActiveHighlight());
    store.subscribe("activeCategoryId", () => this.updateActiveHighlight());
    store.subscribe("activeFeedId", () => this.updateActiveHighlight());
    store.subscribe("activeTagId", () => this.updateActiveHighlight());
    store.subscribe("activeTag", () => this.updateActiveHighlight());

    this.container.addEventListener("click", (e) => {
      // Manage Tags Click
      const manageTagsBtn = e.target.closest("#btn-manage-tags");
      if (manageTagsBtn) {
        e.stopPropagation();
        window.dispatchEvent(new CustomEvent("omnirss:open-tag-settings"));
        return;
      }

      // Empty Trash Button
      const emptyTrashBtn = e.target.closest(".btn-empty-trash");
      if (emptyTrashBtn) {
        e.stopPropagation();
        window.dispatchEvent(new CustomEvent("omnirss:empty-trash"));
        return;
      }

      // Inline Row Actions (Refresh, Mark Read, Feed Properties, Category Settings)
      const actionBtn = e.target.closest(".tree-row-btn");
      if (actionBtn) {
        e.stopPropagation();
        const action = actionBtn.dataset.action;
        const targetType = actionBtn.dataset.targetType;
        const targetId = actionBtn.dataset.targetId;
        const targetName = actionBtn.dataset.targetName || "";

        if (action === "refresh") {
          actionBtn.classList.add("spinning");
          window.dispatchEvent(
            new CustomEvent("omnirss:refresh-scope", {
              detail: { type: targetType, id: targetId, name: targetName, buttonEl: actionBtn },
            })
          );
        } else if (action === "mark-read") {
          window.dispatchEvent(
            new CustomEvent("omnirss:mark-read-scope", {
              detail: { type: targetType, id: targetId },
            })
          );
        } else if (action === "feed-properties") {
          window.dispatchEvent(
            new CustomEvent("omnirss:open-feed-properties", {
              detail: { id: parseInt(targetId, 10), name: targetName },
            })
          );
        } else if (action === "category-settings") {
          window.dispatchEvent(
            new CustomEvent("omnirss:open-category-settings", {
              detail: { id: parseInt(targetId, 10), name: targetName },
            })
          );
        } else if (action === "delete") {
          if (targetType === "category") {
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
        this.saveCollapsedState();
        this.render();
        return;
      }

      // Select folder/feed/tag
      const itemEl = e.target.closest(".tree-item, .category-item, .feed-item");
      if (!itemEl) return;

      const prevFeedId = store.get("activeFeedId");
      const markReadOnSwitch = store.get("markReadOnFeedSwitch");

      const type = itemEl.dataset.type;
      if (type === "filter") {
        const filterVal = itemEl.dataset.filter;
        if (markReadOnSwitch && prevFeedId) {
          window.dispatchEvent(
            new CustomEvent("omnirss:mark-read-scope", {
              detail: { type: "feed", id: prevFeedId, silent: true },
            })
          );
        }
        if (filterVal === "starred" || filterVal === "trash") {
          store.set("hideRead", false);
          const btnHideRead = document.getElementById("btn-toggle-hide-read");
          if (btnHideRead) btnHideRead.classList.remove("active");
        }
        store.update({
          activeFilter: filterVal,
          activeCategoryId: null,
          activeFeedId: null,
          activeTag: null,
          activeTagId: null,
        });
        window.dispatchEvent(new CustomEvent("omnirss:filter-changed"));
      } else if (type === "category") {
        if (markReadOnSwitch && prevFeedId) {
          window.dispatchEvent(
            new CustomEvent("omnirss:mark-read-scope", {
              detail: { type: "feed", id: prevFeedId, silent: true },
            })
          );
        }
        const idVal = itemEl.dataset.id === "uncategorized" ? null : parseInt(itemEl.dataset.id, 10);
        store.update({
          activeFilter: "category",
          activeCategoryId: idVal,
          activeFeedId: null,
          activeTag: null,
          activeTagId: null,
        });
        window.dispatchEvent(new CustomEvent("omnirss:filter-changed"));
      } else if (type === "feed") {
        const nextFeedId = parseInt(itemEl.dataset.id, 10);
        if (markReadOnSwitch && prevFeedId && prevFeedId !== nextFeedId) {
          window.dispatchEvent(
            new CustomEvent("omnirss:mark-read-scope", {
              detail: { type: "feed", id: prevFeedId, silent: true },
            })
          );
        }
        store.update({
          activeFilter: "feed",
          activeCategoryId: null,
          activeFeedId: nextFeedId,
          activeTag: null,
          activeTagId: null,
        });
        window.dispatchEvent(new CustomEvent("omnirss:filter-changed"));
      } else if (type === "tag") {
        if (markReadOnSwitch && prevFeedId) {
          window.dispatchEvent(
            new CustomEvent("omnirss:mark-read-scope", {
              detail: { type: "feed", id: prevFeedId, silent: true },
            })
          );
        }
        store.set("hideRead", false);
        const btnHideRead = document.getElementById("btn-toggle-hide-read");
        if (btnHideRead) btnHideRead.classList.remove("active");

        store.update({
          activeFilter: "tag",
          activeCategoryId: null,
          activeFeedId: null,
          activeTag: itemEl.dataset.name,
          activeTagId: parseInt(itemEl.dataset.id, 10),
        });
        window.dispatchEvent(new CustomEvent("omnirss:filter-changed"));
      }
    });
  }

  initSplitter() {
    let isDragging = false;
    let startY = 0;
    let startHeight = 0;
    let activeSplitter = null;

    const onPointerDown = (e) => {
      const splitter = e.target.closest("#tree-tags-splitter");
      if (!splitter) return;

      e.preventDefault();
      e.stopPropagation();

      isDragging = true;
      activeSplitter = splitter;
      startY = e.clientY;

      const tagsBlock = this.container.querySelector(".tags-group-block");
      startHeight = tagsBlock ? tagsBlock.getBoundingClientRect().height : (store.get("tagsPaneHeight") || 140);

      splitter.classList.add("dragging");
      document.body.classList.add("drag-resizing-active");
    };

    const onPointerMove = (e) => {
      if (!isDragging) return;
      e.preventDefault();

      const tagsPos = store.get("tagsPosition") || "bottom";
      const delta = tagsPos === "top" ? (e.clientY - startY) : (startY - e.clientY);
      const newHeight = Math.max(50, Math.min(500, Math.round(startHeight + delta)));

      const tagsBlock = this.container.querySelector(".tags-group-block");
      if (tagsBlock) {
        tagsBlock.style.height = `${newHeight}px`;
        tagsBlock.style.flex = `0 0 ${newHeight}px`;
        tagsBlock.style.maxHeight = "none";
      }
      store.state.tagsPaneHeight = newHeight;
    };

    const onPointerUp = () => {
      if (!isDragging) return;
      isDragging = false;

      if (activeSplitter) {
        activeSplitter.classList.remove("dragging");
        activeSplitter = null;
      }
      document.body.classList.remove("drag-resizing-active");

      const finalHeight = store.state.tagsPaneHeight;
      if (finalHeight) {
        try {
          localStorage.setItem("omnirss_tags_pane_height", String(finalHeight));
        } catch (_) {}
      }
    };

    this.container.addEventListener("mousedown", onPointerDown);
    window.addEventListener("mousemove", onPointerMove);
    window.addEventListener("mouseup", onPointerUp);
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
    this.saveCollapsedState();
    this.render();
  }

  render() {
    const categories = store.get("categories") || [];
    const feeds = store.get("feeds") || [];
    const hideEmpty = store.get("hideEmptyFeeds");
    const hideEmptyCategories = store.get("hideEmptyCategories");
    const starredCount = store.get("starredCount") || 0;
    const totalArticlesCount = store.get("totalArticlesCount") || 0;
    const trashCount = store.get("trashCount") || 0;
    const tagsPosition = store.get("tagsPosition") || "bottom";
    const tagsPaneHeight = store.get("tagsPaneHeight") || 140;

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

    // Smart Folders Block
    const smartFoldersHtml = `
      <!-- Smart Virtual Folders -->
      <div class="smart-folders-group">
        <div class="tree-item" data-type="filter" data-filter="all">
          <span class="tree-icon">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1"/></svg>
          </span>
          <span class="tree-label">${t("nav.all_feeds")}</span>
          ${totalUnread > 0 ? `<span class="tree-count has-unread">(${totalUnread})</span>` : (totalArticlesCount > 0 ? `<span class="tree-count">(${totalArticlesCount})</span>` : "")}
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
          ${starredCount > 0 ? `<span class="tree-count" id="tree-starred-count">(${starredCount})</span>` : ""}
        </div>

        <div class="tree-item" data-type="filter" data-filter="trash">
          <span class="tree-icon">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          </span>
          <span class="tree-label">${t("nav.trash")}</span>
          ${trashCount > 0 ? `<span class="tree-count" id="tree-trash-count">(${trashCount})</span>` : ""}
          ${trashCount > 0 ? `<button type="button" class="btn-empty-trash tree-row-action-btn" title="${t("reader.empty_trash")}" style="background:none; border:none; color:var(--text-muted); cursor:pointer; padding:2px 4px; border-radius:3px; margin-left:auto; font-size:12px; display:inline-flex; align-items:center;">🧹</button>` : ""}
        </div>
      </div>
    `;

    // Categories & Subscriptions Block
    let categoriesHtml = `<div class="categories-group" id="tree-categories-group" style="flex: 1 1 0%; min-height: 60px; overflow-y: auto;">`;

    // Render each category
    categories.forEach((cat) => {
      const catId = String(cat.id);
      const isCollapsed = this.collapsedCategories.has(catId);
      let catFeeds = feedsByCat[cat.id] || [];
      const catUnread = catUnreadMap[catId] || 0;

      // Filter empty feeds if hideEmpty
      if (hideEmpty) {
        catFeeds = catFeeds.filter((f) => (f.unread_count || 0) > 0);
        if (catFeeds.length === 0 && catUnread === 0) return;
      }

      // Category Error Aggregation (Dead >= 10, Warning >= 3)
      const allOriginalCatFeeds = feedsByCat[cat.id] || [];
      const deadCount = allOriginalCatFeeds.filter((f) => (f.error_count || 0) >= 10).length;
      const warnCount = allOriginalCatFeeds.filter((f) => (f.error_count || 0) >= 3 && (f.error_count || 0) < 10).length;
      let catErrorBadge = "";
      if (deadCount > 0) {
        catErrorBadge += `<span class="category-error-badge dead" title="${t("tree.dead_feeds_warn", { count: deadCount })}">💀 ${deadCount}</span>`;
      }
      if (warnCount > 0) {
        catErrorBadge += `<span class="category-error-badge warning" title="${t("tree.unstable_feeds_warn", { count: warnCount })}">⚠️ ${warnCount}</span>`;
      }

      categoriesHtml += `
        <div class="category-block">
          <div class="category-item" data-type="category" data-id="${cat.id}">
            <span class="category-toggle ${isCollapsed ? "collapsed" : ""}" data-cat-id="${cat.id}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
            </span>
            <span class="tree-icon">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
            </span>
            <span class="tree-label">${this.escape(cat.name)}</span>
            ${catErrorBadge}
            ${catUnread > 0 ? `<span class="tree-count has-unread">(${catUnread})</span>` : ""}
            <div class="tree-row-actions">
              <button class="tree-row-btn btn-settings" data-action="category-settings" data-target-type="category" data-target-id="${cat.id}" data-target-name="${this.escape(cat.name)}" title="${t("tree.category_props")}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
              </button>
              <button class="tree-row-btn btn-refresh" data-action="refresh" data-target-type="category" data-target-id="${cat.id}" data-target-name="${this.escape(cat.name)}" title="${t("tree.refresh_cat")}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
              </button>
              ${catUnread > 0 ? `
                <button class="tree-row-btn" data-action="mark-read" data-target-type="category" data-target-id="${cat.id}" title="${t("tree.mark_node_read")}">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
                </button>
              ` : ""}
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

    if (uncatFeeds.length > 0 || feedsByCat["uncategorized"] && feedsByCat["uncategorized"].length > 0) {
      const isCollapsed = this.collapsedCategories.has("uncategorized");
      const deadCount = (feedsByCat["uncategorized"] || []).filter((f) => (f.error_count || 0) >= 10).length;
      const warnCount = (feedsByCat["uncategorized"] || []).filter((f) => (f.error_count || 0) >= 3 && (f.error_count || 0) < 10).length;
      let catErrorBadge = "";
      if (deadCount > 0) catErrorBadge += `<span class="category-error-badge dead" title="${t("tree.uncat_dead_warn", { count: deadCount })}">💀 ${deadCount}</span>`;
      if (warnCount > 0) catErrorBadge += `<span class="category-error-badge warning" title="${t("tree.uncat_unstable_warn", { count: warnCount })}">⚠️ ${warnCount}</span>`;

      categoriesHtml += `
        <div class="category-block">
          <div class="category-item" data-type="category" data-id="uncategorized">
            <span class="category-toggle ${isCollapsed ? "collapsed" : ""}" data-cat-id="uncategorized">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
            </span>
            <span class="tree-label">${t("tree.uncategorized")}</span>
            ${catErrorBadge}
            ${uncatUnread > 0 ? `<span class="tree-count has-unread">(${uncatUnread})</span>` : ""}
            <div class="tree-row-actions">
              <button class="tree-row-btn btn-refresh" data-action="refresh" data-target-type="category" data-target-id="uncategorized" data-target-name="${t("tree.uncategorized")}" title="${t("tree.refresh_uncat")}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
              </button>
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

    categoriesHtml += `</div>`;


    // Render Labels / Tags Group (QuiteRSS 標籤組與垂直高度調整)
    const tags = store.get("tags") || [];
    let tagsHtml = "";
    let splitterHtml = "";

    if (tags.length > 0) {
      splitterHtml = `<div class="tree-pane-splitter" id="tree-tags-splitter" title="${t("tree.resize_handle_tooltip")}"></div>`;
      tagsHtml = `
        <div class="tags-group-block" style="height: ${tagsPaneHeight}px; min-height: 50px; max-height: 400px; display: flex; flex-direction: column; overflow: hidden; flex-shrink: 0; background: var(--bg-surface);">
          <div class="tags-group-header" style="padding: 4px 8px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; border-bottom: 1px solid var(--border-color-subtle);">
            <span style="display: flex; align-items: center; gap: 4px;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>
              <span>${t("tree.tags")}</span>
            </span>
            <button class="tree-header-action-btn" id="btn-manage-tags" title="${t("tags.manage_title")}" style="background: none; border: none; cursor: pointer; color: var(--text-muted); padding: 2px;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            </button>
          </div>
          <div class="tags-group-list" style="flex: 1; overflow-y: auto; padding: 2px 0;">
            ${tags
              .map(
                (tag) => `
              <div class="tree-item tag-item" data-type="tag" data-id="${tag.id}" data-name="${this.escape(tag.name)}">
                <span class="tree-icon" style="color: ${tag.color_hex || "#3b82f6"};">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="${tag.color_hex || "#3b82f6"}"><circle cx="12" cy="12" r="10"/></svg>
                </span>
                <span class="tree-label">${this.escape(tag.name)}</span>
                ${
                  (tag.unread_count || 0) > 0
                    ? `<span class="tree-count has-unread">(${tag.unread_count})</span>`
                    : (tag.article_count > 0 ? `<span class="tree-count">(${tag.article_count})</span>` : "")
                }
              </div>
            `
              )
              .join("")}
          </div>
        </div>
      `;
    }

    let finalHtml = smartFoldersHtml;
    if (tagsPosition === "top") {
      finalHtml += tagsHtml + (tags.length > 0 ? splitterHtml : "") + categoriesHtml;
    } else {
      finalHtml += categoriesHtml + (tags.length > 0 ? splitterHtml : "") + tagsHtml;
    }

    this.container.innerHTML = finalHtml;
    this.updateActiveHighlight();
  }

  renderFeedItem(feed) {
    const unread = feed.unread_count || 0;
    const initial = (feed.title || "R").charAt(0).toUpperCase();
    const errorCount = feed.error_count || 0;
    const lastError = feed.last_error_message || t("tree.conn_offline");

    let errorBadge = "";
    if (errorCount >= 10) {
      errorBadge = `<span class="feed-error-badge dead" style="font-size: 11px; margin-left: 4px; cursor: help;" title="${t("tree.conn_offline_detail", { count: errorCount, error: this.escape(lastError) })}">💀</span>`;
    } else if (errorCount >= 3) {
      errorBadge = `<span class="feed-error-badge warning" style="font-size: 11px; margin-left: 4px; cursor: help;" title="${t("tree.conn_warn_detail", { count: errorCount, error: this.escape(lastError) })}">⚠️</span>`;
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
          <button class="tree-row-btn btn-settings" data-action="feed-properties" data-target-type="feed" data-target-id="${feed.id}" data-target-name="${this.escape(feed.title || feed.feed_url)}" title="${t("tree.feed_props")}">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </button>
          <button class="tree-row-btn btn-refresh" data-action="refresh" data-target-type="feed" data-target-id="${feed.id}" data-target-name="${this.escape(feed.title || feed.feed_url)}" title="${t("tree.refresh_feed")}">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          </button>
          ${unread > 0 ? `
            <button class="tree-row-btn" data-action="mark-read" data-target-type="feed" data-target-id="${feed.id}" title="${t("tree.mark_node_read")}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
            </button>
          ` : ""}
        </div>
      </div>
    `;
  }

  updateActiveHighlight() {
    const activeFilter = store.get("activeFilter");
    const activeFeedId = store.get("activeFeedId");
    const activeCategoryId = store.get("activeCategoryId");
    const activeTagId = store.get("activeTagId");
    const activeTag = store.get("activeTag");

    this.container.querySelectorAll(".tree-item, .category-item, .feed-item, .tag-item").forEach((el) => {
      el.classList.remove("active");
    });

    if (activeFilter === "feed" && activeFeedId) {
      const feedEl = this.container.querySelector(`.feed-item[data-id="${activeFeedId}"]`);
      if (feedEl) feedEl.classList.add("active");
    } else if (activeFilter === "category") {
      const catVal = activeCategoryId === null ? "uncategorized" : activeCategoryId;
      const catEl = this.container.querySelector(`.category-item[data-id="${catVal}"]`);
      if (catEl) catEl.classList.add("active");
    } else if (activeFilter === "tag") {
      let tagEl = null;
      if (activeTagId) tagEl = this.container.querySelector(`.tag-item[data-id="${activeTagId}"]`);
      if (!tagEl && activeTag) tagEl = this.container.querySelector(`.tag-item[data-name="${activeTag}"]`);
      if (tagEl) tagEl.classList.add("active");
    } else {
      const filterEl = this.container.querySelector(`.tree-item[data-filter="${activeFilter}"]`);
      if (filterEl) filterEl.classList.add("active");
    }
  }

  initContextMenu() {
    const removeMenu = () => {
      const existing = document.querySelector(".tree-context-menu");
      if (existing) existing.remove();
    };

    document.addEventListener("click", removeMenu);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") removeMenu();
    });

    this.container.addEventListener("contextmenu", (e) => {
      const feedEl = e.target.closest(".feed-item");
      const catEl = e.target.closest(".category-item");
      const smartEl = e.target.closest(".tree-item");

      if (!feedEl && !catEl && !smartEl) return;

      e.preventDefault();
      e.stopPropagation();
      removeMenu();

      const menu = document.createElement("div");
      menu.className = "article-context-menu tree-context-menu";

      if (feedEl) {
        const feedId = parseInt(feedEl.dataset.id, 10);
        const feeds = store.get("feeds") || [];
        const feed = feeds.find((f) => f.id === feedId) || {};
        const feedTitle = feed.title || feed.feed_url || t("status.target_feed");
        const hasUnread = (feed.unread_count || 0) > 0;

        menu.innerHTML = `
          <div class="context-menu-item" data-action="feed-properties">
            <span>⚙️</span>
            <span>${t("tree.feed_props")}</span>
          </div>
          <div class="context-menu-item" data-action="refresh-feed">
            <span>🔄</span>
            <span>${t("tree.refresh_feed")}</span>
          </div>
          ${
            hasUnread
              ? `
            <div class="context-menu-item" data-action="mark-read-feed">
              <span>✓</span>
              <span>${t("tree.mark_node_read")}</span>
            </div>
          `
              : ""
          }
          <div class="context-menu-divider"></div>
          <div class="context-menu-item" data-action="copy-feed-url">
            <span>📋</span>
            <span>${t("feed_props.copy_url")}</span>
          </div>
          ${
            feed.site_url || feed.feed_url
              ? `
            <div class="context-menu-item" data-action="open-feed-site">
              <span>🌐</span>
              <span>${t("feed_props.open_site")}</span>
            </div>
          `
              : ""
          }
          <div class="context-menu-divider"></div>
          <div class="context-menu-item danger" data-action="delete-feed" style="color: var(--accent-red, #f87171);">
            <span>🗑️</span>
            <span>${t("tree.delete_feed")}</span>
          </div>
        `;

        menu.addEventListener("click", (menuEvt) => {
          menuEvt.stopPropagation();
          const item = menuEvt.target.closest(".context-menu-item");
          if (!item) return;
          const action = item.dataset.action;
          removeMenu();

          if (action === "feed-properties") {
            window.dispatchEvent(
              new CustomEvent("omnirss:open-feed-properties", {
                detail: { id: feedId, name: feedTitle },
              })
            );
          } else if (action === "refresh-feed") {
            window.dispatchEvent(
              new CustomEvent("omnirss:refresh-scope", {
                detail: { type: "feed", id: feedId, name: feedTitle },
              })
            );
          } else if (action === "mark-read-feed") {
            window.dispatchEvent(
              new CustomEvent("omnirss:mark-read-scope", {
                detail: { type: "feed", id: feedId },
              })
            );
          } else if (action === "copy-feed-url") {
            if (feed.feed_url) {
              navigator.clipboard?.writeText(feed.feed_url).then(() => {
                window.dispatchEvent(
                  new CustomEvent("omnirss:toast", {
                    detail: { message: t("tree.url_copied"), type: "success" },
                  })
                );
              });
            }
          } else if (action === "open-feed-site") {
            const url = feed.site_url || feed.feed_url;
            if (url) window.open(url, "_blank", "noopener,noreferrer");
          } else if (action === "delete-feed") {
            if (window.confirm(t("tree.confirm_delete_feed", { name: feedTitle }))) {
              window.dispatchEvent(
                new CustomEvent("omnirss:delete-feed", {
                  detail: { id: feedId },
                })
              );
            }
          }
        });
      } else if (catEl) {
        const catId = catEl.dataset.id;
        const catTitle = catEl.querySelector(".tree-label")?.textContent || t("status.target_cat");
        const isUncategorized = catId === "uncategorized";

        menu.innerHTML = `
          ${
            !isUncategorized
              ? `
            <div class="context-menu-item" data-action="cat-settings">
              <span>⚙️</span>
              <span>${t("tree.category_props")}</span>
            </div>
          `
              : ""
          }
          <div class="context-menu-item" data-action="refresh-cat">
            <span>🔄</span>
            <span>${t("tree.refresh_cat")}</span>
          </div>
          <div class="context-menu-item" data-action="mark-read-cat">
            <span>✓</span>
            <span>${t("tree.mark_all_read")}</span>
          </div>
          ${
            !isUncategorized
              ? `
            <div class="context-menu-divider"></div>
            <div class="context-menu-item danger" data-action="delete-cat" style="color: var(--accent-red, #f87171);">
              <span>🗑️</span>
              <span>${t("tree.delete_category")}</span>
            </div>
          `
              : ""
          }
        `;

        menu.addEventListener("click", (menuEvt) => {
          menuEvt.stopPropagation();
          const item = menuEvt.target.closest(".context-menu-item");
          if (!item) return;
          const action = item.dataset.action;
          removeMenu();

          if (action === "cat-settings") {
            window.dispatchEvent(
              new CustomEvent("omnirss:open-category-settings", {
                detail: { id: parseInt(catId, 10), name: catTitle },
              })
            );
          } else if (action === "refresh-cat") {
            window.dispatchEvent(
              new CustomEvent("omnirss:refresh-scope", {
                detail: { type: "category", id: catId, name: catTitle },
              })
            );
          } else if (action === "mark-read-cat") {
            window.dispatchEvent(
              new CustomEvent("omnirss:mark-read-scope", {
                detail: { type: "category", id: catId },
              })
            );
          } else if (action === "delete-cat") {
            if (window.confirm(t("tree.confirm_delete_category", { name: catTitle }))) {
              window.dispatchEvent(
                new CustomEvent("omnirss:delete-category", {
                  detail: { id: parseInt(catId, 10) },
                })
              );
            }
          }
        });
      } else if (smartEl) {
        const filterVal = smartEl.dataset.filter;

        menu.innerHTML = `
          <div class="context-menu-item" data-action="refresh-all">
            <span>🔄</span>
            <span>${t("tree.refresh_all")}</span>
          </div>
          <div class="context-menu-item" data-action="mark-read-all">
            <span>✓</span>
            <span>${t("tree.mark_all_read")}</span>
          </div>
        `;

        menu.addEventListener("click", (menuEvt) => {
          menuEvt.stopPropagation();
          const item = menuEvt.target.closest(".context-menu-item");
          if (!item) return;
          const action = item.dataset.action;
          removeMenu();

          if (action === "refresh-all") {
            window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
          } else if (action === "mark-read-all") {
            window.dispatchEvent(
              new CustomEvent("omnirss:mark-read-scope", {
                detail: { type: "filter", id: filterVal || "all" },
              })
            );
          }
        });
      }

      document.body.appendChild(menu);
      const menuWidth = 220;
      const menuHeight = 240;
      let x = e.clientX;
      let y = e.clientY;
      if (x + menuWidth > window.innerWidth) x = window.innerWidth - menuWidth - 8;
      if (y + menuHeight > window.innerHeight) y = window.innerHeight - menuHeight - 8;
      menu.style.left = `${Math.max(8, x)}px`;
      menu.style.top = `${Math.max(8, y)}px`;
    });
  }

  escape(str) {
    if (str === null || str === undefined || str === "null" || str === "undefined") return "";
    return String(str).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }
}
