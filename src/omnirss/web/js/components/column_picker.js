/**
 * OmniRSS 動態欄位自選元件 (Column Picker [ ⊞ ] Component).
 *
 * Provides QuiteRSS style dynamic column toggle checkboxes, reset order button,
 * and persists user column visibility & order preferences.
 */

import { store } from "../state.js";
import { t } from "../i18n.js";
import { pluginRegistry } from "../plugin_registry.js";

export class ColumnPicker {
  constructor(menuEl) {
    this.menuEl = menuEl;
    this.isOpen = false;
    this.init();
  }

  init() {
    // Listen for trigger click
    document.addEventListener("click", (e) => {
      const trigger = e.target.closest("#btn-col-picker");
      if (trigger) {
        e.stopPropagation();
        this.toggle();
        return;
      }

      if (!e.target.closest(".column-picker-menu")) {
        this.close();
      }
    });

    this.menuEl.addEventListener("change", (e) => {
      if (e.target.type === "checkbox") {
        const colKey = e.target.name;
        const currentCols = { ...store.get("columns") };
        currentCols[colKey] = e.target.checked;
        store.set("columns", currentCols);
      }
    });

    this.menuEl.addEventListener("click", (e) => {
      const resetOrderBtn = e.target.closest("#btn-reset-column-order");
      if (resetOrderBtn) {
        e.stopPropagation();
        const defaultOrder = ["status", "star", "title", "actions", "feed", "date", "author", "tags"];
        store.set("columnOrder", defaultOrder);
        window.dispatchEvent(
          new CustomEvent("omnirss:toast", {
            detail: { message: t("columns.reset_order_success"), type: "success" },
          })
        );
        this.close();
        return;
      }

      const resetWidthsBtn = e.target.closest("#btn-reset-column-widths");
      if (resetWidthsBtn) {
        e.stopPropagation();
        store.set("columnWidths", {});
        localStorage.removeItem("omnirss_column_widths");
        window.dispatchEvent(new CustomEvent("omnirss:column-widths-changed"));
        window.dispatchEvent(
          new CustomEvent("omnirss:toast", {
            detail: { message: t("columns.reset_width_success"), type: "success" },
          })
        );
        this.close();
        return;
      }
    });

    this.render();
  }

  toggle() {
    if (this.isOpen) {
      this.close();
    } else {
      this.open();
    }
  }

  open() {
    this.render();
    this.menuEl.classList.add("open");
    this.isOpen = true;
  }

  close() {
    this.menuEl.classList.remove("open");
    this.isOpen = false;
  }

  render() {
    const cols = store.get("columns") || {};
    const allCols = pluginRegistry.getAllListColumns();

    const checkboxItems = allCols
      .map((c) => {
        const isChecked = cols[c.id] !== false;
        const labelText = t(c.label || `columns.${c.id}`);
        return `
          <label class="column-picker-item">
            <input type="checkbox" name="${c.id}" ${isChecked ? "checked" : ""}/>
            <span>${labelText}</span>
          </label>
        `;
      })
      .join("");

    this.menuEl.innerHTML = `
      <div class="column-picker-header">${t("columns.picker_header")}</div>
      ${checkboxItems}
      <div class="column-picker-divider" style="height: 1px; background: var(--border-color); margin: 6px 0;"></div>
      <button class="column-picker-reset-btn" id="btn-reset-column-order" style="width: 100%; text-align: left; padding: 4px 8px; background: none; border: none; color: var(--text-muted); font-size: 11px; cursor: pointer; border-radius: 4px;">↺ ${t("columns.reset_order")}</button>
      <button class="column-picker-reset-btn" id="btn-reset-column-widths" style="width: 100%; text-align: left; padding: 4px 8px; background: none; border: none; color: var(--text-muted); font-size: 11px; cursor: pointer; border-radius: 4px;">↔ ${t("columns.reset_width")}</button>
    `;
  }
}
