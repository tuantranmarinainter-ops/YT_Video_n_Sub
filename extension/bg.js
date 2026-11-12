// Nền: mở bảng quét trên tab, chuyển tiếp lệnh tới app YTSub PC (http://127.0.0.1:8765).
const APP = "http://127.0.0.1:8765";

async function callApp(path, body) {
  try {
    const r = await fetch(APP + path, body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-YTSub": "1" },
      body: JSON.stringify(body),
    });
    return await r.json();
  } catch (e) {
    return { error: "offline" };
  }
}

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id) return;
  await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["panel.js"] });
});

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type === "api") { callApp(msg.path, msg.body).then(reply); return true; }
  if (msg.type === "openApp") { chrome.tabs.create({ url: APP + "/" }); }
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "ytsub-link", title: "Gửi link này vào YTSub", contexts: ["link"],
    targetUrlPatterns: ["*://*.youtube.com/watch*", "*://*.youtube.com/shorts/*", "*://youtu.be/*"],
  });
  chrome.contextMenus.create({
    id: "ytsub-page", title: "Gửi video đang xem vào YTSub", contexts: ["page"],
    documentUrlPatterns: ["*://*.youtube.com/watch*", "*://*.youtube.com/shorts/*"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const url = info.menuItemId === "ytsub-link" ? info.linkUrl : info.pageUrl;
  const r = await callApp("/api/inbox", { items: [{ url, title: info.menuItemId === "ytsub-page" ? tab.title : "" }], source: "menu" });
  const ok = !r.error;
  chrome.action.setBadgeBackgroundColor({ color: ok ? "#3ecf8e" : "#ff4d4d" });
  chrome.action.setBadgeText({ text: ok ? "✓" : "!" });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 2000);
});
