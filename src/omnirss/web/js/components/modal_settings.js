/**
 * OmniRSS 系統偏好設定對話框模組 (System Settings Modal Module).
 */

import { store } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";
import { getEffectiveShortcuts, recordNextKey } from "../keybindings.js";

export function registerSettingsModal(proto) {
  proto.renderSettingsTags = function () {
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
  };

  proto.renderSettingsShortcuts = function () {
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
  };

  proto.openSettings = function (targetTabId = "tab-appearance") {
    const modalSettings = document.getElementById("modal-settings");
    if (!modalSettings) return;

    const themeSelect = document.getElementById("select-setting-theme");
    if (themeSelect) themeSelect.value = store.get("theme") || "dark";

    const fontFamilySelect = document.getElementById("select-setting-font-family");
    if (fontFamilySelect) fontFamilySelect.value = store.get("fontFamily") || "system";

    const tzSelect = document.getElementById("select-setting-timezone");
    if (tzSelect) tzSelect.value = store.get("timezone") || "auto";

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
      if (!minDateVal || minDateVal === "all" || minDateVal.startsWith("1970-01-01")) {
        selectMinDate.value = "all";
        if (customMinDateInput) customMinDateInput.style.display = "none";
      } else if (["today", "7days", "30days", "90days"].includes(minDateVal)) {
        selectMinDate.value = minDateVal;
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

    modalSettings.querySelectorAll(".modal-tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === targetTabId));
    modalSettings.querySelectorAll(".modal-tab-content").forEach((c) => c.classList.toggle("active", c.id === targetTabId));

    if (targetTabId === "tab-tags") {
      this.renderSettingsTags();
    } else if (targetTabId === "tab-shortcuts") {
      this.renderSettingsShortcuts();
    }

    this.openModal("modal-settings");
  };

  proto.buildFullSettingsPayload = function () {
    return {
      theme: store.get("theme") || "dark",
      lang: store.get("lang") || "zh-TW",
      fontSize: store.get("fontSize") || "medium",
      fontFamily: store.get("fontFamily") || "system",
      readerFontSize: store.get("readerFontSize") ?? 15,
      listFontSize: store.get("listFontSize") ?? 13,
      treeFontSize: store.get("treeFontSize") ?? 12,
      readDelaySec: store.get("readDelaySec") ?? 3,
      autoNextCategory: Boolean(store.get("autoNextCategory")),
      customShortcuts: store.get("customShortcuts") || {},
      hideEmptyFeeds: Boolean(store.get("hideEmptyFeeds")),
      hideRead: Boolean(store.get("hideRead")),
      markReadOnFeedSwitch: Boolean(store.get("markReadOnFeedSwitch")),
      refreshOnStartup: store.get("refreshOnStartup") !== false,
      retentionDays: store.get("retentionDays") ?? 60,
      pollIntervalMinutes: store.get("pollIntervalMinutes") ?? 30,
      imageVaultEnabled: store.get("imageVaultEnabled") !== false,
      autoFullText: Boolean(store.get("autoFullText")),
      minPublishDate: store.get("minPublishDate") || null,
      forceMinDate: Boolean(store.get("forceMinDate")),
      columnOrder: store.get("columnOrder") || ["status", "star", "title", "feed", "date", "author", "tags"],
      columnWidths: store.get("columnWidths") || { status: 28, star: 28, title: 0, feed: 140, date: 120, author: 100, tags: 100 },
      columns: store.get("columns") || { status: true, star: true, title: true, feed: true, date: true, author: true, tags: false },
      readerToolbarOrder: store.get("readerToolbarOrder") || ["star", "toggle_read", "run_plugins", "tag", "trash", "fetch_full", "copy_link", "open_url", "font_dec", "font_inc"],
      readerToolbarVisible: store.get("readerToolbarVisible") || { star: true, toggle_read: true, run_plugins: true, tag: true, trash: true, fetch_full: true, copy_link: true, open_url: true, font_dec: true, font_inc: true },
      readerToolbarMode: store.get("readerToolbarMode") || "both",
      tagsPosition: store.get("tagsPosition") || "bottom",
      tagsPaneHeight: store.get("tagsPaneHeight") ?? 140,
      treeWidth: store.get("treeWidth") ?? 240,
      listHeight: store.get("listHeight") ?? 45,
    };
  };

  proto.bindSettings = function () {
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
          const settingsPayload = this.buildFullSettingsPayload();
          await api.updateUserSettings(settingsPayload);
        } catch (_) {}
      }, 500);
    };

    // Appearance & Typography changes
    const themeSelect = document.getElementById("select-setting-theme");
    if (themeSelect) {
      themeSelect.addEventListener("change", (e) => {
        store.set("theme", e.target.value);
        document.documentElement.setAttribute("data-theme", e.target.value);
      });
    }

    const fontFamilySelect = document.getElementById("select-setting-font-family");
    if (fontFamilySelect) {
      fontFamilySelect.addEventListener("change", (e) => {
        store.set("fontFamily", e.target.value);
        window.dispatchEvent(new CustomEvent("omnirss:typography-changed"));
      });
    }

    const tzSelect = document.getElementById("select-setting-timezone");
    if (tzSelect) {
      tzSelect.addEventListener("change", (e) => {
        store.set("timezone", e.target.value);
        window.dispatchEvent(new CustomEvent("omnirss:save-settings-debounced"));
        if (this.listView) this.listView.render();
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
        minPublishDate = "all";
      } else if (["today", "7days", "30days", "90days"].includes(minDateVal)) {
        minPublishDate = minDateVal;
      } else if (minDateVal === "custom") {
        if (customMinDateInput?.value) {
          minPublishDate = customMinDateInput.value;
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

    // Modern 1-Click OPML Import
    const btnTriggerImport = document.getElementById("btn-trigger-import-opml") || document.getElementById("btn-import-opml");
    const fileInput = document.getElementById("input-opml-file");

    if (btnTriggerImport && fileInput) {
      btnTriggerImport.addEventListener("click", () => {
        fileInput.click();
      });

      fileInput.addEventListener("change", async () => {
        if (!fileInput.files || fileInput.files.length === 0) return;
        const file = fileInput.files[0];
        window.dispatchEvent(
          new CustomEvent("omnirss:toast", {
            detail: { message: t("settings.opml_importing") || "正在匯入 OPML 檔案...", type: "info" },
          })
        );

        try {
          const result = await api.importOpml(file);
          const count = result.imported_count || result.imported_feeds || 0;
          this.closeModal("modal-settings");
          window.dispatchEvent(
            new CustomEvent("omnirss:toast", {
              detail: { message: t("settings.opml_import_success", { count }), type: "success" },
            })
          );
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
        } catch (err) {
          window.dispatchEvent(
            new CustomEvent("omnirss:toast", {
              detail: { message: t("settings.opml_import_failed", { error: err.message }), type: "error" },
            })
          );
        } finally {
          fileInput.value = "";
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

    // Danger Zone: Purge Database & All Caches
    const btnPurgeDatabase = document.getElementById("btn-purge-database");
    if (btnPurgeDatabase) {
      btnPurgeDatabase.addEventListener("click", async () => {
        const confirmMsg = t("settings.confirm_purge_database") || "⚠️ 警告：確定要徹底清空資料庫與所有快取嗎？此操作將永久移除所有訂閱來源、歷史文章、自訂標籤與圖片快取，且完全無法復原！";
        if (!confirm(confirmMsg)) return;

        const typedConfirm = prompt(t("settings.prompt_purge_confirm") || "請輸入「PURGE」以確認清空資料庫：");
        if (typedConfirm !== "PURGE" && typedConfirm !== "purge") {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.purge_cancelled") || "已取消清空操作", type: "info" } }));
          return;
        }

        try {
          const res = await api.purgeDatabase();
          store.update({
            articles: [],
            selectedArticle: null,
            feeds: [],
            categories: [],
            tags: [],
            unreadCount: 0,
            starredCount: 0,
            trashCount: 0,
            totalArticlesCount: 0,
            activeFilter: "all",
            activeFeedId: null,
            activeCategoryId: null,
            activeTagId: null,
            activeTag: null,
          });
          this.closeModal("modal-settings");
          const successMsg = (res && res.message) ? res.message : (t("settings.purge_success") || "🔥 資料庫與快取已徹底清空");
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: successMsg, type: "success" } }));
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
          window.dispatchEvent(new CustomEvent("omnirss:filter-changed"));
        } catch (err) {
          const errMsg = err.detail || err.message;
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.purge_failed", { error: errMsg }) || `清空失敗: ${errMsg}`, type: "error" } }));
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
              minPublishDate = "all";
            } else if (["today", "7days", "30days", "90days"].includes(minDateVal)) {
              minPublishDate = minDateVal;
            } else if (minDateVal === "custom" && customMinDateInput?.value) {
              minPublishDate = customMinDateInput.value;
            }
            store.set("minPublishDate", minPublishDate);
          }

          const forceMinDateCb = document.getElementById("checkbox-setting-force-min-date");
          if (forceMinDateCb) store.set("forceMinDate", forceMinDateCb.checked);

          const vaultCheck = document.getElementById("checkbox-image-vault");
          if (vaultCheck) store.set("imageVaultEnabled", vaultCheck.checked);

          // 2. 組裝完整核心設定 Payload 並同步至後端
          const settingsPayload = this.buildFullSettingsPayload();
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
  };
}
