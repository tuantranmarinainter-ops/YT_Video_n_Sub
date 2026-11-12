"""YTSub PC — tải hàng loạt video & phụ đề YouTube. Chạy: python main.py"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import webbrowser

from ytsub.engine import Engine
from ytsub.server import PORT, serve

URL = f"http://127.0.0.1:{PORT}/"


def already_running() -> bool:
    try:
        with urllib.request.urlopen(URL + "api/status", timeout=1.5) as r:
            return json.load(r).get("app") == "ytsub-pc"
    except Exception:
        return False


def open_ui():
    if "--no-browser" in sys.argv:
        return
    # Mở dạng cửa sổ app (không thanh địa chỉ) nếu có Edge/Chrome, không thì mở trình duyệt mặc định.
    cands = [shutil.which("msedge"), shutil.which("chrome"),
             os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
             os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
             os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
             os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")]
    for c in cands:
        if c and os.path.exists(c):
            subprocess.Popen([c, f"--app={URL}", "--window-size=1200,860"])
            return
    webbrowser.open(URL)


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if already_running():
        open_ui()
        return
    engine = Engine()
    httpd = serve(engine)
    print(f"YTSub PC đang chạy tại {URL}")
    print("Giữ cửa sổ này mở trong lúc tải. Đóng cửa sổ (hoặc Ctrl+C) để thoát.")
    open_ui()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        engine.cancel_all()


if __name__ == "__main__":
    main()
