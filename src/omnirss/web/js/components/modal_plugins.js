/**
 * OmniRSS 外掛管理與遙測監控對話框模組 (Plugin Management Center Modal Module).
 */

import { store, safeInputVal } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";
import { parseUtcDate } from "../date_utils.js";
import { OFFICIAL_GEMINI_PRESETS } from "../plugin_registry.js";

export { OFFICIAL_GEMINI_PRESETS };

export function registerPluginsModal(proto) {
  // 4. Plugin Management Center
  proto.bindPlugins = function () {
    const btnOpen = document.getElementById("btn-open-plugins");
    if (btnOpen) {
      btnOpen.addEventListener("click", async () => {
        await this.loadPluginsList();
        this.openModal("modal-plugins");
      });
    }

    // 監聽外掛遙測或設定變更事件，若面板開啟則實時刷新
    window.addEventListener("omnirss:plugins-updated", async () => {
      const modal = document.getElementById("modal-plugins");
      if (modal && modal.classList.contains("active")) {
        await this.loadPluginsList();
      }
    });
  };

  proto.loadPluginsList = async function () {
    const gridEl = document.getElementById("plugin-grid-container");
    if (!gridEl) return;

    const resolveI18nText = (field) => {
      if (!field) return "";
      if (typeof field === "object") {
        const lang = store.get("lang") || "zh-TW";
        return field[lang] || field["zh-TW"] || field["en-US"] || field["en"] || Object.values(field)[0] || "";
      }
      return String(field);
    };

    try {
      const plugins = await api.getPlugins();
      if (!plugins || plugins.length === 0) {
        gridEl.innerHTML = `<div class="empty-state" style="padding: 24px; text-align: center; color: var(--text-muted);">${t("plugins.no_plugins")}</div>`;
        return;
      }

      store.set("plugins", plugins);

      gridEl.innerHTML = plugins.map((p) => {
        const pId = p.plugin_id || p.id;
        const pName = resolveI18nText(p.name) || pId;
        const pDesc = resolveI18nText(p.description) || t("plugins.no_description");
        const slotLabel = t("plugins.slot_" + p.slot_type) || p.slot_type;
        const isTripped = Boolean(p.is_tripped || (p.circuit_status && p.circuit_status.is_tripped));
        const avgMs = Math.round(p.avg_duration_ms || (p.telemetry ? p.telemetry.avg_execution_ms : 0) || 0);
        const runs = p.total_runs || (p.telemetry ? p.telemetry.total_runs : 0) || 0;
        const successRuns = p.success_runs || (p.telemetry ? p.telemetry.success_runs : 0) || 0;
        const successRate = runs > 0 ? Math.round((successRuns / runs) * 100) : null;
        const tb = p.last_error_traceback || (p.telemetry ? p.telemetry.last_error_traceback : "") || "";
        const hasConfig = Boolean(p.config_schema && Object.keys(p.config_schema.properties || {}).length > 0) || Boolean(p.default_config && Object.keys(p.default_config).length > 0);

        return `
          <div class="plugin-card" style="background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px; margin-bottom: 12px; display: flex; flex-direction: column; gap: 8px;">
            <div class="plugin-card-header" style="display: flex; align-items: center; justify-content: space-between;">
              <div class="plugin-card-title" style="display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 13px; color: var(--text-primary);">
                <span>${this.escape(pName)}</span>
                <span class="badge-role-pill user" style="font-size: 10px; padding: 1px 6px;">${slotLabel}</span>
                ${isTripped ? `<span class="badge-role-pill admin" style="background: rgba(239, 68, 68, 0.15); color: #ef4444; border-color: rgba(239, 68, 68, 0.3); font-size: 10px;">${t("plugins.tripped")}</span>` : ""}
              </div>
              <label class="plugin-switch-box" style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer; user-select: none;">
                <span class="plugin-status-text" style="font-size: 11px; font-weight: 600; color: ${p.is_enabled ? 'var(--accent-primary, #60a5fa)' : 'var(--text-muted, #646d7e)'};">${p.is_enabled ? (t("plugins.status_enabled") || "啟用中") : (t("plugins.status_disabled") || "已停用")}</span>
                <input type="checkbox" class="plugin-toggle-checkbox" data-id="${pId}" data-name="${this.escape(pName)}" ${p.is_enabled ? "checked" : ""} style="accent-color: var(--accent-primary); width: 16px; height: 16px; cursor: pointer;" />
              </label>
            </div>
            <div class="text-muted" style="font-size: 12px; color: var(--text-muted); line-height: 1.4;">${this.escape(pDesc)}</div>
            <div class="plugin-telemetry" style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-top: 4px; font-size: 11px; border-top: 1px solid var(--border-color-subtle, rgba(255,255,255,0.05)); padding-top: 8px;">
              <div style="display: flex; align-items: center; gap: 10px; color: var(--text-secondary);">
                <span>⏱️ ${avgMs}ms</span>
                <span>⚡ ${runs} ${t("plugins.runs") || "次執行"}</span>
                <span>🎯 ${t("plugins.success_rate") || "成功率"} <strong style="color: ${successRate !== null ? (successRate > 90 ? 'var(--accent-green, #4ade80)' : 'var(--accent-red, #f87171)') : 'var(--text-muted)'}">${successRate !== null ? successRate + '%' : '-'}</strong></span>
              </div>
              <div style="display: flex; align-items: center; gap: 6px;">
                <button type="button" class="btn btn-sm btn-secondary btn-plugin-logs" data-id="${pId}" data-name="${this.escape(pName)}" style="font-size: 11px; padding: 2px 8px; height: 26px;">📜 ${t("plugins.btn_logs") || "執行日誌"}</button>
                ${
                  p.slot_type === "processor"
                    ? `<button type="button" class="btn btn-sm btn-secondary btn-batch-apply" data-id="${pId}" data-name="${this.escape(pName)}" title="將此外掛重新套用至現存所有符合網址之文章" style="font-size: 11px; padding: 2px 8px; height: 26px;">⚡ 重新套用</button>`
                    : ""
                }
                ${
                  hasConfig
                    ? `<button type="button" class="btn btn-sm btn-secondary btn-plugin-config" data-id="${pId}" style="font-size: 11px; padding: 2px 8px; height: 26px;">${t("plugins.btn_config") || "⚙️ 設定"}</button>`
                    : ""
                }
                ${
                  isTripped
                    ? `<button type="button" class="btn btn-sm btn-danger btn-reset-circuit" data-id="${pId}" style="font-size: 11px; padding: 2px 8px; height: 26px;">${t("plugins.reset_circuit")}</button>`
                    : ""
                }
              </div>
            </div>
            ${
              tb
                ? `
              <details style="margin-top: 4px; font-size: 11px; background: rgba(0,0,0,0.25); border-radius: 4px; padding: 4px 8px;">
                <summary style="cursor: pointer; color: var(--accent-red, #f87171); font-weight: 500;">${t("plugins.traceback_title") || "檢視崩潰堆疊 (Traceback)"}</summary>
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
          const name = cb.dataset.name || id;
          const isChecked = cb.checked;
          try {
            await api.togglePlugin(id, isChecked);
            const statusText = cb.parentElement.querySelector(".plugin-status-text");
            if (statusText) {
              statusText.textContent = isChecked ? (t("plugins.status_enabled") || "啟用中") : (t("plugins.status_disabled") || "已停用");
              statusText.style.color = isChecked ? "var(--accent-primary, #60a5fa)" : "var(--text-muted, #646d7e)";
            }
            // 同步全域快取
            const curPlugins = store.get("plugins") || [];
            const targetP = curPlugins.find((x) => (x.plugin_id || x.id) === id);
            if (targetP) {
              targetP.is_enabled = isChecked;
              store.set("plugins", [...curPlugins]);
            }
            window.dispatchEvent(new CustomEvent("omnirss:plugins-updated"));

            const toastMsg = isChecked
              ? (t("plugins.toggle_on_toast", { name }) || `已開啟「${name}」外掛`)
              : (t("plugins.toggle_off_toast", { name }) || `已停用「${name}」外掛`);
            window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: toastMsg, type: isChecked ? "success" : "info" } }));
          } catch (err) {
            cb.checked = !isChecked; // 失敗回滾
            window.dispatchEvent(
              new CustomEvent("omnirss:toast", {
                detail: {
                  message: `${t("plugins.toggle_failed") || "切換失敗"}: ${err.message}`,
                  type: "error",
                },
              })
            );
          }
        });
      });

      // Batch Apply Button Trigger
      gridEl.querySelectorAll(".btn-batch-apply").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.dataset.id;
          const name = btn.dataset.name || id;
          const origText = btn.innerHTML;
          btn.disabled = true;
          btn.innerHTML = "⏳ 套用中...";
          try {
            const res = await api.batchApplyPlugin(id);
            window.dispatchEvent(
              new CustomEvent("omnirss:toast", {
                detail: {
                  message: `⚡ ${name}: ${res.message || "批次套用完成"}`,
                  type: "success",
                },
              })
            );
            await this.loadPluginsList();
            window.dispatchEvent(new CustomEvent("omnirss:filter-changed"));
          } catch (err) {
            window.dispatchEvent(
              new CustomEvent("omnirss:toast", {
                detail: {
                  message: `批次套用失敗: ${err.message}`,
                  type: "error",
                },
              })
            );
          } finally {
            btn.disabled = false;
            btn.innerHTML = origText;
          }
        });
      });

      // Circuit Reset
      gridEl.querySelectorAll(".btn-reset-circuit").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.dataset.id;
          await api.resetPluginCircuit(id);
          await this.loadPluginsList();
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("plugins.circuit_reset"), type: "success" } }));
        });
      });

      // Plugin Execution Logs Trigger
      gridEl.querySelectorAll(".btn-plugin-logs").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.dataset.id;
          const name = btn.dataset.name || id;
          this.openPluginLogsModal(id, name);
        });
      });

      // Plugin Config Dialog Trigger
      gridEl.querySelectorAll(".btn-plugin-config").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.dataset.id;
          const targetPlugin = plugins.find((p) => (p.plugin_id || p.id) === id);
          if (targetPlugin) {
            this.openPluginConfigModal(targetPlugin);
          }
        });
      });
    } catch (_) {}
  };

  proto.openPluginLogsModal = async function (pluginId, pluginName) {
    const modal = document.getElementById("modal-plugin-logs");
    const titleEl = document.getElementById("plugin-logs-modal-title");
    const container = document.getElementById("plugin-logs-container");
    const countEl = document.getElementById("plugin-logs-count-summary");
    const refreshBtn = document.getElementById("btn-refresh-plugin-logs");
    const clearBtn = document.getElementById("btn-clear-plugin-logs");
    const closeBtn = document.getElementById("btn-close-plugin-logs");
    if (!modal || !container) return;

    if (titleEl) titleEl.textContent = `📜 外掛執行日誌: ${pluginName}`;
    this.openModal("modal-plugin-logs");

    const renderLogs = async () => {
      container.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--text-muted);">正在載入日誌紀錄...</div>`;
      if (countEl) countEl.textContent = "載入中...";
      try {
        const logs = await api.getPluginLogs(pluginId, 100);
        if (countEl) countEl.textContent = `共 ${logs ? logs.length : 0} 筆歷史紀錄（保留最近 200 筆）`;

        if (!logs || logs.length === 0) {
          container.innerHTML = `
            <div style="text-align: center; padding: 36px 20px; color: var(--text-muted); background: var(--bg-surface); border: 1px dashed var(--border-color); border-radius: 8px;">
              <div style="font-size: 24px; margin-bottom: 8px;">📭</div>
              <div>尚無任何執行日誌記錄</div>
              <div style="font-size: 11px; margin-top: 4px; opacity: 0.7;">當此外掛被手動或規則觸發時，即時活動將記錄於此。</div>
            </div>
          `;
          return;
        }

        container.innerHTML = logs.map((log) => {
          const isSuccess = log.status === "success";
          const isTimeout = log.status === "timeout";
          const statusBg = isSuccess ? "rgba(34, 197, 94, 0.15)" : isTimeout ? "rgba(234, 179, 8, 0.15)" : "rgba(239, 68, 68, 0.15)";
          const statusColor = isSuccess ? "#4ade80" : isTimeout ? "#facc15" : "#f87171";
          const statusText = isSuccess ? "🟢 成功" : isTimeout ? "⏳ 逾時" : "🔴 失敗";
          const sourceText = log.trigger_source === "rule" ? "🤖 規則自動" : log.trigger_source === "star" ? "⭐ 星標自動" : log.trigger_source === "feed_crawl" ? "📡 頻道自動" : "👆 手動點擊";

          let localTimeStr = "";
          try {
            const dt = parseUtcDate(log.executed_at);
            const y = dt.getFullYear();
            const m = String(dt.getMonth() + 1).padStart(2, "0");
            const d = String(dt.getDate()).padStart(2, "0");
            const hh = String(dt.getHours()).padStart(2, "0");
            const mm = String(dt.getMinutes()).padStart(2, "0");
            const ss = String(dt.getSeconds()).padStart(2, "0");
            localTimeStr = `${y}-${m}-${d} ${hh}:${mm}:${ss}`;
          } catch (_) {
            localTimeStr = log.executed_at;
          }

          return `
            <div style="background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 6px; padding: 10px 12px; font-size: 12px; display: flex; flex-direction: column; gap: 6px;">
              <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span style="background: ${statusBg}; color: ${statusColor}; font-weight: 600; font-size: 11px; padding: 1px 6px; border-radius: 4px;">${statusText}</span>
                  <span style="font-size: 11px; color: var(--text-muted);" title="UTC: ${this.escape(log.executed_at)}">${this.escape(localTimeStr)}</span>
                  <span style="font-size: 11px; background: var(--bg-hover); padding: 1px 6px; border-radius: 4px; color: var(--text-secondary);">${sourceText}</span>
                  ${log.action_param ? `<span style="font-size: 11px; color: var(--accent-primary);">[${this.escape(log.action_param)}]</span>` : ""}
                </div>
                <div style="font-size: 11px; font-weight: 600; color: var(--text-secondary);">
                  ⏱️ ${log.duration_ms}ms
                </div>
              </div>
              ${log.article_title ? `<div style="font-weight: 500; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">📰 ${this.escape(log.article_title)}</div>` : ""}
              ${
                log.output_preview
                  ? `
                <div style="background: rgba(0,0,0,0.2); border-left: 2px solid #4ade80; padding: 6px 10px; font-size: 11px; color: var(--text-secondary); border-radius: 0 4px 4px 0; white-space: pre-wrap; line-height: 1.4; max-height: 90px; overflow-y: auto;">${this.escape(log.output_preview)}</div>
              `
                  : ""
              }
              ${
                log.error_message
                  ? `
                <div style="background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 4px; padding: 6px 10px; font-size: 11px; color: #fca5a5;">
                  <div style="font-weight: 600; margin-bottom: 2px;">⚠️ 錯誤原因: ${this.escape(log.error_message)}</div>
                  ${log.error_traceback ? `<details style="margin-top: 4px;"><summary style="cursor: pointer; color: #f87171; font-size: 10px;">檢視詳細例外堆疊 (Traceback)</summary><pre style="white-space: pre-wrap; font-size: 10px; margin-top: 4px; max-height: 140px; overflow-y: auto; color: #fecaca;">${this.escape(log.error_traceback)}</pre></details>` : ""}
                </div>
              `
                  : ""
              }
            </div>
          `;
        }).join("");
      } catch (err) {
        container.innerHTML = `<div style="padding: 20px; text-align: center; color: var(--accent-red);">載入日誌失敗: ${this.escape(err.message)}</div>`;
      }
    };

    if (refreshBtn) {
      refreshBtn.onclick = () => renderLogs();
    }

    if (clearBtn) {
      clearBtn.onclick = async () => {
        if (confirm(`確定要清空「${pluginName}」的所有執行日誌與執行記錄嗎？`)) {
          await api.clearPluginLogs(pluginId);
          await renderLogs();
          await this.loadPluginsList();
          window.dispatchEvent(new CustomEvent("omnirss:plugins-updated"));
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: "已清空日誌與執行指標記錄", type: "info" } }));
        }
      };
    }

    if (closeBtn) {
      closeBtn.onclick = () => this.closeModal("modal-plugin-logs");
    }

    await renderLogs();
  };

  proto.openPluginConfigModal = function (plugin) {
    const modal = document.getElementById("modal-plugin-config");
    const container = document.getElementById("plugin-config-form-container");
    const titleEl = document.getElementById("plugin-config-modal-title");
    const form = document.getElementById("form-plugin-dynamic-config");
    if (!modal || !container || !form) return;

    const resolveI18nText = (field) => {
      if (!field) return "";
      if (typeof field === "object") {
        const lang = store.get("lang") || "zh-TW";
        return field[lang] || field["zh-TW"] || field["en-US"] || field["en"] || Object.values(field)[0] || "";
      }
      return String(field);
    };

    const pId = plugin.plugin_id || plugin.id;
    const pluginName = resolveI18nText(plugin.name) || pId;
    if (titleEl) titleEl.textContent = t("plugins.config_title", { name: pluginName }) || `⚙️ 設定外掛: ${pluginName}`;

    const effectiveConfig = { ...(plugin.default_config || {}), ...(plugin.user_config || {}) };
    const modalBox = modal.querySelector(".modal-box");

    // 以 prompt_presets 能力判斷是否渲染 AI 摘要特殊設定面板（Manifest 驅動，不寫死外掛 ID）
    const hasPromptPresets = Array.isArray(effectiveConfig.prompt_presets) && effectiveConfig.prompt_presets.length > 0;
    if (hasPromptPresets) {
      this.renderGeminiPluginConfig(container, plugin, effectiveConfig, resolveI18nText, form, modal);
    } else {
      if (modalBox) modalBox.style.width = "520px";
      const schema = plugin.config_schema || { type: "object", properties: {} };
      const properties = schema.properties || {};

      let fieldsHtml = "";
      const fieldKeys = Object.keys(properties);

      if (fieldKeys.length === 0 && plugin.default_config) {
        Object.keys(plugin.default_config).forEach((k) => {
          properties[k] = { type: typeof plugin.default_config[k], title: k };
        });
      }

      Object.entries(properties).forEach(([key, prop]) => {
        const title = resolveI18nText(prop.title) || key;
        const type = prop.type || "string";
        const format = prop.format || "";
        const currentVal = effectiveConfig[key] !== undefined ? effectiveConfig[key] : (prop.default || "");
        const isPassword = key.includes("api_key") || key.includes("token") || key.includes("password") || key.includes("secret");
        
        const propDesc = resolveI18nText(prop.description);
        let descHtml = propDesc ? `<div style="color: var(--text-muted); font-size: 11px; margin-top: 3px; line-height: 1.3;">${this.escape(propDesc)}</div>` : "";

        if (prop.enum && Array.isArray(prop.enum)) {
          fieldsHtml += `
            <div class="form-group" style="margin-bottom: 12px;">
              <label class="form-label" style="font-size: 11px; margin-bottom: 4px; font-weight: 500;">${this.escape(title)}</label>
              <select class="form-select dynamic-plugin-input" name="${key}" style="height: 36px; font-size: 12px;">
                ${prop.enum.map((opt) => `<option value="${opt}" ${String(opt) === String(currentVal) ? "selected" : ""}>${this.escape(opt)}</option>`).join("")}
              </select>
              ${descHtml}
            </div>
          `;
        } else if (type === "boolean") {
          fieldsHtml += `
            <div class="form-group" style="margin-bottom: 12px;">
              <div style="display: flex; align-items: center; justify-content: space-between;">
                <label class="form-label" style="font-size: 11px; margin-bottom: 0; font-weight: 500;">${this.escape(title)}</label>
                <input type="checkbox" class="dynamic-plugin-input" name="${key}" ${Boolean(currentVal) ? "checked" : ""} style="width: 18px; height: 18px; accent-color: var(--accent-primary); cursor: pointer;" />
              </div>
              ${descHtml}
            </div>
          `;
        } else if (type === "integer" || type === "number") {
          fieldsHtml += `
            <div class="form-group" style="margin-bottom: 12px;">
              <label class="form-label" style="font-size: 11px; margin-bottom: 4px; font-weight: 500;">${this.escape(title)}</label>
              <input type="number" class="form-input dynamic-plugin-input" name="${key}" value="${this.escape(currentVal)}" ${prop.minimum !== undefined ? `min="${prop.minimum}"` : ""} ${prop.maximum !== undefined ? `max="${prop.maximum}"` : ""} style="height: 36px; font-size: 12px;" />
              ${descHtml}
            </div>
          `;
        } else if (format === "textarea" || type === "textarea") {
          fieldsHtml += `
            <div class="form-group" style="margin-bottom: 12px;">
              <label class="form-label" style="font-size: 11px; margin-bottom: 4px; font-weight: 500;">${this.escape(title)}</label>
              <textarea class="form-input dynamic-plugin-input" name="${key}" placeholder="${this.escape(propDesc || title)}" style="height: 105px; min-height: 85px; resize: vertical; font-size: 12px; font-family: inherit; line-height: 1.4; padding: 6px 8px;">${this.escape(currentVal)}</textarea>
              ${descHtml}
            </div>
          `;
        } else {
          fieldsHtml += `
            <div class="form-group" style="margin-bottom: 12px;">
              <label class="form-label" style="font-size: 11px; margin-bottom: 4px; font-weight: 500;">${this.escape(title)}</label>
              <input type="${isPassword ? "password" : "text"}" class="form-input dynamic-plugin-input" name="${key}" value="${this.escape(currentVal)}" placeholder="${this.escape(propDesc || title)}" style="height: 36px; font-size: 12px;" />
              ${descHtml}
            </div>
          `;
        }
      });

      container.innerHTML = fieldsHtml || `<div style="color: var(--text-muted); font-size: 12px; text-align: center; padding: 12px;">${t("plugins.no_custom_config") || "此外掛無需自訂參數設定"}</div>`;

      form.onsubmit = async (e) => {
        e.preventDefault();
        const updatedConfig = {};
        form.querySelectorAll(".dynamic-plugin-input").forEach((input) => {
          const name = input.name;
          if (!name) return;
          if (input.type === "checkbox") {
            updatedConfig[name] = input.checked;
          } else if (input.type === "number") {
            updatedConfig[name] = input.value ? Number(input.value) : 0;
          } else {
            updatedConfig[name] = input.value;
          }
        });

        const saveBtn = form.querySelector("button[type='submit']");
        if (saveBtn) {
          saveBtn.disabled = true;
          saveBtn.textContent = t("plugins.saving") || "儲存中...";
        }

        try {
          await api.updatePluginConfig(pId, updatedConfig);
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("plugins.save_success", { name: pluginName }) || `已成功儲存「${pluginName}」設定！`, type: "success" } }));
          this.closeModal("modal-plugin-config");
          this.closeModal("modal-plugins");
          await this.loadPluginsList();
          window.dispatchEvent(new CustomEvent("omnirss:plugins-updated"));
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("plugins.save_failed", { error: err.message }) || `儲存設定失敗: ${err.message}`, type: "error" } }));
        } finally {
          if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = t("plugins.save_config") || "儲存設定";
          }
        }
      };
    }

    const cancelBtn = document.getElementById("btn-cancel-plugin-config");
    if (cancelBtn) {
      cancelBtn.onclick = () => this.closeModal("modal-plugin-config");
    }

    this.openModal("modal-plugin-config");
  };

  proto.renderGeminiPluginConfig = function (container, plugin, effectiveConfig, resolveI18nText, form, modal) {
    const pId = plugin.plugin_id || plugin.id;
    const modalBox = modal.querySelector(".modal-box");
    if (modalBox) {
      modalBox.style.width = "640px";
    }

    const apiKey = effectiveConfig.api_key || "";
    const model = effectiveConfig.model || "auto";
    const bullets = parseInt(effectiveConfig.summary_bullets, 10) || 4;
    const autoStar = effectiveConfig.auto_summarize_on_star !== false;
    let defaultPresetId = effectiveConfig.default_preset_id || "standard";

    let currentPresets = (Array.isArray(effectiveConfig.prompt_presets) && effectiveConfig.prompt_presets.length > 0)
      ? JSON.parse(JSON.stringify(effectiveConfig.prompt_presets))
      : JSON.parse(JSON.stringify(OFFICIAL_GEMINI_PRESETS));

    let editingPresetId = null;

    let html = `
      <!-- Basic Gemini Settings -->
      <div class="gemini-basic-config" style="display: flex; flex-direction: column; gap: 12px; margin-bottom: 14px;">
        <div class="form-group" style="margin-bottom: 0;">
          <label class="form-label" style="font-size: 11px; margin-bottom: 4px; font-weight: 500;">
            ${t("settings.gemini_api_key") || "Google Gemini API Key (可自備金鑰)"}
          </label>
          <div style="display: flex; gap: 6px; align-items: center;">
            <input type="password" class="form-input dynamic-plugin-input" id="gemini-input-api-key" name="api_key" value="${this.escape(apiKey)}" placeholder="AIzaSy..." style="height: 36px; font-size: 12px; font-family: var(--font-mono); flex: 1;" />
            <button type="button" class="btn btn-secondary btn-nowrap" id="btn-toggle-gemini-key" style="height: 36px; font-size: 11px; padding: 0 10px;" title="顯示/隱藏金鑰">👁️</button>
          </div>
          <div style="margin-top: 4px; font-size: 11px;">
            <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noopener noreferrer" style="color: var(--accent-primary, #60a5fa); text-decoration: underline;">
              ${t("plugins.get_gemini_key") || "🔑 點此前往 Google AI Studio 免費獲取 Gemini API Key"}
            </a>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label" style="font-size: 11px; margin-bottom: 4px; font-weight: 500;">
              ${t("settings.gemini_model") || "模型型號 ('auto' 代表自動探測)"}
            </label>
            <select class="form-select dynamic-plugin-input" id="gemini-select-model" name="model" style="height: 36px; font-size: 12px;">
              <option value="auto" ${!model || model === "auto" ? "selected" : ""}>✨ auto (即時動態探測最新可用型號並智慧階梯降級，推薦)</option>
              <option value="gemini-2.5-flash" ${model === "gemini-2.5-flash" ? "selected" : ""}>gemini-2.5-flash (極速高資訊密度 / 免費額度充足)</option>
              <option value="gemini-2.5-flash-lite" ${model === "gemini-2.5-flash-lite" ? "selected" : ""}>gemini-2.5-flash-lite (低延遲輕量版)</option>
              <option value="gemini-2.5-pro" ${model === "gemini-2.5-pro" ? "selected" : ""}>gemini-2.5-pro (深度推理版)</option>
            </select>
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label" style="font-size: 11px; margin-bottom: 4px; font-weight: 500;">
              ${t("settings.gemini_bullets") || "重點條列數量 (2 ~ 8)"}
            </label>
            <input type="number" class="form-input dynamic-plugin-input" id="gemini-input-bullets" name="summary_bullets" value="${bullets}" min="2" max="8" style="height: 36px; font-size: 12px;" />
          </div>
        </div>

        <div class="form-group" style="margin-bottom: 0;">
          <div style="display: flex; align-items: center; justify-content: space-between;">
            <label class="form-label" style="font-size: 11px; margin-bottom: 0; font-weight: 500;">
              ${t("settings.gemini_auto_star") || "星標收藏時自動觸發 AI 摘要"}
            </label>
            <input type="checkbox" class="dynamic-plugin-input" id="gemini-check-auto-star" name="auto_summarize_on_star" ${autoStar ? "checked" : ""} style="width: 18px; height: 18px; accent-color: var(--accent-primary); cursor: pointer;" />
          </div>
        </div>
      </div>

      <!-- Presets Manager Section -->
      <div class="gemini-presets-section">
        <div class="gemini-presets-header">
          <div class="gemini-presets-title">
            <span>${t("plugins.gemini_presets_title") || "📝 提示詞風格範本庫 (Prompt Presets)"}</span>
          </div>
          <div class="gemini-presets-actions">
            <button type="button" class="btn btn-sm btn-secondary btn-user-action" id="btn-gemini-add-preset" style="font-size: 11px; height: 26px;">
              ${t("plugins.gemini_btn_add_preset") || "➕ 新增提示詞"}
            </button>
            <button type="button" class="btn btn-sm btn-secondary btn-user-action" id="btn-gemini-reset-presets" style="font-size: 11px; height: 26px;">
              ${t("plugins.gemini_btn_reset_presets") || "🔄 重置回原廠預設"}
            </button>
          </div>
        </div>

        <div class="gemini-presets-help">
          ${t("plugins.gemini_presets_desc") || "支援新增自訂提示詞、切換預設風格或刪除範本。支援變數：{title} 標題、{content} 內文、{bullets} 條列數。"}
        </div>

        <!-- Inline Editor Form -->
        <div class="gemini-preset-editor-box" id="gemini-preset-editor-box" style="display: none;">
          <div style="display: flex; align-items: center; justify-content: space-between;">
            <strong id="gemini-editor-title" style="font-size: 12px; color: var(--accent-primary, #60a5fa);">➕ 新增自訂提示詞</strong>
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label" style="font-size: 11px; margin-bottom: 3px; font-weight: 500;">
              ${t("plugins.gemini_preset_name") || "範本名稱"}
            </label>
            <input type="text" class="form-input" id="gemini-editor-name" placeholder="${t("plugins.gemini_preset_name_placeholder") || "例如：金融與股市解讀"}" style="height: 32px; font-size: 12px;" />
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label" style="font-size: 11px; margin-bottom: 3px; font-weight: 500;">
              ${t("plugins.gemini_preset_prompt") || "提示詞內容 (Prompt Template)"}
            </label>
            <textarea class="form-input" id="gemini-editor-prompt" placeholder="${t("plugins.gemini_preset_prompt_placeholder") || "請輸入提示詞範本內容，可使用 {title}、{content}、{bullets} 變數..."}" style="height: 110px; resize: vertical; font-size: 11px; font-family: var(--font-mono); line-height: 1.4; padding: 6px 8px;"></textarea>
          </div>
          <div style="display: flex; justify-content: flex-end; gap: 6px;">
            <button type="button" class="btn btn-sm btn-secondary" id="btn-gemini-cancel-preset" style="font-size: 11px; height: 26px; padding: 0 10px;">
              ${t("plugins.gemini_btn_cancel_preset") || "取消"}
            </button>
            <button type="button" class="btn btn-sm btn-primary" id="btn-gemini-save-preset" style="font-size: 11px; height: 26px; padding: 0 12px;">
              ${t("plugins.gemini_btn_save_preset") || "儲存範本"}
            </button>
          </div>
        </div>

        <!-- Presets Cards List -->
        <div class="gemini-presets-list" id="gemini-presets-list"></div>
      </div>
    `;

    container.innerHTML = html;

    const renderPresetsList = () => {
      const listEl = container.querySelector("#gemini-presets-list");
      if (!listEl) return;

      if (!currentPresets || currentPresets.length === 0) {
        listEl.innerHTML = `<div style="text-align: center; color: var(--text-muted); font-size: 12px; padding: 16px;">尚無提示詞範本，請點擊上方按鈕新增或重置。</div>`;
        return;
      }

      listEl.innerHTML = currentPresets.map((p) => {
        const isDefault = p.id === defaultPresetId;
        const isBuiltin = Boolean(p.is_builtin);
        return `
          <div class="gemini-preset-card ${isDefault ? "is-default" : ""}" data-id="${this.escape(p.id)}">
            <div class="gemini-preset-card-header">
              <div class="gemini-preset-card-title">
                <span class="preset-name-text">${this.escape(p.name)}</span>
                <span class="badge-preset-type ${isBuiltin ? "" : "custom"}">${isBuiltin ? (t("plugins.gemini_badge_builtin") || "內建") : (t("plugins.gemini_badge_custom") || "自訂")}</span>
                ${
                  isDefault
                    ? `<span class="badge-preset-default">${t("plugins.gemini_badge_default") || "🌟 預設範本"}</span>`
                    : `<button type="button" class="btn-user-action btn-gemini-set-default" data-id="${this.escape(p.id)}" title="${t("plugins.gemini_btn_set_default") || "設為預設"}">${t("plugins.gemini_btn_set_default") || "設為預設"}</button>`
                }
              </div>
              <div class="gemini-preset-card-actions">
                <button type="button" class="btn-user-action btn-gemini-edit-preset" data-id="${this.escape(p.id)}" title="${t("plugins.gemini_btn_edit") || "編輯"}">
                  ✏️ ${t("plugins.gemini_btn_edit") || "編輯"}
                </button>
                <button type="button" class="btn-user-action btn-action-danger btn-gemini-del-preset" data-id="${this.escape(p.id)}" title="${t("plugins.gemini_btn_delete") || "刪除"}" ${currentPresets.length <= 1 ? "disabled" : ""}>
                  🗑️
                </button>
              </div>
            </div>
            <div class="gemini-preset-prompt-preview" data-id="${this.escape(p.id)}" title="點擊展開/收合完整提示詞內容">${this.escape(p.prompt || "")}</div>
          </div>
        `;
      }).join("");
    };

    renderPresetsList();

    // Key reveal toggle
    const btnToggleKey = container.querySelector("#btn-toggle-gemini-key");
    const inputKey = container.querySelector("#gemini-input-api-key");
    if (btnToggleKey && inputKey) {
      btnToggleKey.addEventListener("click", () => {
        if (inputKey.type === "password") {
          inputKey.type = "text";
          btnToggleKey.textContent = "🔒";
        } else {
          inputKey.type = "password";
          btnToggleKey.textContent = "👁️";
        }
      });
    }

    // Add preset button
    const editorBox = container.querySelector("#gemini-preset-editor-box");
    const editorTitle = container.querySelector("#gemini-editor-title");
    const editorName = container.querySelector("#gemini-editor-name");
    const editorPrompt = container.querySelector("#gemini-editor-prompt");
    const btnAddPreset = container.querySelector("#btn-gemini-add-preset");
    const btnCancelPreset = container.querySelector("#btn-gemini-cancel-preset");
    const btnSavePreset = container.querySelector("#btn-gemini-save-preset");
    const btnResetPresets = container.querySelector("#btn-gemini-reset-presets");

    if (btnAddPreset) {
      btnAddPreset.addEventListener("click", () => {
        editingPresetId = null;
        if (editorTitle) editorTitle.textContent = t("plugins.gemini_btn_add_preset") || "➕ 新增自訂提示詞";
        if (editorName) editorName.value = "";
        if (editorPrompt) editorPrompt.value = "請針對以下文章內容，以繁體中文產出 {bullets} 點重點摘要：\n\n標題：{title}\n\n內文：\n{content}";
        if (editorBox) {
          editorBox.style.display = "flex";
          editorBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
        if (editorName) editorName.focus();
      });
    }

    if (btnCancelPreset) {
      btnCancelPreset.addEventListener("click", () => {
        if (editorBox) editorBox.style.display = "none";
        editingPresetId = null;
      });
    }

    if (btnSavePreset) {
      btnSavePreset.addEventListener("click", () => {
        const nameVal = (editorName ? editorName.value : "").trim();
        const promptVal = (editorPrompt ? editorPrompt.value : "").trim();

        if (!nameVal) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("plugins.gemini_preset_name_req") || "請輸入範本名稱", type: "warning" }
          }));
          if (editorName) editorName.focus();
          return;
        }

        if (!promptVal) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("plugins.gemini_preset_prompt_req") || "請輸入提示詞內容", type: "warning" }
          }));
          if (editorPrompt) editorPrompt.focus();
          return;
        }

        if (editingPresetId) {
          const idx = currentPresets.findIndex(p => p.id === editingPresetId);
          if (idx !== -1) {
            currentPresets[idx].name = nameVal;
            currentPresets[idx].prompt = promptVal;
          }
        } else {
          const newId = "custom_" + Date.now();
          currentPresets.push({
            id: newId,
            name: nameVal,
            prompt: promptVal,
            is_builtin: false,
          });
        }

        if (editorBox) editorBox.style.display = "none";
        editingPresetId = null;
        renderPresetsList();
        window.dispatchEvent(new CustomEvent("omnirss:toast", {
          detail: { message: `已儲存「${nameVal}」提示詞範本！`, type: "success" }
        }));
      });
    }

    if (btnResetPresets) {
      btnResetPresets.addEventListener("click", () => {
        if (confirm(t("plugins.gemini_reset_confirm") || "確定要將所有提示詞範本重置為原廠預設值（5 組官方範本）嗎？自訂範本將被清除。")) {
          currentPresets = JSON.parse(JSON.stringify(OFFICIAL_GEMINI_PRESETS));
          defaultPresetId = "standard";
          if (editorBox) editorBox.style.display = "none";
          editingPresetId = null;
          renderPresetsList();
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("plugins.gemini_reset_success") || "已成功重置為原廠預設提示詞範本！", type: "success" }
          }));
        }
      });
    }

    // List delegation for set default, edit, delete, preview click
    const listEl = container.querySelector("#gemini-presets-list");
    if (listEl) {
      listEl.addEventListener("click", (e) => {
        // Set Default
        const btnSetDef = e.target.closest(".btn-gemini-set-default");
        if (btnSetDef) {
          const id = btnSetDef.dataset.id;
          defaultPresetId = id;
          const found = currentPresets.find(p => p.id === id);
          renderPresetsList();
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: `已將「${found ? found.name : id}」設為預設提示詞風格`, type: "success" }
          }));
          return;
        }

        // Edit
        const btnEdit = e.target.closest(".btn-gemini-edit-preset");
        if (btnEdit) {
          const id = btnEdit.dataset.id;
          const target = currentPresets.find(p => p.id === id);
          if (target) {
            editingPresetId = id;
            if (editorTitle) editorTitle.textContent = `✏️ 編輯提示詞：${target.name}`;
            if (editorName) editorName.value = target.name;
            if (editorPrompt) editorPrompt.value = target.prompt;
            if (editorBox) {
              editorBox.style.display = "flex";
              editorBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
            }
            if (editorName) editorName.focus();
          }
          return;
        }

        // Delete
        const btnDel = e.target.closest(".btn-gemini-del-preset");
        if (btnDel) {
          const id = btnDel.dataset.id;
          if (currentPresets.length <= 1) {
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: t("plugins.gemini_delete_min_warn") || "至少需要保留一組提示詞範本！", type: "warning" }
            }));
            return;
          }
          const target = currentPresets.find(p => p.id === id);
          const name = target ? target.name : id;
          if (confirm(t("plugins.gemini_delete_confirm", { name }) || `確定要刪除「${name}」提示詞範本嗎？`)) {
            currentPresets = currentPresets.filter(p => p.id !== id);
            if (defaultPresetId === id) {
              defaultPresetId = currentPresets[0].id;
            }
            if (editingPresetId === id) {
              if (editorBox) editorBox.style.display = "none";
              editingPresetId = null;
            }
            renderPresetsList();
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: `已刪除「${name}」提示詞範本`, type: "success" }
            }));
          }
          return;
        }

        // Preview expand toggle
        const previewEl = e.target.closest(".gemini-preset-prompt-preview");
        if (previewEl) {
          previewEl.classList.toggle("expanded");
        }
      });
    }

    // Form submission for Gemini
    form.onsubmit = async (e) => {
      e.preventDefault();
      const updatedConfig = {
        api_key: (container.querySelector("#gemini-input-api-key")?.value || "").trim(),
        model: container.querySelector("#gemini-select-model")?.value || "auto",
        summary_bullets: parseInt(container.querySelector("#gemini-input-bullets")?.value, 10) || 4,
        auto_summarize_on_star: Boolean(container.querySelector("#gemini-check-auto-star")?.checked),
        default_preset_id: defaultPresetId,
        prompt_presets: currentPresets,
      };

      const saveBtn = form.querySelector("button[type='submit']");
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = t("plugins.saving") || "儲存中...";
      }

      try {
        await api.updatePluginConfig(pId, updatedConfig);
        const plugins = store.get("plugins") || [];
        const targetP = plugins.find(p => (p.plugin_id || p.id) === pId);
        if (targetP) {
          targetP.user_config = updatedConfig;
        }
        store.set("plugins", [...plugins]);
        window.dispatchEvent(new CustomEvent("omnirss:toast", {
          detail: { message: t("plugins.save_success", { name: resolveI18nText(plugin.name) || pId }) || `已成功儲存「${pluginName}」設定！`, type: "success" }
        }));
        this.closeModal("modal-plugin-config");
        this.closeModal("modal-plugins");
        await this.loadPluginsList();
        window.dispatchEvent(new CustomEvent("omnirss:plugins-updated"));
      } catch (err) {
        window.dispatchEvent(new CustomEvent("omnirss:toast", {
          detail: { message: t("plugins.save_failed", { error: err.message }) || `儲存設定失敗: ${err.message}`, type: "error" }
        }));
      } finally {
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.textContent = t("plugins.save_config") || "儲存設定";
        }
      }
    };
  };
}
