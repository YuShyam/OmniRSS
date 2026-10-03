/**
 * OmniRSS 文章標籤指派對話框模組 (Article Tags Assignment Modal Module).
 */

import { store, safeInputVal } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";

export function registerTagsModal(proto) {
  /**
   * 綁定文章標籤指派彈窗表單與勾選事件 (🏷️)
   */
  proto.bindArticleTags = function () {
    const formQuickAdd = document.getElementById("form-quick-add-tag");
    if (formQuickAdd) {
      formQuickAdd.addEventListener("submit", async (e) => {
        e.preventDefault();
        const nameInput = document.getElementById("input-quick-tag-name");
        const colorInput = document.getElementById("input-quick-tag-color");
        const name = safeInputVal(nameInput?.value);
        const color = colorInput?.value || "#3b82f6";
        if (!name) return;

        try {
          await api.createTag(name, color);
          const tags = await api.getTags();
          store.set("tags", tags || []);
          if (nameInput) nameInput.value = "";

          // 若目前有文章正在打標，自動為該文章貼上此新標籤
          const currentArtId = this._currentArticleTagModalId;
          const newTag = (tags || []).find((tagItem) => tagItem.name === name);
          if (newTag && currentArtId) {
            await api.toggleArticleTag(currentArtId, newTag.id, "add");
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: t("tags.created_and_attached", { name }), type: "success" }
            }));
            window.dispatchEvent(new CustomEvent("omnirss:tags-updated"));
            window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));
          }
          this.renderArticleTagsCheckboxes(currentArtId);
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("tags.create_failed", { error: err.message }), type: "error" }
          }));
        }
      });
    }

    const container = document.getElementById("article-tags-checkboxes-container");
    if (container) {
      container.addEventListener("change", async (e) => {
        const checkbox = e.target.closest(".article-tag-checkbox");
        if (!checkbox) return;
        const tagId = parseInt(checkbox.dataset.tagId, 10);
        const tagName = checkbox.dataset.tagName || "";
        const articleId = this._currentArticleTagModalId;
        if (!tagId || !articleId) return;

        try {
          const res = await api.toggleArticleTag(articleId, tagId);
          window.dispatchEvent(new CustomEvent("omnirss:tags-updated"));
          window.dispatchEvent(new CustomEvent("omnirss:refresh-all"));

          // 更新當前文章在 store 內的標籤清單
          const articles = store.get("articles") || [];
          const art = articles.find((a) => a.id === articleId);
          if (art && res.tags) {
            art.tags = res.tags;
            store.set("articles", [...articles]);
          }
          const selectedArticle = store.get("selectedArticle");
          if (selectedArticle && selectedArticle.id === articleId) {
            selectedArticle.tags = res.tags || [];
            store.set("selectedArticle", { ...selectedArticle });
          }

          const actionName = res.is_tagged ? t("tags.tag_attached") : t("tags.tag_removed");
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: `${actionName}：${tagName}`, type: "info" }
          }));

          // 動態切換項目背景色彩
          const labelItem = checkbox.closest(".article-tag-checkbox-item");
          if (labelItem) {
            labelItem.style.background = checkbox.checked ? "rgba(59, 130, 246, 0.08)" : "transparent";
          }
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("tags.attach_failed", { error: err.message }), type: "error" }
          }));
          checkbox.checked = !checkbox.checked; // 復原勾選狀態
        }
      });
    }
  };

  /**
   * 開啟文章標籤指派彈窗
   * @param {number} articleId 目標文章 ID
   */
  proto.openArticleTagsModal = async function (articleId) {
    if (!articleId) return;
    this._currentArticleTagModalId = articleId;

    const articles = store.get("articles") || [];
    const currentSelected = store.get("selectedArticle");
    const art = (currentSelected && currentSelected.id === articleId) ? currentSelected : (articles.find((a) => a.id === articleId) || {});
    const title = art.title || t("tags.current_article");
    const subtitle = document.getElementById("article-tags-modal-subtitle");
    if (subtitle) {
      subtitle.textContent = t("tags.modal_subtitle", { name: title.length > 25 ? title.slice(0, 25) + "..." : title });
    }

    // 確保標籤資料最新
    try {
      const tags = await api.getTags();
      store.set("tags", tags || []);
    } catch (_) {}

    this.renderArticleTagsCheckboxes(articleId);
    this.openModal("modal-article-tags");
  };

  /**
   * 渲染文章標籤勾選清單
   * @param {number} articleId 目標文章 ID
   */
  proto.renderArticleTagsCheckboxes = function (articleId) {
    const container = document.getElementById("article-tags-checkboxes-container");
    if (!container) return;

    const tags = store.get("tags") || [];
    const articles = store.get("articles") || [];
    const currentSelected = store.get("selectedArticle");
    const art = (currentSelected && currentSelected.id === articleId) ? currentSelected : (articles.find((a) => a.id === articleId) || {});

    const artTagIds = new Set();
    const artTagNames = new Set();
    if (art && Array.isArray(art.tags)) {
      art.tags.forEach((tagItem) => {
        if (typeof tagItem === "object" && tagItem !== null) {
          if (tagItem.id) artTagIds.add(tagItem.id);
          if (tagItem.name) artTagNames.add(tagItem.name);
        } else if (typeof tagItem === "string" || typeof tagItem === "number") {
          artTagNames.add(String(tagItem));
          artTagIds.add(Number(tagItem));
        }
      });
    }

    if (tags.length === 0) {
      container.innerHTML = `<div style="color: var(--text-muted); font-size: 12px; padding: 12px; text-align: center;">${t("tags.empty_dialog_hint")}</div>`;
      return;
    }

    container.innerHTML = tags.map((tag) => {
      const isChecked = artTagIds.has(tag.id) || artTagNames.has(tag.name);
      return `
        <label class="article-tag-checkbox-item" style="display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; border-radius: 4px; cursor: pointer; user-select: none; background: ${isChecked ? "rgba(59, 130, 246, 0.08)" : "transparent"};">
          <div style="display: flex; align-items: center; gap: 8px;">
            <input type="checkbox" class="article-tag-checkbox" data-tag-id="${tag.id}" data-tag-name="${this.escape(tag.name)}" ${isChecked ? "checked" : ""} style="cursor: pointer;" />
            <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: ${tag.color_hex || "#3b82f6"};"></span>
            <span style="font-size: 13px; font-weight: 500; color: var(--text-primary);">${this.escape(tag.name)}</span>
          </div>
          <span style="font-size: 11px; color: var(--text-muted);">${t("tags.article_count_fmt", { count: tag.article_count || 0 })}</span>
        </label>
      `;
    }).join("");
  };
}
