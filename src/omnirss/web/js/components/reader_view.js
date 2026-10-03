/**
 * OmniRSS 內容閱讀器元件 (Reader View Component).
 *
 * Implements:
 * - Compact draggable action toolbar with DnD reordering
 * - Reader Action Picker [ ⊞ ] for custom button visibility & toggle
 * - Dynamic toolbar items via PluginRegistry & readerToolbarOrder
 * - Two-way state sync for star & read operations
 * - Gemini AI summary & extensible panel containers
 * - Instant font scaling (A- / A+)
 * - Sanitized HTML article body rendering
 */

import { store } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";
import { parseUtcDate } from "../date_utils.js";
import { pluginRegistry, OFFICIAL_GEMINI_PRESETS } from "../plugin_registry.js";

export const ALL_READER_ACTIONS = [
  { key: "star", name: "reader.action_star", defaultName: "收藏星號", defaultVisible: true },
  { key: "toggle_read", name: "reader.action_read", defaultName: "切換已讀/未讀", defaultVisible: true },
  { key: "run_plugins", name: "reader.action_run_plugins", defaultName: "執行外掛", defaultVisible: true },
  { key: "tag", name: "reader.action_tag", defaultName: "標籤管理", defaultVisible: true },
  { key: "trash", name: "reader.action_trash", defaultName: "移至垃圾桶", defaultVisible: true },
  { key: "fetch_full", name: "reader.action_fetch_full", defaultName: "抓取全文", defaultVisible: true },
  { key: "copy_link", name: "reader.action_copy_link", defaultName: "複製連結", defaultVisible: false },
  { key: "open_url", name: "reader.action_open_url", defaultName: "開啟原文", defaultVisible: true },
  { key: "font_dec", name: "reader.action_font_dec", defaultName: "縮小字級 (A-)", defaultVisible: true },
  { key: "font_inc", name: "reader.action_font_inc", defaultName: "放大字級 (A+)", defaultVisible: true },
];

export function matchUrlPattern(url, pattern) {
  if (!url || !pattern) return false;
  const p = String(pattern).trim();
  if (p === "<all_urls>" || p === "*" || p === "*://*/*" || p === "*://*") {
    return /^https?:\/\/.+/i.test(url) || url.startsWith("http");
  }
  try {
    if (p.includes("://")) {
      const [schemePart, rest] = p.split("://", 2);
      let hostPart = rest;
      let pathPart = "/*";
      if (rest.includes("/")) {
        const slashIdx = rest.indexOf("/");
        hostPart = rest.slice(0, slashIdx);
        pathPart = rest.slice(slashIdx);
      }
      const schemeRe = schemePart === "*" ? "https?" : schemePart.replace(/[.+^${}()|[\]\\]/g, "\\$&");
      let hostRe =
        hostPart === "*"
          ? "[^/]+"
          : hostPart.startsWith("*.")
          ? "(?:[a-zA-Z0-9\\-._]+\\.)?" + hostPart.slice(2).replace(/[.+^${}()|[\]\\]/g, "\\$&")
          : hostPart.replace(/[.+^${}()|[\]\\]/g, "\\$&");
      const pathRe =
        pathPart === "/*"
          ? "(?:/.*)?"
          : pathPart.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\\\*/g, ".*");
      const fullRegex = new RegExp(`^${schemeRe}://${hostRe}${pathRe}$`, "i");
      return fullRegex.test(url);
    }
    const regexPattern =
      "^" +
      p
        .replace(/[.+^${}()|[\]\\]/g, "\\$&")
        .replace(/\\\*/g, ".*")
        .replace(/\*/g, ".*")
        .replace(/\?/g, ".") +
      "$";
    return new RegExp(regexPattern, "i").test(url);
  } catch (_) {
    return url.includes(p.replace(/\*/g, ""));
  }
}

export function isPluginApplied(article, pluginId) {
  if (!article || !pluginId) return false;
  const applied = article.applied_plugins || [];
  if (applied.includes(pluginId)) return true;
  const pLower = pluginId.toLowerCase();
  if (pLower.includes("gemini-summary") || pLower.includes("gemini_summary")) {
    return Boolean(article.ai_summary && String(article.ai_summary).trim());
  }
  if (pLower.includes("yahoo")) {
    return Boolean(article.content_html && article.content_html.includes("yh-article"));
  }
  if (pLower.includes("ptt")) {
    return Boolean(
      article.content_html &&
        (article.content_html.includes("ptt-meta-card") || article.content_html.includes("ptt-pushes-card"))
    );
  }
  if (pLower.includes("mobile01")) {
    return Boolean(article.content_html && article.content_html.includes("m01-article"));
  }
  return false;
}

export class ReaderView {
  constructor(containerEl) {
    this.container = containerEl;
    this.draggedActionKey = null;
    this.isPickerOpen = false;

    this._migrateToolbarConfig();
    this.initListeners();
  }

  _migrateToolbarConfig() {
    let order = store.get("readerToolbarOrder");
    let visible = store.get("readerToolbarVisible");
    let changed = false;

    if (!Array.isArray(order)) {
      order = ALL_READER_ACTIONS.map((a) => a.key);
      changed = true;
    } else {
      ALL_READER_ACTIONS.forEach((act) => {
        if (!order.includes(act.key)) {
          order.push(act.key);
          changed = true;
        }
      });
    }

    if (!visible || typeof visible !== "object") {
      visible = {};
      ALL_READER_ACTIONS.forEach((a) => {
        visible[a.key] = a.defaultVisible;
      });
      changed = true;
    } else {
      ALL_READER_ACTIONS.forEach((act) => {
        if (visible[act.key] === undefined) {
          visible[act.key] = act.defaultVisible;
          changed = true;
        }
      });
    }

    if (changed) {
      store.set("readerToolbarOrder", order);
      store.set("readerToolbarVisible", visible);
    }
  }

  _getAiSummaryPlugin() {
    // 動態從 store 查找有 prompt_presets 能力的已啟用外掛，不再寫死 ID
    // Dynamically find any enabled processor plugin that exposes prompt_presets capability
    const plugins = store.get("plugins") || [];
    const aiPlugin = plugins.find((item) => {
      if (item.is_enabled === false) return false;
      const cfg = { ...(item.default_config || {}), ...(item.user_config || {}) };
      return Array.isArray(cfg.prompt_presets) && cfg.prompt_presets.length > 0;
    });
    const aiPluginId = aiPlugin ? (aiPlugin.plugin_id || aiPlugin.id) : null;
    const cfg = aiPlugin ? { ...(aiPlugin.default_config || {}), ...(aiPlugin.user_config || {}) } : null;
    const presets = (cfg && Array.isArray(cfg.prompt_presets) && cfg.prompt_presets.length > 0)
      ? cfg.prompt_presets
      : (typeof OFFICIAL_GEMINI_PRESETS !== "undefined" ? OFFICIAL_GEMINI_PRESETS : []);
    const defaultId = (cfg && cfg.default_preset_id) || "standard";
    return { presets, defaultId, aiPluginId };
  }

  initListeners() {
    store.subscribe("selectedArticle", (article) => this.render(article));
    store.subscribe("readerToolbarOrder", () => {
      const article = store.get("selectedArticle");
      if (article) this.render(article);
    });
    store.subscribe("readerToolbarVisible", () => {
      const article = store.get("selectedArticle");
      if (article) this.render(article);
    });
    store.subscribe("readerToolbarMode", () => {
      const article = store.get("selectedArticle");
      if (article) this.render(article);
    });

    // 監聽外掛設定更新事件，立即刷新工具列與選單
    window.addEventListener("omnirss:plugins-updated", () => {
      const article = store.get("selectedArticle");
      if (article) this.render(article);
    });

    // Handle global click to close reader action picker & AI summary menu
    document.addEventListener("click", (e) => {
      if (this.isPickerOpen) {
        const pickerBtn = e.target.closest("#btn-reader-action-picker");
        const dropdown = e.target.closest("#reader-action-picker-dropdown");
        if (!pickerBtn && !dropdown) {
          this.closePicker();
        }
      }
      const aiGroup = e.target.closest("#group-reader-ai-summary");
      if (!aiGroup) {
        const menu = this.container.querySelector("#menu-ai-summary");
        if (menu) menu.style.display = "none";
      }
      const pluginsGroup = e.target.closest("#group-reader-run-plugins");
      if (!pluginsGroup) {
        const menu = this.container.querySelector("#menu-run-plugins");
        if (menu) menu.style.display = "none";
      }
    });

    // Handle button actions inside reader toolbar & tags
    this.container.addEventListener("click", async (e) => {
      const article = store.get("selectedArticle");

      // 0. Toggle Reader Action Picker Dropdown [ ⊞ ]
      const pickerBtn = e.target.closest("#btn-reader-action-picker");
      if (pickerBtn) {
        e.stopPropagation();
        this.togglePicker();
        return;
      }

      // 0.05 Radio Toggle in Picker for Toolbar Mode (both vs icon_only)
      const modeRadio = e.target.closest(".reader-mode-radio");
      if (modeRadio) {
        e.stopPropagation();
        store.set("readerToolbarMode", modeRadio.value);
        window.dispatchEvent(new CustomEvent("omnirss:reader-toolbar-changed"));
        return;
      }

      // 0.1 Reset Picker to Defaults Button
      const resetPickerBtn = e.target.closest("#btn-reset-reader-picker");
      if (resetPickerBtn) {
        e.stopPropagation();
        const defaultVisible = {};
        ALL_READER_ACTIONS.forEach((a) => {
          defaultVisible[a.key] = a.defaultVisible;
        });
        const defaultOrder = ALL_READER_ACTIONS.map((a) => a.key);
        store.set("readerToolbarVisible", defaultVisible);
        store.set("readerToolbarOrder", defaultOrder);
        store.set("readerToolbarMode", "both");
        window.dispatchEvent(new CustomEvent("omnirss:reader-toolbar-changed"));
        window.dispatchEvent(
          new CustomEvent("omnirss:toast", {
            detail: { message: t("reader.picker_reset_success") || "已恢復預設工具列按鈕", type: "success" },
          })
        );
        return;
      }

      // 0.2 Checkbox toggle in picker
      const toggleCb = e.target.closest(".reader-action-toggle-cb");
      if (toggleCb) {
        e.stopPropagation();
        const actionKey = toggleCb.dataset.actionKey;
        const currentVis = { ...(store.get("readerToolbarVisible") || {}) };
        currentVis[actionKey] = toggleCb.checked;
        store.set("readerToolbarVisible", currentVis);
        window.dispatchEvent(new CustomEvent("omnirss:reader-toolbar-changed"));
        return;
      }

      // Actions below require an active article
      if (!article) return;

      // 0.8 Run Processor Plugins Menu Toggle & Execution
      const runPluginsDropdownBtn = e.target.closest("#btn-reader-run-plugins-dropdown");
      if (runPluginsDropdownBtn) {
        e.stopPropagation();
        const menu = this.container.querySelector("#menu-run-plugins");
        if (menu) {
          menu.style.display = menu.style.display === "none" ? "flex" : "none";
        }
        return;
      }

      // 0.8.1 Toggle Flyout Submenu on mobile/touch
      const toggleSubActionsBtn = e.target.closest(".btn-toggle-sub-actions");
      if (toggleSubActionsBtn) {
        e.stopPropagation();
        const wrapper = toggleSubActionsBtn.closest(".run-plugin-menu-wrapper");
        if (wrapper) {
          wrapper.classList.toggle("is-open");
        }
        return;
      }

      // 0.8.2 Sub-Action Item Click (Specific Style / Action)
      const runPluginSubItem = e.target.closest(".run-plugin-sub-item");
      // 0.8.3 Main Plugin Item / Menu Item Click (Smart Auto)
      const runPluginMainItem = e.target.closest(".run-plugin-item-main") || e.target.closest(".run-plugin-menu-item");
      // 0.8.4 Top Toolbar Main Plugin Button Click (Smart Auto)
      const runPluginMainBtn = e.target.closest("#btn-reader-run-plugins-main");

      if (runPluginSubItem || runPluginMainItem || (runPluginMainBtn && !e.target.closest("#btn-reader-run-plugins-dropdown"))) {
        const menu = this.container.querySelector("#menu-run-plugins");
        if (menu) menu.style.display = "none";
        this.container.querySelectorAll(".run-plugin-menu-wrapper.is-open").forEach((el) => el.classList.remove("is-open"));

        let targetPluginId = null;
        let targetPluginName = "";
        let actionParam = null;
        let actionName = "";

        if (runPluginSubItem) {
          targetPluginId = runPluginSubItem.dataset.pluginId;
          targetPluginName = runPluginSubItem.dataset.pluginName || targetPluginId;
          actionParam = runPluginSubItem.dataset.actionId || null;
          actionName = runPluginSubItem.dataset.actionName || "";
        } else if (runPluginMainItem) {
          targetPluginId = runPluginMainItem.dataset.pluginId;
          targetPluginName = runPluginMainItem.dataset.pluginName || targetPluginId;
          actionParam = null; // Smart Auto
        } else if (runPluginMainBtn) {
          targetPluginId = runPluginMainBtn.dataset.defaultPluginId;
          targetPluginName = runPluginMainBtn.dataset.defaultPluginName || "外掛處理";
          actionParam = null; // Smart Auto
        }

        if (!targetPluginId) {
          if (menu) menu.style.display = "flex";
          return;
        }

        const mainBtn = this.container.querySelector("#btn-reader-run-plugins-main") || runPluginMainBtn;
        if (mainBtn) mainBtn.classList.add("busy");

        const displayActionLabel = actionName ? `「${targetPluginName} - ${actionName}」` : `「${targetPluginName}」`;
        window.dispatchEvent(
          new CustomEvent("omnirss:toast", {
            detail: { message: `正在執行 ${displayActionLabel} 處理文章...`, type: "info" },
          })
        );

        try {
          const updated = await api.executeArticlePlugin(targetPluginId, article.id, actionParam);
          store.set("selectedArticle", updated);

          const articles = store.get("articles") || [];
          const a = articles.find((item) => item.id === article.id);
          if (a) {
            a.content_html = updated.content_html;
            a.content_text = updated.content_text;
            a.applied_plugins = updated.applied_plugins;
            if (updated.ai_summary) {
              a.ai_summary = updated.ai_summary;
            }
          }
          store.set("articles", [...articles]);

          // 即時重新渲染閱讀面板內容與外掛加工徽章
          this.render(updated);

          window.dispatchEvent(
            new CustomEvent("omnirss:toast", {
              detail: { message: `${displayActionLabel} 處理完成！`, type: "success" },
            })
          );
        } catch (err) {
          window.dispatchEvent(
            new CustomEvent("omnirss:toast", {
              detail: { message: `外掛執行失敗: ${err.message}`, type: "error" },
            })
          );
        } finally {
          if (mainBtn) mainBtn.classList.remove("busy");
          window.dispatchEvent(new CustomEvent("omnirss:plugins-updated"));
        }
        return;
      }

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

      // 3.1 AI Summary via Plugin (Universal Slot Dispatch & Dropdown Menu)
      const aiDropdownBtn = e.target.closest("#btn-reader-ai-dropdown");
      if (aiDropdownBtn) {
        e.stopPropagation();
        const menu = this.container.querySelector("#menu-ai-summary");
        if (menu) {
          menu.style.display = menu.style.display === "none" ? "flex" : "none";
        }
        return;
      }

      const aiMenuItem = e.target.closest(".ai-summary-menu-item");
      const aiSummaryBtn = e.target.closest("#btn-reader-ai-summary");

      if (aiMenuItem || aiSummaryBtn) {
        const menu = this.container.querySelector("#menu-ai-summary");
        if (menu) menu.style.display = "none";

        const { presets, defaultId, aiPluginId } = this._getAiSummaryPlugin();
        let selectedPresetId = null;
        let selectedPresetName = "";

        if (aiMenuItem) {
          selectedPresetId = aiMenuItem.dataset.preset;
          const found = presets.find((p) => p.id === selectedPresetId);
          selectedPresetName = found ? found.name : selectedPresetId;
        } else {
          selectedPresetId = defaultId;
          const found = presets.find((p) => p.id === defaultId);
          selectedPresetName = found ? found.name : (t("reader.btn_ai_summary") || "預設風格");
        }

        const mainBtn = this.container.querySelector("#btn-reader-ai-summary") || aiSummaryBtn;

        if (mainBtn) mainBtn.classList.add("busy");
        const loadingMsg = selectedPresetName
          ? `正在產生「${selectedPresetName}」摘要...`
          : (t("reader.ai_summary_loading") || "正在產生重點摘要...");

        window.dispatchEvent(
          new CustomEvent("omnirss:toast", {
            detail: { message: loadingMsg, type: "info" },
          })
        );
        try {
          const updated = await api.executeArticlePlugin(aiPluginId, article.id, selectedPresetId);
          store.set("selectedArticle", updated);

          const articles = store.get("articles") || [];
          const a = articles.find((item) => item.id === article.id);
          if (a) {
            a.ai_summary = updated.ai_summary;
            a.content_html = updated.content_html || a.content_html;
            a.content_text = updated.content_text || a.content_text;
            a.applied_plugins = updated.applied_plugins || a.applied_plugins || [];
          }
          store.set("articles", [...articles]);

          // 即時重新渲染閱讀面板內容與外掛加工徽章
          this.render(updated);

          window.dispatchEvent(
            new CustomEvent("omnirss:toast", {
              detail: {
                message: selectedPresetName
                  ? `「${selectedPresetName}」摘要生成完成`
                  : (t("reader.ai_summary_success") || "重點摘要生成完成"),
                type: "success",
              },
            })
          );
        } catch (err) {
          window.dispatchEvent(
            new CustomEvent("omnirss:toast", {
              detail: { message: t("reader.ai_summary_failed", { error: err.message }) || `摘要生成失敗: ${err.message}`, type: "error" },
            })
          );
        } finally {
          if (mainBtn) mainBtn.classList.remove("busy");
          window.dispatchEvent(new CustomEvent("omnirss:plugins-updated"));
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

      // 3.7 Font Scale Down (A-)
      const fontDecBtn = e.target.closest("#btn-reader-font-dec");
      if (fontDecBtn) {
        const currentSize = parseInt(store.get("readerFontSize") || "15", 10);
        const newSize = Math.max(12, currentSize - 1);
        store.set("readerFontSize", newSize);
        document.documentElement.style.setProperty("--reader-font-size", `${newSize}px`);
        window.dispatchEvent(
          new CustomEvent("omnirss:toast", {
            detail: { message: `${t("reader.font_size_label") || "文章字級"}: ${newSize}px`, type: "info" },
          })
        );
        return;
      }

      // 3.8 Font Scale Up (A+)
      const fontIncBtn = e.target.closest("#btn-reader-font-inc");
      if (fontIncBtn) {
        const currentSize = parseInt(store.get("readerFontSize") || "15", 10);
        const newSize = Math.min(26, currentSize + 1);
        store.set("readerFontSize", newSize);
        document.documentElement.style.setProperty("--reader-font-size", `${newSize}px`);
        window.dispatchEvent(
          new CustomEvent("omnirss:toast", {
            detail: { message: `${t("reader.font_size_label") || "文章字級"}: ${newSize}px`, type: "info" },
          })
        );
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
              detail: { message: t("list.link_copied") || "已複製文章連結", type: "success" },
            })
          );
        }
        return;
      }

      // 6. Feed Chip Click -> Focus feed
      const feedChip = e.target.closest(".clickable-feed-filter");
      if (feedChip) {
        const feedId = parseInt(feedChip.dataset.feedId, 10);
        if (feedId) {
          window.dispatchEvent(new CustomEvent("omnirss:select-feed", { detail: { id: feedId } }));
        }
        return;
      }

      // 7. Content Links Click Handler (Safe Target & PTT User Redirect)
      const contentLink = e.target.closest(".article-content a");
      if (contentLink) {
        const href = contentLink.getAttribute("href") || "";
        if (href.startsWith("/ptt/user/")) {
          e.preventDefault();
          e.stopPropagation();
          const username = href.replace("/ptt/user/", "").split("/")[0].split("?")[0];
          window.open(`https://www.pttweb.cc/user/${encodeURIComponent(username)}`, "_blank", "noopener,noreferrer");
          return;
        }
        if (href && !href.startsWith("#") && !href.startsWith("javascript:")) {
          contentLink.setAttribute("target", "_blank");
          contentLink.setAttribute("rel", "noopener noreferrer");
        }
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
        const order = [...(store.get("readerToolbarOrder") || ALL_READER_ACTIONS.map((a) => a.key))];
        const srcIdx = order.indexOf(this.draggedActionKey);
        if (srcIdx !== -1) {
          order.splice(srcIdx, 1);
          let targetIdx = order.indexOf(targetKey);
          if (!isLeft) targetIdx += 1;
          order.splice(targetIdx, 0, this.draggedActionKey);
          store.set("readerToolbarOrder", order);
          window.dispatchEvent(new CustomEvent("omnirss:reader-toolbar-order-changed"));
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

  togglePicker() {
    this.isPickerOpen = !this.isPickerOpen;
    const dropdown = this.container.querySelector("#reader-action-picker-dropdown");
    const pickerBtn = this.container.querySelector("#btn-reader-action-picker");
    if (dropdown) {
      dropdown.classList.toggle("open", this.isPickerOpen);
      dropdown.style.display = this.isPickerOpen ? "block" : "none";
    }
    if (pickerBtn) pickerBtn.classList.toggle("active", this.isPickerOpen);
  }

  closePicker() {
    this.isPickerOpen = false;
    const dropdown = this.container.querySelector("#reader-action-picker-dropdown");
    const pickerBtn = this.container.querySelector("#btn-reader-action-picker");
    if (dropdown) {
      dropdown.classList.remove("open");
      dropdown.style.display = "none";
    }
    if (pickerBtn) pickerBtn.classList.remove("active");
  }

  render(article) {
    if (!article) {
      this.container.innerHTML = `
        <div class="reader-empty-hero">
          <div class="reader-hero-badge">
            <svg width="60" height="60" viewBox="0 0 512 512" fill="none">
              <defs>
                <linearGradient id="heroRssGrad" x1="0%" y1="100%" x2="100%" y2="0%">
                  <stop offset="0%" stop-color="#ff4500" />
                  <stop offset="50%" stop-color="#f97316" />
                  <stop offset="100%" stop-color="#fbbf24" />
                </linearGradient>
              </defs>
              <circle cx="112" cy="400" r="48" fill="url(#heroRssGrad)" />
              <path d="M112 216 C213.62 216 296 298.38 296 400" stroke="url(#heroRssGrad)" stroke-width="56" stroke-linecap="round" />
              <path d="M112 88 C284.31 88 424 227.69 424 400" stroke="url(#heroRssGrad)" stroke-width="56" stroke-linecap="round" />
            </svg>
          </div>
          <h2 class="reader-hero-title">${t("reader.welcome_title", "OmniRSS 現代高密度閱讀器")}</h2>
          <p class="reader-hero-subtitle">${t("reader.welcome_subtitle", "請從左側列表點選文章開始閱讀，或使用下方鍵盤快捷鍵快速導航")}</p>
          
          <div class="reader-hero-shortcuts">
            <div class="hero-shortcut-chip">
              <span class="shortcut-keys"><kbd>J</kbd> / <kbd>K</kbd></span>
              <span class="shortcut-desc">${t("reader.shortcut_nav", "切換文章")}</span>
            </div>
            <div class="hero-shortcut-chip">
              <span class="shortcut-keys"><kbd>Space</kbd></span>
              <span class="shortcut-desc">${t("reader.shortcut_scroll", "文章捲動")}</span>
            </div>
            <div class="hero-shortcut-chip">
              <span class="shortcut-keys"><kbd>S</kbd></span>
              <span class="shortcut-desc">${t("reader.shortcut_star", "星標收藏")}</span>
            </div>
            <div class="hero-shortcut-chip">
              <span class="shortcut-keys"><kbd>Shift</kbd>+<kbd>A</kbd></span>
              <span class="shortcut-desc">${t("reader.shortcut_mark_read", "全部已讀")}</span>
            </div>
            <div class="hero-shortcut-chip">
              <span class="shortcut-keys"><kbd>/</kbd></span>
              <span class="shortcut-desc">${t("reader.shortcut_search", "快速搜尋")}</span>
            </div>
          </div>
        </div>
      `;
      return;
    }

    const isStarred = article.is_starred === true;
    const isUnread = article.is_read === false || article.is_read === 0 || article.is_unread === true;
    const formattedDate = article.published_at ? parseUtcDate(article.published_at).toLocaleString() : "";
    const articleLink = article.url || article.link;

    const toolbarOrder = store.get("readerToolbarOrder") || ALL_READER_ACTIONS.map((a) => a.key);
    const visibleMap = store.get("readerToolbarVisible") || {};
    const toolbarMode = store.get("readerToolbarMode") || "both";
    const isIconOnly = toolbarMode === "icon_only";

    // Render Draggable Action Buttons from Order (Only if visible)
    const dragSuffix = ` ${t("reader.drag_sort_suffix") || "(可拖曳換位)"}`;
    const actionButtonsHtml = toolbarOrder
      .map((actionKey) => {
        // 檢查是否被使用者勾選隱藏
        if (visibleMap[actionKey] === false) return "";

        const btnClass = `icon-btn reader-action-drag ${isIconOnly ? "icon-only-btn" : ""}`;

        if (actionKey === "star") {
          const label = isStarred ? t("reader.unstar") : t("reader.star");
          return `
            <button class="${btnClass} ${isStarred ? "active starred" : ""}" id="btn-reader-toggle-star" draggable="true" data-action-key="star" title="${label}${dragSuffix}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="${isStarred ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
              ${!isIconOnly ? `<span>${label}</span>` : ""}
            </button>
          `;
        }
        if (actionKey === "toggle_read") {
          const label = isUnread ? t("reader.mark_read") : t("reader.mark_unread");
          return `
            <button class="${btnClass}" id="btn-reader-toggle-read" draggable="true" data-action-key="toggle_read" title="${label}${dragSuffix}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
              ${!isIconOnly ? `<span>${label}</span>` : ""}
            </button>
          `;
        }
        if (actionKey === "run_plugins") {
          const plugins = store.get("plugins") || [];
          const activeProcessors = plugins.filter(
            (p) => p.slot_type === "processor" && p.is_enabled !== false
          );
          if (activeProcessors.length === 0) return "";

          const url = (article.url || article.link || "").toLowerCase();

          // 輔助函式：判斷是否為通用萬用規則
          const isUniversalPattern = (patterns) => {
            if (!Array.isArray(patterns) || patterns.length === 0) return false;
            return patterns.some((pat) => {
              const s = String(pat).trim();
              return s === "<all_urls>" || s === "*" || s === "*://*/*" || s === "*://*";
            });
          };

          // 1. 第一順位：命中專屬網域（非通用萬用規則）且尚未套用過的外掛
          let matchedP = activeProcessors.find((p) => {
            const pId = p.plugin_id || p.id;
            if (isPluginApplied(article, pId)) return false;
            const patterns = p.match_patterns || (p.manifest && p.manifest.match_patterns) || [];
            if (Array.isArray(patterns) && patterns.length > 0 && !isUniversalPattern(patterns)) {
              return patterns.some((pat) => matchUrlPattern(url, pat));
            }
            return false;
          });

          let isAllApplied = false;

          // 2. 第二順位：若無專屬外掛（或專屬外掛已套用），尋找尚未套用之全網址外掛（如 Gemini AI 摘要）
          if (!matchedP) {
            matchedP = activeProcessors.find((p) => {
              const pId = p.plugin_id || p.id;
              if (isPluginApplied(article, pId)) return false;
              const patterns = p.match_patterns || (p.manifest && p.manifest.match_patterns) || [];
              return isUniversalPattern(patterns);
            });
          }

          // 3. 保底：若所有適用外掛均已套用或無命中，則選擇第一個外掛，並標記 isAllApplied = true
          if (!matchedP) {
            matchedP = activeProcessors[0];
            isAllApplied = true;
          }

          const resolveI18nText = (field) => {
            if (!field) return "";
            if (typeof field === "object") {
              const lang = store.get("lang") || "zh-TW";
              return field[lang] || field["zh-TW"] || field["en-US"] || field["en"] || Object.values(field)[0] || "";
            }
            return String(field);
          };

          const getPluginActions = (p) => {
            if (Array.isArray(p.actions) && p.actions.length > 0) return p.actions;
            if (p.manifest && Array.isArray(p.manifest.actions) && p.manifest.actions.length > 0) return p.manifest.actions;
            const cfg = { ...(p.default_config || {}), ...(p.user_config || {}) };
            if (Array.isArray(cfg.prompt_presets) && cfg.prompt_presets.length > 0) {
              return cfg.prompt_presets.map((pr) => ({
                id: pr.id,
                name: pr.name,
                description: pr.description || "",
                icon: pr.icon || "✨",
              }));
            }
            return [];
          };

          const defaultPName = resolveI18nText(matchedP.name) || (matchedP.plugin_id || matchedP.id);
          const defaultPIcon = matchedP.icon || (matchedP.manifest && matchedP.manifest.icon) || "🧩";
          const label = t("reader.action_run_plugins") || "外掛處理";

          return `
            <div class="run-plugins-btn-group reader-action-drag" id="group-reader-run-plugins" draggable="true" data-action-key="run_plugins" style="position: relative; display: inline-flex; align-items: center;">
              <button class="icon-btn btn-run-plugins-main ${isIconOnly ? "icon-only-btn" : ""}" id="btn-reader-run-plugins-main" title="${label}: ${defaultPName}${isAllApplied ? " (已皆處理)" : " (推薦)"}${dragSuffix}" data-default-plugin-id="${matchedP.plugin_id || matchedP.id}" data-default-plugin-name="${this.escape(defaultPName)}" style="border-top-right-radius: 0; border-bottom-right-radius: 0; border-right: none;">
                <span style="font-size: 13px;">${this.escape(defaultPIcon)}</span>
                ${!isIconOnly ? `<span>${label}</span>` : ""}
              </button>
              <button class="icon-btn btn-run-plugins-dropdown" id="btn-reader-run-plugins-dropdown" title="選擇外掛處理器與風格動作" style="border-top-left-radius: 0; border-bottom-left-radius: 0; padding: 0 4px; min-width: 18px;">
                <span class="dropdown-caret" style="font-size: 10px;">▾</span>
              </button>
              <div class="run-plugins-menu" id="menu-run-plugins" style="display:none; position: absolute; top: calc(100% + 4px); left: 0; background: var(--bg-surface-elevated, var(--bg-surface)); border: 1px solid var(--border-color); border-radius: 6px; box-shadow: 0 8px 24px rgba(0,0,0,0.3); z-index: 100; min-width: 210px; flex-direction: column; padding: 4px; gap: 2px;">
                <div style="font-size: 10px; color: var(--text-muted); padding: 4px 8px; font-weight: 600; border-bottom: 1px solid var(--border-color-subtle, rgba(255,255,255,0.05)); margin-bottom: 2px;">選擇處理外掛 (Processor)</div>
                ${activeProcessors
                  .map((p) => {
                    const pId = p.plugin_id || p.id;
                    const pName = resolveI18nText(p.name) || pId;
                    const pIcon = p.icon || (p.manifest && p.manifest.icon) || "🧩";
                    const isMatched = !isAllApplied && (pId === (matchedP.plugin_id || matchedP.id));
                    const isApplied = isPluginApplied(article, pId);
                    const actions = getPluginActions(p);

                    if (actions.length > 0) {
                      return `
                        <div class="run-plugin-menu-wrapper ${isMatched ? "is-recommended" : ""}" data-plugin-id="${this.escape(pId)}">
                          <div class="run-plugin-item-main" data-plugin-id="${this.escape(pId)}" data-plugin-name="${this.escape(pName)}" title="${this.escape(pName)} (智慧自動)">
                            <span class="plugin-item-left">
                              <span class="sub-item-icon">${this.escape(pIcon)}</span>
                              <span class="plugin-menu-name">${this.escape(pName)}</span>
                            </span>
                            <span class="plugin-item-badges">
                              ${isMatched ? `<span class="badge-rec">推薦</span>` : ""}
                              ${isApplied ? `<span class="badge-applied">已套用</span>` : ""}
                            </span>
                          </div>
                          <button type="button" class="btn-toggle-sub-actions" title="展開自選風格與動作">
                            <span class="arrow-caret">▸</span>
                          </button>
                          <div class="run-plugin-submenu">
                            <div class="run-plugin-submenu-header">${this.escape(pName)} 風格/動作</div>
                            ${actions
                              .map((act) => {
                                const actName = resolveI18nText(act.name) || act.id;
                                const actDesc = resolveI18nText(act.description) || "";
                                const actIcon = act.icon || "⚡";
                                return `
                                  <div class="run-plugin-sub-item" data-plugin-id="${this.escape(pId)}" data-plugin-name="${this.escape(pName)}" data-action-id="${this.escape(act.id)}" data-action-name="${this.escape(actName)}">
                                    <span class="sub-item-icon">${this.escape(actIcon)}</span>
                                    <div class="sub-item-content">
                                      <span class="sub-item-name">${this.escape(actName)}</span>
                                      ${actDesc ? `<span class="sub-item-desc">${this.escape(actDesc)}</span>` : ""}
                                    </div>
                                  </div>
                                `;
                              })
                              .join("")}
                          </div>
                        </div>
                      `;
                    }

                    return `
                      <div class="run-plugin-menu-item ${isMatched ? "is-recommended" : ""}" data-plugin-id="${this.escape(pId)}" data-plugin-name="${this.escape(pName)}">
                        <span class="plugin-item-left">
                          <span class="sub-item-icon">${this.escape(pIcon)}</span>
                          <span class="plugin-menu-name">${this.escape(pName)}</span>
                        </span>
                        <span class="plugin-item-badges">
                          ${isMatched ? `<span class="badge-rec">推薦</span>` : ""}
                          ${isApplied ? `<span class="badge-applied">已套用</span>` : ""}
                        </span>
                      </div>
                    `;
                  })
                  .join("")}
              </div>
            </div>
          `;
        }
        if (actionKey === "tag") {
          const label = t("tree.tags") || "標籤";
          return `
            <button class="${btnClass}" id="btn-reader-tag" draggable="true" data-action-key="tag" title="${t("reader.action_tag") || "標籤管理"}${dragSuffix}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>
              ${!isIconOnly ? `<span>${label}</span>` : ""}
            </button>
          `;
        }
        if (actionKey === "trash") {
          const isTrash = Boolean(article.is_trash) || store.get("activeFilter") === "trash";
          const label = isTrash ? t("reader.restore") : t("reader.trash");
          return `
            <button class="${btnClass} ${isTrash ? "danger" : ""}" id="btn-reader-trash" draggable="true" data-action-key="trash" title="${label}${dragSuffix}">
              ${
                isTrash
                  ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>`
                  : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`
              }
              ${!isIconOnly ? `<span>${label}</span>` : ""}
            </button>
          `;
        }
        if (actionKey === "fetch_full") {
          const label = t("reader.fetch_full") || "抓取全文";
          return `
            <button class="${btnClass}" id="btn-reader-fetch-full" draggable="true" data-action-key="fetch_full" title="${t("reader.action_fetch_full") || "📖 抓取全文"}${dragSuffix}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
              ${!isIconOnly ? `<span>${label}</span>` : ""}
            </button>
          `;
        }
        if (actionKey === "copy_link") {
          const label = t("reader.copy_link") || "複製連結";
          return `
            <button class="${btnClass}" id="btn-reader-copy-link" draggable="true" data-action-key="copy_link" title="${t("reader.action_copy_link") || "📋 複製連結"}${dragSuffix}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              ${!isIconOnly ? `<span>${label}</span>` : ""}
            </button>
          `;
        }
        if (actionKey === "open_url") {
          const label = t("reader.open_original") || "開啟原文";
          return articleLink
            ? `
            <a class="${btnClass}" href="${articleLink}" target="_blank" rel="noopener noreferrer" draggable="true" data-action-key="open_url" title="${t("reader.action_open_url") || "🌐 開啟原文"}${dragSuffix}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
              ${!isIconOnly ? `<span>${label}</span>` : ""}
            </a>
          `
            : "";
        }
        if (actionKey === "font_dec") {
          return `
            <button class="${btnClass}" id="btn-reader-font-dec" draggable="true" data-action-key="font_dec" title="${t("reader.action_font_dec") || "🔤 縮小字級 (A-)"}${dragSuffix}">
              <span style="font-size: 11px; font-weight: 700; font-family: sans-serif;">A-</span>
            </button>
          `;
        }
        if (actionKey === "font_inc") {
          return `
            <button class="${btnClass}" id="btn-reader-font-inc" draggable="true" data-action-key="font_inc" title="${t("reader.action_font_inc") || "🔤 放大字級 (A+)"}${dragSuffix}">
              <span style="font-size: 13px; font-weight: 700; font-family: sans-serif;">A+</span>
            </button>
          `;
        }
        return "";
      })
      .join("");

    // Render Picker Dropdown Checkbox Items
    const activePlugins = store.get("plugins") || [];
    // 動態偵測是否有具 prompt_presets 能力的已啟用外掛（Manifest 驅動，不寫死特定 ID）
    const hasAiSummaryPlugin = activePlugins.some((p) => {
      if (p.is_enabled === false) return false;
      const cfg = { ...(p.default_config || {}), ...(p.user_config || {}) };
      return Array.isArray(cfg.prompt_presets) && cfg.prompt_presets.length > 0;
    });
    const hasProcessorPlugins = activePlugins.some((p) => p.slot_type === "processor" && p.is_enabled !== false);

    const availableActions = ALL_READER_ACTIONS.filter((action) => {
      if (action.key === "ai_summary" && !hasAiSummaryPlugin) return false;
      if (action.key === "run_plugins" && !hasProcessorPlugins) return false;
      return true;
    });

    const pickerItemsHtml = availableActions.map((action) => {
      const isChecked = visibleMap[action.key] !== false;
      const labelText = t(action.name, action.defaultName);
      return `
        <label class="reader-picker-item">
          <input type="checkbox" class="reader-action-toggle-cb" data-action-key="${action.key}" ${isChecked ? "checked" : ""} />
          <span>${labelText}</span>
        </label>
      `;
    }).join("");

    let html = `
      <!-- Compact Draggable Actions Toolbar with Picker ⊞ -->
      <div class="reader-toolbar">
        <div class="reader-toolbar-group ${isIconOnly ? "icon-only-mode" : ""}">
          ${actionButtonsHtml}
        </div>

        <div class="reader-toolbar-right" style="margin-left: auto; position: relative;">
          <button class="icon-btn reader-picker-trigger-btn ${this.isPickerOpen ? "active" : ""}" id="btn-reader-action-picker" title="${t("reader.customize_toolbar", "自選閱讀器工具列按鈕 (⊞)")}">
            <span class="picker-trigger-icon">⊞</span>
          </button>

          <!-- Dropdown Popover (Guaranteed hidden unless open) -->
          <div class="reader-action-picker-dropdown ${this.isPickerOpen ? "open" : ""}" id="reader-action-picker-dropdown" style="display: ${this.isPickerOpen ? "block" : "none"};">
            <div class="picker-header">
              <span>${t("reader.picker_title", "自選閱讀按鈕")}</span>
              <button type="button" class="btn-text-reset" id="btn-reset-reader-picker">${t("common.reset", "重置")}</button>
            </div>
            <div class="picker-mode-section">
              <div class="picker-mode-title">${t("reader.display_mode_title", "按鈕顯示樣式")}</div>
              <div class="picker-mode-options">
                <label class="picker-mode-label">
                  <input type="radio" name="reader-toolbar-mode" class="reader-mode-radio" value="both" ${!isIconOnly ? "checked" : ""} />
                  <span>${t("reader.mode_both", "圖示與文字")}</span>
                </label>
                <label class="picker-mode-label">
                  <input type="radio" name="reader-toolbar-mode" class="reader-mode-radio" value="icon_only" ${isIconOnly ? "checked" : ""} />
                  <span>${t("reader.mode_icon_only", "純圖標")}</span>
                </label>
              </div>
            </div>
            <div class="picker-list">
              ${pickerItemsHtml}
            </div>
          </div>
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
            ${(article.applied_plugins || [])
              .map((pId) => {
                // 從 store 動態查詢外掛的 badge 元資料，完全移除硬編碼字典
                const allPlugins = store.get("plugins") || [];
                const pluginObj = allPlugins.find((p) => (p.plugin_id || p.id) === pId);
                const badge = pluginObj && pluginObj.badge;
                const name = badge ? badge.short_name : (pluginObj ? (pluginObj.name && typeof pluginObj.name === "object" ? (pluginObj.name["zh-TW"] || Object.values(pluginObj.name)[0]) : pluginObj.name) : pId.split("/")[1] || pId);
                const icon = badge ? badge.icon : "🧩";
                const color = badge ? badge.color : "#60a5fa";
                return `<span class="badge-plugin-applied" title="已套用 ${this.escape(name)} 外掛加工" style="display: inline-flex; align-items: center; gap: 4px; font-size: 11px; padding: 1px 7px; border-radius: 4px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.15); color: ${color}; font-weight: 500;">${icon} ${this.escape(name)}</span>`;
              })
              .join("")}
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

    // 增強文章內圖片載入：注入 no-referrer、lazy loading、還原 data-src，並設定 onerror 智能中繼代理
    this.container.querySelectorAll(".article-content img").forEach((img) => {
      if (!img.getAttribute("referrerpolicy")) {
        img.setAttribute("referrerpolicy", "no-referrer");
      }
      if (!img.getAttribute("loading")) {
        img.setAttribute("loading", "lazy");
      }
      const dataSrc = img.getAttribute("data-src") || img.getAttribute("data-original");
      if (dataSrc && (!img.getAttribute("src") || img.getAttribute("src").startsWith("data:"))) {
        img.setAttribute("src", dataSrc);
      }

      // 智能中繼容錯：若外部圖片載入失敗 (如遭本地電信 DNS 阻擋、403 防盜鏈)，自動切換至 OCI 代理中繼
      img.addEventListener(
        "error",
        function onImgError() {
          const curSrc = this.getAttribute("src") || this.src || "";
          if (!this.dataset.proxied && curSrc && curSrc.startsWith("http") && !curSrc.includes("/api/assets/proxy")) {
            this.dataset.proxied = "true";
            this.src = `/api/assets/proxy?url=${encodeURIComponent(curSrc)}`;
          }
        },
        { once: true }
      );
    });
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
}
