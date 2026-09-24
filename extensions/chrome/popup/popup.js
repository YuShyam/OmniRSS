/**
 * OmniRSS Chrome Extension 彈窗互動邏輯 (Popup Script).
 */

document.addEventListener("DOMContentLoaded", async () => {
  const connBadge = document.getElementById("conn-badge");
  const previewTitle = document.getElementById("preview-title");
  const previewUrl = document.getElementById("preview-url");
  const btnClip = document.getElementById("btn-clip-page");
  const btnRelay = document.getElementById("btn-edge-relay");
  const toastEl = document.getElementById("toast-msg");

  let extractedData = null;

  // 1. 讀取擴充套件設定
  const config = await chrome.storage.sync.get(["serverUrl", "apiKey"]);
  const serverUrl = (config.serverUrl || "http://localhost:8000").replace(/\/+$/, "");
  const apiKey = config.apiKey || "";

  // 2. 檢驗後端連線狀態
  try {
    const healthRes = await fetch(`${serverUrl}/api/health`);
    if (healthRes.ok) {
      connBadge.textContent = "已連線";
      connBadge.className = "status-pill connected";
    } else {
      connBadge.textContent = "伺服器異常";
      connBadge.className = "status-pill error";
    }
  } catch (_) {
    connBadge.textContent = "未連線";
    connBadge.className = "status-pill error";
  }

  // 3. 向當前活動分頁請求中繼資料
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab && tab.id) {
      previewTitle.textContent = tab.title || "未知標題";
      previewUrl.textContent = tab.url || "";

      chrome.tabs.sendMessage(tab.id, { action: "EXTRACT_PAGE_DATA" }, (res) => {
        if (chrome.runtime.lastError || !res || !res.success) {
          // Fallback 使用分頁標題與 URL
          extractedData = {
            url: tab.url,
            title: tab.title,
            html_content: `<p><a href="${tab.url}">${tab.title}</a></p>`,
            snippet: tab.title,
            author: null,
            cover_image_url: null,
          };
        } else {
          extractedData = res.data;
          previewTitle.textContent = extractedData.title;
        }
      });
    }
  } catch (err) {
    previewTitle.textContent = "無法擷取此分頁 (受瀏覽器安全限制)";
  }

  function showToast(msg, isSuccess = true) {
    toastEl.textContent = msg;
    toastEl.className = `toast-msg ${isSuccess ? "success" : "error"}`;
    setTimeout(() => {
      toastEl.className = "toast-msg";
    }, 4000);
  }

  // 4. 快剪按鈕事件
  btnClip.addEventListener("click", async () => {
    if (!extractedData || !extractedData.url) {
      showToast("無法取得網頁資料", false);
      return;
    }

    if (!apiKey) {
      showToast("請先至設定頁填寫 API Key", false);
      return;
    }

    btnClip.disabled = true;
    btnClip.textContent = "存入中...";

    try {
      const res = await fetch(`${serverUrl}/api/articles/push`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
        body: JSON.stringify({
          url: extractedData.url,
          title: extractedData.title,
          html_content: extractedData.html_content || `<p>${extractedData.snippet}</p>`,
          author: extractedData.author,
          cover_image_url: extractedData.cover_image_url,
        }),
      });

      if (res.ok) {
        showToast("🎉 已成功剪藏至 OmniRSS！", true);
      } else {
        const errJson = await res.json().catch(() => ({}));
        showToast(`剪藏失敗: ${errJson.detail || "HTTP " + res.status}`, false);
      }
    } catch (err) {
      showToast(`連線失敗: ${err.message}`, false);
    } finally {
      btnClip.disabled = false;
      btnClip.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
        <span>📌 存入 OmniRSS</span>
      `;
    }
  });

  // 5. 邊緣中繼手動觸發
  btnRelay.addEventListener("click", () => {
    btnRelay.disabled = true;
    btnRelay.textContent = "中繼執行中...";

    chrome.runtime.sendMessage({ action: "RUN_EDGE_RELAY_NOW" }, (res) => {
      btnRelay.disabled = false;
      btnRelay.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
        <span>🔄 立即執行邊緣中繼</span>
      `;

      if (res && res.success) {
        showToast(`中繼完成: 成功抓取 ${res.count || 0} 個頻道`, true);
      } else {
        showToast(`中繼失敗: ${res ? res.error : "未知錯誤"}`, false);
      }
    });
  });
});
