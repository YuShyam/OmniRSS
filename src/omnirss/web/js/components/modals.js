/**
 * OmniRSS 彈窗對話框與設定中心元件 (Modals & Dialog Controller).
 *
 * Manages modal lifecycles for Add Feed, Add Folder, Rule Manager,
 * Plugin Observability Dashboard, Tabbed Settings, and Authentication.
 */

import { store } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";

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
      const closeBtn = e.target.closest(".modal-close-btn, .btn-modal-cancel");
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

    this.bindAddFeed();
    this.bindAddCategory();
    this.bindCategorySettings();
    this.bindRules();
    this.bindPlugins();
    this.bindSettings();
    this.bindAuth();
  }

  openModal(modalId) {
    const el = document.getElementById(modalId);
    if (el) el.classList.add("open");
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
          catSelect.innerHTML = `<option value="">未分類</option>` +
            categories.map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
        }
        this.openModal("modal-add-feed");
      });
    }

    const form = document.getElementById("form-add-feed");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const url = document.getElementById("input-feed-url").value.trim();
      const catId = document.getElementById("select-feed-category").value || null;
      const customTitle = document.getElementById("input-feed-title").value.trim() || null;
      const requiresFlareSolverr = Boolean(document.getElementById("checkbox-feed-flaresolverr")?.checked);

      if (!url) return;

      try {
        await api.addFeed(url, catId ? parseInt(catId, 10) : null, customTitle, requiresFlareSolverr);
        form.reset();
        this.closeModal("modal-add-feed");
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "訂閱源新增成功", type: "success" } }));
        window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
      } catch (err) {
        alert(`新增失敗: ${err.message}`);
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
      const name = document.getElementById("input-category-name").value.trim();
      if (!name) return;

      try {
        await api.createCategory(name);
        form.reset();
        this.closeModal("modal-add-category");
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "分類建立成功", type: "success" } }));
        window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
      } catch (err) {
        alert(`建立失敗: ${err.message}`);
      }
    });
  }

  // 2.5 Category Settings
  openCategorySettings(categoryData) {
    if (!categoryData) return;
    const { id, name } = categoryData;
    const idInput = document.getElementById("input-cat-settings-id");
    const nameInput = document.getElementById("input-cat-settings-name");
    const retentionSelect = document.getElementById("select-cat-retention");
    if (idInput) idInput.value = id;
    if (nameInput) nameInput.value = name;

    const categories = store.get("categories") || [];
    const currentCat = categories.find((c) => c.id === id);
    if (retentionSelect && currentCat) {
      retentionSelect.value = currentCat.custom_retention_days !== null && currentCat.custom_retention_days !== undefined
        ? String(currentCat.custom_retention_days)
        : "";
    }

    this.openModal("modal-category-settings");
  }

  bindCategorySettings() {
    const form = document.getElementById("form-category-settings");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const id = parseInt(document.getElementById("input-cat-settings-id").value, 10);
      const name = document.getElementById("input-cat-settings-name").value.trim();
      const retentionVal = document.getElementById("select-cat-retention").value;
      const customRetentionDays = retentionVal === "" ? null : parseInt(retentionVal, 10);

      if (!id || !name) return;

      try {
        await api.updateCategory(id, {
          name,
          custom_retention_days: customRetentionDays,
        });
        this.closeModal("modal-category-settings");
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "分類設定已更新", type: "success" } }));
        window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
      } catch (err) {
        alert(`更新分類失敗: ${err.message}`);
      }
    });

    const deleteBtn = document.getElementById("btn-delete-current-category");
    if (deleteBtn) {
      deleteBtn.addEventListener("click", async () => {
        const id = parseInt(document.getElementById("input-cat-settings-id").value, 10);
        const name = document.getElementById("input-cat-settings-name").value.trim();
        if (!id) return;

        if (window.confirm(`確定要刪除分類「${name}」嗎？其下的訂閱源將自動保留並轉為未分類。`)) {
          try {
            await api.deleteCategory(id);
            this.closeModal("modal-category-settings");
            window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "已成功刪除分類", type: "success" } }));
            window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
          } catch (err) {
            alert(`刪除分類失敗: ${err.message}`);
          }
        }
      });
    }
  }

  // 3. Rules Manager
  bindRules() {
    const btnOpen = document.getElementById("btn-open-rules");
    if (btnOpen) {
      btnOpen.addEventListener("click", async () => {
        await this.loadRulesList();
        this.openModal("modal-rules");
      });
    }

    const form = document.getElementById("form-add-rule");
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const name = document.getElementById("input-rule-name").value.trim();
        const field = document.getElementById("select-rule-field").value;
        const operator = document.getElementById("select-rule-op").value;
        const value = document.getElementById("input-rule-val").value.trim();
        const actionType = document.getElementById("select-rule-action").value;

        const rulePayload = {
          name,
          sort_order: 10,
          is_enabled: true,
          conditions: [{ field, operator, value }],
          actions: [{ action_type: actionType, parameters: {} }],
        };

        try {
          await api.createRule(rulePayload);
          form.reset();
          await this.loadRulesList();
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "過濾規則新增成功", type: "success" } }));
        } catch (err) {
          alert(`新增規則失敗: ${err.message}`);
        }
      });
    }
  }

  async loadRulesList() {
    const listEl = document.getElementById("rules-list-container");
    if (!listEl) return;

    try {
      const rules = await api.getRules();
      if (!rules || rules.length === 0) {
        listEl.innerHTML = `<div class="text-muted" style="font-size: 12px; padding: 10px 0;">目前尚未設定任何自訂過濾規則</div>`;
        return;
      }

      listEl.innerHTML = rules.map((r) => {
        const priority = r.sort_order ?? r.priority ?? 0;
        return `
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 8px; background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 4px; margin-bottom: 6px;">
          <div>
            <strong>${r.name}</strong>
            <span class="text-muted" style="font-size: 11px; margin-left: 6px;">(優先級: ${priority})</span>
          </div>
          <button class="btn btn-danger btn-delete-rule" data-id="${r.id}" style="padding: 2px 8px; font-size: 11px;">刪除</button>
        </div>
      `;
      }).join("");

      listEl.querySelectorAll(".btn-delete-rule").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.dataset.id;
          await api.deleteRule(id);
          await this.loadRulesList();
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
        gridEl.innerHTML = `<div class="empty-state">尚無已掛載的外掛套件</div>`;
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
            <div class="text-muted" style="font-size: 12px;">${p.description || "無描述"}</div>
            <div class="plugin-telemetry" style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; font-size: 11px;">
              <span class="telemetry-item">⚡ 耗時: <strong>${avgMs}ms</strong></span>
              <span class="telemetry-item">🔄 次數: <strong>${runs}</strong></span>
              <span class="telemetry-item">🎯 成功率: <strong style="color: ${successRate > 90 ? 'var(--accent-green, #4ade80)' : 'var(--accent-red, #f87171)'}">${successRate}%</strong></span>
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
                <summary style="cursor: pointer; color: var(--accent-red, #f87171);">⚠️ 檢視最後錯誤堆疊 (Traceback)</summary>
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
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "外掛狀態已更新", type: "success" } }));
        });
      });

      // Circuit Reset
      gridEl.querySelectorAll(".btn-reset-circuit").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.dataset.id;
          await api.resetPluginCircuit(id);
          await this.loadPluginsList();
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "熔斷狀態已重置", type: "success" } }));
        });
      });
    } catch (_) {}
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
      });
    });

    const btnOpen = document.getElementById("btn-open-settings");
    if (btnOpen) {
      btnOpen.addEventListener("click", () => {
        const user = store.get("user");
        const keyInput = document.getElementById("input-api-key");
        if (keyInput && user) {
          keyInput.value = user.api_key || "";
        }

        // Sync form controls from store
        const themeSelect = document.getElementById("select-setting-theme");
        if (themeSelect) themeSelect.value = store.get("theme") || "dark";

        const fontSelect = document.getElementById("select-setting-font-size");
        if (fontSelect) fontSelect.value = store.get("fontSize") || "medium";

        const delaySelect = document.getElementById("select-setting-read-delay");
        if (delaySelect) delaySelect.value = String(store.get("readDelaySec") ?? 3);

        const hideEmptyCheck = document.getElementById("checkbox-hide-empty");
        if (hideEmptyCheck) hideEmptyCheck.checked = Boolean(store.get("hideEmptyFeeds"));

        const retentionSelect = document.getElementById("select-setting-retention");
        if (retentionSelect) retentionSelect.value = String(store.get("retentionDays") ?? 60);

        const pollSelect = document.getElementById("select-setting-poll-interval");
        if (pollSelect) pollSelect.value = String(store.get("pollIntervalMinutes") ?? 30);

        const vaultCheck = document.getElementById("checkbox-image-vault");
        if (vaultCheck) vaultCheck.checked = store.get("imageVaultEnabled") !== false;

        this.openModal("modal-settings");
      });
    }

    const saveSettingsToBackend = () => {
      clearTimeout(this._saveSettingsTimer);
      this._saveSettingsTimer = setTimeout(async () => {
        try {
          const settingsPayload = {
            theme: store.get("theme") || "dark",
            fontSize: store.get("fontSize") || "medium",
            readDelaySec: store.get("readDelaySec") ?? 3,
            hideEmptyFeeds: Boolean(store.get("hideEmptyFeeds")),
            retentionDays: store.get("retentionDays") ?? 60,
            pollIntervalMinutes: store.get("pollIntervalMinutes") ?? 30,
            imageVaultEnabled: store.get("imageVaultEnabled") !== false,
          };
          await api.updateUserSettings(settingsPayload);
        } catch (_) {}
      }, 500);
    };

    // Appearance changes
    const themeSelect = document.getElementById("select-setting-theme");
    if (themeSelect) {
      themeSelect.addEventListener("change", (e) => {
        store.set("theme", e.target.value);
        document.documentElement.setAttribute("data-theme", e.target.value);
        saveSettingsToBackend();
      });
    }

    const fontSelect = document.getElementById("select-setting-font-size");
    if (fontSelect) {
      fontSelect.addEventListener("change", (e) => {
        store.set("fontSize", e.target.value);
        window.dispatchEvent(new CustomEvent("omnirss:font-size-changed", { detail: { size: e.target.value } }));
        saveSettingsToBackend();
      });
    }

    // Reading Behavior changes
    const delaySelect = document.getElementById("select-setting-read-delay");
    if (delaySelect) {
      delaySelect.addEventListener("change", (e) => {
        store.set("readDelaySec", parseInt(e.target.value, 10));
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "已更新閱讀已讀延遲設定", type: "success" } }));
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

    // Schedule & Retention changes
    const retentionSelect = document.getElementById("select-setting-retention");
    if (retentionSelect) {
      retentionSelect.addEventListener("change", (e) => {
        store.set("retentionDays", parseInt(e.target.value, 10));
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "已更新文章保留天數設定", type: "success" } }));
        saveSettingsToBackend();
      });
    }

    const pollSelect = document.getElementById("select-setting-poll-interval");
    if (pollSelect) {
      pollSelect.addEventListener("change", (e) => {
        store.set("pollIntervalMinutes", parseInt(e.target.value, 10));
        window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "已更新排程抓取間隔設定", type: "success" } }));
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
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "OPML 匯出完成", type: "success" } }));
        } catch (err) {
          alert(`匯出失敗: ${err.message}`);
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
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: `匯入成功: 新增 ${count} 個頻道`, type: "success" } }));
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
        } catch (err) {
          alert(`匯入失敗: ${err.message}`);
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
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "已清空所有訂閱來源", type: "success" } }));
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
        } catch (err) {
          alert(`清空失敗: ${err.message}`);
        }
      });
    }

    // API Key copy & regen
    const btnRegenKey = document.getElementById("btn-regen-key");
    if (btnRegenKey) {
      btnRegenKey.addEventListener("click", async () => {
        if (!confirm("確定要重新產生 API Key 嗎？舊金鑰將立即失效！")) return;
        try {
          const res = await api.regenerateApiKey();
          const keyInput = document.getElementById("input-api-key");
          if (keyInput) keyInput.value = res.api_key;
          const user = store.get("user");
          if (user) user.api_key = res.api_key;
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "API Key 已更新", type: "success" } }));
        } catch (err) {
          alert(`生成失敗: ${err.message}`);
        }
      });
    }

    const btnCopyKey = document.getElementById("btn-copy-key");
    if (btnCopyKey) {
      btnCopyKey.addEventListener("click", () => {
        const keyInput = document.getElementById("input-api-key");
        if (keyInput && keyInput.value) {
          navigator.clipboard.writeText(keyInput.value);
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("settings.copied"), type: "success" } }));
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
            errEl.textContent = err.message || "登入失敗";
            errEl.style.display = "block";
          }
        }
      });
    }
  }
}
