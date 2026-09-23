/**
 * OmniRSS 彈窗對話框與設定中心元件 (Modals & Dialog Controller).
 *
 * Manages modal lifecycles for Add Feed, Add Folder, Rule Manager,
 * Plugin Observability Dashboard, OPML Import/Export, and Settings.
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

    this.bindAddFeed();
    this.bindAddCategory();
    this.bindRules();
    this.bindPlugins();
    this.bindOpml();
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
    const form = document.getElementById("form-add-feed");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const url = document.getElementById("input-feed-url").value.trim();
      const catId = document.getElementById("select-feed-category").value || null;
      const customTitle = document.getElementById("input-feed-title").value.trim() || null;

      if (!url) return;

      try {
        await api.addFeed(url, catId ? parseInt(catId, 10) : null, customTitle);
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
          priority: 10,
          is_active: true,
          stop_processing: false,
          conditions: {
            logic: "AND",
            rules: [{ field, operator, value }],
          },
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

      listEl.innerHTML = rules.map((r) => `
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 8px; background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 4px; margin-bottom: 6px;">
          <div>
            <strong>${r.name}</strong>
            <span class="text-muted" style="font-size: 11px; margin-left: 6px;">(優先級: ${r.priority})</span>
          </div>
          <button class="btn btn-danger btn-delete-rule" data-id="${r.id}" style="padding: 2px 8px; font-size: 11px;">刪除</button>
        </div>
      `).join("");

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
        const isTripped = p.circuit_status && p.circuit_status.is_tripped;
        const avgMs = p.telemetry ? Math.round(p.telemetry.avg_execution_ms || 0) : 0;
        const runs = p.telemetry ? p.telemetry.total_runs || 0 : 0;

        return `
          <div class="plugin-card">
            <div class="plugin-card-header">
              <div class="plugin-card-title">
                <span>${p.name}</span>
                <span class="plugin-slot-badge">${p.slot_type}</span>
                ${isTripped ? `<span class="tripped-badge">${t("plugins.tripped")}</span>` : ""}
              </div>
              <label class="plugin-switch">
                <input type="checkbox" class="plugin-toggle-checkbox" data-id="${p.id}" ${p.is_enabled ? "checked" : ""}/>
                <span class="switch-slider"></span>
              </label>
            </div>
            <div class="text-muted" style="font-size: 12px;">${p.description || "無描述"}</div>
            <div class="plugin-telemetry">
              <span class="telemetry-item">⚡ 平均耗時: <strong>${avgMs}ms</strong></span>
              <span class="telemetry-item">🔄 執行次數: <strong>${runs}</strong></span>
              ${
                isTripped
                  ? `<button class="btn btn-reset-circuit" data-id="${p.id}" style="padding: 1px 6px; font-size: 10px;">${t("plugins.reset_circuit")}</button>`
                  : ""
              }
            </div>
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

  // 5. OPML Import/Export
  bindOpml() {
    const btnOpen = document.getElementById("btn-open-opml");
    if (btnOpen) {
      btnOpen.addEventListener("click", () => this.openModal("modal-opml"));
    }

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
        } catch (err) {
          alert(`匯出失敗: ${err.message}`);
        }
      });
    }

    const formImport = document.getElementById("form-import-opml");
    if (formImport) {
      formImport.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fileInput = document.getElementById("input-opml-file");
        if (!fileInput.files || fileInput.files.length === 0) return;

        try {
          const result = await api.importOpml(fileInput.files[0]);
          this.closeModal("modal-opml");
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: `匯入成功: 新增 ${result.imported_feeds} 個頻道`, type: "success" } }));
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
        } catch (err) {
          alert(`匯入失敗: ${err.message}`);
        }
      });
    }
  }

  // 6. Settings & API Key
  bindSettings() {
    const btnOpen = document.getElementById("btn-open-settings");
    if (btnOpen) {
      btnOpen.addEventListener("click", () => {
        const user = store.get("user");
        const keyInput = document.getElementById("input-api-key");
        if (keyInput && user) {
          keyInput.value = user.api_key || "";
        }
        this.openModal("modal-settings");
      });
    }

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

  // 7. Auth Login Modal
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
