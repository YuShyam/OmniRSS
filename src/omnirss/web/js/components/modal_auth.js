/**
 * OmniRSS 認證登入對話框模組 (Authentication Modal Module).
 */

import { store } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";

export function registerAuthModal(proto) {
  /**
   * 綁定登入認證彈窗與表單事件
   */
  proto.bindAuth = function () {
    window.addEventListener("omnirss:auth-required", () => {
      const errEl = document.getElementById("login-error");
      if (errEl) errEl.style.display = "none";
      this.openModal("modal-login");
    });

    const formLogin = document.getElementById("form-login");
    if (formLogin) {
      formLogin.addEventListener("submit", async (e) => {
        e.preventDefault();
        const uInput = document.getElementById("login-username");
        const pInput = document.getElementById("login-password");
        const u = uInput ? uInput.value.trim() : "";
        const p = pInput ? pInput.value : "";
        const errEl = document.getElementById("login-error");
        const submitBtn = document.getElementById("btn-submit-login");

        if (!u || !p) {
          if (errEl) {
            errEl.textContent = !u ? (t("auth.enter_username") || "請輸入使用者名稱") : (t("auth.enter_password") || "請輸入密碼");
            errEl.style.display = "block";
          }
          return;
        }

        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.dataset.origText = submitBtn.textContent;
          submitBtn.textContent = t("common.loading") || "登入中...";
        }

        try {
          const res = await api.login(u, p);
          store.set("token", res.access_token);
          this.closeModal("modal-login");
          if (errEl) errEl.style.display = "none";
          window.dispatchEvent(new CustomEvent("omnirss:auth-success"));
        } catch (err) {
          if (errEl) {
            errEl.textContent = err.message || t("auth.login_failed") || "登入失敗，請檢查使用者名稱或密碼";
            errEl.style.display = "block";
          }
        } finally {
          if (submitBtn) {
            submitBtn.disabled = false;
            if (submitBtn.dataset.origText) {
              submitBtn.textContent = submitBtn.dataset.origText;
            }
          }
        }
      });
    }
  };
}
