/**
 * OmniRSS Chrome Extension 設定頁面邏輯 (Options Script).
 */

document.addEventListener("DOMContentLoaded", async () => {
  const serverUrlInput = document.getElementById("server-url");
  const apiKeyInput = document.getElementById("api-key");
  const intervalSelect = document.getElementById("relay-interval");
  const btnSave = document.getElementById("btn-save");
  const statusMsg = document.getElementById("status-msg");

  // 1. 載入現有設定
  const config = await chrome.storage.sync.get(["serverUrl", "apiKey", "relayIntervalMin"]);
  serverUrlInput.value = config.serverUrl || "http://localhost:8000";
  apiKeyInput.value = config.apiKey || "";
  intervalSelect.value = String(config.relayIntervalMin || 30);

  // 2. 儲存設定
  btnSave.addEventListener("click", async () => {
    const serverUrl = serverUrlInput.value.trim() || "http://localhost:8000";
    const apiKey = apiKeyInput.value.trim();
    const intervalMin = parseInt(intervalSelect.value, 10) || 30;

    await chrome.storage.sync.set({
      serverUrl,
      apiKey,
      relayIntervalMin: intervalMin,
    });

    // 通知後台更新 Alarm 週期
    chrome.runtime.sendMessage({
      action: "UPDATE_ALARM_INTERVAL",
      intervalMinutes: intervalMin,
    });

    statusMsg.textContent = "✅ 設定已成功儲存！";
    statusMsg.className = "status-msg success";
    setTimeout(() => {
      statusMsg.className = "status-msg";
    }, 3000);
  });
});
