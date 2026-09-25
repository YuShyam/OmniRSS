/**
 * OmniRSS 彈窗對話框與設定中心元件 (Modals & Dialog Controller).
 *
 * Manages modal lifecycles for Add Feed, Add Folder, Rule Manager,
 * Plugin Observability Dashboard, Tabbed Settings, and Authentication.
 */

import { store } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";
import { getEffectiveShortcuts, recordNextKey, DEFAULT_SHORTCUTS } from "../keybindings.js";

export function safeInputVal(v) {
  if (v === null || v === undefined || v === "null" || v === "undefined") return "";
  return String(v).trim();
}

export class ModalController {
  constructor() {
    this.init();
  }

  init() {
    // Global Close Button & Backdrop Click
    document.addEventListener("click", (e) => {
      if (e.target.classList.contains("modal-overlay")) {
        e.target.classList.remove("open");
      }
      const closeBtn = e.target.closest(
        ".modal-close-btn, .btn-modal-cancel, .modal-cancel-btn, .modal-close-btn-action, [data-action='close-modal'], [data-dismiss='modal']"
      );
      if (closeBtn) {
        const modal = closeBtn.closest(".modal-overlay");
        if (modal) modal.classList.remove("open");
      }
    });

    window.addEventListener("omnirss:open-modal", (e) => {
      if (e.detail && e.detail.modalId) {
        this.openModal(e.detail.modalId);
      }
    });

    window.addEventListener("omnirss:open-tag-settings", () => {
      this.openSettings("tab-tags");
    });

    window.addEventListener("omnirss:open-tag-modal", (e) => {
      if (e.detail && e.detail.articleId) {
        this.openArticleTagsModal(e.detail.articleId);
      }
    });

    window.addEventListener("omnirss:open-feed-properties", (e) => {
      const feedId = e.detail && (e.detail.id ?? e.detail.feedId);
      if (feedId) {
        this.openFeedPropertiesModal(feedId);
      }
    });

    window.addEventListener("omnirss:open-category-settings", (e) => {
      const detail = e.detail || {};
      const catId = detail.id ?? detail.categoryId;
      const categories = store.get("categories") || [];
      const cat = categories.find((c) => String(c.id) === String(catId)) || { id: catId, name: detail.name || t("tree.category_props") };
      this.openCategorySettings(cat);
    });

    this.bindAddFeed();
    this.bindAddCategory();
    this.bindCategorySettings();
    this.bindFeedProperties();
    this.bindRules();
    this.bindPlugins();
    this.bindSettings();
    this.bindAuth();
    this.bindArticleTags();
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

  openModal(modalId) {
    const el = document.getElementById(modalId);
    if (el) {
      el.classList.add("open");
      // 自動洗淨彈窗內所有文字輸入框與 placeholder，杜絕 "null" / "undefined"
      el.querySelectorAll("input, textarea").forEach((inp) => {
        if (inp.value === "null" || inp.value === "undefined") {
          inp.value = "";
        }
        if (inp.getAttribute("placeholder") === "null" || inp.getAttribute("placeholder") === "undefined") {
          inp.removeAttribute("placeholder");
        }
      });
    }
  }

  closeModal(modalId) {
    const el = document.getElementById(modalId);
    if (el) el.classList.remove("open");
  }

  // 1. Add Feed
  bindAddFeed() {
    const btnOpen = document.getElementById("btn-add-feed");
    if (btnOpen) {
      btnOpen.addEventListener("click", () => {
        const catSelect = document.getElementById("select-feed-category");
        if (catSelect) {
          const categories = store.get("categories") || [];
          catSelect.innerHTML = `<option value="">${t("tree.uncategorized")}</option>` +
            categories.map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
        }
        this.openModal("modal-add-feed");
      });
    }

    const form = document.getElementById("form-add-feed");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const url = safeInputVal(document.getElementById("input-feed-url")?.value);
      const catId = document.getElementById("select-feed-category")?.value || null;
      const customTitle = safeInputVal(document.getElementById("input-feed-title")?.value) || null;
      const requiresFlareSolverr = Boolean(document.getElementById("checkbox-feed-flaresolverr")?.checked);
      const autoFullText = Boolean(document.getElementById("checkbox-feed-auto-full-text")?.checked);

      if (!url) return;

      try {
        await api.addFeed(url, catId ? parseInt(catId, 10) : null, customTitle, requiresFlareSolverr, autoFullText);
        form.reset();
        this.closeModal("modal-add-feed");
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("modals.feed_created_success"), type: "success" } }));
        window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
      } catch (err) {
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("modals.feed_create_failed", { error: err.message }), type: "error" } }));
      }
    });
  }

  // 2. Add Category
  bindAddCategory() {
    const btnOpen = document.getElementById("btn-add-category");
    if (btnOpen) {
      btnOpen.addEventListener("click", () => this.openModal("modal-add-category"));
    }

    const form = document.getElementById("form-add-category");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const name = safeInputVal(document.getElementById("input-category-name")?.value);
      if (!name) return;

      try {
        await api.createCategory(name);
        form.reset();
        this.closeModal("modal-add-category");
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("modals.cat_created_success"), type: "success" } }));
        window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
      } catch (err) {
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("modals.cat_create_failed", { error: err.message }), type: "error" } }));
      }
    });
  }

  // 2.5 Advanced Tabbed Category Settings Center
  async openCategorySettings(categoryData) {
    if (!categoryData) return;
    const { id, name } = categoryData;
    const idInput = document.getElementById("input-cat-settings-id");
    const nameInput = document.getElementById("input-cat-settings-name");
    const retentionSelect = document.getElementById("select-cat-retention");
    const titleDisplay = document.getElementById("category-settings-title-display");
    if (idInput) idInput.value = id;
    if (nameInput) nameInput.value = safeInputVal(name);
    if (titleDisplay) titleDisplay.textContent = t("cat_props.title_display", { name });

    // 重置分頁至第 1 個 Tab
    const tabBtns = document.querySelectorAll("#category-settings-tabs .modal-tab-btn");
    const tabContents = document.querySelectorAll("#modal-category-settings .modal-tab-content");
    tabBtns.forEach((b, i) => b.classList.toggle("active", i === 0));
    tabContents.forEach((c, i) => c.classList.toggle("active", i === 0));

    // 清空重置輸入欄位，避免殘留上一個分類的值或顯示 null
    const sortSelect = document.getElementById("select-cat-sort");
    const hideReadCb = document.getElementById("checkbox-cat-hide-read");
    const inclKw = document.getElementById("input-cat-filter-keywords");
    const exclKw = document.getElementById("input-cat-exclude-keywords");
    const selectMinDate = document.getElementById("select-cat-min-date");
    const customMinDateInput = document.getElementById("input-cat-custom-min-date");
    const forceMinDateCb = document.getElementById("checkbox-cat-force-min-date");

    if (sortSelect) sortSelect.value = "published_desc";
    if (hideReadCb) hideReadCb.checked = false;
    if (inclKw) inclKw.value = "";
    if (exclKw) exclKw.value = "";
    if (selectMinDate) selectMinDate.value = "default";
    if (customMinDateInput) {
      customMinDateInput.value = "";
      customMinDateInput.style.display = "none";
    }
    if (forceMinDateCb) forceMinDateCb.checked = false;

    // 載入該分類即時狀態儀表板數據
    try {
      const stats = await api.getCategoryStats(id);
      if (stats) {
        const feedsEl = document.getElementById("stat-cat-feeds");
        const artsEl = document.getElementById("stat-cat-articles");
        const unreadEl = document.getElementById("stat-cat-unread");
        const statusEl = document.getElementById("stat-cat-status");
        const lastArtEl = document.getElementById("input-cat-last-article");
        const lastCheckEl = document.getElementById("input-cat-last-check");
        const pauseCheckbox = document.getElementById("checkbox-cat-pause-updates");

        if (feedsEl) feedsEl.textContent = String(stats.feed_count ?? 0);
        if (artsEl) artsEl.textContent = String(stats.article_count ?? 0);
        if (unreadEl) unreadEl.textContent = String(stats.unread_count ?? 0);
        if (lastArtEl) lastArtEl.value = stats.last_article_at && stats.last_article_at !== "null" ? stats.last_article_at : t("cat_props.no_articles");
        if (lastCheckEl) lastCheckEl.value = stats.last_checked_at && stats.last_checked_at !== "null" ? stats.last_checked_at : t("cat_props.checking_soon");

        if (pauseCheckbox) {
          pauseCheckbox.checked = Boolean(stats.is_paused);
        }
        if (statusEl) {
          if (stats.is_paused) {
            statusEl.textContent = t("cat_props.status_paused");
            statusEl.style.color = "#ef4444";
          } else {
            statusEl.textContent = t("cat_props.status_normal");
            statusEl.style.color = "#10b981";
          }
        }
      }
    } catch (e) {
      console.warn("無法取得分類統計:", e);
    }

    // 載入該分類保留天數與抓取頻率及收錄起始時間
    const categories = store.get("categories") || [];
    const currentCat = categories.find((c) => c.id === id);
    const intervalSelect = document.getElementById("select-cat-interval");
    if (retentionSelect && currentCat) {
      retentionSelect.value = currentCat.custom_retention_days !== null && currentCat.custom_retention_days !== undefined
        ? String(currentCat.custom_retention_days)
        : "";
    }
    if (intervalSelect && currentCat) {
      intervalSelect.value = currentCat.custom_interval_minutes !== null && currentCat.custom_interval_minutes !== undefined
        ? String(currentCat.custom_interval_minutes)
        : "";
    }
    if (currentCat) {
      if (forceMinDateCb) forceMinDateCb.checked = Boolean(currentCat.force_min_date);
      if (selectMinDate) {
        if (!currentCat.custom_min_date || currentCat.custom_min_date === "null") {
          selectMinDate.value = "default";
          if (customMinDateInput) customMinDateInput.style.display = "none";
        } else if (currentCat.custom_min_date.startsWith("1970-01-01")) {
          selectMinDate.value = "all";
          if (customMinDateInput) customMinDateInput.style.display = "none";
        } else {
          selectMinDate.value = "custom";
          if (customMinDateInput) {
            customMinDateInput.value = currentCat.custom_min_date.slice(0, 10);
            customMinDateInput.style.display = "block";
          }
        }
      }
    }

    // 載入本地偏好設定 (Sort, Hide Read, Keywords) - 徹底防止 "null" 出現
    try {
      const rawPrefs = localStorage.getItem(`omnirss:cat-prefs:${id}`);
      if (rawPrefs) {
        const prefs = JSON.parse(rawPrefs);
        if (sortSelect && prefs.sort) sortSelect.value = prefs.sort;
        if (hideReadCb && prefs.hide_read !== undefined) hideReadCb.checked = Boolean(prefs.hide_read);
        if (inclKw) inclKw.value = safeInputVal(prefs.include_keywords);
        if (exclKw) exclKw.value = safeInputVal(prefs.exclude_keywords);
      }
    } catch (_) {}

    this.openModal("modal-category-settings");
  }

  bindCategorySettings() {
    // 綁定分類設定內部 Tabs 切換
    const tabNav = document.getElementById("category-settings-tabs");
    if (tabNav) {
      tabNav.addEventListener("click", (e) => {
        const btn = e.target.closest(".modal-tab-btn");
        if (!btn) return;
        const targetTab = btn.dataset.tab;
        if (!targetTab) return;

        tabNav.querySelectorAll(".modal-tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
        const modal = document.getElementById("modal-category-settings");
        if (modal) {
          modal.querySelectorAll(".modal-tab-content").forEach((content) => {
            content.classList.toggle("active", content.id === targetTab);
          });
        }
      });
    }

    // 綁定分類收錄時間下拉選單切換
    const selectMinDate = document.getElementById("select-cat-min-date");
    const customMinDateInput = document.getElementById("input-cat-custom-min-date");
    if (selectMinDate && customMinDateInput) {
      selectMinDate.addEventListener("change", () => {
        if (selectMinDate.value === "custom") {
          customMinDateInput.style.display = "block";
          customMinDateInput.focus();
        } else {
          customMinDateInput.style.display = "none";
        }
      });
    }

    const form = document.getElementById("form-category-settings");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const id = parseInt(document.getElementById("input-cat-settings-id").value, 10);
      const name = safeInputVal(document.getElementById("input-cat-settings-name")?.value);
      const retentionVal = document.getElementById("select-cat-retention").value;
      const customRetentionDays = retentionVal === "" ? null : parseInt(retentionVal, 10);
      const intervalVal = document.getElementById("select-cat-interval")?.value;
      const customIntervalMinutes = intervalVal === "" || !intervalVal ? null : parseInt(intervalVal, 10);
      const isPaused = Boolean(document.getElementById("checkbox-cat-pause-updates")?.checked);

      // Min Date Handling
      let customMinDate = null;
      const minDateVal = selectMinDate ? selectMinDate.value : "default";
      if (minDateVal === "all") {
        customMinDate = "1970-01-01 00:00:00";
      } else if (minDateVal === "today") {
        const now = new Date();
        customMinDate = now.toISOString().slice(0, 10) + " 00:00:00";
      } else if (minDateVal === "7days") {
        const d = new Date(Date.now() - 7 * 86400000);
        customMinDate = d.toISOString().slice(0, 10) + " 00:00:00";
      } else if (minDateVal === "30days") {
        const d = new Date(Date.now() - 30 * 86400000);
        customMinDate = d.toISOString().slice(0, 10) + " 00:00:00";
      } else if (minDateVal === "custom") {
        if (customMinDateInput?.value) {
          customMinDate = customMinDateInput.value + " 00:00:00";
        }
      }
      const forceMinDate = Boolean(document.getElementById("checkbox-cat-force-min-date")?.checked);

      if (!id || !name) return;

      // 儲存視圖與過濾偏好至 localStorage
      try {
        const prefs = {
          sort: document.getElementById("select-cat-sort")?.value || "published_desc",
          hide_read: Boolean(document.getElementById("checkbox-cat-hide-read")?.checked),
          include_keywords: safeInputVal(document.getElementById("input-cat-filter-keywords")?.value),
          exclude_keywords: safeInputVal(document.getElementById("input-cat-exclude-keywords")?.value),
        };
        localStorage.setItem(`omnirss:cat-prefs:${id}`, JSON.stringify(prefs));
      } catch (_) {}

      try {
        await api.updateCategory(id, {
          name,
          custom_retention_days: customRetentionDays,
          custom_interval_minutes: customIntervalMinutes,
          custom_min_date: customMinDate,
          force_min_date: forceMinDate,
          is_paused: isPaused,
        });
        this.closeModal("modal-category-settings");
        window.dispatchEvent(new CustomEvent("omnirss:toast", {
          detail: {
            message: isPaused ? t("cat_props.saved_paused", { name }) : t("cat_props.saved_updated", { name }),
            type: "success"
          }
        }));
        window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
      } catch (err) {
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("cat_props.update_failed", { error: err.message }), type: "error" } }));
      }
    });

    const deleteBtn = document.getElementById("btn-delete-current-category");
    if (deleteBtn) {
      deleteBtn.addEventListener("click", async () => {
        const id = parseInt(document.getElementById("input-cat-settings-id").value, 10);
        const name = document.getElementById("input-cat-settings-name").value.trim();
        if (!id) return;

        if (window.confirm(t("cat_props.confirm_delete", { name }))) {
          try {
            await api.deleteCategory(id);
            this.closeModal("modal-category-settings");
            window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("cat_props.delete_success"), type: "success" } }));
            window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
          } catch (err) {
            window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("cat_props.delete_failed", { error: err.message }), type: "error" } }));
          }
        }
      });
    }
  }

  // 2.8 Feed Properties Modal & Health Diagnostic (Tabbed Layout)
  async openFeedPropertiesModal(feedId) {
    if (!feedId) return;

    const idInput = document.getElementById("feed-prop-id");
    const customTitleInput = document.getElementById("feed-prop-custom-title");
    const catSelect = document.getElementById("feed-prop-category-select");
    const feedUrlInput = document.getElementById("feed-prop-feed-url");
    const openFeedBtn = document.getElementById("btn-feed-prop-open-feed");
    const siteUrlInput = document.getElementById("feed-prop-site-url");
    const openSiteBtn = document.getElementById("btn-feed-prop-open-site");
    const selectInterval = document.getElementById("select-feed-prop-interval");
    const customIntervalInput = document.getElementById("input-feed-prop-custom-interval");
    const selectRetention = document.getElementById("select-feed-prop-retention");
    const customRetentionInput = document.getElementById("input-feed-prop-custom-retention");
    const selectMinDate = document.getElementById("select-feed-prop-min-date");
    const customMinDateInput = document.getElementById("input-feed-prop-custom-min-date");
    const flareCheckbox = document.getElementById("feed-prop-flaresolverr");
    const autoFullTextCheckbox = document.getElementById("feed-prop-auto-full-text");
    const pausedCheckbox = document.getElementById("feed-prop-paused");
    const authUserInput = document.getElementById("feed-prop-auth-user");
    const authPassInput = document.getElementById("feed-prop-auth-pass");
    const lastCheckedEl = document.getElementById("feed-prop-last-checked");
    const totalArtEl = document.getElementById("feed-prop-total-articles");
    const unreadArtEl = document.getElementById("feed-prop-unread-articles");
    const statusBadgeEl = document.getElementById("feed-prop-status-badge");
    const testFeedbackBox = document.getElementById("feed-prop-test-feedback");
    const generalFeedbackBox = document.getElementById("feed-prop-general-test-feedback");
    const errorDetailsBox = document.getElementById("feed-prop-error-details");
    const errorMsgEl = document.getElementById("feed-prop-error-msg");

    if (idInput) idInput.value = feedId;

    // Reset tabs to Tab 1 (基本資訊)
    const tabBtns = document.querySelectorAll("#feed-properties-tabs .modal-tab-btn");
    const tabContents = document.querySelectorAll("#modal-feed-properties .modal-tab-content");
    tabBtns.forEach((b, i) => b.classList.toggle("active", i === 0));
    tabContents.forEach((c, i) => c.classList.toggle("active", i === 0));

    // Reset feedback
    if (testFeedbackBox) testFeedbackBox.style.display = "none";
    if (generalFeedbackBox) generalFeedbackBox.style.display = "none";
    if (errorDetailsBox) errorDetailsBox.style.display = "none";

    if (catSelect) {
      const categories = store.get("categories") || [];
      catSelect.innerHTML = `<option value="">(${t("tree.uncategorized")})</option>` +
        categories.map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
    }

    try {
      const feed = await api.getFeed(feedId);
      if (feed) {
        const titleDisplay = document.getElementById("feed-properties-title-display");
        if (titleDisplay) {
          titleDisplay.textContent = t("feed_props.title_display", { name: feed.custom_title || feed.title || t("feed_props.untitled_feed") });
        }

        if (customTitleInput) customTitleInput.value = safeInputVal(feed.custom_title);
        if (catSelect) catSelect.value = feed.category_id !== null && feed.category_id !== undefined ? String(feed.category_id) : "";
        if (feedUrlInput) feedUrlInput.value = safeInputVal(feed.feed_url);
        if (siteUrlInput) siteUrlInput.value = safeInputVal(feed.site_url);

        // Link buttons
        if (openFeedBtn) {
          if (feed.feed_url) {
            openFeedBtn.href = feed.feed_url;
            openFeedBtn.style.opacity = "1";
            openFeedBtn.style.pointerEvents = "auto";
          } else {
            openFeedBtn.href = "#";
            openFeedBtn.style.opacity = "0.5";
            openFeedBtn.style.pointerEvents = "none";
          }
        }

        if (openSiteBtn) {
          if (feed.site_url) {
            openSiteBtn.href = feed.site_url;
            openSiteBtn.style.opacity = "1";
            openSiteBtn.style.pointerEvents = "auto";
          } else {
            openSiteBtn.href = "#";
            openSiteBtn.style.opacity = "0.5";
            openSiteBtn.style.pointerEvents = "none";
          }
        }

        // Interval Preset / Custom
        if (selectInterval) {
          const standardIntervals = ["5", "15", "30", "60", "120", "360", "720", "1440"];
          if (feed.check_interval_minutes === null || feed.check_interval_minutes === undefined) {
            selectInterval.value = "default";
            if (customIntervalInput) customIntervalInput.style.display = "none";
          } else if (standardIntervals.includes(String(feed.check_interval_minutes))) {
            selectInterval.value = String(feed.check_interval_minutes);
            if (customIntervalInput) customIntervalInput.style.display = "none";
          } else {
            selectInterval.value = "custom";
            if (customIntervalInput) {
              customIntervalInput.value = safeInputVal(feed.check_interval_minutes);
              customIntervalInput.style.display = "block";
            }
          }
        }

        // Retention Preset / Custom
        if (selectRetention) {
          const standardRetentions = ["0", "7", "14", "30", "60", "90", "180", "365"];
          if (feed.custom_retention_days === null || feed.custom_retention_days === undefined) {
            selectRetention.value = "default";
            if (customRetentionInput) customRetentionInput.style.display = "none";
          } else if (standardRetentions.includes(String(feed.custom_retention_days))) {
            selectRetention.value = String(feed.custom_retention_days);
            if (customRetentionInput) customRetentionInput.style.display = "none";
          } else {
            selectRetention.value = "custom";
            if (customRetentionInput) {
              customRetentionInput.value = safeInputVal(feed.custom_retention_days);
              customRetentionInput.style.display = "block";
            }
          }
        }

        // Min Date (Accept Articles After) & Force Min Date
        const forceMinDateCb = document.getElementById("checkbox-feed-prop-force-min-date");
        if (forceMinDateCb) {
          forceMinDateCb.checked = Boolean(feed.force_min_date);
        }

        if (selectMinDate) {
          if (!feed.min_publish_date || feed.min_publish_date === "null") {
            selectMinDate.value = "default";
            if (customMinDateInput) customMinDateInput.style.display = "none";
          } else if (feed.min_publish_date.startsWith("1970-01-01")) {
            selectMinDate.value = "all";
            if (customMinDateInput) customMinDateInput.style.display = "none";
          } else {
            selectMinDate.value = "custom";
            if (customMinDateInput) {
              customMinDateInput.value = feed.min_publish_date.slice(0, 10);
              customMinDateInput.style.display = "block";
            }
          }
        }

        if (flareCheckbox) flareCheckbox.checked = Boolean(feed.requires_flaresolverr);
        if (autoFullTextCheckbox) autoFullTextCheckbox.checked = Boolean(feed.auto_full_text);
        if (pausedCheckbox) pausedCheckbox.checked = Boolean(feed.is_paused);
        if (authUserInput) authUserInput.value = safeInputVal(feed.auth_username);
        if (authPassInput) authPassInput.value = safeInputVal(feed.auth_password);

        if (lastCheckedEl) lastCheckedEl.textContent = feed.last_checked_at && feed.last_checked_at !== "null" ? feed.last_checked_at : t("feed_props.checking_soon");
        if (totalArtEl) totalArtEl.textContent = String(feed.total_articles ?? feed.article_count ?? 0);
        if (unreadArtEl) unreadArtEl.textContent = String(feed.unread_articles ?? feed.unread_count ?? 0);

        if (statusBadgeEl) {
          statusBadgeEl.className = "badge-status-pill";
          if (feed.error_count > 0 || feed.last_error_message) {
            statusBadgeEl.classList.add("error");
            statusBadgeEl.textContent = t("feed_props.status_error", { count: feed.error_count || 1 });
          } else if (feed.is_paused) {
            statusBadgeEl.classList.add("paused");
            statusBadgeEl.textContent = t("feed_props.status_paused");
          } else {
            statusBadgeEl.textContent = t("feed_props.status_normal");
          }
        }

        if (errorDetailsBox && errorMsgEl) {
          if (feed.last_error_message) {
            errorDetailsBox.style.display = "block";
            errorMsgEl.textContent = feed.last_error_message;
          } else {
            errorDetailsBox.style.display = "none";
          }
        }
      }
    } catch (err) {
      console.warn("無法取得訂閱源屬性:", err);
    }

    this.openModal("modal-feed-properties");
  }

  bindFeedProperties() {
    // Tab 切換事件綁定
    const tabsNav = document.getElementById("feed-properties-tabs");
    if (tabsNav) {
      tabsNav.addEventListener("click", (e) => {
        const btn = e.target.closest(".modal-tab-btn");
        if (!btn) return;
        const targetTab = btn.dataset.tab;
        if (!targetTab) return;
        tabsNav.querySelectorAll(".modal-tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
        document.querySelectorAll("#modal-feed-properties .modal-tab-content").forEach((c) => {
          c.classList.toggle("active", c.id === targetTab);
        });
      });
    }

    const feedUrlInput = document.getElementById("feed-prop-feed-url");
    const openFeedBtn = document.getElementById("btn-feed-prop-open-feed");
    if (feedUrlInput && openFeedBtn) {
      feedUrlInput.addEventListener("input", (e) => {
        const val = safeInputVal(e.target.value);
        if (val) {
          openFeedBtn.href = val;
          openFeedBtn.style.opacity = "1";
          openFeedBtn.style.pointerEvents = "auto";
        } else {
          openFeedBtn.href = "#";
          openFeedBtn.style.opacity = "0.5";
          openFeedBtn.style.pointerEvents = "none";
        }
      });
    }

    const siteUrlInput = document.getElementById("feed-prop-site-url");
    const openSiteBtn = document.getElementById("btn-feed-prop-open-site");
    if (siteUrlInput && openSiteBtn) {
      siteUrlInput.addEventListener("input", (e) => {
        const val = safeInputVal(e.target.value);
        if (val) {
          openSiteBtn.href = val;
          openSiteBtn.style.opacity = "1";
          openSiteBtn.style.pointerEvents = "auto";
        } else {
          openSiteBtn.href = "#";
          openSiteBtn.style.opacity = "0.5";
          openSiteBtn.style.pointerEvents = "none";
        }
      });
    }

    // Interval Select Toggle
    const selectInterval = document.getElementById("select-feed-prop-interval");
    const customIntervalInput = document.getElementById("input-feed-prop-custom-interval");
    if (selectInterval && customIntervalInput) {
      selectInterval.addEventListener("change", () => {
        if (selectInterval.value === "custom") {
          customIntervalInput.style.display = "block";
          customIntervalInput.focus();
        } else {
          customIntervalInput.style.display = "none";
        }
      });
    }

    // Retention Select Toggle
    const selectRetention = document.getElementById("select-feed-prop-retention");
    const customRetentionInput = document.getElementById("input-feed-prop-custom-retention");
    if (selectRetention && customRetentionInput) {
      selectRetention.addEventListener("change", () => {
        if (selectRetention.value === "custom") {
          customRetentionInput.style.display = "block";
          customRetentionInput.focus();
        } else {
          customRetentionInput.style.display = "none";
        }
      });
    }

    // Min Date Select Toggle
    const selectMinDate = document.getElementById("select-feed-prop-min-date");
    const customMinDateInput = document.getElementById("input-feed-prop-custom-min-date");
    if (selectMinDate && customMinDateInput) {
      selectMinDate.addEventListener("change", () => {
        if (selectMinDate.value === "custom") {
          customMinDateInput.style.display = "block";
          customMinDateInput.focus();
        } else {
          customMinDateInput.style.display = "none";
        }
      });
    }

    // Test Connection Button (即時回饋至基本資訊卡片與診斷頁)
    const btnTestUrl = document.getElementById("btn-feed-prop-test-url");
    if (btnTestUrl) {
      btnTestUrl.addEventListener("click", async () => {
        const url = safeInputVal(document.getElementById("feed-prop-feed-url")?.value);
        if (!url) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("feed_props.enter_url_warn"), type: "warning" }
          }));
          return;
        }

        const authUser = safeInputVal(document.getElementById("feed-prop-auth-user")?.value) || null;
        const authPass = safeInputVal(document.getElementById("feed-prop-auth-pass")?.value) || null;
        const flare = Boolean(document.getElementById("feed-prop-flaresolverr")?.checked);

        const spinner = btnTestUrl.querySelector(".btn-spinner");
        const btnText = btnTestUrl.querySelector(".btn-text");
        const generalFeedback = document.getElementById("feed-prop-general-test-feedback");
        const diagFeedback = document.getElementById("feed-prop-test-feedback");
        const diagMsgEl = document.getElementById("feed-prop-test-msg");

        if (spinner) spinner.style.display = "inline-block";
        if (btnText) btnText.textContent = t("feed_props.connecting_btn");
        btnTestUrl.disabled = true;

        try {
          const res = await api.testFeedUrl(url, authUser, authPass, flare);
          const isOk = res && res.status === "ok";
          const msgHtml = isOk
            ? t("feed_props.test_success_html", { count: res.item_count, title: res.title ? t("feed_props.test_channel_title", { title: this.escape(res.title) }) : "" })
            : t("feed_props.test_fail_html", { status: res.http_status || "ERR", error: this.escape(res.error_detail || t("feed_props.cannot_parse")) });
          const bgStyle = isOk ? "rgba(34, 197, 94, 0.12)" : "rgba(239, 68, 68, 0.12)";
          const borderStyle = isOk ? "1px solid rgba(34, 197, 94, 0.3)" : "1px solid rgba(239, 68, 68, 0.3)";
          const colorStyle = isOk ? "#22c55e" : "#ef4444";

          if (generalFeedback) {
            generalFeedback.style.display = "block";
            generalFeedback.style.background = bgStyle;
            generalFeedback.style.border = borderStyle;
            generalFeedback.style.color = colorStyle;
            generalFeedback.innerHTML = msgHtml;
          }

          if (diagFeedback && diagMsgEl) {
            diagFeedback.style.display = "block";
            diagFeedback.style.background = bgStyle;
            diagFeedback.style.border = borderStyle;
            diagFeedback.style.color = colorStyle;
            diagMsgEl.innerHTML = msgHtml;
          }

          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: {
              message: isOk ? t("feed_props.test_success_short", { count: res.item_count }) : t("feed_props.test_fail_short", { detail: res.error_detail || t("feed_props.cannot_parse") }),
              type: isOk ? "success" : "warning",
            }
          }));
        } catch (err) {
          const errHtml = t("feed_props.test_error_html", { error: this.escape(err.message) });
          if (generalFeedback) {
            generalFeedback.style.display = "block";
            generalFeedback.style.background = "rgba(239, 68, 68, 0.12)";
            generalFeedback.style.border = "1px solid rgba(239, 68, 68, 0.3)";
            generalFeedback.style.color = "#ef4444";
            generalFeedback.innerHTML = errHtml;
          }
          if (diagFeedback && diagMsgEl) {
            diagFeedback.style.display = "block";
            diagFeedback.style.background = "rgba(239, 68, 68, 0.12)";
            diagFeedback.style.border = "1px solid rgba(239, 68, 68, 0.3)";
            diagFeedback.style.color = "#ef4444";
            diagMsgEl.innerHTML = errHtml;
          }
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("feed_props.conn_err_toast", { error: err.message }), type: "danger" }
          }));
        } finally {
          if (spinner) spinner.style.display = "none";
          if (btnText) btnText.textContent = t("feed_props.test_btn_normal");
          btnTestUrl.disabled = false;
        }
      });
    }

    // Form Submit
    const form = document.getElementById("form-feed-properties");
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const id = parseInt(document.getElementById("feed-prop-id").value, 10);
        if (!id) return;

        const customTitle = safeInputVal(document.getElementById("feed-prop-custom-title")?.value) || null;
        const catVal = document.getElementById("feed-prop-category-select").value;
        const categoryId = catVal ? parseInt(catVal, 10) : null;
        const feedUrl = safeInputVal(document.getElementById("feed-prop-feed-url")?.value);
        const siteUrl = safeInputVal(document.getElementById("feed-prop-site-url")?.value) || null;

        // Interval
        let checkInterval = null;
        const intVal = selectInterval ? selectInterval.value : "default";
        if (intVal === "custom") {
          const parsed = parseInt(customIntervalInput?.value, 10);
          checkInterval = !isNaN(parsed) && parsed >= 5 ? parsed : 30;
        } else if (intVal !== "default") {
          checkInterval = parseInt(intVal, 10);
        }

        // Retention
        let customRetention = null;
        const retVal = selectRetention ? selectRetention.value : "default";
        if (retVal === "custom") {
          const parsed = parseInt(customRetentionInput?.value, 10);
          customRetention = !isNaN(parsed) && parsed >= 0 ? parsed : null;
        } else if (retVal !== "default") {
          customRetention = parseInt(retVal, 10);
        }

        // Min Date
        let minPublishDate = null;
        const minDateVal = selectMinDate ? selectMinDate.value : "default";
        if (minDateVal === "all") {
          minPublishDate = "1970-01-01 00:00:00";
        } else if (minDateVal === "today") {
          const now = new Date();
          minPublishDate = now.toISOString().slice(0, 10) + " 00:00:00";
        } else if (minDateVal === "7days") {
          const d = new Date(Date.now() - 7 * 86400000);
          minPublishDate = d.toISOString().slice(0, 10) + " 00:00:00";
        } else if (minDateVal === "30days") {
          const d = new Date(Date.now() - 30 * 86400000);
          minPublishDate = d.toISOString().slice(0, 10) + " 00:00:00";
        } else if (minDateVal === "custom") {
          if (customMinDateInput?.value) {
            minPublishDate = customMinDateInput.value + " 00:00:00";
          }
        }
        const forceMinDate = Boolean(document.getElementById("checkbox-feed-prop-force-min-date")?.checked);

        const flaresolverr = Boolean(document.getElementById("feed-prop-flaresolverr")?.checked);
        const autoFullText = Boolean(document.getElementById("feed-prop-auto-full-text")?.checked);
        const isPaused = Boolean(document.getElementById("feed-prop-paused")?.checked);
        const authUsername = safeInputVal(document.getElementById("feed-prop-auth-user")?.value) || null;
        const authPassword = safeInputVal(document.getElementById("feed-prop-auth-pass")?.value) || null;

        try {
          await api.updateFeed(id, {
            custom_title: customTitle,
            category_id: categoryId,
            feed_url: feedUrl,
            site_url: siteUrl,
            check_interval_minutes: checkInterval,
            custom_retention_days: customRetention,
            min_publish_date: minPublishDate,
            force_min_date: forceMinDate,
            requires_flaresolverr: flaresolverr,
            auto_full_text: autoFullText,
            is_paused: isPaused,
            auth_username: authUsername,
            auth_password: authPassword,
          });

          this.closeModal("modal-feed-properties");
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("feed_props.saved_success"), type: "success" }
          }));
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("feed_props.save_failed", { error: err.message }), type: "error" } }));
        }
      });
    }

    // Delete Feed
    const deleteBtn = document.getElementById("btn-feed-prop-delete");
    if (deleteBtn) {
      deleteBtn.addEventListener("click", async () => {
        const id = parseInt(document.getElementById("feed-prop-id").value, 10);
        const title = document.getElementById("feed-prop-custom-title").value.trim() || t("feed_props.this_feed");
        if (!id) return;

        if (window.confirm(t("feed_props.confirm_delete", { name: title }))) {
          try {
            await api.deleteFeed(id);
            this.closeModal("modal-feed-properties");
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: t("feed_props.delete_success"), type: "success" }
            }));
            window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
          } catch (err) {
            window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("feed_props.delete_failed", { error: err.message }), type: "error" } }));
          }
        }
      });
    }
  }


  // 3. Rules Manager (Multi-condition & Advanced Actions)
  createRuleConditionRow(field = "title", operator = "contains", value = "") {
    const row = document.createElement("div");
    row.className = "rule-condition-row";
    row.innerHTML = `
      <select class="form-select rule-cond-field" style="min-height: 36px; height: 36px; font-size: 12px; line-height: 1.4; padding: 6px 10px;">
        <option value="title" ${field === "title" ? "selected" : ""}>${t("rules.field_title")}</option>
        <option value="feed_title" ${field === "feed_title" ? "selected" : ""}>${t("rules.field_feed")}</option>
        <option value="content" ${field === "content" ? "selected" : ""}>${t("rules.field_content")}</option>
        <option value="author" ${field === "author" ? "selected" : ""}>${t("rules.field_author")}</option>
        <option value="url" ${field === "url" ? "selected" : ""}>${t("rules.field_url")}</option>
      </select>
      <select class="form-select rule-cond-op" style="min-height: 36px; height: 36px; font-size: 12px; line-height: 1.4; padding: 6px 10px;">
        <option value="contains" ${operator === "contains" ? "selected" : ""}>${t("rules.op_contains")}</option>
        <option value="not_contains" ${operator === "not_contains" ? "selected" : ""}>${t("rules.op_not_contains")}</option>
        <option value="equals" ${operator === "equals" ? "selected" : ""}>${t("rules.op_equals")}</option>
        <option value="regex" ${operator === "regex" ? "selected" : ""}>${t("rules.op_regex")}</option>
      </select>
      <input type="text" class="form-input rule-cond-val" placeholder="${t("rules.cond_input_placeholder")}" value="${this.escape(value)}" required style="min-height: 36px; height: 36px; font-size: 12px; line-height: 1.4; padding: 6px 10px;" />
      <button type="button" class="rule-row-delete-btn" title="${t("rules.cond_delete_title")}" style="min-height: 36px; height: 36px; width: 36px;">✕</button>
    `;

    const delBtn = row.querySelector(".rule-row-delete-btn");
    delBtn.addEventListener("click", () => {
      const container = document.getElementById("rule-conditions-rows");
      if (container && container.children.length > 1) {
        row.remove();
      } else {
        const valInput = row.querySelector(".rule-cond-val");
        if (valInput) valInput.value = "";
      }
    });

    return row;
  }

  initRuleConditionRows(conditions = []) {
    const container = document.getElementById("rule-conditions-rows");
    if (!container) return;
    container.innerHTML = "";
    if (conditions && conditions.length > 0) {
      conditions.forEach((c) => {
        container.appendChild(this.createRuleConditionRow(c.field || "title", c.operator || "contains", c.value || ""));
      });
    } else {
      container.appendChild(this.createRuleConditionRow("feed_title", "contains", ""));
      container.appendChild(this.createRuleConditionRow("title", "contains", ""));
    }
  }

  collectRuleConditions() {
    const container = document.getElementById("rule-conditions-rows");
    if (!container) return [];
    const rows = container.querySelectorAll(".rule-condition-row");
    const conditions = [];
    rows.forEach((row) => {
      const field = row.querySelector(".rule-cond-field")?.value || "title";
      const operator = row.querySelector(".rule-cond-op")?.value || "contains";
      const value = safeInputVal(row.querySelector(".rule-cond-val")?.value);
      if (value) {
        conditions.push({ field, operator, value });
      }
    });
    return conditions;
  }

  bindRules() {
    const btnOpen = document.getElementById("btn-open-rules");
    if (btnOpen) {
      btnOpen.addEventListener("click", async () => {
        const preview = document.getElementById("rule-test-preview-container");
        if (preview) {
          preview.style.display = "none";
          const previewList = document.getElementById("rule-test-preview-list");
          if (previewList) previewList.innerHTML = "";
        }
        this.initRuleConditionRows();
        await this.loadRulesList();
        this.openModal("modal-rules");
      });
    }

    // 增加一條條件按鈕
    const btnAddCondition = document.getElementById("btn-add-rule-condition");
    if (btnAddCondition) {
      btnAddCondition.addEventListener("click", () => {
        const container = document.getElementById("rule-conditions-rows");
        if (container) {
          container.appendChild(this.createRuleConditionRow("title", "contains", ""));
        }
      });
    }

    // 動作切換：當選取附加標籤時顯示標籤設定盒
    const selectAction = document.getElementById("select-rule-action");
    const tagParamBox = document.getElementById("rule-tag-param-box");
    const selectTag = document.getElementById("select-rule-tag-target");
    const customTagInput = document.getElementById("input-rule-custom-tag");

    const populateTags = () => {
      const tags = store.get("tags") || [];
      if (selectTag) {
        const defaultList = [
          { name: t("rules.tag_important", "重要"), color: "#ef4444" },
          { name: t("rules.tag_work", "工作"), color: "#f97316" },
          { name: t("rules.tag_personal", "個人"), color: "#22c55e" },
          { name: t("rules.tag_to_read", "待讀"), color: "#3b82f6" },
          { name: t("rules.tag_read_later", "稍後閱讀"), color: "#a855f7" },
        ];
        const merged = [...defaultList];
        tags.forEach((tagItem) => {
          if (!merged.some((x) => x.name === tagItem.name)) {
            merged.push(tagItem);
          }
        });
        selectTag.innerHTML = merged.map((tagItem) => `<option value="${this.escape(tagItem.name)}">${this.escape(tagItem.name)}</option>`).join("") +
          `<option value="__custom__">${t("rules.custom_tag_option")}</option>`;
      }
    };

    if (selectAction && tagParamBox) {
      selectAction.addEventListener("change", () => {
        if (selectAction.value === "add_tag") {
          tagParamBox.style.display = "block";
          populateTags();
        } else {
          tagParamBox.style.display = "none";
        }
      });
    }

    if (selectTag && customTagInput) {
      selectTag.addEventListener("change", () => {
        if (selectTag.value === "__custom__") {
          customTagInput.style.display = "block";
          customTagInput.focus();
        } else {
          customTagInput.style.display = "none";
        }
      });
    }

    // 立即套用所有規則至現有文章
    const btnApplyAll = document.getElementById("btn-apply-all-rules");
    if (btnApplyAll) {
      btnApplyAll.addEventListener("click", async () => {
        if (btnApplyAll.classList.contains("busy")) return;
        btnApplyAll.classList.add("busy");
        try {
          const res = await api.applyAllRules();
          const count = res.affected_articles_count || 0;
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("rules.exec_all_success", { count }), type: "success" }
          }));
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("rules.exec_all_failed", { error: err.message }), type: "error" } }));
        } finally {
          btnApplyAll.classList.remove("busy");
        }
      });
    }

    // 測試當前編輯的條件
    const btnTestCurrent = document.getElementById("btn-test-current-rule");
    if (btnTestCurrent) {
      btnTestCurrent.addEventListener("click", async () => {
        const conditions = this.collectRuleConditions();
        if (conditions.length === 0) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("rules.fill_keyword_warn"), type: "warning" }
          }));
          return;
        }
        const matchMode = document.getElementById("select-rule-match-mode")?.value || "all";
        await this.testAndPreviewRuleConditions(conditions, matchMode);
      });
    }

    // 關閉測試比對預覽
    const btnCloseTest = document.getElementById("btn-close-test-preview");
    if (btnCloseTest) {
      btnCloseTest.addEventListener("click", () => {
        const container = document.getElementById("rule-test-preview-container");
        if (container) container.style.display = "none";
      });
    }

    const form = document.getElementById("form-add-rule");
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const name = safeInputVal(document.getElementById("input-rule-name")?.value);
        const matchMode = document.getElementById("select-rule-match-mode")?.value || "all";
        const actionType = document.getElementById("select-rule-action")?.value || "mark_read";
        const conditions = this.collectRuleConditions();

        if (!name) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("rules.enter_name_warn"), type: "warning" } }));
          return;
        }

        if (conditions.length === 0) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("rules.enter_valid_cond_warn"), type: "warning" } }));
          return;
        }

        const actionParams = {};
        if (actionType === "add_tag") {
          let tagName = selectTag?.value || t("rules.default_tag_name", "重要");
          if (tagName === "__custom__") {
            tagName = safeInputVal(customTagInput?.value);
            if (!tagName) {
              window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("rules.enter_custom_tag_warn"), type: "warning" } }));
              if (customTagInput) customTagInput.focus();
              return;
            }
          }
          actionParams.tag = tagName;
        }

        const rulePayload = {
          name,
          sort_order: 10,
          is_enabled: true,
          conditions: {
            match_mode: matchMode,
            rules: conditions,
          },
          actions: [{ action_type: actionType, parameters: actionParams }],
        };

        try {
          await api.createRule(rulePayload);
          form.reset();
          if (tagParamBox) tagParamBox.style.display = "none";
          if (customTagInput) customTagInput.style.display = "none";
          const previewContainer = document.getElementById("rule-test-preview-container");
          if (previewContainer) {
            previewContainer.style.display = "none";
            const previewList = document.getElementById("rule-test-preview-list");
            if (previewList) previewList.innerHTML = "";
          }
          this.initRuleConditionRows();
          await this.loadRulesList();
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("rules.create_success", { name }), type: "success" }
          }));
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("rules.create_failed", { error: err.message }), type: "error" } }));
        }
      });
    }
  }

  async testAndPreviewRuleConditions(conditions, matchMode = "all") {
    const previewContainer = document.getElementById("rule-test-preview-container");
    const previewTitle = document.getElementById("rule-test-preview-title");
    const previewList = document.getElementById("rule-test-preview-list");
    if (!previewContainer || !previewList) return;

    previewContainer.style.display = "block";
    previewList.innerHTML = `<div class="text-muted" style="padding: 8px 0;">${t("rules.preview_matching")}</div>`;

    try {
      const payload = Array.isArray(conditions)
        ? { conditions, match_mode: matchMode }
        : conditions;

      const res = await api.testRule(payload);
      const matches = res.articles || res.matched_articles || [];
      const total = res.count !== undefined ? res.count : (res.matched_count !== undefined ? res.matched_count : matches.length);

      if (previewTitle) {
        previewTitle.innerHTML = t("rules.preview_result_title", { count: total });
      }

      if (matches.length === 0) {
        previewList.innerHTML = `<div class="text-muted" style="padding: 6px 0;">${t("rules.preview_empty")}</div>`;
        return;
      }

      previewList.innerHTML = matches.map((art) => `
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 8px; border-bottom: 1px solid var(--border-color-subtle); gap: 10px;">
          <div style="flex: 1; min-width: 0;">
            <div style="font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary);" title="${this.escape(art.title || '')}">
              ${this.escape(art.title || t("common.untitled"))}
            </div>
            <div style="font-size: 11px; color: var(--text-muted); display: flex; gap: 8px;">
              <span>📡 ${this.escape(art.feed_title || t("rules.unknown_source"))}</span>
              ${art.published_at ? `<span>⏱️ ${art.published_at.slice(0, 16)}</span>` : ""}
            </div>
          </div>
          <span class="badge-status-pill" style="font-size: 10px; flex-shrink: 0;">${t("rules.condition_matched")}</span>
        </div>
      `).join("");
    } catch (err) {
      previewList.innerHTML = `<div style="color: var(--accent-red, #ef4444); padding: 6px 0;">${t("rules.preview_failed", { error: this.escape(err.message) })}</div>`;
    }
  }

  async loadRulesList() {
    const listEl = document.getElementById("rules-list-container");
    if (!listEl) return;

    try {
      const rules = await api.getRules();
      if (!rules || rules.length === 0) {
        listEl.innerHTML = `<div class="text-muted" style="font-size: 12px; padding: 14px 0; text-align: center;">${t("rules.empty_rules_hint")}</div>`;
        return;
      }

      listEl.innerHTML = rules.map((r) => {
        let conds = [];
        let matchMode = "all";
        if (Array.isArray(r.conditions)) {
          conds = r.conditions;
        } else if (r.conditions && typeof r.conditions === "object") {
          matchMode = r.conditions.match_mode || "all";
          conds = r.conditions.rules || [];
        }

        const modeBadge = matchMode === "any"
          ? `<span style="background: rgba(234, 179, 8, 0.15); color: #eab308; border: 1px solid rgba(234, 179, 8, 0.3); border-radius: 3px; padding: 1px 4px; font-size: 10px; font-weight: 600;">${t("rules.or_badge")}</span>`
          : `<span style="background: rgba(59, 130, 246, 0.15); color: #3b82f6; border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 3px; padding: 1px 4px; font-size: 10px; font-weight: 600;">${t("rules.and_badge")}</span>`;

        const fieldMap = {
          title: t("rules.field_title"),
          feed_title: t("rules.field_feed_title"),
          content: t("rules.field_content"),
          author: t("rules.field_author"),
          url: t("rules.field_url")
        };
        const opMap = {
          contains: t("rules.op_contains"),
          not_contains: t("rules.op_not_contains"),
          equals: t("rules.op_equals"),
          regex: t("rules.op_regex")
        };

        const condDesc = conds.map((c) => {
          const f = fieldMap[c.field] || c.field;
          const op = opMap[c.operator] || c.operator;
          return `[${f} ${op} "${c.value}"]`;
        }).join(matchMode === "any" ? t("rules.join_or") : t("rules.join_and"));

        const firstAction = (r.actions && r.actions[0]) || { action_type: "mark_read", parameters: {} };
        const actionType = firstAction.action_type || "mark_read";
        const actionParams = firstAction.parameters || {};
        const actionMap = {
          mark_read: t("rules.action_mark_read"),
          star: t("rules.action_star"),
          trash: t("rules.action_trash"),
          add_tag: t("rules.action_add_tag", { tag: actionParams.tag || t("rules.default_tag_name") }),
          ai_summary: t("rules.action_ai_summary")
        };
        const actionText = actionMap[actionType] || actionType;

        const rawConditionsForTest = JSON.stringify(r.conditions || []);

        return `
        <div class="rule-card-item">
          <div style="flex: 1; min-width: 0;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
              <strong style="font-size: 13px; color: var(--text-primary);">${this.escape(r.name || t("rules.unnamed_rule"))}</strong>
              ${modeBadge}
              <span style="font-size: 11px; font-weight: 600; color: var(--accent-primary); background: var(--accent-primary-dim, rgba(59,130,246,0.1)); padding: 1px 6px; border-radius: 3px;">
                ${this.escape(actionText)}
              </span>
            </div>
            <div class="text-muted" style="font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${this.escape(condDesc)}">
              ${this.escape(condDesc) || t("rules.no_conditions")}
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 6px; flex-shrink: 0;">
            <button type="button" class="btn btn-sm btn-test-rule" data-rule='${this.escape(rawConditionsForTest)}' style="padding: 3px 8px; font-size: 11px;">${t("rules.test_rule_btn")}</button>
            <button type="button" class="btn btn-sm btn-apply-rule" data-id="${r.id}" style="padding: 3px 8px; font-size: 11px; background: var(--accent-primary-dim); color: var(--accent-primary); border: 1px solid var(--accent-primary);">${t("rules.apply_now_btn")}</button>
            <button type="button" class="btn btn-sm btn-danger btn-delete-rule" data-id="${r.id}" style="padding: 3px 8px; font-size: 11px;">${t("rules.delete_btn")}</button>
          </div>
        </div>
      `;
      }).join("");

      listEl.querySelectorAll(".btn-test-rule").forEach((btn) => {
        btn.addEventListener("click", async () => {
          try {
            const raw = btn.dataset.rule;
            let condObj = JSON.parse(raw);
            if (Array.isArray(condObj)) {
              await this.testAndPreviewRuleConditions(condObj, "all");
            } else if (condObj && typeof condObj === "object") {
              await this.testAndPreviewRuleConditions(condObj.rules || [], condObj.match_mode || "all");
            }
          } catch (e) {
            window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("rules.parse_cond_failed", { error: e.message }), type: "error" } }));
          }
        });
      });

      listEl.querySelectorAll(".btn-apply-rule").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.dataset.id;
          btn.disabled = true;
          try {
            const res = await api.applyRule(id);
            const count = res.affected_articles_count || 0;
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: t("rules.apply_single_success", { count }), type: "success" }
            }));
            window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
          } catch (err) {
            window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("rules.exec_all_failed", { error: err.message }), type: "error" } }));
          } finally {
            btn.disabled = false;
          }
        });
      });

      listEl.querySelectorAll(".btn-delete-rule").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.dataset.id;
          if (window.confirm(t("rules.confirm_delete"))) {
            await api.deleteRule(id);
            await this.loadRulesList();
            window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("rules.delete_success"), type: "success" } }));
          }
        });
      });
    } catch (_) {}
  }

  // 4. Plugin Management Center
  bindPlugins() {
    const btnOpen = document.getElementById("btn-open-plugins");
    if (btnOpen) {
      btnOpen.addEventListener("click", async () => {
        await this.loadPluginsList();
        this.openModal("modal-plugins");
      });
    }
  }

  async loadPluginsList() {
    const gridEl = document.getElementById("plugin-grid-container");
    if (!gridEl) return;

    try {
      const plugins = await api.getPlugins();
      if (!plugins || plugins.length === 0) {
        gridEl.innerHTML = `<div class="empty-state">${t("plugins.empty_state")}</div>`;
        return;
      }

      gridEl.innerHTML = plugins.map((p) => {
        const pId = p.plugin_id || p.id;
        const isTripped = Boolean(p.is_tripped || (p.circuit_status && p.circuit_status.is_tripped));
        const avgMs = Math.round(p.avg_duration_ms || (p.telemetry ? p.telemetry.avg_execution_ms : 0) || 0);
        const runs = p.total_runs || (p.telemetry ? p.telemetry.total_runs : 0) || 0;
        const successRuns = p.success_runs || (p.telemetry ? p.telemetry.success_runs : 0) || 0;
        const successRate = runs > 0 ? Math.round((successRuns / runs) * 100) : 100;
        const tb = p.last_error_traceback || (p.telemetry ? p.telemetry.last_error_traceback : "") || "";

        return `
          <div class="plugin-card">
            <div class="plugin-card-header">
              <div class="plugin-card-title">
                <span>${p.name}</span>
                <span class="plugin-slot-badge">${p.slot_type}</span>
                ${isTripped ? `<span class="tripped-badge">${t("plugins.tripped")}</span>` : ""}
              </div>
              <label class="plugin-switch">
                <input type="checkbox" class="plugin-toggle-checkbox" data-id="${pId}" ${p.is_enabled ? "checked" : ""}/>
                <span class="switch-slider"></span>
              </label>
            </div>
            <div class="text-muted" style="font-size: 12px;">${p.description || t("plugins.no_desc")}</div>
            <div class="plugin-telemetry" style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; font-size: 11px;">
              <span class="telemetry-item">${t("plugins.telemetry_time", { ms: avgMs })}</span>
              <span class="telemetry-item">${t("plugins.telemetry_runs", { runs: runs })}</span>
              <span class="telemetry-item">${t("plugins.telemetry_rate")}<strong style="color: ${successRate > 90 ? 'var(--accent-green, #4ade80)' : 'var(--accent-red, #f87171)'}">${successRate}%</strong></span>
              ${
                isTripped
                  ? `<button class="btn btn-reset-circuit" data-id="${pId}" style="padding: 1px 6px; font-size: 10px;">${t("plugins.reset_circuit")}</button>`
                  : ""
              }
            </div>
            ${
              tb
                ? `
              <details style="margin-top: 8px; font-size: 11px; background: rgba(0,0,0,0.25); border-radius: 4px; padding: 4px 8px;">
                <summary style="cursor: pointer; color: var(--accent-red, #f87171);">${t("plugins.view_traceback")}</summary>
                <pre style="white-space: pre-wrap; font-size: 10px; margin-top: 4px; max-height: 120px; overflow-y: auto; color: #fca5a5;">${this.escape(tb)}</pre>
              </details>
            `
                : ""
            }
          </div>
        `;
      }).join("");

      // Toggle Switches
      gridEl.querySelectorAll(".plugin-toggle-checkbox").forEach((cb) => {
        cb.addEventListener("change", async () => {
          const id = cb.dataset.id;
          await api.togglePlugin(id, cb.checked);
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("plugins.state_updated"), type: "success" } }));
        });
      });

      // Circuit Reset
      gridEl.querySelectorAll(".btn-reset-circuit").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.dataset.id;
          await api.resetPluginCircuit(id);
          await this.loadPluginsList();
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("plugins.circuit_reset_success"), type: "success" } }));
        });
      });
    } catch (_) {}
  }

  openSettings(targetTabId = "tab-appearance") {
    const modalSettings = document.getElementById("modal-settings");
    if (!modalSettings) return;

    const user = store.get("user");
    const keyInput = document.getElementById("input-api-key");
    if (keyInput) {
      if (user && user.api_key) {
        keyInput.value = safeInputVal(user.api_key);
      } else {
        keyInput.value = "";
        api.getMe().then((userData) => {
          if (userData && userData.api_key) {
            store.set("user", userData);
            keyInput.value = safeInputVal(userData.api_key);
          }
        }).catch((e) => console.warn("無法取得 API Key:", e));
      }
    }

    const themeSelect = document.getElementById("select-setting-theme");
    if (themeSelect) themeSelect.value = store.get("theme") || "dark";

    const fontFamilySelect = document.getElementById("select-setting-font-family");
    if (fontFamilySelect) fontFamilySelect.value = store.get("fontFamily") || "system";

    const syncFontSection = (presetId, rangeId, displayId, storeVal, defaultPresets) => {
      const presetEl = document.getElementById(presetId);
      const rangeEl = document.getElementById(rangeId);
      const displayEl = document.getElementById(displayId);
      if (rangeEl) rangeEl.value = storeVal;
      if (displayEl) displayEl.textContent = `${storeVal}px`;
      if (presetEl) {
        if (defaultPresets.includes(String(storeVal))) {
          presetEl.value = String(storeVal);
        } else {
          presetEl.value = "custom";
        }
      }
    };

    syncFontSection("select-reader-font-preset", "range-reader-font-size", "display-reader-font-val", store.get("readerFontSize") || 15, ["13", "15", "18", "22"]);
    syncFontSection("select-list-font-preset", "range-list-font-size", "display-list-font-val", store.get("listFontSize") || 13, ["11", "13", "15", "17"]);
    syncFontSection("select-tree-font-preset", "range-tree-font-size", "display-tree-font-val", store.get("treeFontSize") || 12, ["11", "12", "14", "16"]);

    const delaySelect = document.getElementById("select-setting-read-delay");
    if (delaySelect) delaySelect.value = String(store.get("readDelaySec") ?? 3);

    const hideEmptyCheck = document.getElementById("checkbox-hide-empty");
    if (hideEmptyCheck) hideEmptyCheck.checked = Boolean(store.get("hideEmptyFeeds"));

    const autoNextCheck = document.getElementById("checkbox-auto-next-category");
    if (autoNextCheck) autoNextCheck.checked = Boolean(store.get("autoNextCategory"));

    const autoFullTextCheck = document.getElementById("checkbox-setting-auto-full-text");
    if (autoFullTextCheck) autoFullTextCheck.checked = Boolean(store.get("autoFullText"));

    const retentionSelect = document.getElementById("select-setting-retention");
    if (retentionSelect) retentionSelect.value = String(store.get("retentionDays") ?? 60);

    const pollSelect = document.getElementById("select-setting-poll-interval");
    if (pollSelect) pollSelect.value = String(store.get("pollIntervalMinutes") ?? 30);

    const selectMinDate = document.getElementById("select-setting-min-date");
    const customMinDateInput = document.getElementById("input-setting-custom-min-date");
    const forceMinDateCb = document.getElementById("checkbox-setting-force-min-date");
    const minDateVal = store.get("minPublishDate");
    const forceMinDateVal = store.get("forceMinDate");

    if (forceMinDateCb) forceMinDateCb.checked = Boolean(forceMinDateVal);

    if (selectMinDate) {
      if (!minDateVal || minDateVal.startsWith("1970-01-01")) {
        selectMinDate.value = "all";
        if (customMinDateInput) customMinDateInput.style.display = "none";
      } else {
        selectMinDate.value = "custom";
        if (customMinDateInput) {
          customMinDateInput.value = minDateVal.slice(0, 10);
          customMinDateInput.style.display = "block";
        }
      }
    }

    const vaultCheck = document.getElementById("checkbox-image-vault");
    if (vaultCheck) vaultCheck.checked = store.get("imageVaultEnabled") !== false;

    const startupCheck = document.getElementById("checkbox-setting-refresh-on-startup");
    if (startupCheck) startupCheck.checked = store.get("refreshOnStartup") !== false;

    const markReadOnSwitchCheck = document.getElementById("checkbox-setting-mark-read-on-switch");
    if (markReadOnSwitchCheck) markReadOnSwitchCheck.checked = Boolean(store.get("markReadOnFeedSwitch"));

    modalSettings.querySelectorAll(".modal-tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === targetTabId));
    modalSettings.querySelectorAll(".modal-tab-content").forEach((c) => c.classList.toggle("active", c.id === targetTabId));

    if (targetTabId === "tab-tags") {
      this.renderSettingsTags();
    } else if (targetTabId === "tab-shortcuts") {
      this.renderSettingsShortcuts();
    }

    this.openModal("modal-settings");
  }

  renderSettingsTags() {
    const tagNameInput = document.getElementById("input-tag-name");
    if (tagNameInput && (tagNameInput.value === "null" || tagNameInput.value === "undefined")) {
      tagNameInput.value = "";
    }
    const container = document.getElementById("settings-tags-list-container");
    if (!container) return;

    const tags = store.get("tags") || [];
    if (tags.length === 0) {
      container.innerHTML = `<div style="padding: 16px; text-align: center; color: var(--text-muted); font-size: 12px;">${t("tags.empty_tags")}</div>`;
      return;
    }

    const html = tags.map((tagItem, idx) => {
      const keyBadge = idx < 9 ? `<kbd class="kbd-badge" style="margin-right: 6px;">${idx + 1}</kbd>` : "";
      return `
        <div class="settings-tag-row">
          <div style="display: flex; align-items: center; gap: 8px;">
            ${keyBadge}
            <span class="settings-tag-pill" style="border-color: ${tagItem.color_hex}50; background: ${tagItem.color_hex}1a; color: ${tagItem.color_hex};">
              <span class="tag-dot" style="background: ${tagItem.color_hex};"></span>
              ${this.escape(tagItem.name || t("tags.unnamed_tag"))}
            </span>
            <span style="font-size: 11px; color: var(--text-muted);">${t("tags.unread_article_count_fmt", { unread: tagItem.unread_count || 0, total: tagItem.article_count || 0 })}</span>
          </div>
          <div style="display: flex; align-items: center; gap: 6px;">
            <button type="button" class="btn btn-sm btn-danger btn-delete-tag" data-id="${tagItem.id}" data-name="${this.escape(tagItem.name || '')}" style="padding: 2px 8px; font-size: 11px;">${t("tags.delete_btn")}</button>
          </div>
        </div>
      `;
    }).join("");

    container.innerHTML = html;
  }

  renderSettingsShortcuts() {
    const container = document.getElementById("settings-shortcuts-list");
    if (!container) return;

    const shortcuts = getEffectiveShortcuts();
    const html = Object.entries(shortcuts).map(([action, def]) => {
      const keysHtml = def.keys.map((k) => `<kbd class="kbd-badge">${k}</kbd>`).join(" / ");
      return `
        <div class="shortcut-manage-row">
          <div style="font-weight: 500;">${def.label}</div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <div>${keysHtml}</div>
            <button type="button" class="shortcut-record-btn" data-action="${action}">${t("hotkeys.record_btn")}</button>
          </div>
        </div>
      `;
    }).join("");

    container.innerHTML = html;
  }

  // 5. Upgraded Settings Center (Tabs, Reading Behavior, Backup/OPML, API Keys)
  bindSettings() {
    const modalSettings = document.getElementById("modal-settings");
    if (!modalSettings) return;

    // Tabs switching
    modalSettings.querySelectorAll(".modal-tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const targetTab = btn.dataset.tab;
        modalSettings.querySelectorAll(".modal-tab-btn").forEach((b) => b.classList.remove("active"));
        modalSettings.querySelectorAll(".modal-tab-content").forEach((c) => c.classList.remove("active"));
        btn.classList.add("active");
        const contentEl = document.getElementById(targetTab);
        if (contentEl) contentEl.classList.add("active");

        if (targetTab === "tab-tags") {
          this.renderSettingsTags();
        } else if (targetTab === "tab-shortcuts") {
          this.renderSettingsShortcuts();
        }
      });
    });

    const btnOpen = document.getElementById("btn-open-settings");
    if (btnOpen) {
      btnOpen.addEventListener("click", () => {
        this.openSettings("tab-appearance");
      });
    }

    const saveSettingsToBackend = () => {
      clearTimeout(this._saveSettingsTimer);
      this._saveSettingsTimer = setTimeout(async () => {
        try {
          const settingsPayload = {
            theme: store.get("theme") || "dark",
            fontFamily: store.get("fontFamily") || "system",
            readerFontSize: store.get("readerFontSize") || 15,
            listFontSize: store.get("listFontSize") || 13,
            treeFontSize: store.get("treeFontSize") || 12,
            fontSize: store.get("fontSize") || "medium",
            readDelaySec: store.get("readDelaySec") ?? 3,
            hideEmptyFeeds: Boolean(store.get("hideEmptyFeeds")),
            markReadOnFeedSwitch: Boolean(store.get("markReadOnFeedSwitch")),
            refreshOnStartup: store.get("refreshOnStartup") !== false,
            autoNextCategory: Boolean(store.get("autoNextCategory")),
            retentionDays: store.get("retentionDays") ?? 60,
            pollIntervalMinutes: store.get("pollIntervalMinutes") ?? 30,
            minPublishDate: store.get("minPublishDate"),
            forceMinDate: Boolean(store.get("forceMinDate")),
            imageVaultEnabled: store.get("imageVaultEnabled") !== false,
            columnOrder: store.get("columnOrder") || ["status", "star", "title", "feed", "date", "author", "tags"],
            columnWidths: store.get("columnWidths") || {},
            readerToolbarOrder: store.get("readerToolbarOrder") || ["star", "toggle_read", "trash", "fetch_full", "copy_link", "open_url"],
            tagsPosition: store.get("tagsPosition") || "bottom",
            tagsPaneHeight: store.get("tagsPaneHeight") || 140,
            customShortcuts: store.get("customShortcuts") || {},
          };
          await api.updateUserSettings(settingsPayload);
        } catch (_) {}
      }, 500);
    };

    window.addEventListener("omnirss:column-order-changed", () => saveSettingsToBackend());
    window.addEventListener("omnirss:column-widths-changed", () => saveSettingsToBackend());
    window.addEventListener("omnirss:reader-toolbar-order-changed", () => saveSettingsToBackend());

    // Appearance & Typography changes
    const themeSelect = document.getElementById("select-setting-theme");
    if (themeSelect) {
      themeSelect.addEventListener("change", (e) => {
        store.set("theme", e.target.value);
        document.documentElement.setAttribute("data-theme", e.target.value);
        saveSettingsToBackend();
      });
    }

    const fontFamilySelect = document.getElementById("select-setting-font-family");
    if (fontFamilySelect) {
      fontFamilySelect.addEventListener("change", (e) => {
        store.set("fontFamily", e.target.value);
        window.dispatchEvent(new CustomEvent("omnirss:typography-changed"));
        saveSettingsToBackend();
      });
    }

    const setupFontControl = (presetId, rangeId, displayId, storeKey, defaultPresets) => {
      const presetEl = document.getElementById(presetId);
      const rangeEl = document.getElementById(rangeId);
      const displayEl = document.getElementById(displayId);

      if (rangeEl) {
        rangeEl.addEventListener("input", (e) => {
          const val = parseInt(e.target.value, 10);
          if (displayEl) displayEl.textContent = `${val}px`;
          if (presetEl) {
            presetEl.value = defaultPresets.includes(String(val)) ? String(val) : "custom";
          }
          store.set(storeKey, val);
          window.dispatchEvent(new CustomEvent("omnirss:typography-changed"));
          saveSettingsToBackend();
        });
      }

      if (presetEl) {
        presetEl.addEventListener("change", (e) => {
          if (e.target.value !== "custom") {
            const val = parseInt(e.target.value, 10);
            if (rangeEl) rangeEl.value = val;
            if (displayEl) displayEl.textContent = `${val}px`;
            store.set(storeKey, val);
            window.dispatchEvent(new CustomEvent("omnirss:typography-changed"));
            saveSettingsToBackend();
          }
        });
      }
    };

    setupFontControl("select-reader-font-preset", "range-reader-font-size", "display-reader-font-val", "readerFontSize", ["13", "15", "18", "22"]);
    setupFontControl("select-list-font-preset", "range-list-font-size", "display-list-font-val", "listFontSize", ["11", "13", "15", "17"]);
    setupFontControl("select-tree-font-preset", "range-tree-font-size", "display-tree-font-val", "treeFontSize", ["11", "12", "14", "16"]);

    const btnResetFonts = document.getElementById("btn-reset-font-sizes");
    if (btnResetFonts) {
      btnResetFonts.addEventListener("click", () => {
        store.set("fontFamily", "system");
        store.set("readerFontSize", 15);
        store.set("listFontSize", 13);
        store.set("treeFontSize", 12);
        if (fontFamilySelect) fontFamilySelect.value = "system";

        const syncSection = (presetId, rangeId, displayId, val, defaultPresets) => {
          const p = document.getElementById(presetId);
          const r = document.getElementById(rangeId);
          const d = document.getElementById(displayId);
          if (r) r.value = val;
          if (d) d.textContent = `${val}px`;
          if (p) p.value = defaultPresets.includes(String(val)) ? String(val) : "custom";
        };
        syncSection("select-reader-font-preset", "range-reader-font-size", "display-reader-font-val", 15, ["13", "15", "18", "22"]);
        syncSection("select-list-font-preset", "range-list-font-size", "display-list-font-val", 13, ["11", "13", "15", "17"]);
        syncSection("select-tree-font-preset", "range-tree-font-size", "display-tree-font-val", 12, ["11", "12", "14", "16"]);

        window.dispatchEvent(new CustomEvent("omnirss:typography-changed"));
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.reset_typography_success"), type: "success" } }));
        saveSettingsToBackend();
      });
    }

    const btnResetColWidths = document.getElementById("btn-reset-column-widths");
    if (btnResetColWidths) {
      btnResetColWidths.addEventListener("click", () => {
        store.set("columnWidths", {});
        localStorage.removeItem("omnirss_column_widths");
        window.dispatchEvent(new CustomEvent("omnirss:column-widths-changed"));
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.reset_col_widths_success"), type: "success" } }));
        saveSettingsToBackend();
      });
    }

    // Reading Behavior changes
    const delaySelect = document.getElementById("select-setting-read-delay");
    if (delaySelect) {
      delaySelect.addEventListener("change", (e) => {
        store.set("readDelaySec", parseInt(e.target.value, 10));
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.update_delay_success"), type: "success" } }));
        saveSettingsToBackend();
      });
    }

    const hideEmptyCheck = document.getElementById("checkbox-hide-empty");
    if (hideEmptyCheck) {
      hideEmptyCheck.addEventListener("change", (e) => {
        store.set("hideEmptyFeeds", e.target.checked);
        saveSettingsToBackend();
      });
    }

    const autoNextCheck = document.getElementById("checkbox-auto-next-category");
    if (autoNextCheck) {
      autoNextCheck.addEventListener("change", (e) => {
        store.set("autoNextCategory", e.target.checked);
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.update_auto_next_success"), type: "success" } }));
        saveSettingsToBackend();
      });
    }

    const autoFullTextCheck = document.getElementById("checkbox-setting-auto-full-text");
    if (autoFullTextCheck) {
      autoFullTextCheck.addEventListener("change", (e) => {
        store.set("autoFullText", e.target.checked);
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.update_auto_full_text_success"), type: "success" } }));
        saveSettingsToBackend();
      });
    }

    // Tag Management Event Bindings
    document.querySelectorAll(".color-preset-dot").forEach((dot) => {
      dot.addEventListener("click", () => {
        const color = dot.dataset.color;
        const colorInput = document.getElementById("input-tag-color");
        if (colorInput) colorInput.value = color;
      });
    });

    const formAddTag = document.getElementById("form-add-tag");
    if (formAddTag) {
      formAddTag.addEventListener("submit", async (e) => {
        e.preventDefault();
        const name = document.getElementById("input-tag-name").value.trim();
        const color = document.getElementById("input-tag-color").value;
        if (!name) return;
        try {
          await api.createTag(name, color);
          const tags = await api.getTags();
          store.set("tags", tags || []);
          formAddTag.reset();
          this.renderSettingsTags();
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("tags.create_success", { name }), type: "success" } }));
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("tags.create_failed", { error: err.message }), type: "error" } }));
        }
      });
    }

    const tagsListContainer = document.getElementById("settings-tags-list-container");
    if (tagsListContainer) {
      tagsListContainer.addEventListener("click", async (e) => {
        const delBtn = e.target.closest(".btn-delete-tag");
        if (delBtn) {
          const tagId = parseInt(delBtn.dataset.id, 10);
          const tagName = delBtn.dataset.name;
          if (!confirm(t("tags.confirm_delete", { name: tagName }))) return;
          try {
            await api.deleteTag(tagId);
            const tags = await api.getTags();
            store.set("tags", tags || []);
            this.renderSettingsTags();
            window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("tags.delete_success"), type: "success" } }));
          } catch (err) {
            window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("tags.delete_failed", { error: err.message }), type: "error" } }));
          }
        }
      });
    }

    // Shortcuts Management Event Bindings
    const shortcutsContainer = document.getElementById("settings-shortcuts-list");
    if (shortcutsContainer) {
      shortcutsContainer.addEventListener("click", (e) => {
        const recBtn = e.target.closest(".shortcut-record-btn");
        if (recBtn) {
          const action = recBtn.dataset.action;
          recBtn.textContent = t("hotkeys.press_any_key");
          recBtn.classList.add("recording");

          recordNextKey((newKey) => {
            const currentCustom = store.get("customShortcuts") || {};
            const updatedCustom = { ...currentCustom, [action]: [newKey] };
            store.set("customShortcuts", updatedCustom);
            saveSettingsToBackend();
            this.renderSettingsShortcuts();
            window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("hotkeys.updated_toast", { key: newKey }), type: "success" } }));
          });
        }
      });
    }

    const btnResetShortcuts = document.getElementById("btn-reset-shortcuts");
    if (btnResetShortcuts) {
      btnResetShortcuts.addEventListener("click", () => {
        if (!confirm(t("hotkeys.confirm_reset"))) return;
        store.set("customShortcuts", {});
        saveSettingsToBackend();
        this.renderSettingsShortcuts();
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("hotkeys.reset_success"), type: "success" } }));
      });
    }

    // Schedule & Retention changes
    const retentionSelect = document.getElementById("select-setting-retention");
    if (retentionSelect) {
      retentionSelect.addEventListener("change", (e) => {
        store.set("retentionDays", parseInt(e.target.value, 10));
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.update_retention_success"), type: "success" } }));
        saveSettingsToBackend();
      });
    }

    const pollSelect = document.getElementById("select-setting-poll-interval");
    if (pollSelect) {
      pollSelect.addEventListener("change", (e) => {
        store.set("pollIntervalMinutes", parseInt(e.target.value, 10));
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.update_poll_success"), type: "success" } }));
        saveSettingsToBackend();
      });
    }

    const vaultCheck = document.getElementById("checkbox-image-vault");
    if (vaultCheck) {
      vaultCheck.addEventListener("change", (e) => {
        store.set("imageVaultEnabled", e.target.checked);
        saveSettingsToBackend();
      });
    }

    const startupCheck = document.getElementById("checkbox-setting-refresh-on-startup");
    if (startupCheck) {
      startupCheck.addEventListener("change", (e) => {
        store.set("refreshOnStartup", e.target.checked);
        saveSettingsToBackend();
      });
    }

    const markReadOnSwitchCheck = document.getElementById("checkbox-setting-mark-read-on-switch");
    if (markReadOnSwitchCheck) {
      markReadOnSwitchCheck.addEventListener("change", (e) => {
        store.set("markReadOnFeedSwitch", e.target.checked);
        saveSettingsToBackend();
      });
    }

    // Global Min Date & Force Min Date
    const selectMinDate = document.getElementById("select-setting-min-date");
    const customMinDateInput = document.getElementById("input-setting-custom-min-date");
    const forceMinDateCb = document.getElementById("checkbox-setting-force-min-date");

    const updateGlobalMinDate = () => {
      let minPublishDate = null;
      const minDateVal = selectMinDate ? selectMinDate.value : "all";
      if (minDateVal === "all") {
        minPublishDate = "1970-01-01 00:00:00";
      } else if (minDateVal === "today") {
        const now = new Date();
        minPublishDate = now.toISOString().slice(0, 10) + " 00:00:00";
      } else if (minDateVal === "7days") {
        const d = new Date(Date.now() - 7 * 86400000);
        minPublishDate = d.toISOString().slice(0, 10) + " 00:00:00";
      } else if (minDateVal === "30days") {
        const d = new Date(Date.now() - 30 * 86400000);
        minPublishDate = d.toISOString().slice(0, 10) + " 00:00:00";
      } else if (minDateVal === "custom") {
        if (customMinDateInput?.value) {
          minPublishDate = customMinDateInput.value + " 00:00:00";
        }
      }
      store.set("minPublishDate", minPublishDate);
      saveSettingsToBackend();
    };

    if (selectMinDate && customMinDateInput) {
      selectMinDate.addEventListener("change", () => {
        if (selectMinDate.value === "custom") {
          customMinDateInput.style.display = "block";
          customMinDateInput.focus();
        } else {
          customMinDateInput.style.display = "none";
        }
        updateGlobalMinDate();
      });
      customMinDateInput.addEventListener("change", () => {
        updateGlobalMinDate();
      });
    }

    if (forceMinDateCb) {
      forceMinDateCb.addEventListener("change", (e) => {
        store.set("forceMinDate", e.target.checked);
        saveSettingsToBackend();
      });
    }

    // OPML Export
    const btnExport = document.getElementById("btn-export-opml");
    if (btnExport) {
      btnExport.addEventListener("click", async () => {
        try {
          const opmlText = await api.exportOpml();
          const blob = new Blob([opmlText], { type: "text/xml;charset=utf-8" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `omnirss_backup_${new Date().toISOString().slice(0, 10)}.opml`;
          a.click();
          URL.revokeObjectURL(url);
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.opml_export_success"), type: "success" } }));
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.opml_export_failed", { error: err.message }), type: "error" } }));
        }
      });
    }

    // OPML Import
    const formImport = document.getElementById("form-import-opml");
    if (formImport) {
      formImport.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fileInput = document.getElementById("input-opml-file");
        if (!fileInput.files || fileInput.files.length === 0) return;

        try {
          const result = await api.importOpml(fileInput.files[0]);
          const count = result.imported_count || result.imported_feeds || 0;
          this.closeModal("modal-settings");
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.opml_import_success", { count }), type: "success" } }));
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.opml_import_failed", { error: err.message }), type: "error" } }));
        }
      });
    }

    // Danger Zone: Clear All Feeds
    const btnClearAll = document.getElementById("btn-clear-all-feeds");
    if (btnClearAll) {
      btnClearAll.addEventListener("click", async () => {
        if (!confirm(t("settings.confirm_delete_all_feeds"))) return;
        try {
          const feeds = store.get("feeds") || [];
          for (const f of feeds) {
            await api.deleteFeed(f.id);
          }
          this.closeModal("modal-settings");
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.clear_feeds_success"), type: "success" } }));
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.clear_feeds_failed", { error: err.message }), type: "error" } }));
        }
      });
    }

    // API Key copy & regen
    const btnRegenKey = document.getElementById("btn-regenerate-api-key") || document.getElementById("btn-regen-key");
    if (btnRegenKey) {
      btnRegenKey.addEventListener("click", async () => {
        if (!confirm(t("settings.confirm_regen_api_key"))) return;
        try {
          const res = await api.regenerateApiKey();
          const keyInput = document.getElementById("input-api-key");
          if (keyInput) keyInput.value = safeInputVal(res?.api_key);
          const user = store.get("user");
          if (user) user.api_key = safeInputVal(res?.api_key);
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.api_key_regen_success"), type: "success" } }));
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.api_key_regen_failed", { error: err.message }), type: "error" } }));
        }
      });
    }

    const btnCopyKey = document.getElementById("btn-copy-api-key") || document.getElementById("btn-copy-key");
    if (btnCopyKey) {
      btnCopyKey.addEventListener("click", () => {
        const keyInput = document.getElementById("input-api-key");
        if (keyInput && keyInput.value) {
          navigator.clipboard.writeText(keyInput.value);
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.copied"), type: "success" } }));
        }
      });
    }

    // Save Settings Button in Modal Footer
    const btnSaveSettings = document.getElementById("btn-save-settings");
    if (btnSaveSettings) {
      btnSaveSettings.addEventListener("click", async () => {
        try {
          // 1. 從當前 DOM 表單即時提取最新設定值並同步至 store
          const themeSelect = document.getElementById("select-setting-theme");
          if (themeSelect) {
            store.set("theme", themeSelect.value);
            document.documentElement.setAttribute("data-theme", themeSelect.value);
          }

          const fontFamilySelect = document.getElementById("select-setting-font-family");
          if (fontFamilySelect) store.set("fontFamily", fontFamilySelect.value);

          const rangeReaderFont = document.getElementById("range-reader-font-size");
          if (rangeReaderFont) store.set("readerFontSize", parseInt(rangeReaderFont.value, 10));

          const rangeListFont = document.getElementById("range-list-font-size");
          if (rangeListFont) store.set("listFontSize", parseInt(rangeListFont.value, 10));

          const rangeTreeFont = document.getElementById("range-tree-font-size");
          if (rangeTreeFont) store.set("treeFontSize", parseInt(rangeTreeFont.value, 10));

          const delaySelect = document.getElementById("select-setting-read-delay");
          if (delaySelect) store.set("readDelaySec", parseInt(delaySelect.value, 10));

          const hideEmptyCheck = document.getElementById("checkbox-hide-empty");
          if (hideEmptyCheck) store.set("hideEmptyFeeds", hideEmptyCheck.checked);

          const markReadOnSwitchCheck = document.getElementById("checkbox-setting-mark-read-on-switch");
          if (markReadOnSwitchCheck) store.set("markReadOnFeedSwitch", markReadOnSwitchCheck.checked);

          const startupCheck = document.getElementById("checkbox-setting-refresh-on-startup");
          if (startupCheck) store.set("refreshOnStartup", startupCheck.checked);

          const autoNextCheck = document.getElementById("checkbox-auto-next-category");
          if (autoNextCheck) store.set("autoNextCategory", autoNextCheck.checked);

          const autoFullTextCheck = document.getElementById("checkbox-setting-auto-full-text");
          if (autoFullTextCheck) store.set("autoFullText", autoFullTextCheck.checked);

          const retentionSelect = document.getElementById("select-setting-retention");
          if (retentionSelect) store.set("retentionDays", parseInt(retentionSelect.value, 10));

          const pollSelect = document.getElementById("select-setting-poll-interval");
          if (pollSelect) store.set("pollIntervalMinutes", parseInt(pollSelect.value, 10));

          const selectMinDate = document.getElementById("select-setting-min-date");
          const customMinDateInput = document.getElementById("input-setting-custom-min-date");
          if (selectMinDate) {
            const minDateVal = selectMinDate.value;
            let minPublishDate = null;
            if (minDateVal === "all") {
              minPublishDate = "1970-01-01 00:00:00";
            } else if (minDateVal === "today") {
              const now = new Date();
              minPublishDate = now.toISOString().slice(0, 10) + " 00:00:00";
            } else if (minDateVal === "7days") {
              const d = new Date(Date.now() - 7 * 86400000);
              minPublishDate = d.toISOString().slice(0, 10) + " 00:00:00";
            } else if (minDateVal === "30days") {
              const d = new Date(Date.now() - 30 * 86400000);
              minPublishDate = d.toISOString().slice(0, 10) + " 00:00:00";
            } else if (minDateVal === "custom" && customMinDateInput?.value) {
              minPublishDate = customMinDateInput.value + " 00:00:00";
            }
            store.set("minPublishDate", minPublishDate);
          }

          const forceMinDateCb = document.getElementById("checkbox-setting-force-min-date");
          if (forceMinDateCb) store.set("forceMinDate", forceMinDateCb.checked);

          const vaultCheck = document.getElementById("checkbox-image-vault");
          if (vaultCheck) store.set("imageVaultEnabled", vaultCheck.checked);

          // 2. 組裝 Payload 並同步至後端
          const settingsPayload = {
            theme: store.get("theme") || "dark",
            fontFamily: store.get("fontFamily") || "system",
            readerFontSize: store.get("readerFontSize") || 15,
            listFontSize: store.get("listFontSize") || 13,
            treeFontSize: store.get("treeFontSize") || 12,
            fontSize: store.get("fontSize") || "medium",
            readDelaySec: store.get("readDelaySec") ?? 3,
            hideEmptyFeeds: Boolean(store.get("hideEmptyFeeds")),
            markReadOnFeedSwitch: Boolean(store.get("markReadOnFeedSwitch")),
            refreshOnStartup: store.get("refreshOnStartup") !== false,
            autoNextCategory: Boolean(store.get("autoNextCategory")),
            autoFullText: Boolean(store.get("autoFullText")),
            retentionDays: store.get("retentionDays") ?? 60,
            pollIntervalMinutes: store.get("pollIntervalMinutes") ?? 30,
            minPublishDate: store.get("minPublishDate"),
            forceMinDate: Boolean(store.get("forceMinDate")),
            imageVaultEnabled: store.get("imageVaultEnabled") !== false,
            columnOrder: store.get("columnOrder") || ["status", "star", "title", "feed", "date", "author", "tags"],
            columnWidths: store.get("columnWidths") || {},
            readerToolbarOrder: store.get("readerToolbarOrder") || ["star", "toggle_read", "trash", "fetch_full", "copy_link", "open_url"],
            tagsPosition: store.get("tagsPosition") || "bottom",
            tagsPaneHeight: store.get("tagsPaneHeight") || 140,
            customShortcuts: store.get("customShortcuts") || {},
          };

          await api.updateUserSettings(settingsPayload);
          window.dispatchEvent(new CustomEvent("omnirss:typography-changed"));
          window.dispatchEvent(new CustomEvent("omnirss:column-order-changed"));
          this.closeModal("modal-settings");
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.save_success"), type: "success" } }));
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.save_failed", { error: err.message }), type: "error" } }));
        }
      });
    }
  }

  // 6. Auth Login Modal
  bindAuth() {
    window.addEventListener("omnirss:auth-required", () => {
      this.openModal("modal-login");
    });

    const formLogin = document.getElementById("form-login");
    if (formLogin) {
      formLogin.addEventListener("submit", async (e) => {
        e.preventDefault();
        const u = document.getElementById("login-username").value.trim();
        const p = document.getElementById("login-password").value;
        const errEl = document.getElementById("login-error");

        try {
          const res = await api.login(u, p);
          store.set("token", res.access_token);
          const me = await api.getMe();
          store.set("user", me);
          this.closeModal("modal-login");
          if (errEl) errEl.style.display = "none";
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
        } catch (err) {
          if (errEl) {
            errEl.textContent = err.message || t("auth.login_failed");
            errEl.style.display = "block";
          }
        }
      });
    }
  }

  // 7. Article Tags Assignment Dialog (🏷️)
  bindArticleTags() {
    const formQuickAdd = document.getElementById("form-quick-add-tag");
    if (formQuickAdd) {
      formQuickAdd.addEventListener("submit", async (e) => {
        e.preventDefault();
        const nameInput = document.getElementById("input-quick-tag-name");
        const colorInput = document.getElementById("input-quick-tag-color");
        const name = safeInputVal(nameInput?.value);
        const color = colorInput?.value || "#3b82f6";
        if (!name) return;

        try {
          await api.createTag(name, color);
          const tags = await api.getTags();
          store.set("tags", tags || []);
          if (nameInput) nameInput.value = "";

          // 若目前有文章正在打標，自動為該文章貼上此新標籤
          const currentArtId = this._currentArticleTagModalId;
          const newTag = (tags || []).find((tagItem) => tagItem.name === name);
          if (newTag && currentArtId) {
            await api.toggleArticleTag(currentArtId, newTag.id, "add");
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: t("tags.created_and_attached", { name }), type: "success" }
            }));
            window.dispatchEvent(new CustomEvent("omnirss:tags-updated"));
            window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
          }
          this.renderArticleTagsCheckboxes(currentArtId);
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("tags.create_failed", { error: err.message }), type: "error" }
          }));
        }
      });
    }

    const container = document.getElementById("article-tags-checkboxes-container");
    if (container) {
      container.addEventListener("change", async (e) => {
        const checkbox = e.target.closest(".article-tag-checkbox");
        if (!checkbox) return;
        const tagId = parseInt(checkbox.dataset.tagId, 10);
        const tagName = checkbox.dataset.tagName || "";
        const articleId = this._currentArticleTagModalId;
        if (!tagId || !articleId) return;

        try {
          const res = await api.toggleArticleTag(articleId, tagId);
          window.dispatchEvent(new CustomEvent("omnirss:tags-updated"));
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));

          // 更新當前文章在 store 內的標籤清單
          const articles = store.get("articles") || [];
          const art = articles.find((a) => a.id === articleId);
          if (art && res.tags) {
            art.tags = res.tags;
            store.set("articles", [...articles]);
          }
          const selectedArticle = store.get("selectedArticle");
          if (selectedArticle && selectedArticle.id === articleId) {
            selectedArticle.tags = res.tags || [];
            store.set("selectedArticle", { ...selectedArticle });
          }

          const actionName = res.is_tagged ? t("tags.tag_attached") : t("tags.tag_removed");
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: `${actionName}：${tagName}`, type: "info" }
          }));

          // 動態切換項目背景色彩
          const labelItem = checkbox.closest(".article-tag-checkbox-item");
          if (labelItem) {
            labelItem.style.background = checkbox.checked ? "rgba(59, 130, 246, 0.08)" : "transparent";
          }
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("tags.attach_failed", { error: err.message }), type: "error" }
          }));
          checkbox.checked = !checkbox.checked; // 復原勾選狀態
        }
      });
    }
  }

  async openArticleTagsModal(articleId) {
    if (!articleId) return;
    this._currentArticleTagModalId = articleId;

    const articles = store.get("articles") || [];
    const currentSelected = store.get("selectedArticle");
    const art = (currentSelected && currentSelected.id === articleId) ? currentSelected : (articles.find((a) => a.id === articleId) || {});
    const title = art.title || t("tags.current_article");
    const subtitle = document.getElementById("article-tags-modal-subtitle");
    if (subtitle) {
      subtitle.textContent = t("tags.modal_subtitle", { name: title.length > 25 ? title.slice(0, 25) + "..." : title });
    }

    // 確保標籤資料最新
    try {
      const tags = await api.getTags();
      store.set("tags", tags || []);
    } catch (_) {}

    this.renderArticleTagsCheckboxes(articleId);
    this.openModal("modal-article-tags");
  }

  renderArticleTagsCheckboxes(articleId) {
    const container = document.getElementById("article-tags-checkboxes-container");
    if (!container) return;

    const tags = store.get("tags") || [];
    const articles = store.get("articles") || [];
    const currentSelected = store.get("selectedArticle");
    const art = (currentSelected && currentSelected.id === articleId) ? currentSelected : (articles.find((a) => a.id === articleId) || {});

    const artTagIds = new Set();
    const artTagNames = new Set();
    if (art && Array.isArray(art.tags)) {
      art.tags.forEach((tagItem) => {
        if (typeof tagItem === "object" && tagItem !== null) {
          if (tagItem.id) artTagIds.add(tagItem.id);
          if (tagItem.name) artTagNames.add(tagItem.name);
        } else if (typeof tagItem === "string" || typeof tagItem === "number") {
          artTagNames.add(String(tagItem));
          artTagIds.add(Number(tagItem));
        }
      });
    }

    if (tags.length === 0) {
      container.innerHTML = `<div style="color: var(--text-muted); font-size: 12px; padding: 12px; text-align: center;">${t("tags.empty_dialog_hint")}</div>`;
      return;
    }

    container.innerHTML = tags.map((tag) => {
      const isChecked = artTagIds.has(tag.id) || artTagNames.has(tag.name);
      return `
        <label class="article-tag-checkbox-item" style="display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; border-radius: 4px; cursor: pointer; user-select: none; background: ${isChecked ? "rgba(59, 130, 246, 0.08)" : "transparent"};">
          <div style="display: flex; align-items: center; gap: 8px;">
            <input type="checkbox" class="article-tag-checkbox" data-tag-id="${tag.id}" data-tag-name="${this.escape(tag.name)}" ${isChecked ? "checked" : ""} style="cursor: pointer;" />
            <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: ${tag.color_hex || "#3b82f6"};"></span>
            <span style="font-size: 13px; font-weight: 500; color: var(--text-primary);">${this.escape(tag.name)}</span>
          </div>
          <span style="font-size: 11px; color: var(--text-muted);">${t("tags.article_count_fmt", { count: tag.article_count || 0 })}</span>
        </label>
      `;
    }).join("");
  }
}
