"""HTTP server nội bộ (127.0.0.1) phục vụ giao diện web + API cho extension."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .engine import RES_DIR, APP_DIR, Engine, ffmpeg_path

PORT = 8765
VERSION = "1.0.0"
WEB_DIR = RES_DIR / "ytsub" / "web" if (RES_DIR / "ytsub" / "web").exists() else Path(__file__).parent / "web"


def extension_dir() -> Path:
    for p in (APP_DIR / "extension", RES_DIR / "extension"):
        if p.exists():
            return p
    return APP_DIR / "extension"


def open_path(p: str | Path, select: bool = False):
    p = str(p)
    if os.name == "nt":
        if select and os.path.isfile(p):
            subprocess.Popen(["explorer", "/select,", p])
        else:
            os.startfile(p if os.path.isdir(p) else os.path.dirname(p) or p)
    else:
        subprocess.Popen(["xdg-open", p if os.path.isdir(p) else os.path.dirname(p)])


def pick_dir(initial: str) -> str | None:
    result = {}

    def ui():
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        result["d"] = filedialog.askdirectory(initialdir=initial, title="Chọn thư mục lưu")
        root.destroy()

    t = threading.Thread(target=ui)
    t.start()
    t.join()
    return result.get("d") or None


def make_handler(engine: Engine):
    class H(BaseHTTPRequestHandler):
        server_version = "YTSubPC"

        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                return self._send(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/api/status":
                s = engine.settings.snapshot()
                return self._json({"app": "ytsub-pc", "version": VERSION, "ytdlp": engine.ytdlp_version,
                                   "ffmpeg": bool(ffmpeg_path()), "update": engine.update_msg, "settings": s,
                                   "stats": engine.stats(), "inbox_rev": engine.inbox_rev,
                                   "inbox_count": len(engine.inbox), "ext_dir": str(extension_dir())})
            if path == "/api/jobs":
                return self._json({"jobs": engine.jobs_json(), "stats": engine.stats()})
            if path == "/api/inbox":
                return self._json({"rev": engine.inbox_rev, "items": list(engine.inbox)})
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            # Chặn trang web lạ gọi vào: chỉ UI của app và extension mới gửi header này.
            if self.headers.get("X-YTSub") != "1":
                return self._json({"error": "forbidden"}, 403)
            path = urlparse(self.path).path
            try:
                b = self._body()
                if path == "/api/enqueue":
                    ids = engine.enqueue(b.get("items") or b.get("urls") or [], b.get("opts"))
                    return self._json({"ok": True, "added": len(ids), "ids": ids})
                if path == "/api/list":
                    return self._json(engine.list_url(b["url"]))
                if path == "/api/inbox":
                    n = engine.inbox_add(b.get("items") or [], b.get("source", ""))
                    return self._json({"ok": True, "added": n, "total": len(engine.inbox)})
                if path == "/api/inbox/clear":
                    engine.inbox_clear(b.get("urls"))
                    return self._json({"ok": True})
                if path == "/api/settings":
                    engine.settings.update(b)
                    return self._json({"ok": True, "settings": engine.settings.snapshot()})
                if path == "/api/cancel":
                    engine.cancel(b["id"])
                elif path == "/api/cancel_all":
                    engine.cancel_all()
                elif path == "/api/retry":
                    engine.retry(b["id"])
                elif path == "/api/retry_failed":
                    engine.retry_failed()
                elif path == "/api/clear":
                    engine.clear_finished()
                elif path == "/api/update":
                    engine.update_ytdlp()
                elif path == "/api/open":
                    target = b.get("path") or engine.settings.get("out_dir")
                    Path(engine.settings.get("out_dir")).mkdir(parents=True, exist_ok=True)
                    open_path(target, select=bool(b.get("path")))
                elif path == "/api/open_ext":
                    open_path(extension_dir())
                elif path == "/api/pickdir":
                    d = pick_dir(engine.settings.get("out_dir"))
                    if d:
                        engine.settings.update({"out_dir": d})
                    return self._json({"ok": True, "dir": d})
                elif path == "/api/ping":
                    pass
                else:
                    return self._json({"error": "not found"}, 404)
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)[:500]}, 400)

    return H


def serve(engine: Engine, port: int = PORT) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(engine))
    httpd.daemon_threads = True
    return httpd
