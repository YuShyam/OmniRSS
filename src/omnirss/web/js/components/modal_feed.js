/**
 * OmniRSS 訂閱源新增與屬性對話框模組 (Feed Add & Properties Modal Module).
 */

import { store, safeInputVal } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";

export function registerFeedModal(proto) {
  // 1. Add Feed
  proto.bindAddFeed = function () {
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
  };

  // 2. Feed Properties Modal & Health Diagnostic (Tabbed Layout)
  proto.openFeedPropertiesModal = async function (feedId) {
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
          const val = feed.min_publish_date;
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
  };

  proto.bindFeedProperties = function () {
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

        // Min Date (支援動態相對時間代碼與自訂日期)
        let minPublishDate = null;
        const minDateVal = selectMinDate ? selectMinDate.value : "default";
        if (minDateVal === "default") {
          minPublishDate = null;
        } else if (minDateVal === "all") {
          minPublishDate = "all";
        } else if (["today", "7days", "30days", "90days"].includes(minDateVal)) {
          minPublishDate = minDateVal;
        } else if (minDateVal === "custom") {
          if (customMinDateInput?.value) {
            minPublishDate = customMinDateInput.value;
          }
        }
        const forceMinDate = Boolean(document.getElementById("checkbox-feed-prop-force-min-date")?.checked);

        const flaresolverr = Boolean(document.getElementById("feed-prop-flaresolverr")?.checked);
        const autoFullText = Boolean(document.getElementById("feed-prop-auto-full-text")?.checked);
        const isPaused = Boolean(document.getElementById("feed-prop-paused")?.checked);
        const authUsername = safeInputVal(document.getElementById("feed-prop-auth-user")?.value) || null;
        const authPassword = safeInputVal(document.getElementById("feed-prop-auth-pass")?.value) || null;

        try {
          const res = await api.updateFeed(id, {
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

          if (res && res.feed_id && store.get("activeFeedId") === id) {
            store.set("activeFeedId", res.feed_id);
          }

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
  };
}
