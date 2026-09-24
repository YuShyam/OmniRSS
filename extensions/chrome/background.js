/**
 * OmniRSS Chrome Extension 後台背景服務 (Background Service Worker).
 *
 * Handles periodic Edge Relay polling alarms, context menu creation, and article push relaying.
 */

const DEFAULT_SERVER_URL = "http://localhost:8000";
const ALARM_NAME = "omnirss_edge_relay_alarm";

// 擴充套件安裝或啟動時初始化
chrome.runtime.onInstalled.addListener(async () => {
  console.log("OmniRSS Extension Installed.");
  const config = await chrome.storage.sync.get(["serverUrl", "apiKey", "enableRelay", "relayIntervalMin"]);
  
  if (!config.serverUrl) {
    await chrome.storage.sync.set({
      serverUrl: DEFAULT_SERVER_URL,
      apiKey: "",
      enableRelay: true,
      relayIntervalMin: 30,
    });
  }

  setupRelayAlarm(config.relayIntervalMin || 30);
});

// 設定定時鬧鐘
function setupRelayAlarm(intervalMinutes) {
  chrome.alarms.clear(ALARM_NAME, () => {
    chrome.alarms.create(ALARM_NAME, {
      periodInMinutes: Math.max(5, intervalMinutes),
    });
    console.log(`Edge Relay alarm scheduled every ${intervalMinutes} minutes.`);
  });
}

// 監聽定時鬧鐘觸發邊緣中繼
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === ALARM_NAME) {
    const config = await chrome.storage.sync.get(["serverUrl", "apiKey", "enableRelay"]);
    if (config.enableRelay && config.serverUrl && config.apiKey) {
      console.log("Triggering periodic Edge Relay...");
      await executeEdgeRelay(config.serverUrl, config.apiKey);
    }
  }
});

// 執行邊緣中繼 (Edge Relay Engine)
async function executeEdgeRelay(serverUrl, apiKey) {
  try {
    const baseUrl = serverUrl.replace(/\/+$/, "");
    const tasksRes = await fetch(`${baseUrl}/api/feeds/edge-tasks`, {
      headers: { "X-API-Key": apiKey },
    });

    if (!tasksRes.ok) {
      console.warn(`Edge Relay failed to get tasks: HTTP ${tasksRes.status}`);
      return { success: false, error: `HTTP ${tasksRes.status}` };
    }

    const tasks = await tasksRes.json();
    if (!Array.isArray(tasks) || tasks.length === 0) {
      return { success: true, count: 0, message: "無待中繼之頻道" };
    }

    let successCount = 0;
    for (const task of tasks) {
      try {
        console.log(`Relaying feed: ${task.title} (${task.feed_url})`);
        const feedRes = await fetch(task.feed_url, {
          headers: {
            "User-Agent": navigator.userAgent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
          },
        });

        if (feedRes.ok) {
          const rawXml = await feedRes.text();
          const ingestRes = await fetch(`${baseUrl}/api/feeds/${task.feed_id}/ingest`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-API-Key": apiKey,
            },
            body: JSON.stringify({ feed_id: task.feed_id, raw_xml: rawXml }),
          });

          if (ingestRes.ok) {
            successCount += 1;
          }
        }
      } catch (feedErr) {
        console.warn(`Relay failed for feed ${task.feed_id}:`, feedErr);
      }
    }

    return { success: true, count: successCount, total: tasks.length };
  } catch (err) {
    console.error("Execute Edge Relay critical error:", err);
    return { success: false, error: err.message };
  }
}

// 監聽來自 Popup 的執行請求
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "RUN_EDGE_RELAY_NOW") {
    chrome.storage.sync.get(["serverUrl", "apiKey"]).then(async (config) => {
      const res = await executeEdgeRelay(config.serverUrl || DEFAULT_SERVER_URL, config.apiKey || "");
      sendResponse(res);
    });
    return true;
  } else if (request.action === "UPDATE_ALARM_INTERVAL") {
    setupRelayAlarm(request.intervalMinutes || 30);
    sendResponse({ success: true });
  }
  return true;
});
