/**
 * OmniRSS 動態欄位自選元件 (Column Picker [ ⊞ ] Component).
 *
 * Provides QuiteRSS style dynamic column toggle checkboxes and persists
 * user column visibility preferences to localStorage.
 */

import { store } from "../state.js";
import { t } from "../i18n.js";

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
    const colDefs = [
      { key: "status", label: t("columns.status") },
      { key: "star", label: t("columns.star") },
      { key: "title", label: t("columns.title") },
      { key: "feed", label: t("columns.feed") },
      { key: "date", label: t("columns.date") },
      { key: "author", label: t("columns.author") },
      { key: "tags", label: t("columns.tags") },
    ];

    const html = colDefs.map(
      (c) => `
        <label class="column-picker-item">
          <input type="checkbox" name="${c.key}" ${cols[c.key] ? "checked" : ""}/>
          <span>${c.label}</span>
        </label>
      `
    ).join("");

    this.menuEl.innerHTML = html;
  }
}
