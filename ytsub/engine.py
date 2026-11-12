"""Hàng đợi tải hàng loạt: yt-dlp + FFmpeg (port từ Engine.kt, chạy nhiều job song song)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from . import subs

FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent.parent
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
DATA_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "YTSub-PC"
SETTINGS_FILE = DATA_DIR / "settings.json"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

VI_COLOR = "#FFE14D"
LANG_NAMES = {"en": "tiếng Anh", "vi": "tiếng Việt", "ja": "tiếng Nhật", "ko": "tiếng Hàn",
              "zh-Hans": "tiếng Trung", "fr": "tiếng Pháp", "de": "tiếng Đức", "es": "tiếng Tây Ban Nha"}
ISO3 = {"en": "eng", "vi": "vie", "ja": "jpn", "ko": "kor", "zh-Hans": "chi", "fr": "fre", "de": "ger", "es": "spa"}
FORMATS = {
    "best": "bv*+ba/b",
    "1080": "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
    "720": "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=720]+ba/b[height<=720]/b",
    "480": "bv*[height<=480][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=480]+ba/b[height<=480]/b",
}
TABS = {"Videos", "Shorts", "Live", "Streams", "Podcasts", "Releases"}
DEFAULT_OPTS = {"mode": "subs", "quality": "1080", "sub": "orig", "attach": "srt", "font": "m", "subfmt": "srt"}
DEFAULT_SETTINGS = {
    "out_dir": str(Path.home() / "Downloads" / "YTSub"),
    "workers": 2,            # số video tải cùng lúc
    "per_channel": True,     # mỗi kênh 1 thư mục con
    "skip_existing": True,   # bỏ qua video đã tải
    "cookies": "",           # chrome | edge | firefox | "" (lấy cookie trình duyệt khi YouTube chặn)
    "sleep": 2,              # nghỉ giữa các video (giây)
    "lang1": "en",
    "lang2": "vi",
    "defaults": dict(DEFAULT_OPTS),
}


class Canceled(Exception):
    pass


def lang_name(code: str) -> str:
    return LANG_NAMES.get(code, code)


def safe_name(s: str, limit: int = 80) -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", s or "").strip(" .")[:limit].strip()
    return s or "video"


def short_err(text: str) -> str:
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    err = next((x for x in reversed(lines) if x.startswith("ERROR")), lines[-1] if lines else "Lỗi không rõ")
    return err[:400]


# ---------------------------------------------------------------- tìm công cụ
def find_bin(name: str) -> str | None:
    for p in (APP_DIR / "bin" / f"{name}.exe", RES_DIR / "bin" / f"{name}.exe", APP_DIR / f"{name}.exe"):
        if p.exists():
            return str(p)
    return shutil.which(name)


def ytdlp_cmd() -> list[str]:
    exe = find_bin("yt-dlp")
    if exe:
        return [exe]
    if not FROZEN:
        return [sys.executable, "-m", "yt_dlp"]
    raise RuntimeError("Không tìm thấy yt-dlp.exe (đặt vào thư mục bin cạnh app).")


def ffmpeg_path() -> str | None:
    return find_bin("ffmpeg")


# ---------------------------------------------------------------- cài đặt
class Settings:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = json.loads(json.dumps(DEFAULT_SETTINGS))
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            self.data.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
            self.data["defaults"] = {**DEFAULT_OPTS, **(saved.get("defaults") or {})}
        except Exception:
            pass

    def get(self, k):
        with self.lock:
            return self.data[k]

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.data))

    def update(self, patch: dict):
        with self.lock:
            for k, v in patch.items():
                if k == "defaults" and isinstance(v, dict):
                    self.data["defaults"] = {**self.data["defaults"], **{a: b for a, b in v.items() if a in DEFAULT_OPTS}}
                elif k in DEFAULT_SETTINGS:
                    self.data[k] = v
            self.data["workers"] = max(1, min(6, int(self.data.get("workers") or 1)))
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- job
class Job:
    def __init__(self, url: str, opts: dict, title: str = ""):
        self.id = uuid.uuid4().hex[:10]
        self.url = url
        self.opts = {**DEFAULT_OPTS, **(opts or {})}
        self.status = "queued"  # queued | running | done | error | canceled | skipped
        self.stage = "Đang chờ…"
        self.pct: float | None = None
        self.info: dict | None = {"title": title} if title else None
        self.error: str | None = None
        self.canceled = False
        self.warnings: list[str] = []
        self.files: list[str] = []
        self.procs: list[subprocess.Popen] = []
        self.created = time.time()

    def to_json(self) -> dict:
        return {"id": self.id, "url": self.url, "status": self.status, "stage": self.stage, "pct": self.pct,
                "info": self.info, "error": self.error, "warnings": list(self.warnings),
                "files": list(self.files), "opts": self.opts}

    def check(self):
        if self.canceled:
            raise Canceled()


class Engine:
    def __init__(self):
        self.settings = Settings()
        self.jobs: list[Job] = []
        self.lock = threading.Condition()
        self.inbox: list[dict] = []   # link do extension gửi sang, chờ người dùng duyệt
        self.inbox_rev = 0
        self.ytdlp_version = None
        self.update_msg = ""
        threading.Thread(target=self._scheduler, daemon=True).start()
        threading.Thread(target=self._probe_version, daemon=True).start()

    # ------------------------------------------------ chạy yt-dlp
    def _base_args(self) -> list[str]:
        a = ["--encoding", "utf-8", "--no-update", "--no-colors"]
        ff = ffmpeg_path()
        if ff:
            a += ["--ffmpeg-location", ff]
        if not shutil.which("deno") and shutil.which("node"):
            a += ["--js-runtimes", "node"]
        ck = self.settings.get("cookies")
        if ck:
            a += ["--cookies-from-browser", ck]
        return a

    def _run(self, args: list[str], job: Job | None = None, on_line=None, base=True) -> str:
        cmd = ytdlp_cmd() + (self._base_args() if base else []) + args
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        with tempfile.TemporaryFile() as errf:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, stdin=subprocess.DEVNULL,
                                 env=env, creationflags=NO_WINDOW)
            if job:
                job.procs.append(p)
            out = []
            try:
                for raw in p.stdout:
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    out.append(line)
                    if on_line:
                        on_line(line)
                code = p.wait()
            finally:
                if job and p in job.procs:
                    job.procs.remove(p)
            if job:
                job.check()
            if code != 0:
                errf.seek(0)
                raise RuntimeError(short_err(errf.read().decode("utf-8", "replace")))
        return "\n".join(out)

    def _probe_version(self):
        try:
            self.ytdlp_version = self._run(["--version"], base=False).strip().splitlines()[-1]
        except Exception as e:
            self.ytdlp_version = None
            self.update_msg = f"Không chạy được yt-dlp: {e}"

    def update_ytdlp(self):
        def work():
            self.update_msg = "Đang cập nhật yt-dlp…"
            try:
                exe = find_bin("yt-dlp")
                if exe and exe.lower().endswith(".exe") and "Scripts" not in exe:
                    out = self._run(["-U"], base=False)
                else:
                    r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"],
                                       capture_output=True, text=True, creationflags=NO_WINDOW)
                    out = r.stdout + r.stderr
                self._probe_version()
                self.update_msg = "Đã cập nhật yt-dlp" if "Updated" in out or "Successfully" in out else "yt-dlp đã mới nhất"
            except Exception as e:
                self.update_msg = f"Không cập nhật được: {str(e)[:150]}"
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------ liệt kê kênh / playlist
    def list_url(self, url: str) -> dict:
        raw = self._run(["--flat-playlist", "--yes-playlist", "-J", url])
        data = json.loads(next(x for x in reversed(raw.splitlines()) if x.startswith("{")))
        items, seen = [], set()

        def walk(node, tab=""):
            ents = node.get("entries")
            if ents is None:
                vid = node.get("id")
                if not vid or vid in seen or len(vid) != 11:
                    return
                seen.add(vid)
                u = node.get("url") or node.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
                if not u.startswith("http"):
                    u = f"https://www.youtube.com/watch?v={vid}"
                items.append({"id": vid, "url": u, "title": node.get("title") or vid,
                              "duration": node.get("duration"), "tab": tab,
                              "short": "/shorts/" in u or tab.lower().endswith("shorts")})
                return
            suffix = (node.get("title") or "").rsplit(" - ", 1)[-1]
            sub = suffix if suffix in TABS else tab
            for e in ents:
                if e:
                    walk(e, sub)

        if data.get("_type") == "playlist":
            walk(data)
        else:
            walk({k: v for k, v in data.items() if k != "entries"})
        return {"title": data.get("title") or data.get("channel") or "", "items": items}

    # ------------------------------------------------ hàng đợi
    def enqueue(self, items: list, opts: dict | None = None) -> list[str]:
        opts = {**self.settings.get("defaults"), **(opts or {})}
        ids = []
        with self.lock:
            existing = {j.url for j in self.jobs if j.status in ("queued", "running")}
            for it in items:
                url, title = (it, "") if isinstance(it, str) else (it.get("url", ""), it.get("title", ""))
                url = url.strip()
                if not url or url in existing:
                    continue
                existing.add(url)
                j = Job(url, opts, title)
                self.jobs.append(j)
                ids.append(j.id)
            self.lock.notify_all()
        return ids

    def _scheduler(self):
        while True:
            with self.lock:
                running = sum(1 for j in self.jobs if j.status == "running")
                nxt = next((j for j in self.jobs if j.status == "queued"), None)
                if nxt is None or running >= self.settings.get("workers"):
                    self.lock.wait(1.0)
                    continue
                nxt.status = "running"
            threading.Thread(target=self._run_job, args=(nxt,), daemon=True).start()

    def jobs_json(self) -> list:
        with self.lock:
            return [j.to_json() for j in self.jobs]

    def _find(self, jid):
        with self.lock:
            return next((j for j in self.jobs if j.id == jid), None)

    def cancel(self, jid: str):
        j = self._find(jid)
        if not j:
            return
        j.canceled = True
        if j.status == "queued":
            j.status, j.stage = "canceled", "Đã huỷ"
        for p in list(j.procs):
            try:
                p.kill()
            except Exception:
                pass

    def cancel_all(self):
        for j in list(self.jobs):
            if j.status in ("queued", "running"):
                self.cancel(j.id)

    def retry(self, jid: str):
        j = self._find(jid)
        if j and j.status in ("error", "canceled"):
            with self.lock:
                self.jobs.remove(j)
            self.enqueue([{"url": j.url, "title": (j.info or {}).get("title", "")}], j.opts)

    def retry_failed(self):
        for j in [j for j in self.jobs if j.status == "error"]:
            self.retry(j.id)

    def clear_finished(self):
        with self.lock:
            self.jobs = [j for j in self.jobs if j.status in ("queued", "running")]

    def stats(self) -> dict:
        with self.lock:
            st = {}
            for j in self.jobs:
                st[j.status] = st.get(j.status, 0) + 1
            return st

    # ------------------------------------------------ inbox (từ extension)
    def inbox_add(self, items: list, source: str = "") -> int:
        with self.lock:
            have = {x["url"] for x in self.inbox}
            n = 0
            for it in items:
                url = (it if isinstance(it, str) else it.get("url", "")).strip()
                if not url or url in have:
                    continue
                have.add(url)
                d = {"url": url, "source": source} if isinstance(it, str) else {**it, "url": url, "source": source}
                d.setdefault("id", _vid(url))
                d.setdefault("title", d["id"] or url)
                d.setdefault("short", "/shorts/" in url)
                self.inbox.append(d)
                n += 1
            self.inbox_rev += 1
            return n

    def inbox_clear(self, urls: list | None = None):
        with self.lock:
            self.inbox = [x for x in self.inbox if urls is not None and x["url"] not in set(urls)]
            self.inbox_rev += 1

    # ------------------------------------------------ chạy 1 job
    def _pick_track(self, info: dict, lang: str):
        def keys(o):
            return [k for k in (o or {}) if not k.startswith("live_chat")]

        def match(ks):
            return next((k for k in ks if k == lang), None) or \
                next((k for k in ks if k.split("-")[0].lower() == lang.split("-")[0].lower()), None)

        manual, auto = keys(info.get("subtitles")), keys(info.get("automatic_captions"))
        if (m := match(manual)):
            return m, "manual"
        if f"{lang}-orig" in auto:
            return f"{lang}-orig", "auto"
        if (m := match(auto)):
            return m, "auto"
        return None

    def _orig_track(self, info: dict, prefs: tuple = ()):
        """Phụ đề theo ngôn ngữ gốc của video.

        Thứ tự: bản tự động gốc (-orig, ưu tiên bản thủ công cùng ngôn ngữ) > thủ công đúng ngôn ngữ video
        > thủ công theo ngôn ngữ ưa thích (lang1, lang2) > thủ công đầu tiên > bản tự động duy nhất.
        """
        only_manual = {"subtitles": info.get("subtitles")}
        only_auto = {"automatic_captions": info.get("automatic_captions")}
        manual = [k for k in (info.get("subtitles") or {}) if not k.startswith("live_chat")]
        auto = list(info.get("automatic_captions") or {})
        orig = next((k for k in auto if k.endswith("-orig")), None)
        if orig:
            return self._pick_track(only_manual, orig.removesuffix("-orig")) or (orig, "auto")
        lang = info.get("language")
        if lang and (t := self._pick_track(only_manual, lang)):
            return t
        for p in prefs:
            if p and (t := self._pick_track(only_manual, p)):
                return t
        if manual:
            return manual[0], "manual"
        if len(auto) == 1:
            return auto[0], "auto"
        for p in (lang, *prefs):
            if p and (t := self._pick_track(only_auto, p)):
                return t
        return None

    def _fetch_track(self, job: Job, url: str, key: str, manual: bool, tmp: Path) -> list:
        d = tmp / f"sub_{abs(hash(key))}"
        d.mkdir(exist_ok=True)
        self._run(["--no-playlist", "--skip-download", "--write-subs" if manual else "--write-auto-subs",
                   "--sub-langs", re.escape(key), "--sub-format", "json3/vtt/srt/best",
                   "-o", str(d / "sub.%(ext)s"), url], job)
        f = next((x for x in d.iterdir() if x.name.startswith("sub.")), None)
        if not f:
            return []
        try:
            return subs.load(f)
        except Exception:
            return []

    def _out_dir(self, info: dict) -> Path:
        base = Path(self.settings.get("out_dir")).expanduser()
        if self.settings.get("per_channel"):
            base = base / safe_name(info.get("channel") or info.get("uploader") or "Khac", 60)
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _publish(self, job: Job, src: Path, dest_dir: Path, name: str):
        dest = dest_dir / name
        shutil.move(str(src), str(dest))
        job.files.append(str(dest))

    def _run_job(self, job: Job):
        tmp = Path(tempfile.mkdtemp(prefix=f"ytsub_{job.id}_"))
        o = job.opts
        l1, l2 = self.settings.get("lang1"), self.settings.get("lang2")
        try:
            job.check()
            job.stage, job.pct = "Đang lấy thông tin video…", None
            raw = self._run(["-J", "--no-playlist", job.url], job)
            info = json.loads(next(x for x in reversed(raw.splitlines()) if x.startswith("{")))
            if info.get("_type") == "playlist":
                info = (info.get("entries") or [None])[0] or {}
            url = info.get("webpage_url") or job.url
            w, h = info.get("width") or 0, info.get("height") or 0
            vertical = (w and h > w) or "/shorts/" in url
            job.info = {"id": info.get("id"), "title": info.get("title"), "uploader": info.get("channel") or info.get("uploader"),
                        "duration": info.get("duration"), "thumbnail": info.get("thumbnail"), "vertical": bool(vertical)}
            name = f"{safe_name(info.get('title'))} [{info.get('id')}]"
            out_dir = self._out_dir(info)
            duration = float(info.get("duration") or 0)

            ext = {"video": "mp4", "audio": "mp3"}.get(o["mode"])
            if self.settings.get("skip_existing"):
                probe = list(out_dir.glob(f"*[[]{info.get('id')}[]].{ext or o['subfmt']}")) if ext else \
                    list(out_dir.glob(f"*[[]{info.get('id')}[]].*.{o['subfmt']}"))
                if probe:
                    job.status, job.stage, job.pct = "skipped", "Đã có sẵn, bỏ qua", 100.0
                    job.files = [str(p) for p in probe]
                    return

            # 1) phụ đề
            want = {"none": [], "l1": [l1], "l2": [l2], "both": [l1, l2], "orig": ["orig"]}.get(o["sub"], [])
            cues: dict[str, list] = {}
            for lang in want:
                job.check()
                if lang == "orig":
                    t = self._orig_track(info, (l1, l2))
                    lang = t[0].removesuffix("-orig") if t else (info.get("language") or "gốc")
                else:
                    t = self._pick_track(info, lang)
                if not t:
                    job.warnings.append(f"Video không có phụ đề {lang_name(lang)}.")
                    continue
                key, kind = t
                job.stage = f"Đang tải phụ đề {lang_name(lang)}…"
                try:
                    c = self._fetch_track(job, url, key, kind == "manual", tmp)
                except Canceled:
                    raise
                except Exception as e:
                    job.warnings.append(f"Lỗi tải phụ đề {lang_name(lang)}: {str(e)[:150]}")
                    continue
                if not c:
                    job.warnings.append(f"Phụ đề {lang_name(lang)} rỗng.")
                    continue
                cues[lang] = c
                if kind == "auto":
                    job.warnings.append(f"Phụ đề {lang_name(lang)} là bản tự động/YouTube dịch (có thể chưa chuẩn).")
            fmt_sub = subs.to_txt if (o["mode"] == "subs" and o["subfmt"] == "txt") else subs.to_srt
            sub_ext = "txt" if fmt_sub is subs.to_txt else "srt"
            srt: dict[str, Path] = {}
            for lang, c in cues.items():
                p = tmp / f"{lang}.srt"
                p.write_text(subs.to_srt(c), encoding="utf-8")
                srt[lang] = p
            if l1 in cues and l2 in cues:
                p = tmp / "both.srt"
                p.write_text(subs.to_srt(subs.merge_bilingual(cues[l1], cues[l2])), encoding="utf-8")
                srt["both"] = p
            if want and not srt:
                job.warnings.append("Không lấy được phụ đề nào.")
            job.check()

            # 2) video / audio
            media = None
            if o["mode"] in ("video", "audio"):
                job.stage, job.pct = ("Đang tải âm thanh…" if o["mode"] == "audio" else "Đang tải video…"), 0.0
                args = ["--no-playlist", "--newline", "--progress-template",
                        "download:@@P %(progress.downloaded_bytes)s %(progress.total_bytes)s %(progress.total_bytes_estimate)s",
                        "-o", str(tmp / "media.%(ext)s")]
                if o["mode"] == "audio":
                    args += ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "192K"]
                else:
                    args += ["-f", FORMATS.get(o["quality"], FORMATS["best"]), "--merge-output-format", "mp4"]
                part = [0]

                def on_line(line):
                    if line.startswith("@@P"):
                        bits = line.split()[1:]
                        try:
                            done = float(bits[0])
                            total = next((float(b) for b in bits[1:] if b not in ("NA", "None")), 0)
                            if total:
                                job.pct = min(99.0, done / total * 100)
                        except Exception:
                            pass
                    elif "[download] Destination" in line:
                        part[0] += 1
                        if o["mode"] == "video" and part[0] > 1:
                            job.stage = "Đang tải âm thanh…"
                    elif "[Merger]" in line or "[ExtractAudio]" in line:
                        job.stage, job.pct = "Đang ghép file…", None

                self._run(args + [url], job, on_line)
                cands = [p for p in tmp.iterdir() if p.name.startswith("media.") and p.suffix not in (".part", ".ytdl")]
                if not cands:
                    raise RuntimeError("Không tìm thấy file sau khi tải.")
                media = max(cands, key=lambda p: p.stat().st_size)

            # 3) gắn phụ đề
            if media and o["mode"] == "video" and srt and o["attach"] in ("soft", "burn"):
                src = tmp / f"src{media.suffix}"
                media.rename(src)
                out = tmp / "final.mp4"
                if o["attach"] == "soft":
                    tracks = [k for k in (l1, l2) if k in srt]
                    a = ["-i", src.name]
                    for k in tracks:
                        a += ["-i", srt[k].name]
                    a += ["-map", "0:v", "-map", "0:a?"]
                    for i in range(len(tracks)):
                        a += ["-map", f"{i + 1}:0"]
                    a += ["-c", "copy", "-c:s", "mov_text"]
                    for i, k in enumerate(tracks):
                        a += [f"-metadata:s:s:{i}", f"language={ISO3.get(k, k)}",
                              f"-metadata:s:s:{i}", f"title={lang_name(k).capitalize()}"]
                    a += ["-disposition:s:0", "default", out.name]
                    self._ffmpeg(job, a, tmp, 0, "Đang nhúng phụ đề…")
                else:
                    pick = {"l1": l1, "l2": l2, "both": "both"}.get(o["sub"], "both")
                    burn_lang = pick if pick in srt else next(iter(srt))
                    burn = tmp / "burn.srt"
                    if burn_lang == "both":
                        burn.write_text(subs.to_srt(subs.merge_bilingual(cues[l1], cues[l2], VI_COLOR)), encoding="utf-8")
                    else:
                        shutil.copy(srt[burn_lang], burn)
                    fs = {"s": (14, 8), "m": (18, 10), "l": (22, 13)}.get(o["font"], (18, 10))[1 if vertical else 0]
                    style = (f"FontName=Arial,FontSize={fs},Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                             f"BorderStyle=1,Outline=1.6,Shadow=0,MarginV={60 if vertical else 18}")
                    a = ["-i", src.name, "-vf", f"subtitles=burn.srt:force_style='{style}'",
                         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                         "-c:a", "copy", "-movflags", "+faststart", out.name]
                    self._ffmpeg(job, a, tmp, duration, "Đang in phụ đề lên video…")
                media = out

            # 4) lưu
            job.stage, job.pct = "Đang lưu…", None
            if media:
                self._publish(job, media, out_dir, f"{name}{media.suffix}")
            labels = {**{k: k for k in srt}, l1: l1, l2: l2, "both": f"{l1}-{l2}"}
            for k in dict.fromkeys([l1, l2, "both", *srt]):
                if k in srt:
                    p = srt[k]
                    if sub_ext == "txt":
                        p = tmp / f"{k}.txt"
                        src_cues = subs.merge_bilingual(cues[l1], cues[l2]) if k == "both" else cues[k]
                        p.write_text(subs.to_txt(src_cues), encoding="utf-8")
                    self._publish(job, p, out_dir, f"{name}.{labels[k]}.{sub_ext}")
            if o["mode"] == "subs" and not job.files:
                raise RuntimeError("Video không có phụ đề (YouTube không cung cấp).")
            job.status, job.stage, job.pct = "done", "Xong", 100.0
        except Canceled:
            job.status, job.stage, job.pct = "canceled", "Đã huỷ", None
        except Exception as e:
            if job.canceled:
                job.status, job.stage, job.pct = "canceled", "Đã huỷ", None
            else:
                msg = str(e)[:400]
                if "Sign in to confirm" in msg:
                    msg += " → YouTube đang chặn: bật 'Lấy cookie trình duyệt' trong Cài đặt, giảm số luồng hoặc thử lại sau."
                job.status, job.stage, job.error, job.pct = "error", "Lỗi", msg, None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            sl = float(self.settings.get("sleep") or 0)
            if sl > 0 and job.status == "done":
                time.sleep(sl)
            with self.lock:
                self.lock.notify_all()

    def _ffmpeg(self, job: Job, args: list, cwd: Path, duration: float, label: str):
        ff = ffmpeg_path()
        if not ff:
            raise RuntimeError("Không tìm thấy ffmpeg.exe")
        job.stage, job.pct = label, (0.0 if duration > 0 else None)
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats"] + args
        with tempfile.TemporaryFile() as errf:
            p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=errf,
                                 stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
            job.procs.append(p)
            for raw in p.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if duration > 0 and line.startswith("out_time_us="):
                    try:
                        job.pct = max(0.0, min(99.0, int(line.split("=")[1]) / 1e6 / duration * 100))
                    except ValueError:
                        pass
            code = p.wait()
            if p in job.procs:
                job.procs.remove(p)
            job.check()
            if code != 0:
                errf.seek(0)
                raise RuntimeError(f"FFmpeg lỗi ({code}): {errf.read().decode('utf-8', 'replace')[-400:]}")


def _vid(url: str) -> str:
    m = re.search(r"(?:v=|/shorts/|youtu\.be/|/live/)([\w-]{11})", url)
    return m.group(1) if m else ""
