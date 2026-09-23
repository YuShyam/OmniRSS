/**
 * OmniRSS 鍵盤快捷鍵監聽控制器 (Keyboard Shortcuts Controller).
 *
 * Implements full QuiteRSS & Vim keyboard navigation flows:
 * - j / k: Next / Previous Article
 * - Space: Scroll reader or jump to next unread
 * - m: Toggle Read / Unread
 * - s: Toggle Star
 * - v / o: Open Original URL in New Tab
 * - r: Refresh Current Feed
 * - Shift+A: Mark All Read in View
 * - /: Search Focus
 * - b: Toggle Sidebar
 * - ?: Show Shortcuts Cheatsheet
 */

import { store } from "./state.js";
import { api } from "./api_client.js";

export function initKeybindings() {
  window.addEventListener("keydown", async (e) => {
    // If typing in input, textarea, or contentEditable, ignore shortcut keys unless Escape
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

    // Modal open check: if modal open, Escape closes it
    const openModal = document.querySelector(".modal-overlay.open");
    if (openModal) {
      if (e.key === "Escape") {
        openModal.classList.remove("open");
        e.preventDefault();
      }
      return;
    }

    const articles = store.get("articles") || [];
    const selectedId = store.get("selectedArticleId");
    let currentIndex = articles.findIndex((a) => a.id === selectedId);

    switch (e.key) {
      // Navigation: Next (j / ArrowDown)
      case "j":
      case "ArrowDown": {
        e.preventDefault();
        if (articles.length === 0) return;
        const nextIndex = Math.min(currentIndex + 1, articles.length - 1);
        const nextArticle = articles[nextIndex];
        if (nextArticle) {
          window.dispatchEvent(new CustomEvent("omnirss:select-article", { detail: { id: nextArticle.id } }));
        }
        break;
      }

      // Navigation: Previous (k / ArrowUp)
      case "k":
      case "ArrowUp": {
        e.preventDefault();
        if (articles.length === 0) return;
        const prevIndex = Math.max(currentIndex - 1, 0);
        const prevArticle = articles[prevIndex];
        if (prevArticle) {
          window.dispatchEvent(new CustomEvent("omnirss:select-article", { detail: { id: prevArticle.id } }));
        }
        break;
      }

      // Action: Toggle Read / Unread (m)
      case "m": {
        e.preventDefault();
        if (!selectedId) return;
        const art = articles.find((a) => a.id === selectedId);
        if (art) {
          const newUnread = !art.is_unread;
          await api.updateArticleState(selectedId, { is_unread: newUnread });
          art.is_unread = newUnread;
          store.set("articles", [...articles]);
        }
        break;
      }

      // Action: Toggle Star (s / *)
      case "s":
      case "*": {
        e.preventDefault();
        if (!selectedId) return;
        const art = articles.find((a) => a.id === selectedId);
        if (art) {
          const newStarred = !art.is_starred;
          await api.updateArticleState(selectedId, { is_starred: newStarred });
          art.is_starred = newStarred;
          store.set("articles", [...articles]);
        }
        break;
      }

      // Action: Open in New Tab (v / o)
      case "v":
      case "o": {
        e.preventDefault();
        const art = articles.find((a) => a.id === selectedId);
        if (art && art.link) {
          window.open(art.link, "_blank", "noopener,noreferrer");
        }
        break;
      }

      // Action: Mark All Read (Shift+A)
      case "A": {
        if (e.shiftKey) {
          e.preventDefault();
          const filter = store.get("activeFilter");
          const feedId = store.get("activeFeedId");
          const catId = store.get("activeCategoryId");
          await api.markAllRead(feedId, catId);
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
        }
        break;
      }

      // Action: Refresh (r)
      case "r": {
        e.preventDefault();
        const feedId = store.get("activeFeedId");
        if (feedId) {
          await api.refreshFeed(feedId);
        } else {
          await api.refreshAllFeeds();
        }
        window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
        break;
      }

      // Action: Search Focus (/)
      case "/": {
        e.preventDefault();
        const searchInput = document.getElementById("global-search");
        if (searchInput) searchInput.focus();
        break;
      }

      // Action: Toggle Sidebar (b)
      case "b": {
        e.preventDefault();
        const treePane = document.querySelector(".pane-tree");
        if (treePane) {
          treePane.style.display = treePane.style.display === "none" ? "flex" : "none";
        }
        break;
      }

      // Help: Cheatsheet (?)
      case "?": {
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
