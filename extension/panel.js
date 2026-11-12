// Bảng nổi trên trang YouTube: quét link video/Shorts, tự cuộn, chọn, gửi vào app.
(() => {
  const HOST_ID = "ytsub-panel-host";
  const old = document.getElementById(HOST_ID);
  if (old) { old.remove(); window.__ytsubStop = true; return; } // bấm lần nữa = đóng

  const api = (path, body) => new Promise((res) => chrome.runtime.sendMessage({ type: "api", path, body }, res));
  const items = new Map(); // id -> {id,url,title,short}
  const sel = new Set();
  let scrolling = false;

  // ---------- giao diện (shadow DOM để không bị CSS YouTube ảnh hưởng)
  const host = document.createElement("div");
  host.id = HOST_ID;
  host.style.cssText = "position:fixed;top:64px;right:16px;z-index:2147483647";
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `
<style>
*{box-sizing:border-box;font-family:"Segoe UI",system-ui,sans-serif}
.p{width:380px;max-height:calc(100vh - 90px);display:flex;flex-direction:column;background:#171a21;color:#e8eaf0;border:1px solid #2b3140;border-radius:12px;box-shadow:0 12px 40px #0008;font-size:13px}
.hd{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid #2b3140;cursor:move}
.hd b{font-size:14px}.hd b i{color:#ff4d4d;font-style:normal}
.st{font-size:11.5px;color:#8b93a7;margin-left:auto}.st.on{color:#3ecf8e}.st.off{color:#ff6b6b}
.x{background:none;border:0;color:#8b93a7;font-size:18px;cursor:pointer;padding:0 2px}
.bd{padding:10px 12px;display:flex;flex-direction:column;gap:8px;min-height:0}
.row{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
button{background:#232836;color:#e8eaf0;border:1px solid #2b3140;border-radius:7px;padding:6px 10px;font-size:12.5px;cursor:pointer}
button:hover{border-color:#4b5568}button:disabled{opacity:.5;cursor:default}
button.pri{background:#ff4d4d;border-color:#ff4d4d;color:#fff;font-weight:600}
button.sm{padding:3px 8px;font-size:12px}
input[type=text],input[type=number]{background:#0c0e12;color:#e8eaf0;border:1px solid #2b3140;border-radius:7px;padding:5px 8px;font-size:12.5px}
label{display:flex;align-items:center;gap:4px;font-size:12px;color:#c9cfdc;cursor:pointer}
input[type=checkbox]{accent-color:#ff4d4d}
.list{overflow:auto;min-height:80px;max-height:46vh;border:1px solid #2b3140;border-radius:8px;background:#0c0e12}
.it{display:flex;gap:8px;align-items:center;padding:5px 8px;border-bottom:1px solid #1b1f28;cursor:pointer}
.it:hover{background:#151922}
.it .t{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tag{font-size:10px;padding:0 5px;border-radius:4px;background:#3a2430;color:#ff9db0}
.empty{color:#8b93a7;padding:18px;text-align:center}
.msg{font-size:12px;color:#8b93a7;min-height:16px}
.cnt{margin-left:auto;font-size:12px;color:#8b93a7}
</style>
<div class="p">
  <div class="hd" id="drag"><b>YT<i>Sub</i></b> lấy link<span class="st" id="st">…</span><button class="x" id="close" title="Đóng">×</button></div>
  <div class="bd">
    <div class="row">
      <button id="scan">Quét trang</button>
      <button id="auto">⇣ Tự cuộn lấy hết</button>
      <label title="Dừng tự cuộn khi đủ số này (để trống = lấy hết)">Tối đa <input type="number" id="max" min="1" placeholder="tất cả" style="width:72px"></label>
    </div>
    <div class="row">
      <input type="text" id="q" placeholder="Lọc theo tên…" style="flex:1">
      <label><input type="checkbox" id="fv" checked>Video</label>
      <label><input type="checkbox" id="fs" checked>Shorts</label>
    </div>
    <div class="row">
      <button class="sm" id="all">Chọn tất cả</button><button class="sm" id="none">Bỏ chọn</button>
      <button class="sm" id="first">Chọn N đầu</button>
      <button class="sm" id="clr">Xoá</button>
      <span class="cnt" id="cnt"></span>
    </div>
    <div class="list" id="list"><div class="empty">Bấm “Quét trang” hoặc “Tự cuộn lấy hết”.</div></div>
    <div class="row">
      <button class="pri" id="send" style="flex:1">Gửi vào YTSub</button>
      <button id="now" title="Thêm thẳng vào hàng đợi với cài đặt hiện tại của app">Gửi &amp; tải ngay</button>
      <button id="copy">Copy</button>
    </div>
    <div class="msg" id="msg"></div>
  </div>
</div>`;
  document.documentElement.appendChild(host);
  const $ = (s) => root.querySelector(s);
  const msg = (t) => { $("#msg").textContent = t; };

  // ---------- kéo thả bảng
  (() => {
    let sx, sy, ox, oy;
    $("#drag").addEventListener("mousedown", (e) => {
      if (e.target.closest("button")) return;
      sx = e.clientX; sy = e.clientY; const r = host.getBoundingClientRect(); ox = r.left; oy = r.top;
      const mv = (ev) => { host.style.left = ox + ev.clientX - sx + "px"; host.style.top = oy + ev.clientY - sy + "px"; host.style.right = "auto"; };
      const up = () => { removeEventListener("mousemove", mv); removeEventListener("mouseup", up); };
      addEventListener("mousemove", mv); addEventListener("mouseup", up);
    });
  })();

  // ---------- quét link
  const SKIP = "#masthead-container, ytd-guide-renderer, ytd-mini-guide-renderer, tp-yt-app-drawer, #ytsub-panel-host";
  const idOf = (href) => {
    const m = href.match(/[?&]v=([\w-]{11})/) || href.match(/\/shorts\/([\w-]{11})/) || href.match(/youtu\.be\/([\w-]{11})/);
    return m ? m[1] : null;
  };
  const isJunk = (t) => !t || /^\d{1,2}(:\d{2}){1,2}$/.test(t) || /^(SHORTS|LIVE|TRỰC TIẾP)$/i.test(t);
  function collect() {
    const before = items.size;
    for (const a of document.querySelectorAll('a[href*="/watch?v="], a[href*="/shorts/"]')) {
      if (a.closest(SKIP)) continue;
      const id = idOf(a.href);
      if (!id) continue;
      const short = a.href.includes("/shorts/");
      let title = (a.getAttribute("title") || a.textContent || "").replace(/\s+/g, " ").trim();
      if (isJunk(title)) title = (a.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim();
      if (isJunk(title)) title = "";
      const cur = items.get(id);
      if (!cur) {
        items.set(id, { id, short, title, url: short ? `https://www.youtube.com/shorts/${id}` : `https://www.youtube.com/watch?v=${id}` });
        sel.add(id);
      } else if (!cur.title && title) cur.title = title;
    }
    // trang đang xem cũng tính
    const self = idOf(location.href);
    if (self && !items.has(self)) {
      const short = location.pathname.startsWith("/shorts/");
      items.set(self, { id: self, short, title: document.title.replace(/ - YouTube$/, ""), url: short ? `https://www.youtube.com/shorts/${self}` : `https://www.youtube.com/watch?v=${self}` });
      sel.add(self);
    }
    render();
    return items.size - before;
  }

  const maxN = () => parseInt($("#max").value, 10) || 0;
  async function autoScroll() {
    if (scrolling) { scrolling = false; return; }
    scrolling = true; window.__ytsubStop = false;
    $("#auto").textContent = "■ Dừng";
    let idle = 0;
    while (scrolling && !window.__ytsubStop) {
      window.scrollTo(0, document.documentElement.scrollHeight);
      await new Promise((r) => setTimeout(r, 1300));
      const added = collect();
      msg(`Đang cuộn… đã có ${items.size} link`);
      if (maxN() && items.size >= maxN()) { msg(`Đủ ${maxN()} link.`); break; }
      const spinner = document.querySelector("ytd-continuation-item-renderer, tp-yt-paper-spinner[active]");
      idle = added ? 0 : idle + 1;
      if (idle >= (spinner ? 8 : 4)) { msg(`Đã hết trang · ${items.size} link.`); break; }
    }
    scrolling = false; $("#auto").textContent = "⇣ Tự cuộn lấy hết";
    if (maxN()) selectFirst();
    render();
  }

  // ---------- danh sách
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function visible() {
    const q = $("#q").value.toLowerCase().trim(), v = $("#fv").checked, s = $("#fs").checked;
    return [...items.values()].filter((i) => (i.short ? s : v) && (!q || (i.title || "").toLowerCase().includes(q)));
  }
  function render() {
    const vis = visible();
    $("#list").innerHTML = items.size
      ? vis.map((i) => `<label class="it" data-id="${i.id}"><input type="checkbox" ${sel.has(i.id) ? "checked" : ""}><span class="t" title="${esc(i.title)}">${esc(i.title || i.id)}</span>${i.short ? '<span class="tag">Shorts</span>' : ""}</label>`).join("") || '<div class="empty">Không có mục nào khớp bộ lọc.</div>'
      : '<div class="empty">Bấm “Quét trang” hoặc “Tự cuộn lấy hết”.</div>';
    const n = chosen().length;
    $("#cnt").textContent = `${n} chọn / ${items.size}`;
    ["#send", "#now", "#copy"].forEach((s) => ($(s).disabled = !n));
  }
  const chosen = () => visible().filter((i) => sel.has(i.id));
  function selectFirst() {
    const n = maxN() || 100;
    sel.clear(); visible().slice(0, n).forEach((i) => sel.add(i.id));
  }

  $("#list").addEventListener("change", (e) => {
    const id = e.target.closest(".it")?.dataset.id; if (!id) return;
    e.target.checked ? sel.add(id) : sel.delete(id); render();
  });
  ["#q", "#fv", "#fs"].forEach((s) => $(s).addEventListener("input", render));
  $("#scan").onclick = () => { const n = collect(); msg(`Thêm ${n} link (tổng ${items.size}). Cuộn xuống để tải thêm hoặc dùng “Tự cuộn”.`); };
  $("#auto").onclick = autoScroll;
  $("#all").onclick = () => { visible().forEach((i) => sel.add(i.id)); render(); };
  $("#none").onclick = () => { visible().forEach((i) => sel.delete(i.id)); render(); };
  $("#first").onclick = () => { selectFirst(); render(); msg(`Đã chọn ${chosen().length} mục đầu (đặt số ở ô “Tối đa”, mặc định 100).`); };
  $("#clr").onclick = () => { items.clear(); sel.clear(); render(); msg(""); };
  $("#close").onclick = () => { scrolling = false; host.remove(); };

  const payload = () => chosen().map((i) => ({ url: i.url, title: i.title, id: i.id, short: i.short }));
  $("#send").onclick = async () => {
    const r = await api("/api/inbox", { items: payload(), source: location.href });
    if (r?.error) return offline();
    msg(`✓ Đã gửi ${r.added} link mới vào app (mục “Từ extension”). Mở app để chọn cài đặt và tải.`);
  };
  $("#now").onclick = async () => {
    const r = await api("/api/enqueue", { items: payload() });
    if (r?.error) return offline();
    msg(`✓ Đã thêm ${r.added} video vào hàng đợi tải của app.`);
  };
  $("#copy").onclick = async () => {
    await navigator.clipboard.writeText(chosen().map((i) => i.url).join("\n"));
    msg(`✓ Đã copy ${chosen().length} link — dán vào ô “Thêm link” của app.`);
  };
  function offline() {
    msg("✗ Không kết nối được app. Hãy mở YTSub PC trước (hoặc dùng nút Copy).");
    status();
  }

  async function status() {
    const r = await api("/api/status");
    const st = $("#st");
    if (r && !r.error) { st.textContent = "● app đang chạy"; st.className = "st on"; }
    else { st.textContent = "● app chưa mở"; st.className = "st off"; }
  }
  status();
  collect();
})();
