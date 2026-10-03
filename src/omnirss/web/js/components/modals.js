/**
 * OmniRSS 彈窗對話框與設定中心協調器 (Modals Coordinator).
 *
 * 協調管理 8 大對話框模組：
 * 1. modal_feed: 新增訂閱源與來源屬性對話框
 * 2. modal_category: 新增分類與進階分類屬性中心
 * 3. modal_rules: 自動化規則管理員
 * 4. modal_plugins: 擴充外掛儀表板與即時日誌
 * 5. modal_settings: 偏好設定分頁中心 (外觀、排版、快捷鍵、標籤管理、資料維護)
 * 6. modal_account: 個人帳號與多使用者權限管理
 * 7. modal_auth: 登入認證彈窗
 * 8. modal_tags: 文章標籤指派對話框
 */

import { store } from "../state.js";
import { t } from "../i18n.js";
import { registerFeedModal } from "./modal_feed.js";
import { registerCategoryModal } from "./modal_category.js";
import { registerRulesModal } from "./modal_rules.js";
import { registerPluginsModal } from "./modal_plugins.js";
import { registerSettingsModal } from "./modal_settings.js";
import { registerAccountModal } from "./modal_account.js";
import { registerAuthModal } from "./modal_auth.js";
import { registerTagsModal } from "./modal_tags.js";

/**
 * 安全解析輸入值，防禦 "null" / "undefined" 字串污染
 * @param {*} v 任意輸入值
 * @returns {string} 洗淨後字串
 */
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
        if (e.target.id === "modal-login" && !store.get("user")) {
          // 未登入時禁止點擊背景關閉登入彈窗
          return;
        }
        e.target.classList.remove("open");
      }
      const closeBtn = e.target.closest(
        ".modal-close-btn, .btn-modal-cancel, .modal-cancel-btn, .modal-close-btn-action, [data-action='close-modal'], [data-dismiss='modal']"
      );
      if (closeBtn) {
        const modal = closeBtn.closest(".modal-overlay");
        if (modal) {
          if (modal.id === "modal-login" && !store.get("user")) {
            return;
          }
          modal.classList.remove("open");
        }
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

    window.addEventListener("omnirss:open-account-modal", (e) => {
      this.openAccountModal(e.detail?.tab);
    });

    // 綁定各子模組表單與事件
    this.bindAddFeed();
    this.bindAddCategory();
    this.bindCategorySettings();
    this.bindFeedProperties();
    this.bindRules();
    this.bindPlugins();
    this.bindSettings();
    this.bindAccount();
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
    // 預先清理關閉其他非當前之開啟彈窗，杜絕多層遮罩覆蓋導致按鈕點擊無效
    document.querySelectorAll(".modal-overlay.open").forEach((m) => {
      if (m.id !== modalId) m.classList.remove("open");
    });

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
}

// 掛載 8 大模組至 ModalController 原型鏈
registerFeedModal(ModalController.prototype);
registerCategoryModal(ModalController.prototype);
registerRulesModal(ModalController.prototype);
registerPluginsModal(ModalController.prototype);
registerSettingsModal(ModalController.prototype);
registerAccountModal(ModalController.prototype);
registerAuthModal(ModalController.prototype);
registerTagsModal(ModalController.prototype);
