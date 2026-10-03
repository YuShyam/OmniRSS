/**
 * OmniRSS 自動化過濾規則對話框模組 (Rules Manager Modal Module).
 *
 * QuiteRSS v2 Multi-condition & Actions Pipeline.
 */

import { store, safeInputVal } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";

export function registerRulesModal(proto) {
  proto.createRuleConditionRow = function (field = "title", operator = "contains", value = "") {
    const row = document.createElement("div");
    row.className = "rule-condition-row";
    row.style.cssText = "display: flex; gap: 6px; align-items: center;";
    const isValDisabled = operator === "is_empty" || operator === "is_not_empty";

    const getValControlHtml = (f, curVal) => {
      if (f === "is_read") {
        const isRead = curVal === "read" || curVal === "true";
        return `
          <select class="form-select rule-cond-val" style="min-height: 32px; height: 32px; font-size: 12px; padding: 4px 8px; flex: 1;">
            <option value="unread" ${!isRead ? "selected" : ""}>未讀 (unread)</option>
            <option value="read" ${isRead ? "selected" : ""}>已讀 (read)</option>
          </select>
        `;
      }
      if (f === "is_starred") {
        const isStarred = curVal === "starred" || curVal === "true";
        return `
          <select class="form-select rule-cond-val" style="min-height: 32px; height: 32px; font-size: 12px; padding: 4px 8px; flex: 1;">
            <option value="starred" ${isStarred ? "selected" : ""}>已加星號 (starred)</option>
            <option value="unstarred" ${!isStarred ? "selected" : ""}>未標星號 (unstarred)</option>
          </select>
        `;
      }
      return `<input type="text" class="form-input rule-cond-val" placeholder="${isValDisabled ? (t("rules.val_empty_desc") || "(無需填寫關鍵字)") : (t("rules.val_placeholder") || "輸入關鍵字 (可留空)")}" value="${this.escape(curVal)}" ${isValDisabled ? "disabled style='opacity: 0.5; min-height: 32px; height: 32px; font-size: 12px; padding: 4px 8px; flex: 1;'" : "style='min-height: 32px; height: 32px; font-size: 12px; padding: 4px 8px; flex: 1;'"} />`;
    };

    row.innerHTML = `
      <select class="form-select rule-cond-field" style="min-height: 32px; height: 32px; font-size: 12px; padding: 4px 8px; width: 140px; flex-shrink: 0;">
        <optgroup label="📄 文章文字內容">
          <option value="title" ${field === "title" ? "selected" : ""}>${t("rules.field_title") || "文章標題"}</option>
          <option value="author" ${field === "author" ? "selected" : ""}>${t("rules.field_author") || "文章作者"}</option>
          <option value="content" ${field === "content" ? "selected" : ""}>${t("rules.field_content") || "文章內文 (純文字)"}</option>
          <option value="content_html" ${field === "content_html" ? "selected" : ""}>${t("rules.field_content_html") || "HTML 原始碼 (含網址)"}</option>
          <option value="url" ${field === "url" ? "selected" : ""}>${t("rules.field_url") || "文章網址"}</option>
        </optgroup>
        <optgroup label="🏷️ 頻道與標籤">
          <option value="feed_title" ${field === "feed_title" ? "selected" : ""}>${t("rules.field_feed") || "來源頻道"}</option>
          <option value="tag" ${field === "tag" ? "selected" : ""}>${t("rules.field_tag") || "文章標籤"}</option>
        </optgroup>
        <optgroup label="👁️ 文章動態狀態">
          <option value="is_read" ${field === "is_read" ? "selected" : ""}>${t("rules.field_is_read") || "閱讀狀態 (已讀/未讀)"}</option>
          <option value="is_starred" ${field === "is_starred" ? "selected" : ""}>${t("rules.field_is_starred") || "星號狀態 (已標星/未標星)"}</option>
        </optgroup>
      </select>
      <select class="form-select rule-cond-op" style="min-height: 32px; height: 32px; font-size: 12px; padding: 4px 8px; width: 130px; flex-shrink: 0;">
        <option value="contains" ${operator === "contains" ? "selected" : ""}>${t("rules.op_contains") || "包含"}</option>
        <option value="not_contains" ${operator === "not_contains" ? "selected" : ""}>${t("rules.op_not_contains") || "不包含"}</option>
        <option value="equals" ${operator === "equals" ? "selected" : ""}>${t("rules.op_equals") || "完全等於"}</option>
        <option value="not_equals" ${operator === "not_equals" ? "selected" : ""}>${t("rules.op_not_equals") || "不等於 / 不是"}</option>
        <option value="is_not_empty" ${operator === "is_not_empty" ? "selected" : ""}>${t("rules.op_is_not_empty") || "不是空白 (非空)"}</option>
        <option value="is_empty" ${operator === "is_empty" ? "selected" : ""}>${t("rules.op_is_empty") || "為空白 (為空)"}</option>
        <option value="starts_with" ${operator === "starts_with" ? "selected" : ""}>${t("rules.op_starts_with") || "開頭為"}</option>
        <option value="ends_with" ${operator === "ends_with" ? "selected" : ""}>${t("rules.op_ends_with") || "結尾為"}</option>
        <option value="regex" ${operator === "regex" ? "selected" : ""}>${t("rules.op_regex") || "正規表達式"}</option>
      </select>
      <div class="rule-cond-val-container" style="display: flex; flex: 1; align-items: center;">
        ${getValControlHtml(field, value)}
      </div>
      <button type="button" class="rule-row-delete-btn btn btn-sm btn-secondary" title="${t("rules.del_cond_tooltip") || "刪除此條件"}" style="min-height: 32px; height: 32px; width: 32px; padding: 0; display: flex; align-items: center; justify-content: center; color: var(--text-muted);">✕</button>
    `;

    const fieldSelect = row.querySelector(".rule-cond-field");
    const opSelect = row.querySelector(".rule-cond-op");
    const valContainer = row.querySelector(".rule-cond-val-container");

    if (fieldSelect && valContainer) {
      fieldSelect.addEventListener("change", () => {
        const curField = fieldSelect.value;
        const oldVal = row.querySelector(".rule-cond-val")?.value || "";
        valContainer.innerHTML = getValControlHtml(curField, oldVal);
      });
    }

    if (opSelect && valContainer) {
      opSelect.addEventListener("change", () => {
        const opVal = opSelect.value;
        const valInput = row.querySelector("input.rule-cond-val");
        if (valInput) {
          if (opVal === "is_empty" || opVal === "is_not_empty") {
            valInput.disabled = true;
            valInput.style.opacity = "0.5";
            valInput.placeholder = t("rules.val_empty_desc") || "(無需填寫關鍵字)";
          } else {
            valInput.disabled = false;
            valInput.style.opacity = "1";
            valInput.placeholder = t("rules.val_placeholder") || "輸入關鍵字 (可留空)";
          }
        }
      });
    }

    const delBtn = row.querySelector(".rule-row-delete-btn");
    delBtn.addEventListener("click", () => {
      const parentContainer = row.closest(".rule-group-conditions-container");
      if (parentContainer && parentContainer.children.length > 1) {
        row.remove();
      } else {
        const valIn = row.querySelector(".rule-cond-val");
        if (valIn) valIn.value = "";
      }
    });

    return row;
  };

  proto.createRuleConditionGroup = function (groupIndex = 1, matchMode = "all", conditions = []) {
    const grp = document.createElement("div");
    grp.className = "rule-condition-group-card";
    grp.style.cssText = "background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 6px; padding: 10px;";

    grp.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-weight: 700; font-size: 12px; color: var(--accent-primary);">🏷️ ${t("rules.group_title", { index: groupIndex }) || `條件群組 #${groupIndex}`}</span>
          <select class="form-select rule-group-match-mode" style="height: 26px; min-height: 26px; font-size: 11px; padding: 1px 6px; width: 170px;">
            <option value="all" ${matchMode === "all" ? "selected" : ""}>${t("rules.group_match_all") || "符合組內所有條件 (AND)"}</option>
            <option value="any" ${matchMode === "any" ? "selected" : ""}>${t("rules.group_match_any") || "符合組內任一條件 (OR)"}</option>
          </select>
        </div>
        <div style="display: flex; gap: 6px;">
          <button type="button" class="btn btn-sm btn-add-cond-to-group" style="font-size: 11px; padding: 2px 8px; height: 24px;">➕ 新增條件</button>
          <button type="button" class="btn btn-sm btn-delete-group btn-danger" style="font-size: 11px; padding: 2px 8px; height: 24px;" title="${t("rules.del_group_tooltip") || "刪除此群組"}">🗑️</button>
        </div>
      </div>
      <div class="rule-group-conditions-container" style="display: flex; flex-direction: column; gap: 6px;"></div>
    `;

    const condsContainer = grp.querySelector(".rule-group-conditions-container");
    if (conditions && conditions.length > 0) {
      conditions.forEach((c) => {
        condsContainer.appendChild(this.createRuleConditionRow(c.field || "title", c.operator || "contains", c.value || ""));
      });
    } else {
      condsContainer.appendChild(this.createRuleConditionRow("title", "contains", ""));
    }

    const btnAdd = grp.querySelector(".btn-add-cond-to-group");
    btnAdd.addEventListener("click", () => {
      condsContainer.appendChild(this.createRuleConditionRow("title", "contains", ""));
    });

    const btnDelGrp = grp.querySelector(".btn-delete-group");
    btnDelGrp.addEventListener("click", () => {
      const allGroups = document.getElementById("rule-condition-groups-container");
      if (allGroups && allGroups.children.length > 1) {
        grp.remove();
      } else {
        window.dispatchEvent(new CustomEvent("omnirss:toast", {
          detail: { message: "至少需保留一個條件群組", type: "warning" }
        }));
      }
    });

    return grp;
  };

  proto.initRuleConditionGroups = function (groups = []) {
    const container = document.getElementById("rule-condition-groups-container");
    if (!container) return;
    container.innerHTML = "";
    if (groups && groups.length > 0) {
      groups.forEach((g, idx) => {
        const mode = g.match_mode || "all";
        const conds = g.conditions || g.rules || [];
        container.appendChild(this.createRuleConditionGroup(idx + 1, mode, conds));
      });
    } else {
      container.appendChild(this.createRuleConditionGroup(1, "all", [
        { field: "title", operator: "contains", value: "" }
      ]));
    }
  };

  proto.collectRuleConditionGroups = function () {
    const container = document.getElementById("rule-condition-groups-container");
    if (!container) return [];
    const grpEls = container.querySelectorAll(".rule-condition-group-card");
    const groups = [];

    grpEls.forEach((grp) => {
      const mode = grp.querySelector(".rule-group-match-mode")?.value || "all";
      const rows = grp.querySelectorAll(".rule-condition-row");
      const conditions = [];
      rows.forEach((row) => {
        const field = row.querySelector(".rule-cond-field")?.value || "title";
        const operator = row.querySelector(".rule-cond-op")?.value || "contains";
        const valEl = row.querySelector(".rule-cond-val");
        const value = valEl ? valEl.value : "";
        conditions.push({ field, operator, value });
      });
      if (conditions.length > 0) {
        groups.push({ match_mode: mode, conditions });
      }
    });

    return groups;
  };

  proto.resetFeedFilter = function () {
    const feedFilterInput = document.getElementById("input-rule-feed-filter");
    if (feedFilterInput) feedFilterInput.value = "";
    const feedLabels = document.querySelectorAll("#rule-scope-feeds-list label");
    feedLabels.forEach((lbl) => {
      lbl.style.display = "flex";
    });
  };

  proto.editRule = function (rule) {
    this.resetFeedFilter();
    const editIdInput = document.getElementById("input-rule-edit-id");
    const nameInput = document.getElementById("input-rule-name");
    const scopeSelect = document.getElementById("select-rule-scope-type");
    const catSelect = document.getElementById("select-rule-scope-category");
    const catBox = document.getElementById("rule-scope-category-box");
    const feedsBox = document.getElementById("rule-scope-feeds-box");
    const btnCancel = document.getElementById("btn-cancel-edit-rule");
    const btnSubmit = document.getElementById("btn-submit-rule");
    const formTitle = document.querySelector("#form-add-rule [data-i18n='rules.form_title']");

    if (editIdInput) editIdInput.value = rule.id || "";
    if (nameInput) nameInput.value = rule.name || rule.rule_name || "";
    if (scopeSelect) {
      scopeSelect.value = rule.scope_type || "all";
      if (catBox) catBox.style.display = rule.scope_type === "category" ? "block" : "none";
      if (feedsBox) feedsBox.style.display = rule.scope_type === "feeds" ? "block" : "none";
    }
    if (catSelect && rule.scope_category_id) {
      catSelect.value = String(rule.scope_category_id);
    }
    if (rule.scope_feed_ids && Array.isArray(rule.scope_feed_ids)) {
      const feedIdSet = new Set(rule.scope_feed_ids.map(Number));
      document.querySelectorAll(".rule-scope-feed-chk").forEach((chk) => {
        chk.checked = feedIdSet.has(Number(chk.value));
      });
    }

    // Condition groups
    const groups = rule.condition_groups && rule.condition_groups.length > 0
      ? rule.condition_groups
      : (rule.conditions ? [{ match_mode: rule.match_mode || "all", conditions: rule.conditions.rules || rule.conditions }] : []);
    this.initRuleConditionGroups(groups);

    // Actions
    const acts = rule.actions || [];
    const actTypes = new Set(acts.map((a) => a.action || a.action_type));

    const chkMarkRead = document.getElementById("chk-act-mark-read");
    const chkMarkUnread = document.getElementById("chk-act-mark-unread");
    const chkStar = document.getElementById("chk-act-star");
    const chkUnstar = document.getElementById("chk-act-unstar");
    const chkTrash = document.getElementById("chk-act-trash");
    const chkStop = document.getElementById("chk-act-stop");
    const chkTag = document.getElementById("chk-act-add-tag");
    const chkColor = document.getElementById("chk-act-set-color");
    const tagDetails = document.getElementById("rule-action-tag-details");
    const colorDetails = document.getElementById("rule-action-color-details");
    const selectTag = document.getElementById("select-rule-tag-target");
    const customTagInput = document.getElementById("input-rule-custom-tag");
    const colorHexInput = document.getElementById("input-rule-color-hex");
    const colorPickerInput = document.getElementById("rule-color-picker-input");

    if (chkMarkRead) chkMarkRead.checked = actTypes.has("mark_read");
    if (chkMarkUnread) chkMarkUnread.checked = actTypes.has("mark_unread");
    if (chkStar) chkStar.checked = actTypes.has("star");
    if (chkUnstar) chkUnstar.checked = actTypes.has("unstar");
    if (chkTrash) chkTrash.checked = actTypes.has("trash");
    if (chkStop) chkStop.checked = actTypes.has("stop_processing");

    const tagAct = acts.find((a) => (a.action || a.action_type) === "add_tag" || (a.action || a.action_type) === "add_tags");
    if (chkTag) {
      chkTag.checked = Boolean(tagAct);
      if (tagDetails) tagDetails.style.display = tagAct ? "block" : "none";
      if (tagAct) {
        const tagName = (tagAct.params || tagAct.parameters || {}).tag_name || (tagAct.params || tagAct.parameters || {}).tag || "重要";
        const tagOpt = selectTag?.querySelector(`option[value="${tagName}"]`);
        if (tagOpt && selectTag) {
          selectTag.value = tagName;
          if (customTagInput) customTagInput.style.display = "none";
        } else if (selectTag && customTagInput) {
          selectTag.value = "__custom__";
          customTagInput.value = tagName;
          customTagInput.style.display = "block";
        }
      }
    }

    const colorAct = acts.find((a) => (a.action || a.action_type) === "set_color");
    if (chkColor) {
      chkColor.checked = Boolean(colorAct);
      if (colorDetails) colorDetails.style.display = colorAct ? "block" : "none";
      if (colorAct) {
        const hex = (colorAct.params || colorAct.parameters || {}).color || (colorAct.params || colorAct.parameters || {}).hex || "#ef4444";
        if (colorHexInput) colorHexInput.value = hex;
        if (colorPickerInput) colorPickerInput.value = hex;
      }
    }

    const pluginAct = acts.find((a) => (a.action || a.action_type) === "execute_plugin" || (a.action || a.action_type) === "run_plugin" || (a.action || a.action_type) === "ai_summary");
    const chkPlugin = document.getElementById("chk-act-plugin");
    const pluginDetails = document.getElementById("rule-action-plugin-details");
    const selectPlugin = document.getElementById("select-rule-plugin-target");
    const selectPreset = document.getElementById("select-rule-plugin-preset");

    if (chkPlugin) {
      chkPlugin.checked = Boolean(pluginAct);
      if (pluginDetails) pluginDetails.style.display = pluginAct ? "block" : "none";
      if (pluginAct) {
        const pParams = pluginAct.params || pluginAct.parameters || {};
        const pId = pParams.plugin_id || pParams.id || "";
        const pPreset = pParams.preset || pParams.preset_id || pParams.param || "standard";
        if (selectPlugin) selectPlugin.value = pId;
        if (selectPreset) selectPreset.value = pPreset;
      }
    }

    if (btnCancel) btnCancel.style.display = "inline-block";
    if (btnSubmit) btnSubmit.textContent = "💾 更新規則";
    if (formTitle) formTitle.textContent = `✏️ 編輯規則：${rule.name || rule.rule_name || ""}`;

    const form = document.getElementById("form-add-rule");
    if (form) form.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  proto.resetRuleEditState = function () {
    this.resetFeedFilter();
    const editIdInput = document.getElementById("input-rule-edit-id");
    const btnCancel = document.getElementById("btn-cancel-edit-rule");
    const btnSubmit = document.getElementById("btn-submit-rule");
    const formTitle = document.querySelector("#form-add-rule [data-i18n='rules.form_title']");
    const form = document.getElementById("form-add-rule");
    const tagDetails = document.getElementById("rule-action-tag-details");
    const colorDetails = document.getElementById("rule-action-color-details");
    const pluginDetails = document.getElementById("rule-action-plugin-details");
    const customTagInput = document.getElementById("input-rule-custom-tag");
    const catBox = document.getElementById("rule-scope-category-box");
    const feedsBox = document.getElementById("rule-scope-feeds-box");

    if (editIdInput) editIdInput.value = "";
    if (form) form.reset();
    if (tagDetails) tagDetails.style.display = "none";
    if (colorDetails) colorDetails.style.display = "none";
    if (pluginDetails) pluginDetails.style.display = "none";
    if (customTagInput) customTagInput.style.display = "none";
    if (catBox) catBox.style.display = "none";
    if (feedsBox) feedsBox.style.display = "none";
    if (btnCancel) btnCancel.style.display = "none";
    if (btnSubmit) btnSubmit.textContent = "💾 儲存規則";
    if (formTitle) formTitle.textContent = "⚡ 規則設定";
    this.initRuleConditionGroups();
  };

  proto.bindRules = function () {
    const btnOpen = document.getElementById("btn-open-rules");
    if (btnOpen) {
      btnOpen.addEventListener("click", async () => {
        const preview = document.getElementById("rule-test-preview-container");
        if (preview) {
          preview.style.display = "none";
          const previewList = document.getElementById("rule-test-preview-list");
          if (previewList) previewList.innerHTML = "";
        }
        this.populateRuleScopeAndTags();
        this.resetRuleEditState();
        await this.loadRulesList();
        this.openModal("modal-rules");
      });
    }

    // 0. 匯出所有規則 (JSON 下載)
    const btnExport = document.getElementById("btn-export-rules");
    if (btnExport) {
      btnExport.addEventListener("click", async () => {
        try {
          const exportData = await api.exportRules();
          const jsonStr = JSON.stringify(exportData, null, 2);
          const blob = new Blob([jsonStr], { type: "application/json" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          const dateStr = new Date().toISOString().slice(0, 10);
          a.href = url;
          a.download = `omnirss_rules_${dateStr}.json`;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: `已成功匯出 ${exportData.total_rules || (exportData.rules || []).length} 條規則！`, type: "success" }
          }));
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: `匯出規則失敗: ${err.message}`, type: "error" }
          }));
        }
      });
    }

    // 0.1 匯入規則 (JSON 檔案上傳)
    const btnImport = document.getElementById("btn-import-rules");
    const fileImportInput = document.getElementById("input-import-rules-file");
    if (btnImport && fileImportInput) {
      btnImport.addEventListener("click", () => {
        fileImportInput.value = "";
        fileImportInput.click();
      });

      fileImportInput.addEventListener("change", async (e) => {
        const file = e.target.files && e.target.files[0];
        if (!file) return;
        try {
          const text = await file.text();
          const parsed = JSON.parse(text);
          const res = await api.importRules(parsed);
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: res.message || `成功匯入 ${res.imported_count} 條規則！`, type: "success" }
          }));
          this.resetRuleEditState();
          await this.loadRulesList();
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: `匯入規則失敗: ${err.message}`, type: "error" }
          }));
        }
      });
    }

    // 0.2 目標頻道即時過濾搜尋
    const feedFilterInput = document.getElementById("input-rule-feed-filter");
    if (feedFilterInput) {
      feedFilterInput.addEventListener("input", () => {
        const q = feedFilterInput.value.trim().toLowerCase();
        const feedLabels = document.querySelectorAll("#rule-scope-feeds-list label");
        feedLabels.forEach((lbl) => {
          const text = lbl.textContent.toLowerCase();
          lbl.style.display = (!q || text.includes(q)) ? "flex" : "none";
        });
      });
      feedFilterInput.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          this.resetFeedFilter();
        }
      });
    }

    const btnCancelEdit = document.getElementById("btn-cancel-edit-rule");
    if (btnCancelEdit) {
      btnCancelEdit.addEventListener("click", () => this.resetRuleEditState());
    }

    // 1. 新增條件群組
    const btnAddGroup = document.getElementById("btn-add-condition-group");
    if (btnAddGroup) {
      btnAddGroup.addEventListener("click", () => {
        const container = document.getElementById("rule-condition-groups-container");
        if (container) {
          const nextIdx = container.children.length + 1;
          container.appendChild(this.createRuleConditionGroup(nextIdx, "all", []));
        }
      });
    }

    // 2. 新聞源範圍 Scope 切換
    const selectScope = document.getElementById("select-rule-scope-type");
    const catBox = document.getElementById("rule-scope-category-box");
    const feedsBox = document.getElementById("rule-scope-feeds-box");

    if (selectScope) {
      selectScope.addEventListener("change", () => {
        const scope = selectScope.value;
        if (catBox) catBox.style.display = scope === "category" ? "block" : "none";
        if (feedsBox) feedsBox.style.display = scope === "feeds" ? "block" : "none";
      });
    }

    // 3. 動作勾選展開
    const chkTag = document.getElementById("chk-act-add-tag");
    const tagDetails = document.getElementById("rule-action-tag-details");
    const selectTag = document.getElementById("select-rule-tag-target");
    const customTagInput = document.getElementById("input-rule-custom-tag");

    if (chkTag && tagDetails) {
      chkTag.addEventListener("change", () => {
        tagDetails.style.display = chkTag.checked ? "block" : "none";
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

    // 4. 底色高亮色票與自訂選色器
    const chkColor = document.getElementById("chk-act-set-color");
    const colorDetails = document.getElementById("rule-action-color-details");
    const colorHexInput = document.getElementById("input-rule-color-hex");
    const colorPickerInput = document.getElementById("rule-color-picker-input");
    const swatchBtns = document.querySelectorAll(".rule-color-swatch");

    if (chkColor && colorDetails) {
      chkColor.addEventListener("change", () => {
        colorDetails.style.display = chkColor.checked ? "block" : "none";
      });
    }

    // 4.5 外掛動作勾選展開
    const chkPlugin = document.getElementById("chk-act-plugin");
    const pluginDetails = document.getElementById("rule-action-plugin-details");
    if (chkPlugin && pluginDetails) {
      chkPlugin.addEventListener("change", () => {
        pluginDetails.style.display = chkPlugin.checked ? "block" : "none";
      });
    }

    swatchBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        swatchBtns.forEach((b) => (b.style.border = "2px solid transparent"));
        btn.style.border = "2px solid #fff";
        const c = btn.dataset.color;
        if (colorHexInput) colorHexInput.value = c;
        if (colorPickerInput) colorPickerInput.value = c;
      });
    });

    if (colorPickerInput && colorHexInput) {
      colorPickerInput.addEventListener("input", () => {
        colorHexInput.value = colorPickerInput.value;
        swatchBtns.forEach((b) => (b.style.border = "2px solid transparent"));
      });
      colorHexInput.addEventListener("input", () => {
        const val = colorHexInput.value.trim();
        if (/^#[0-9A-Fa-f]{6}$/.test(val)) {
          colorPickerInput.value = val;
        }
      });
    }

    // 5. 立即套用所有規則至現有文章
    const btnApplyAll = document.getElementById("btn-apply-all-rules");
    if (btnApplyAll) {
      btnApplyAll.addEventListener("click", async () => {
        if (btnApplyAll.classList.contains("busy")) return;
        btnApplyAll.classList.add("busy");
        try {
          const res = await api.applyAllRules();
          const count = res.affected_articles_count || 0;
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("rules.apply_all_success", { count }), type: "success" }
          }));
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("rules.apply_all_failed", { error: err.message }), type: "error" } }));
        } finally {
          btnApplyAll.classList.remove("busy");
        }
      });
    }

    // 6. 測試當前規則群組
    const btnTestCurrent = document.getElementById("btn-test-current-rule");
    if (btnTestCurrent) {
      btnTestCurrent.addEventListener("click", async () => {
        const groups = this.collectRuleConditionGroups();
        if (groups.length === 0) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("rules.prompt_condition") || "請至少設定一條有效條件", type: "warning" }
          }));
          return;
        }
        const scopeType = document.getElementById("select-rule-scope-type")?.value || "all";
        const scopeCatId = document.getElementById("select-rule-scope-category")?.value;
        const checkedFeeds = Array.from(document.querySelectorAll(".rule-scope-feed-chk:checked")).map((c) => parseInt(c.value, 10));

        await this.testAndPreviewRuleConditions({
          scope_type: scopeType,
          scope_category_id: scopeCatId ? parseInt(scopeCatId, 10) : null,
          scope_feed_ids: checkedFeeds,
          condition_groups: groups,
        });
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

    // 7. 提交儲存規則
    const form = document.getElementById("form-add-rule");
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const name = safeInputVal(document.getElementById("input-rule-name")?.value);
        const scopeType = document.getElementById("select-rule-scope-type")?.value || "all";
        const scopeCatId = document.getElementById("select-rule-scope-category")?.value;
        const checkedFeeds = Array.from(document.querySelectorAll(".rule-scope-feed-chk:checked")).map((c) => parseInt(c.value, 10));
        const groups = this.collectRuleConditionGroups();

        if (!name) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("rules.prompt_name") || "請輸入規則名稱", type: "warning" } }));
          return;
        }

        if (groups.length === 0) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("rules.prompt_condition") || "請至少設定一條有效條件", type: "warning" } }));
          return;
        }

        // 收集 Actions
        const actions = [];
        if (document.getElementById("chk-act-mark-read")?.checked) actions.push({ action: "mark_read" });
        if (document.getElementById("chk-act-mark-unread")?.checked) actions.push({ action: "mark_unread" });
        if (document.getElementById("chk-act-star")?.checked) actions.push({ action: "star" });
        if (document.getElementById("chk-act-unstar")?.checked) actions.push({ action: "unstar" });
        if (document.getElementById("chk-act-trash")?.checked) actions.push({ action: "trash" });
        if (document.getElementById("chk-act-stop")?.checked) actions.push({ action: "stop_processing" });

        if (document.getElementById("chk-act-add-tag")?.checked) {
          const selectTagEl = document.getElementById("select-rule-tag-target");
          const customTagInputEl = document.getElementById("input-rule-custom-tag");
          let tagName = selectTagEl?.value || "重要";
          if (tagName === "__custom__") {
            tagName = safeInputVal(customTagInputEl?.value);
            if (!tagName) {
              window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("rules.prompt_custom_tag") || "請輸入自訂標籤名稱", type: "warning" } }));
              if (customTagInputEl) customTagInputEl.focus();
              return;
            }
          }
          actions.push({ action: "add_tag", params: { tag_name: tagName } });
        }

        if (document.getElementById("chk-act-set-color")?.checked) {
          const colorHexInputEl = document.getElementById("input-rule-color-hex");
          const colorHex = (colorHexInputEl?.value || "#ef4444").trim();
          actions.push({ action: "set_color", params: { color: colorHex } });
        }

        if (document.getElementById("chk-act-plugin")?.checked) {
          const pluginTarget = document.getElementById("select-rule-plugin-target")?.value || "";
          if (pluginTarget) {
            const pluginPreset = document.getElementById("select-rule-plugin-preset")?.value || "standard";
            actions.push({
              action: "execute_plugin",
              params: { plugin_id: pluginTarget, preset: pluginPreset, param: pluginPreset },
            });
          }
        }

        if (actions.length === 0) {
          // 預設給已讀動作
          actions.push({ action: "mark_read" });
        }

        const rulePayload = {
          name,
          sort_order: 10,
          is_enabled: true,
          scope_type: scopeType,
          scope_category_id: scopeType === "category" && scopeCatId ? parseInt(scopeCatId, 10) : null,
          scope_feed_ids: scopeType === "feeds" ? checkedFeeds : [],
          match_mode: "all",
          condition_groups: groups,
          actions,
        };

        const editId = document.getElementById("input-rule-edit-id")?.value;
        try {
          if (editId) {
            await api.updateRule(editId, rulePayload);
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: t("rules.update_success", { name }) || `已成功更新規則「${name}」！`, type: "success" }
            }));
          } else {
            await api.createRule(rulePayload);
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: t("rules.save_success", { name }) || `已成功建立規則「${name}」！`, type: "success" }
            }));
          }
          this.resetRuleEditState();
          await this.loadRulesList();
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: (editId ? t("rules.update_failed") : t("rules.save_failed", { error: err.message })) || `操作失敗: ${err.message}`, type: "error" } }));
        }
      });
    }
  };

  proto.populateRuleScopeAndTags = function () {
    this.resetFeedFilter();
    const cats = store.get("categories") || [];
    const feeds = store.get("feeds") || [];
    const tags = store.get("tags") || [];

    // 1. 分類選單
    const selectCat = document.getElementById("select-rule-scope-category");
    if (selectCat) {
      selectCat.innerHTML = cats.map((c) => `<option value="${c.id}">${this.escape(c.name)}</option>`).join("");
    }

    // 2. 頻道多選清單
    const feedsList = document.getElementById("rule-scope-feeds-list");
    if (feedsList) {
      feedsList.innerHTML = feeds.map((f) => `
        <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
          <input type="checkbox" class="rule-scope-feed-chk" value="${f.id}" style="accent-color: var(--accent-primary);" />
          <span title="${this.escape(f.title)}">${this.escape(f.title)}</span>
        </label>
      `).join("");
    }

    // 3. 標籤選單
    const selectTag = document.getElementById("select-rule-tag-target");
    if (selectTag) {
      const defaultList = [
        { name: "重要", color: "#ef4444" },
        { name: "工作", color: "#f97316" },
        { name: "個人", color: "#22c55e" },
        { name: "待讀", color: "#3b82f6" },
        { name: "稍後閱讀", color: "#a855f7" },
      ];
      const merged = [...defaultList];
      tags.forEach((tagItem) => {
        if (!merged.some((x) => x.name === tagItem.name)) {
          merged.push(tagItem);
        }
      });
      selectTag.innerHTML = merged.map((tagItem) => `<option value="${this.escape(tagItem.name)}">${this.escape(tagItem.name)}</option>`).join("") +
        `<option value="__custom__">${t("rules.custom_tag_option") || "➕ 自訂標籤名稱..."}</option>`;
    }
  };

  proto.testAndPreviewRuleConditions = async function (payload) {
    const previewContainer = document.getElementById("rule-test-preview-container");
    const previewTitle = document.getElementById("rule-test-preview-title");
    const previewList = document.getElementById("rule-test-preview-list");
    if (!previewContainer || !previewList) return;

    previewContainer.style.display = "block";
    previewList.innerHTML = `<div class="text-muted" style="padding: 8px 0;">${t("rules.testing") || "🔍 正在比對資料庫文章..."}</div>`;

    try {
      const res = await api.testRule(payload);
      const matches = res.articles || res.matched_articles || [];
      const total = res.count !== undefined ? res.count : (res.matched_count !== undefined ? res.matched_count : matches.length);

      if (previewTitle) {
        previewTitle.innerHTML = t("rules.test_found_fmt", { count: total }) || `🔍 規則比對測試結果：共命中 <strong>${total}</strong> 篇符合條件文章`;
      }

      if (matches.length === 0) {
        previewList.innerHTML = `<div class="text-muted" style="padding: 6px 0;">${t("rules.test_not_found") || "資料庫中無符合當前條件的文章"}</div>`;
        return;
      }

      previewList.innerHTML = matches.map((art) => `
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 8px; border-bottom: 1px solid var(--border-color-subtle); gap: 10px;">
          <div style="flex: 1; min-width: 0;">
            <div style="font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary);" title="${this.escape(art.title || '')}">
              ${this.escape(art.title || t("common.untitled") || "無標題")}
            </div>
            <div style="font-size: 11px; color: var(--text-muted); display: flex; gap: 8px;">
              <span>📡 ${this.escape(art.feed_title || t("rules.unknown_source") || "來源頻道")}</span>
              ${art.published_at ? `<span>⏱️ ${art.published_at.slice(0, 16)}</span>` : ""}
            </div>
          </div>
          <span class="badge-status-pill" style="font-size: 10px; flex-shrink: 0;">命中</span>
        </div>
      `).join("");
    } catch (err) {
      previewList.innerHTML = `<div style="color: var(--accent-red, #ef4444); padding: 6px 0;">${t("rules.test_failed", { error: this.escape(err.message) }) || err.message}</div>`;
    }
  };

  proto.loadRulesList = async function () {
    const listEl = document.getElementById("rules-list-container");
    if (!listEl) return;

    // 動態填充「執行外掛」選擇器 - 從 store 讀取已啟用的 processor 外掛（Manifest 驅動）
    const pluginSelectEl = document.getElementById("select-rule-plugin-target");
    if (pluginSelectEl) {
      const allPlugins = store.get("plugins") || [];
      const processorPlugins = allPlugins.filter((p) => p.slot_type === "processor" && p.is_enabled !== false);
      const resolveI18nName = (name) => {
        if (!name) return "";
        if (typeof name === "object") {
          const lang = store.get("lang") || "zh-TW";
          return name[lang] || name["zh-TW"] || name["en-US"] || Object.values(name)[0] || "";
        }
        return String(name);
      };
      const currentVal = pluginSelectEl.value;
      pluginSelectEl.innerHTML = processorPlugins.length > 0
        ? processorPlugins.map((p) => {
            const pId = p.plugin_id || p.id;
            const badge = p.badge;
            const label = badge ? `${badge.icon} ${badge.short_name} - ${resolveI18nName(p.name)}` : resolveI18nName(p.name) || pId;
            return `<option value="${pId}">${label}</option>`;
          }).join("")
        : `<option value="" disabled>(無可用的處理外掛)</option>`;
      // 恢復先前選中的值（若仍可用）
      if (currentVal && pluginSelectEl.querySelector(`option[value="${CSS.escape(currentVal)}"]`)) {
        pluginSelectEl.value = currentVal;
      }
    }

    try {
      const rules = await api.getRules();
      if (!rules || rules.length === 0) {
        listEl.innerHTML = `<div class="text-muted" style="font-size: 12px; padding: 14px 0; text-align: center;">${t("rules.no_rules") || "目前尚未設定任何自訂過濾規則"}</div>`;
        return;
      }

      const cats = store.get("categories") || [];
      const feeds = store.get("feeds") || [];

      listEl.innerHTML = rules.map((r) => {
        // 解析 Scope 下方雙維度呈現
        let scopeDetailHtml = `<span style="color: var(--text-secondary); font-weight: 600;">📡 套用來源:</span> <span style="color: #94a3b8;" title="套用所有訂閱頻道">🌐 全域 (所有訂閱頻道)</span>`;

        if (r.scope_type === "category") {
          const cat = cats.find((c) => c.id === r.scope_category_id);
          const catName = cat ? cat.name : (r.scope_category_name || "未指定分類");
          scopeDetailHtml = `<span style="color: var(--text-secondary); font-weight: 600;">📡 目標分類:</span> <span style="color: #c084fc;" title="套用分類：${this.escape(catName)}">📁 ${this.escape(catName)}</span>`;
        } else if (r.scope_type === "feeds") {
          const feedIdList = r.scope_feed_ids || [];
          const matchedFeeds = feedIdList.map((fid) => feeds.find((f) => Number(f.id) === Number(fid))).filter(Boolean);
          const feedNames = matchedFeeds.map((f) => f.title || f.name);
          const feedNamesText = feedNames.length > 0 ? feedNames.join(", ") : (r.scope_feed_titles && r.scope_feed_titles.length > 0 ? r.scope_feed_titles.join(", ") : `${feedIdList.length} 個指定頻道`);
          const tooltipList = feedNames.length > 0 ? feedNames : (r.scope_feed_titles || []);
          const tooltipText = tooltipList.length > 0 ? `套用目標頻道 (${tooltipList.length} 個)：\n` + tooltipList.map((n) => `• ${n}`).join("\n") : "未指定頻道";

          scopeDetailHtml = `<span style="color: var(--text-secondary); font-weight: 600;">📡 目標頻道:</span> <span style="color: #60a5fa; cursor: help;" title="${this.escape(tooltipText)}">📡 ${this.escape(feedNamesText)}</span>`;
        }

        // 解析條件文字
        const fieldMap = {
          title: "標題",
          feed_title: "頻道",
          content: "內文",
          author: "作者",
          url: "網址",
          tag: "標籤",
        };
        const opMap = {
          contains: "包含",
          not_contains: "不包含",
          equals: "=",
          not_equals: "≠",
          is_empty: "為空白",
          is_not_empty: "不是空白",
          starts_with: "開頭為",
          ends_with: "結尾為",
          regex: "正則",
        };

        const groups = r.condition_groups && r.condition_groups.length > 0
          ? r.condition_groups
          : (r.conditions ? [{ match_mode: r.match_mode || "all", conditions: r.conditions.rules || r.conditions }] : []);

        const groupDescs = groups.map((g, gIdx) => {
          const mode = g.match_mode || "all";
          const condList = g.conditions || g.rules || [];
          const innerStr = condList.map((c) => {
            const f = fieldMap[c.field] || c.field;
            const op = opMap[c.operator] || c.operator;
            if (c.operator === "is_empty" || c.operator === "is_not_empty") {
              return `${f} ${op}`;
            }
            return `${f} ${op} "${c.value || ""}"`;
          }).join(mode === "any" ? " 或 " : " 且 ");
          return `[${innerStr}]`;
        }).join(" 且 ");

        // 解析動作 Badges
        const acts = r.actions || [];
        const actionBadges = acts.map((a) => {
          const actType = a.action || a.action_type || "mark_read";
          const params = a.params || a.parameters || {};
          if (actType === "mark_read") return `<span style="font-size: 10px; font-weight: 600; color: #3b82f6; background: rgba(59,130,246,0.1); padding: 1px 5px; border-radius: 3px;">標記已讀</span>`;
          if (actType === "mark_unread") return `<span style="font-size: 10px; font-weight: 600; color: #eab308; background: rgba(234,179,8,0.1); padding: 1px 5px; border-radius: 3px;">標記未讀</span>`;
          if (actType === "star") return `<span style="font-size: 10px; font-weight: 600; color: #f59e0b; background: rgba(245,158,11,0.1); padding: 1px 5px; border-radius: 3px;">⭐ 加星</span>`;
          if (actType === "unstar") return `<span style="font-size: 10px; font-weight: 600; color: #94a3b8; background: rgba(148,163,184,0.1); padding: 1px 5px; border-radius: 3px;">取消星號</span>`;
          if (actType === "trash") return `<span style="font-size: 10px; font-weight: 600; color: #ef4444; background: rgba(239,68,68,0.1); padding: 1px 5px; border-radius: 3px;">🗑️ 垃圾桶</span>`;
          if (actType === "add_tag" || actType === "add_tags") {
            const tagVal = params.tag_name || params.tag || params.tags || "重要";
            return `<span style="font-size: 10px; font-weight: 600; color: #10b981; background: rgba(16,185,129,0.1); padding: 1px 5px; border-radius: 3px;">🏷️ ${this.escape(String(tagVal))}</span>`;
          }
          if (actType === "set_color") {
            const hex = params.color || params.hex || "#ef4444";
            return `<span style="font-size: 10px; font-weight: 600; color: ${hex}; background: color-mix(in srgb, ${hex} 15%, transparent); border: 1px solid ${hex}; padding: 1px 5px; border-radius: 3px;">🎨 高亮底色</span>`;
          }
          if (actType === "execute_plugin" || actType === "run_plugin" || actType === "ai_summary") {
            const pId = params.plugin_id || params.id || "";
            const preset = params.preset || params.preset_id || params.param || "standard";
            // 從 store 動態查詢外掛名稱，改以 badge.short_name 或外掛名稱顯示
            const allPlugins = store.get("plugins") || [];
            const pluginObj = allPlugins.find((p) => (p.plugin_id || p.id) === pId);
            const badge = pluginObj && pluginObj.badge;
            const pName = badge ? badge.short_name : (pluginObj && pluginObj.name ? (typeof pluginObj.name === "object" ? (pluginObj.name["zh-TW"] || Object.values(pluginObj.name)[0]) : pluginObj.name) : (pId.split("/")[1] || pId || "外掛"));
            const presetLabelMap = { standard: "標準", tldr: "極簡", insights: "產業", entertainment: "影視", roast: "短評" };
            const presetText = presetLabelMap[preset] || preset;
            return `<span style="font-size: 10px; font-weight: 600; color: #a855f7; background: rgba(168,85,247,0.1); border: 1px solid rgba(168,85,247,0.3); padding: 1px 5px; border-radius: 3px;">🤖 ${pName} (${presetText})</span>`;
          }
          if (actType === "stop_processing") return `<span style="font-size: 10px; font-weight: 600; color: #94a3b8; background: rgba(148,163,184,0.1); padding: 1px 5px; border-radius: 3px;">⛔ 停止後續</span>`;
          return `<span style="font-size: 10px; font-weight: 600; color: var(--accent-primary); background: var(--accent-primary-dim); padding: 1px 5px; border-radius: 3px;">${this.escape(actType)}</span>`;
        }).join(" ");

        const rawRuleForTest = JSON.stringify({
          scope_type: r.scope_type || "all",
          scope_category_id: r.scope_category_id,
          scope_feed_ids: r.scope_feed_ids || [],
          condition_groups: groups,
        });

        return `
        <div class="rule-card-item" style="background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 6px; padding: 10px 12px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between; gap: 12px;">
          <div style="flex: 1; min-width: 0;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px; flex-wrap: wrap;">
              <strong style="font-size: 13px; color: var(--text-primary);">${this.escape(r.name || t("rules.untitled_rule") || "未命名規則")}</strong>
              ${actionBadges}
            </div>
            <div style="font-size: 11px; margin-top: 4px; display: flex; flex-direction: column; gap: 2px;">
              <div class="text-muted" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${this.escape(groupDescs)}">
                <span style="color: var(--text-secondary); font-weight: 600;">🔍 比對條件:</span> ${this.escape(groupDescs) || (t("rules.no_conditions") || "無條件")}
              </div>
              <div class="text-muted" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                ${scopeDetailHtml}
              </div>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 6px; flex-shrink: 0;">
            <button type="button" class="btn btn-sm btn-secondary btn-edit-rule" data-id="${r.id}" style="padding: 3px 8px; font-size: 11px;">✏️ 編輯</button>
            <button type="button" class="btn btn-sm btn-test-rule" data-rule='${this.escape(rawRuleForTest)}' style="padding: 3px 8px; font-size: 11px;">🔍 測試</button>
            <button type="button" class="btn btn-sm btn-apply-rule" data-id="${r.id}" style="padding: 3px 8px; font-size: 11px; background: var(--accent-primary-dim); color: var(--accent-primary); border: 1px solid var(--accent-primary);">▶ 立即套用</button>
            <button type="button" class="btn btn-sm btn-danger btn-delete-rule" data-id="${r.id}" style="padding: 3px 8px; font-size: 11px;">🗑️ 刪除</button>
          </div>
        </div>
      `;
      }).join("");

      listEl.querySelectorAll(".btn-edit-rule").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.dataset.id;
          const target = rules.find((x) => String(x.id) === String(id));
          if (target) {
            this.editRule(target);
          }
        });
      });

      listEl.querySelectorAll(".btn-test-rule").forEach((btn) => {
        btn.addEventListener("click", async () => {
          try {
            const raw = btn.dataset.rule;
            const payload = JSON.parse(raw);
            await this.testAndPreviewRuleConditions(payload);
          } catch (e) {
            window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: `解析失敗: ${e.message}`, type: "error" } }));
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
              detail: { message: `已成功套用至 ${count} 篇現有文章`, type: "success" }
            }));
            window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
          } catch (err) {
            window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: `套用失敗: ${err.message}`, type: "error" } }));
          } finally {
            btn.disabled = false;
          }
        });
      });

      listEl.querySelectorAll(".btn-delete-rule").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const id = btn.dataset.id;
          if (window.confirm(t("rules.delete_confirm") || "確定要刪除此規則嗎？")) {
            await api.deleteRule(id);
            await this.loadRulesList();
            window.dispatchEvent(new CustomEvent("omnirss:toast", { detail: { message: t("rules.delete_success") || "已刪除規則", type: "success" } }));
          }
        });
      });
    } catch (_) {}
  };
}
