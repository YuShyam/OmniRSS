/**
 * OmniRSS 鍵盤快捷鍵監聽控制器 (Keyboard Shortcuts Controller).
 *
 * Implements full QuiteRSS & Vim keyboard navigation flows:
 * - j / k / ArrowDown / ArrowUp: Next / Previous Article
 * - Space: Scroll reader or jump to next unread
 * - m: Toggle Read / Unread
 * - s / *: Toggle Star
 * - v / o: Open Original URL in New Tab
 * - r / F5: Refresh Current Feed / All
 * - Shift+A: Mark All Read in View
 * - /: Search Focus
 * - b: Toggle Sidebar
 * - 1..9: Toggle Tag 1..9 on selected article (QuiteRSS ergonomics)
 * - 0: Clear all tags on selected article
 * - ?: Show Shortcuts Cheatsheet
 *
 * Supports dynamic user keymap customization & auto category leaping.
 */

import { store } from "./state.js";
import { api } from "./api_client.js";
import { t } from "./i18n.js";

export const DEFAULT_SHORTCUTS = {
  nextArticle: { key: "hotkeys.next_article", label: "下一篇文章", keys: ["j", "ArrowDown"] },
  prevArticle: { key: "hotkeys.prev_article", label: "上一篇文章", keys: ["k", "ArrowUp"] },
  toggleRead: { key: "hotkeys.toggle_read", label: "標記已讀 / 未讀", keys: ["m"] },
  toggleStar: { key: "hotkeys.toggle_star", label: "加星 / 取消星標", keys: ["s", "*"] },
  openOriginal: { key: "hotkeys.open_original", label: "開啟原始網址", keys: ["v", "o", "Enter"] },
  trashArticle: { key: "hotkeys.trash_article", label: "刪除 / 移至垃圾桶", keys: ["Delete", "Backspace", "d"] },
  refresh: { key: "hotkeys.refresh", label: "重新整理 (當前頻道/全部)", keys: ["r", "F5"] },
  markAllRead: { key: "hotkeys.mark_all_read", label: "全部標記為已讀", keys: ["Shift+A"] },
  search: { key: "hotkeys.search", label: "聚焦全域搜尋", keys: ["/"] },
  toggleSidebar: { key: "hotkeys.toggle_sidebar", label: "展開 / 隱藏側邊欄", keys: ["b"] },
  nextUnread: { key: "hotkeys.next_unread", label: "跳轉下一未讀 / 滾動", keys: ["Space"] },
  tag1: { key: "hotkeys.tag_1", label: "切換標籤 1", keys: ["1"] },
  tag2: { key: "hotkeys.tag_2", label: "切換標籤 2", keys: ["2"] },
  tag3: { key: "hotkeys.tag_3", label: "切換標籤 3", keys: ["3"] },
  tag4: { key: "hotkeys.tag_4", label: "切換標籤 4", keys: ["4"] },
  tag5: { key: "hotkeys.tag_5", label: "切換標籤 5", keys: ["5"] },
  clearTags: { key: "hotkeys.clear_tags", label: "清除所有標籤", keys: ["0"] },
  showHelp: { key: "hotkeys.show_help", label: "快捷鍵指南說明", keys: ["?"] },
};

export function getEffectiveShortcuts() {
  const custom = store.get("customShortcuts") || {};
  const result = {};
  for (const [action, def] of Object.entries(DEFAULT_SHORTCUTS)) {
    result[action] = {
      label: def.key ? t(def.key, def.label) : def.label,
      keys: custom[action] && custom[action].length > 0 ? custom[action] : def.keys,
    };
  }
  return result;
}

function matchKey(e, keyStr) {
  if (!keyStr) return false;

  const isShift = keyStr.startsWith("Shift+");
  const isCtrl = keyStr.startsWith("Ctrl+");
  const isAlt = keyStr.startsWith("Alt+");

  let pureKey = keyStr;
  if (isShift) pureKey = keyStr.slice(6);
  if (isCtrl) pureKey = keyStr.slice(5);
  if (isAlt) pureKey = keyStr.slice(4);

  if (isShift && !e.shiftKey) return false;
  if (isCtrl && !e.ctrlKey && !e.metaKey) return false;
  if (isAlt && !e.altKey) return false;

  if (pureKey === "Space") {
    return e.key === " " || e.code === "Space";
  }

  return pureKey.toLowerCase() === e.key.toLowerCase();
}

function getTriggeredAction(e, shortcuts) {
  for (const [action, def] of Object.entries(shortcuts)) {
    if (def.keys.some((k) => matchKey(e, k))) {
      return action;
    }
  }
  return null;
}

export function jumpToNextUnreadCategory() {
  const categories = store.get("categories") || [];
  const feeds = store.get("feeds") || [];
  const activeCatId = store.get("activeCategoryId");

  if (!categories || categories.length === 0) return false;

  // 動態建立分類未讀計數映射
  const catUnreadMap = {};
  feeds.forEach((f) => {
    const unread = f.unread_count || 0;
    const catId = f.category_id ? String(f.category_id) : "uncategorized";
    catUnreadMap[catId] = (catUnreadMap[catId] || 0) + unread;
  });

  let currentIdx = categories.findIndex((c) => c.id === activeCatId);
  if (currentIdx === -1) currentIdx = 0;

  for (let i = 1; i <= categories.length; i++) {
    const nextIdx = (currentIdx + i) % categories.length;
    const cat = categories[nextIdx];
    const unread = catUnreadMap[String(cat.id)] !== undefined ? catUnreadMap[String(cat.id)] : (cat.unread_count || 0);
    if (cat && unread > 0 && cat.id !== activeCatId) {
      store.update({
        activeFilter: "category",
        activeCategoryId: cat.id,
        activeFeedId: null,
        activeTag: null,
        activeTagId: null,
      });
      window.dispatchEvent(new CustomEvent("omnirss:filter-changed"));
      window.dispatchEvent(
        new CustomEvent("omnirss:toast", {
          detail: { message: t("hotkeys.jump_next_cat_success", { name: cat.name }), type: "info" },
        })
      );
      return true;
    }
  }
  return false;
}

export function recordNextKey(callback) {
  const listener = (e) => {
    e.preventDefault();
    e.stopPropagation();

    if (["Shift", "Control", "Alt", "Meta"].includes(e.key)) return;

    let keyStr = "";
    if (e.ctrlKey) keyStr += "Ctrl+";
    if (e.altKey) keyStr += "Alt+";
    if (e.shiftKey && e.key.length === 1) keyStr += "Shift+";

    let baseKey = e.key;
    if (baseKey === " ") baseKey = "Space";
    else if (baseKey.length === 1) baseKey = baseKey.toUpperCase();

    keyStr += baseKey;
    window.removeEventListener("keydown", listener, true);
    callback(keyStr);
  };
  window.addEventListener("keydown", listener, true);
}

export function initKeybindings() {
  window.addEventListener("keydown", async (e) => {
    const target = e.target;
    const isInput =
      target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.tagName === "SELECT" ||
      target.isContentEditable;

    if (isInput) {
      if (e.key === "Escape") {
        target.blur();
      }
      return;
    }

    const openModal = document.querySelector(".modal-overlay.open");
    if (openModal) {
      if (e.key === "Escape") {
        openModal.classList.remove("open");
        e.preventDefault();
      }
      return;
    }

    const shortcuts = getEffectiveShortcuts();
    const action = getTriggeredAction(e, shortcuts);
    if (!action) return;

    const articles = store.get("articles") || [];
    const selectedId = store.get("selectedArticleId");
    let currentIndex = articles.findIndex((a) => a.id === selectedId);

    switch (action) {
      case "nextArticle": {
        e.preventDefault();
        if (articles.length === 0) {
          if (store.get("autoNextCategory") && store.get("activeFilter") === "category") {
            jumpToNextUnreadCategory();
          }
          return;
        }
        if (currentIndex === articles.length - 1) {
          if (store.get("autoNextCategory") && store.get("activeFilter") === "category") {
            jumpToNextUnreadCategory();
          }
          return;
        }
        const nextIndex = Math.min(currentIndex + 1, articles.length - 1);
        const nextArticle = articles[nextIndex];
        if (nextArticle) {
          window.dispatchEvent(new CustomEvent("omnirss:select-article", { detail: { id: nextArticle.id } }));
        }
        break;
      }

      case "prevArticle": {
        e.preventDefault();
        if (articles.length === 0) return;
        const prevIndex = Math.max(currentIndex - 1, 0);
        const prevArticle = articles[prevIndex];
        if (prevArticle) {
          window.dispatchEvent(new CustomEvent("omnirss:select-article", { detail: { id: prevArticle.id } }));
        }
        break;
      }

      case "nextUnread": {
        e.preventDefault();
        if (articles.length === 0) {
          if (store.get("autoNextCategory") && store.get("activeFilter") === "category") {
            jumpToNextUnreadCategory();
          }
          return;
        }
        // Find next unread starting from currentIndex + 1
        let unreadIdx = -1;
        for (let i = currentIndex + 1; i < articles.length; i++) {
          const a = articles[i];
          if (a.is_unread || a.is_read === false || a.is_read === 0) {
            unreadIdx = i;
            break;
          }
        }
        if (unreadIdx !== -1) {
          window.dispatchEvent(new CustomEvent("omnirss:select-article", { detail: { id: articles[unreadIdx].id } }));
        } else {
          if (store.get("autoNextCategory") && store.get("activeFilter") === "category") {
            jumpToNextUnreadCategory();
          }
        }
        break;
      }

      case "toggleRead": {
        e.preventDefault();
        if (!selectedId) return;
        const art = articles.find((a) => a.id === selectedId);
        if (art) {
          const currentUnread = art.is_unread ?? (art.is_read === 0 || art.is_read === false);
          const newUnread = !currentUnread;
          await api.updateArticleState(selectedId, { is_read: !newUnread, is_unread: newUnread });
          art.is_unread = newUnread;
          art.is_read = !newUnread ? 1 : 0;
          store.set("articles", [...articles]);
          const sel = store.get("selectedArticle");
          if (sel && sel.id === selectedId) {
            sel.is_read = !newUnread;
            sel.is_unread = newUnread;
            store.set("selectedArticle", { ...sel });
          }
        }
        break;
      }

      case "toggleStar": {
        e.preventDefault();
        if (!selectedId) return;
        const art = articles.find((a) => a.id === selectedId);
        if (art) {
          const newStarred = !art.is_starred;
          await api.updateArticleState(selectedId, { is_starred: newStarred });
          art.is_starred = newStarred;
          store.set("articles", [...articles]);
          const sel = store.get("selectedArticle");
          if (sel && sel.id === selectedId) {
            sel.is_starred = newStarred;
            store.set("selectedArticle", { ...sel });
          }
        }
        break;
      }

      case "openOriginal": {
        e.preventDefault();
        const art = articles.find((a) => a.id === selectedId) || store.get("selectedArticle");
        const link = art ? (art.url || art.link) : null;
        if (link) {
          window.open(link, "_blank", "noopener,noreferrer");
        }
        break;
      }

      case "markAllRead": {
        e.preventDefault();
        const filter = store.get("activeFilter");
        const feedId = store.get("activeFeedId");
        const catId = store.get("activeCategoryId");
        await api.markAllRead(feedId, catId);
        window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
        if (store.get("autoNextCategory") && filter === "category") {
          jumpToNextUnreadCategory();
        }
        break;
      }

      case "refresh": {
        e.preventDefault();
        const refreshBtn = document.getElementById("btn-refresh-all");
        if (refreshBtn) {
          refreshBtn.click();
        } else {
          await api.refreshAllFeeds();
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
        }
        break;
      }

      case "search": {
        e.preventDefault();
        const searchInput = document.getElementById("global-search");
        if (searchInput) searchInput.focus();
        break;
      }

      case "toggleSidebar": {
        e.preventDefault();
        const treePane = document.querySelector(".pane-tree");
        if (treePane) {
          treePane.style.display = treePane.style.display === "none" ? "flex" : "none";
        }
        break;
      }

      case "tag1":
      case "tag2":
      case "tag3":
      case "tag4":
      case "tag5":
      case "tag6":
      case "tag7":
      case "tag8":
      case "tag9": {
        e.preventDefault();
        if (!selectedId) return;
        const tagIndex = parseInt(action.replace("tag", ""), 10) - 1;
        const tags = store.get("tags") || [];
        const targetTag = tags[tagIndex];
        if (!targetTag) return;

        window.dispatchEvent(
          new CustomEvent("omnirss:tag-article", {
            detail: {
              articleId: selectedId,
              tagId: targetTag.id,
            },
          })
        );
        break;
      }

      case "clearTags": {
        e.preventDefault();
        if (!selectedId) return;
        window.dispatchEvent(
          new CustomEvent("omnirss:clear-article-tags", {
            detail: {
              articleId: selectedId,
            },
          })
        );
        break;
      }

      case "trashArticle": {
        e.preventDefault();
        if (!selectedId) return;
        window.dispatchEvent(
          new CustomEvent("omnirss:trash-article", {
            detail: {
              articleId: selectedId,
            },
          })
        );
        break;
      }

      case "showHelp": {
        e.preventDefault();
        const modal = document.getElementById("modal-hotkeys");
        if (modal) modal.classList.add("open");
        break;
      }

      default:
        break;
    }
  });
}
