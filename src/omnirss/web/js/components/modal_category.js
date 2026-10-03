/**
 * OmniRSS 分類新增與屬性設定對話框模組 (Category Add & Settings Modal Module).
 */

import { store, safeInputVal } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";

export function registerCategoryModal(proto) {
  // 1. Add Category
  proto.bindAddCategory = function () {
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
  };

  // 2. Advanced Tabbed Category Settings Center
  proto.openCategorySettings = async function (categoryData) {
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
        const val = currentCat.custom_min_date;
        if (!val || val === "null" || val === "default") {
          selectMinDate.value = "default";
          if (customMinDateInput) customMinDateInput.style.display = "none";
        } else if (val === "all" || val.startsWith("1970-01-01")) {
          selectMinDate.value = "all";
          if (customMinDateInput) customMinDateInput.style.display = "none";
        } else if (["today", "7days", "30days", "90days"].includes(val)) {
          selectMinDate.value = val;
          if (customMinDateInput) customMinDateInput.style.display = "none";
        } else {
          selectMinDate.value = "custom";
          if (customMinDateInput) {
            customMinDateInput.value = val.slice(0, 10);
            customMinDateInput.style.display = "block";
          }
        }
      }
    }

    // 載入分類偏好設定 (Sort, Hide Read, Keywords, Columns, Auto Full Text) - 直接從 DB 物件讀取
    try {
      let prefs = currentCat?.view_preferences;
      if (typeof prefs === "string") {
        prefs = JSON.parse(prefs || "{}");
      }
      if (prefs) {
        if (sortSelect && prefs.sort) sortSelect.value = prefs.sort;
        if (hideReadCb && prefs.hide_read !== undefined) hideReadCb.checked = Boolean(prefs.hide_read);
        if (inclKw) inclKw.value = safeInputVal(prefs.include_keywords);
        if (exclKw) exclKw.value = safeInputVal(prefs.exclude_keywords);
      }
    } catch (_) {}

    // 載入分類自動擷取全文 (auto_full_text) 狀態
    const autoFullTextCb = document.getElementById("checkbox-cat-auto-full-text");
    if (autoFullTextCb) {
      autoFullTextCb.checked = Boolean(currentCat?.auto_full_text);
    }

    // 載入文章列表欄位偏好勾選狀態
    const globalCols = store.get("columns") || { status: true, star: true, title: true, feed: true, date: true, author: true, tags: false };
    const cbThumb = document.getElementById("checkbox-col-thumb");
    const cbAuthor = document.getElementById("checkbox-col-author");
    const cbFeed = document.getElementById("checkbox-col-feed");
    const cbDate = document.getElementById("checkbox-col-date");
    if (cbThumb) cbThumb.checked = globalCols.tags !== undefined ? Boolean(globalCols.status) : true;
    if (cbAuthor) cbAuthor.checked = Boolean(globalCols.author);
    if (cbFeed) cbFeed.checked = Boolean(globalCols.feed);
    if (cbDate) cbDate.checked = Boolean(globalCols.date);

    this.openModal("modal-category-settings");
  };

  proto.bindCategorySettings = function () {
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

    // 綁定分類設定視窗中文章列表欄位偏好勾選變更
    const handleColChange = () => {
      const currentCols = store.get("columns") || { status: true, star: true, title: true, feed: true, date: true, author: true, tags: false };
      const cbAuthor = document.getElementById("checkbox-col-author");
      const cbFeed = document.getElementById("checkbox-col-feed");
      const cbDate = document.getElementById("checkbox-col-date");
      store.set("columns", {
        ...currentCols,
        author: cbAuthor ? cbAuthor.checked : currentCols.author,
        feed: cbFeed ? cbFeed.checked : currentCols.feed,
        date: cbDate ? cbDate.checked : currentCols.date,
      });
    };
    document.getElementById("checkbox-col-thumb")?.addEventListener("change", handleColChange);
    document.getElementById("checkbox-col-author")?.addEventListener("change", handleColChange);
    document.getElementById("checkbox-col-feed")?.addEventListener("change", handleColChange);
    document.getElementById("checkbox-col-date")?.addEventListener("change", handleColChange);

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

      // Min Date Handling (支援動態相對時間代碼與自訂日期)
      let customMinDate = null;
      const minDateVal = selectMinDate ? selectMinDate.value : "default";
      if (minDateVal === "default") {
        customMinDate = null;
      } else if (minDateVal === "all") {
        customMinDate = "all";
      } else if (["today", "7days", "30days", "90days"].includes(minDateVal)) {
        customMinDate = minDateVal;
      } else if (minDateVal === "custom") {
        if (customMinDateInput?.value) {
          customMinDate = customMinDateInput.value;
        }
      }
      const forceMinDate = Boolean(document.getElementById("checkbox-cat-force-min-date")?.checked);

      // 組合分類專屬視圖與過濾偏好 (直接寫入 DB categories.view_preferences)
      const autoFullText = Boolean(document.getElementById("checkbox-cat-auto-full-text")?.checked);
      const prefs = {
        sort: document.getElementById("select-cat-sort")?.value || "published_desc",
        hide_read: Boolean(document.getElementById("checkbox-cat-hide-read")?.checked),
        include_keywords: safeInputVal(document.getElementById("input-cat-filter-keywords")?.value),
        exclude_keywords: safeInputVal(document.getElementById("input-cat-exclude-keywords")?.value),
      };

      try {
        await api.updateCategory(id, {
          name,
          custom_retention_days: customRetentionDays,
          custom_interval_minutes: customIntervalMinutes,
          custom_min_date: customMinDate,
          force_min_date: forceMinDate,
          is_paused: isPaused,
          auto_full_text: autoFullText,
          view_preferences: JSON.stringify(prefs),
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
  };
}
