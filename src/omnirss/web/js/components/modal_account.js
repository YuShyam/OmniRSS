/**
 * OmniRSS 使用者帳號與權限管理對話框模組 (User Account & Permissions Modal Module).
 */

import { store, safeInputVal } from "../state.js";
import { api } from "../api_client.js";
import { t } from "../i18n.js";

export function registerAccountModal(proto) {
  /**
   * 開啟使用者個人帳號與系統管理中心彈窗
   * @param {string} targetTabId 目標分頁 ID (預設 tab-account-security)
   */
  proto.openAccountModal = async function (targetTabId = "tab-account-security") {
    const modalAccount = document.getElementById("modal-account");
    if (!modalAccount) return;

    const user = store.get("user") || {};
    const username = safeInputVal(user.username) || "User";
    const isAdmin = Boolean(user.is_admin);

    // 1. 更新個人資訊橫幅卡片
    const avatarInitial = document.getElementById("account-avatar-initial");
    const usernameDisplay = document.getElementById("account-current-username");
    const roleBadge = document.getElementById("account-current-role-badge");
    const createdAtDisplay = document.getElementById("account-created-at-display");
    const apiKeyInput = document.getElementById("input-account-api-key");

    if (avatarInitial) avatarInitial.textContent = username.charAt(0).toUpperCase();
    if (usernameDisplay) usernameDisplay.textContent = username;
    if (roleBadge) {
      roleBadge.textContent = isAdmin ? t("users.role_admin") : t("users.role_user");
      roleBadge.className = `badge-role-pill ${isAdmin ? "admin" : "user"}`;
    }
    if (createdAtDisplay) {
      const createdStr = user.created_at ? new Date(user.created_at).toLocaleString() : "-";
      createdAtDisplay.textContent = `${t("users.col_created")}: ${createdStr}`;
    }
    if (apiKeyInput) {
      apiKeyInput.value = safeInputVal(user.api_key);
    }

    // 2. 權限控制：僅 Admin 能看見「👥 使用者管理」與「📋 系統日誌」Tab
    const userMgmtTabBtn = document.getElementById("tab-btn-user-management");
    const systemLogsTabBtn = document.getElementById("tab-btn-system-logs");
    if (userMgmtTabBtn) userMgmtTabBtn.style.display = isAdmin ? "inline-flex" : "none";
    if (systemLogsTabBtn) systemLogsTabBtn.style.display = isAdmin ? "inline-flex" : "none";

    // 若非 Admin 嘗試切到管理分頁，自動回退至帳號安全
    let activeTabId = targetTabId;
    if (!isAdmin && (activeTabId === "tab-user-management" || activeTabId === "tab-system-logs")) {
      activeTabId = "tab-account-security";
    }

    // 3. 切換 Tab 按鈕與內容面板
    modalAccount.querySelectorAll(".modal-tab-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === activeTabId);
    });
    modalAccount.querySelectorAll(".modal-tab-content").forEach((c) => {
      c.classList.toggle("active", c.id === activeTabId);
    });

    // 4. 若進入相應分頁，自動拉取資料
    if (activeTabId === "tab-user-management" && isAdmin) {
      await this.loadUsersList();
    } else if (activeTabId === "tab-system-logs" && isAdmin) {
      await this.loadSystemLogs("all");
    }

    // 5. 重置密碼變更表單
    const formChangePwd = document.getElementById("form-change-password");
    if (formChangePwd) formChangePwd.reset();

    this.openModal("modal-account");
  };

  /**
   * 載入並渲染系統資安與稽核日誌 (Admin Only - 去味大師風格)
   * @param {string} category 篩選分類 (all, security, error)
   */
  proto.loadSystemLogs = async function (category = "all") {
    const container = document.getElementById("system-logs-container");
    if (!container) return;

    container.innerHTML = `<div style="color: var(--text-muted); text-align: center; padding: 20px;">載入日誌中...</div>`;

    try {
      const res = await api.getSystemLogs(category);
      const logs = res?.logs || [];

      if (logs.length === 0) {
        container.innerHTML = `<div style="color: var(--text-muted); text-align: center; padding: 20px;">尚無相關系統日誌紀錄</div>`;
        return;
      }

      container.innerHTML = logs.map((log) => {
        let style = "color: var(--text-secondary);";
        let badge = "";
        
        if (log.level === "ALERT" || log.raw.includes("[SECURITY")) {
          style = "color: #f87171; font-weight: 600; background: rgba(239, 68, 68, 0.1); padding: 2px 6px; border-radius: 4px;";
          badge = `<span style="background: #ef4444; color: #fff; padding: 1px 5px; border-radius: 3px; font-size: 10px; margin-right: 6px;">登入警示</span>`;
        } else if (log.level === "ERROR") {
          style = "color: #fca5a5;";
          badge = `<span style="background: #dc2626; color: #fff; padding: 1px 5px; border-radius: 3px; font-size: 10px; margin-right: 6px;">系統異常</span>`;
        } else if (log.level === "WARNING") {
          style = "color: #fbbf24;";
          badge = `<span style="background: #d97706; color: #fff; padding: 1px 5px; border-radius: 3px; font-size: 10px; margin-right: 6px;">警示</span>`;
        }

        return `<div style="margin-bottom: 4px; border-bottom: 1px dashed rgba(255,255,255,0.05); padding-bottom: 3px; ${style}">${badge}${this.escape(log.raw)}</div>`;
      }).join("");

    } catch (err) {
      container.innerHTML = `<div style="color: #ef4444; text-align: center; padding: 16px;">讀取日誌失敗: ${this.escape(err.message)}</div>`;
    }
  };

  /**
   * 載入並渲染多使用者管理名冊表格 (Admin Only)
   */
  proto.loadUsersList = async function () {
    const tbody = document.getElementById("users-table-tbody");
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; padding: 24px; color: var(--text-muted);">${t("common.loading") || "載入中..."}</td></tr>`;

    try {
      const users = await api.getUsers();
      const currentUser = store.get("user") || {};

      const countBadge = document.getElementById("users-count-badge");
      if (countBadge) {
        countBadge.textContent = t("users.count_badge", { count: users?.length || 0 });
        countBadge.style.display = "inline-flex";
      }

      if (!users || users.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; padding: 24px; color: var(--text-muted);">${t("users.empty_list")}</td></tr>`;
        return;
      }

      tbody.innerHTML = users.map((u) => {
        const isSelf = u.id === currentUser.id;
        const initial = (u.username || "U").charAt(0).toUpperCase();
        const roleLabel = u.is_admin ? t("users.role_admin") : t("users.role_user");
        const roleBadgeClass = u.is_admin ? "admin" : "user";
        const createdStr = u.created_at ? new Date(u.created_at).toLocaleDateString() : "-";
        const countsStr = `${u.feed_count ?? 0} / ${u.unread_count ?? 0}`;

        return `
          <tr>
            <td>
              <div class="col-user-info">
                <div class="user-avatar-sm">${initial}</div>
                <div class="user-name-text">
                  <span>${this.escape(u.username)}</span>
                  ${isSelf ? `<span class="badge-current-user">${t("users.current_user")}</span>` : ""}
                </div>
              </div>
            </td>
            <td style="text-align: center;">
              <span class="badge-role-pill ${roleBadgeClass}">${roleLabel}</span>
            </td>
            <td style="text-align: center; color: var(--text-secondary); font-family: var(--font-mono); font-size: 11px;">
              ${countsStr}
            </td>
            <td style="text-align: center; color: var(--text-muted); font-size: 11px;">
              ${createdStr}
            </td>
            <td style="text-align: right;">
              <div class="user-action-group">
                <button type="button" class="btn-user-action btn-user-reset-pwd" data-id="${u.id}" data-username="${this.escape(u.username)}" title="${t("users.action_reset_pwd")}">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="7.5" cy="7.5" r="3.5"/><path d="M21 2l-2 2m-1.5 1.5L10 13m-2 2H4v4h4l1-1m2-2l3-3"/></svg>
                  <span>${t("users.action_reset_pwd")}</span>
                </button>
                <button type="button" class="btn-user-action btn-user-toggle-role" data-id="${u.id}" data-username="${this.escape(u.username)}" data-admin="${u.is_admin ? "true" : "false"}" ${isSelf ? "disabled" : ""} title="${t("users.action_toggle_role")}">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                  <span>${u.is_admin ? t("users.action_demote") : t("users.action_promote")}</span>
                </button>
                <button type="button" class="btn-user-action btn-action-danger btn-user-delete" data-id="${u.id}" data-username="${this.escape(u.username)}" ${isSelf ? "disabled" : ""} title="${t("users.action_delete")}">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                  <span>${t("users.action_delete")}</span>
                </button>
              </div>
            </td>
          </tr>
        `;
      }).join("");

      // 綁定名冊表格按鈕事件
      tbody.querySelectorAll(".btn-user-reset-pwd").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const userId = parseInt(btn.dataset.id, 10);
          const username = btn.dataset.username;
          const newPassword = prompt(t("users.prompt_new_pwd", { username }));
          if (newPassword === null) return;
          if (newPassword.trim().length < 6) {
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: t("users.pwd_too_short"), type: "error" }
            }));
            return;
          }
          try {
            await api.updateUser(userId, { password: newPassword.trim() });
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: t("users.pwd_reset_success", { username }), type: "success" }
            }));
          } catch (err) {
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: t("users.pwd_reset_failed", { error: err.message }), type: "error" }
            }));
          }
        });
      });

      tbody.querySelectorAll(".btn-user-toggle-role").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const userId = parseInt(btn.dataset.id, 10);
          const username = btn.dataset.username;
          const isCurrentlyAdmin = btn.dataset.admin === "true";
          const newRoleIsAdmin = !isCurrentlyAdmin;
          const actionMsg = newRoleIsAdmin ? t("users.confirm_promote", { username }) : t("users.confirm_demote", { username });

          if (!confirm(actionMsg)) return;

          try {
            await api.updateUser(userId, { is_admin: newRoleIsAdmin });
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: t("users.role_update_success", { username }), type: "success" }
            }));
            await this.loadUsersList();
          } catch (err) {
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: t("users.role_update_failed", { error: err.message }), type: "error" }
            }));
          }
        });
      });

      tbody.querySelectorAll(".btn-user-delete").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const userId = parseInt(btn.dataset.id, 10);
          const username = btn.dataset.username;
          if (!confirm(t("users.confirm_delete", { username }))) return;

          try {
            await api.deleteUser(userId);
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: t("users.delete_success", { username }), type: "success" }
            }));
            await this.loadUsersList();
          } catch (err) {
            window.dispatchEvent(new CustomEvent("omnirss:toast", {
              detail: { message: t("users.delete_failed", { error: err.message }), type: "error" }
            }));
          }
        });
      });

    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; padding: 18px; color: #ef4444;">${t("users.load_failed", { error: err.message })}</td></tr>`;
    }
  };

  /**
   * 綁定使用者帳號與權限管理彈窗表單事件
   */
  proto.bindAccount = function () {
    const modalAccount = document.getElementById("modal-account");
    if (!modalAccount) return;

    // 1. Tab 切換事件
    modalAccount.querySelectorAll(".modal-tab-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const targetTab = btn.dataset.tab;
        modalAccount.querySelectorAll(".modal-tab-btn").forEach((b) => b.classList.remove("active"));
        modalAccount.querySelectorAll(".modal-tab-content").forEach((c) => c.classList.remove("active"));
        btn.classList.add("active");
        const contentEl = document.getElementById(targetTab);
        if (contentEl) contentEl.classList.add("active");

        if (targetTab === "tab-user-management") {
          await this.loadUsersList();
        } else if (targetTab === "tab-system-logs") {
          await this.loadSystemLogs("all");
        }
      });
    });

    // 1.5 日誌動態篩選按鈕事件
    modalAccount.querySelectorAll(".btn-log-filter").forEach((btn) => {
      btn.addEventListener("click", async () => {
        modalAccount.querySelectorAll(".btn-log-filter").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        const filter = btn.dataset.filter || "all";
        await this.loadSystemLogs(filter);
      });
    });

    const btnRefreshLogs = document.getElementById("btn-refresh-system-logs");
    if (btnRefreshLogs) {
      btnRefreshLogs.addEventListener("click", async () => {
        const activeFilterBtn = modalAccount.querySelector(".btn-log-filter.active");
        const filter = activeFilterBtn?.dataset.filter || "all";
        await this.loadSystemLogs(filter);
      });
    }

    // 2. 變更密碼表單提交
    const formChangePassword = document.getElementById("form-change-password");
    if (formChangePassword) {
      formChangePassword.addEventListener("submit", async (e) => {
        e.preventDefault();
        const oldPwd = document.getElementById("input-account-old-pwd")?.value || "";
        const newPwd = document.getElementById("input-account-new-pwd")?.value || "";
        const confirmPwd = document.getElementById("input-account-confirm-pwd")?.value || "";

        if (newPwd.length < 6) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("account.pwd_too_short"), type: "error" }
          }));
          return;
        }

        if (newPwd !== confirmPwd) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("account.pwd_mismatch"), type: "error" }
          }));
          return;
        }

        try {
          await api.changePassword(oldPwd, newPwd);
          formChangePassword.reset();
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("account.pwd_change_success"), type: "success" }
          }));
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("account.pwd_change_failed", { error: err.message }), type: "error" }
          }));
        }
      });
    }

    // 3. API 金鑰複製與重新產生
    const btnCopyApiKey = document.getElementById("btn-account-copy-api-key");
    if (btnCopyApiKey) {
      btnCopyApiKey.addEventListener("click", () => {
        const keyInput = document.getElementById("input-account-api-key");
        if (keyInput && keyInput.value) {
          navigator.clipboard.writeText(keyInput.value);
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("settings.copied"), type: "success" }
          }));
        }
      });
    }

    const btnRegenApiKey = document.getElementById("btn-account-regen-api-key");
    if (btnRegenApiKey) {
      btnRegenApiKey.addEventListener("click", async () => {
        if (!confirm(t("settings.confirm_regen_api_key"))) return;
        try {
          const res = await api.regenerateApiKey();
          const keyInput = document.getElementById("input-account-api-key");
          if (keyInput) keyInput.value = safeInputVal(res?.api_key);
          const user = store.get("user");
          if (user) user.api_key = safeInputVal(res?.api_key);
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("settings.api_key_regen_success"), type: "success" }
          }));
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("settings.api_key_regen_failed", { error: err.message }), type: "error" }
          }));
        }
      });
    }

    // 4. 管理員新增使用者表單提交
    const formAdminCreateUser = document.getElementById("form-admin-create-user");
    if (formAdminCreateUser) {
      formAdminCreateUser.addEventListener("submit", async (e) => {
        e.preventDefault();
        const usernameInput = document.getElementById("input-admin-new-username");
        const passwordInput = document.getElementById("input-admin-new-password");
        const roleSelect = document.getElementById("select-admin-new-role");

        const username = usernameInput?.value.trim() || "";
        const password = passwordInput?.value.trim() || "";
        const isAdmin = roleSelect?.value === "admin";

        if (!username || !password) return;
        if (password.length < 6) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("users.pwd_too_short"), type: "error" }
          }));
          return;
        }

        try {
          await api.createUser({ username, password, is_admin: isAdmin });
          formAdminCreateUser.reset();
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("users.create_success", { username }), type: "success" }
          }));
          await this.loadUsersList();
        } catch (err) {
          window.dispatchEvent(new CustomEvent("omnirss:toast", {
            detail: { message: t("users.create_failed", { error: err.message }), type: "error" }
          }));
        }
      });
    }

    // 5. 重新整理使用者名冊
    const btnRefreshUsers = document.getElementById("btn-refresh-users-list");
    if (btnRefreshUsers) {
      btnRefreshUsers.addEventListener("click", () => {
        this.loadUsersList();
      });
    }
  };
}
