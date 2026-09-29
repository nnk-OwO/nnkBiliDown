"""下载任务队列。

- ThreadPoolExecutor 并发 1-3
- yt-dlp 负责 DASH 音视频下载，ffmpeg 自动合并
- progress_hook / postprocessor_hook 实时回传进度
- WebSocket 广播由 main.py 中的 bridge 完成
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yt_dlp

from .bilibili import (
    BiliError,
    BiliResolver,
    USER_AGENT,
    build_format_selector,
    cookie_to_netscape,
)
from .config import ConfigManager, HistoryStore, now_iso
from .runtime import ffmpeg_dir, ffmpeg_exe

try:
    from yt_dlp.extractor.bilibili import BiliBiliIE
except ImportError:  # yt-dlp 结构变化时不影响启动
    BiliBiliIE = None

# yt-dlp 2025+ 的 Bilibili 提取器会把 Referer 设成视频页，近期 B 站对此返回 412。
# 这里在运行时打一个小补丁：playurl 请求固定使用主站 Referer。
_YTDLP_PATCHED = False


def _patch_ytdlp_bilibili_referer() -> None:
    global _YTDLP_PATCHED
    if _YTDLP_PATCHED or BiliBiliIE is None:
        return
    try:
        original = BiliBiliIE._download_playinfo

        def patched(self, bvid, cid, headers=None, query=None, **kwargs):  # noqa: ANN001
            fixed = dict(headers or {})
            fixed.setdefault("Referer", "https://www.bilibili.com/")
            fixed.setdefault("User-Agent", USER_AGENT)
            return original(self, bvid, cid, headers=fixed, query=query, **kwargs)

        BiliBiliIE._download_playinfo = patched
        _YTDLP_PATCHED = True
    except Exception:
        # 打补丁失败不应阻止应用启动；最坏情况是 412 时给出错误提示
        pass


class SilentLogger:
    """避免 yt-dlp 把下载细节（可能包含签名 URL）打到控制台。"""

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        pass


class DownloadCancelled(Exception):
    pass


def _safe_unlink(path: str | None) -> bool:
    if not path:
        return False
    try:
        Path(path).unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    # 保险：即使第三方异常回显了 Cookie，也先脱敏
    text = re.sub(r"(SESSDATA|bili_jct|DedeUserID__ckMd5)=[^&\s;]+", r"\1=***", text, flags=re.I)
    text = re.sub(r"(Cookie:\s*)[^\n]+", r"\1***", text, flags=re.I)
    if "412" in text or "Precondition Failed" in text:
        return "B 站风控校验失败（412）。请稍后重试，或在浏览器中打开一次该视频后再试。"
    if "ffmpeg" in text.lower() or "ffprobe" in text.lower():
        if ffmpeg_exe():
            return "音视频合并失败（ffmpeg 已就绪）。请重试，或改用 MP4 + AVC 输出。"
        return "未找到 ffmpeg 或合并失败。客户端已内置 ffmpeg，请确认安装包完整后重试。"
    if "requested format is not available" in text.lower() or "requested format" in text.lower():
        return "所选清晰度/编码不可用，请返回重新选择其它清晰度。"
    if "cookie" in text.lower() or "login" in text.lower() or "会员" in text:
        return "账号权限不足或登录失效，请重新登录后重试。"
    if len(text) > 500:
        text = text[:500] + "…"
    return text or "下载失败"


class DownloadManager:
    def __init__(self, config: ConfigManager, history: HistoryStore):
        _patch_ytdlp_bilibili_referer()
        self.config = config
        self.history = history
        self._lock = threading.RLock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._cancel_events: dict[str, threading.Event] = {}
        self._last_broadcast: dict[str, float] = {}
        self._last_persist = 0.0
        self._running = 0
        self._executor: ThreadPoolExecutor | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws_sockets: set[Any] = set()
        self._reload_history()
        self._rebuild_executor()

    # ------------------------------------------------------------------
    # 基础状态
    # ------------------------------------------------------------------
    def _reload_history(self) -> None:
        with self._lock:
            self._tasks.clear()
            self._order.clear()
            records = list(reversed(self.history.all()))
            for record in records:
                tid = str(record.get("id") or uuid.uuid4().hex[:12])
                if tid in self._tasks:
                    continue
                # 上次进程退出时仍处于中间状态的任务视为失败，避免开机自动下载
                if record.get("status") in ("queued", "downloading"):
                    record = {**record, "status": "failed", "error": "应用重启导致任务中断，请重试"}
                record.setdefault("progress", 0)
                record.setdefault("speed", 0)
                record.setdefault("eta", None)
                self._tasks[tid] = record
                self._order.append(tid)
        if self._order:
            self._persist()

    def _rebuild_executor(self) -> None:
        with self._lock:
            settings = self.config.get_settings()
            workers = max(1, min(3, int(settings.get("max_concurrent") or 2)))
            old = self._executor
            self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bilidl")
            if old is not None:
                # 不 shutdown，避免正在运行的任务被误杀；旧 executor 由 GC 回收
                pass

    def attach_ws(self, loop: asyncio.AbstractEventLoop, sockets: set[Any]) -> None:
        self._loop = loop
        self._ws_sockets = sockets

    def _broadcast(self, message: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed() or not self._ws_sockets:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._broadcast_async(message), loop)
            future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        except RuntimeError:
            pass

    async def _broadcast_async(self, message: dict[str, Any]) -> None:
        import json

        dead = []
        text = json.dumps(message, ensure_ascii=False, default=str)
        for ws in list(self._ws_sockets):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._ws_sockets.discard(ws)

    def _persist(self) -> None:
        try:
            records = [dict(self._tasks[tid]) for tid in self._order if tid in self._tasks]
            for r in records:
                for key in list(r):
                    if key.startswith("_"):
                        r.pop(key, None)
            self.history.save(records)
        except Exception:
            pass

    def _update(self, tid: str, **fields: Any) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(tid)
            if not task:
                return None
            task.update(fields)
            task["updated_at"] = now_iso()
            public = self._public(task)
        self._broadcast({"type": "task_update", "task": public})
        now = time.monotonic()
        if now - self._last_persist > 1.5:
            self._last_persist = now
            self._persist()
        return public

    @staticmethod
    def _public(task: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in task.items() if not k.startswith("_")}

    def get_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._public(self._tasks[tid]) for tid in reversed(self._order) if tid in self._tasks]

    def get(self, tid: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(tid)
            return self._public(task) if task else None

    # ------------------------------------------------------------------
    # 创建 / 控制
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_urls(payload: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        if payload.get("url"):
            urls.append(str(payload["url"]))
        for u in payload.get("urls") or []:
            if u:
                urls.append(str(u))
        batch = str(payload.get("batch_text") or "").strip()
        if batch:
            parts = [p.strip() for line in batch.splitlines() for p in re.split(r"[\s,]+", line)]
            urls.extend([p for p in parts if p])
        return list(dict.fromkeys(urls))

    def _pick_quality(self, info: dict[str, Any], requested: Any) -> tuple[int, str, str]:
        options = info.get("quality_options") or []
        available = [o for o in options if o.get("available")]
        if not options:
            return 0, "自动", "auto"
        chosen = None
        if isinstance(requested, int):
            chosen = next((o for o in options if o["quality"] == requested), None)
        elif isinstance(requested, str) and requested and requested != "best":
            wanted = requested.lower()
            for o in options:
                if str(o["quality"]) == wanted or wanted in str(o["label"]).lower():
                    chosen = o
                    break
        if chosen is None:
            chosen = (available or options)[0]
        if not chosen.get("available"):
            hint = "大会员" if chosen.get("requires_vip") else "登录"
            raise BiliError(f"当前账号无法下载 {chosen['label']}，请先{hint}或选择其它清晰度")
        return int(chosen["quality"]), str(chosen["label"]), str(chosen.get("codec") or "auto")

    def _pick_codec(self, quality: int, info: dict[str, Any], requested_codec: str | None) -> str:
        codec = requested_codec or self.config.get_settings().get("preferred_codec") or "auto"
        options = info.get("quality_options") or []
        group = next((o for o in options if o.get("quality") == quality), None)
        if group and codec != "auto":
            codes = [c.get("value") for c in group.get("codecs") or []]
            if codes and codec not in codes:
                codec = "auto"
        return codec

    def create_tasks(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        urls = self._extract_urls(payload)
        if not urls:
            raise BiliError("请提供至少一个 URL")
        settings = self.config.get_settings()
        proxy = settings.get("proxy") or ""
        cookie = self.config.get_cookie()
        page_indexes = [int(x) for x in (payload.get("page_indexes") or [])]
        created: list[dict[str, Any]] = []
        parse_errors: list[str] = []

        for raw_url in urls:
            resolver = BiliResolver(cookie=cookie, proxy=proxy)
            try:
                info = resolver.parse(raw_url)
            except BiliError as exc:
                parse_errors.append(f"{raw_url}: {exc}")
                continue
            finally:
                resolver.close()

            try:
                quality, quality_label, _ = self._pick_quality(
                    info,
                    payload.get("quality")
                    if payload.get("quality") is not None
                    else settings.get("default_quality"),
                )
                codec = self._pick_codec(quality, info, payload.get("codec"))
                output_format = payload.get("output_format") or settings.get("output_format") or "mp4"
                pages = info.get("pages") or []
                selected = [i for i in page_indexes if 1 <= i <= len(pages)] or list(range(1, len(pages) + 1))

                for page in pages:
                    if page["index"] not in selected:
                        continue
                    tid = uuid.uuid4().hex[:12]
                    page_title = page.get("part") or f"P{page['index']}"
                    task = {
                        "id": tid,
                        "url": raw_url,
                        "page_url": page.get("url") or raw_url,
                        "page_index": int(page.get("index") or 1),
                        "page_title": page_title,
                        "video_title": str(info.get("title") or page_title),
                        "uploader": str(info.get("uploader") or ""),
                        "cover": str(info.get("cover") or ""),
                        "cid": int(page.get("cid") or 0),
                        "quality": quality,
                        "quality_label": quality_label,
                        "codec": codec,
                        "output_format": output_format,
                        "download_subtitles": bool(
                            payload.get("download_subtitles")
                            if payload.get("download_subtitles") is not None
                            else settings.get("download_subtitles")
                        ),
                        "download_danmaku": bool(
                            payload.get("download_danmaku")
                            if payload.get("download_danmaku") is not None
                            else settings.get("download_danmaku")
                        ),
                        "download_thumbnail": bool(
                            payload.get("download_thumbnail")
                            if payload.get("download_thumbnail") is not None
                            else settings.get("download_thumbnail")
                        ),
                        "status": "queued",
                        "progress": 0.0,
                        "downloaded_bytes": 0,
                        "total_bytes": 0,
                        "speed": 0.0,
                        "eta": None,
                        "filename": "",
                        "filepath": "",
                        "stage": "等待下载",
                        "error": "",
                        "created_at": now_iso(),
                        "updated_at": now_iso(),
                        "started_at": None,
                        "finished_at": None,
                        "attempts": 0,
                        "_file_downloaded": {},
                        "_file_totals": {},
                    }
                    with self._lock:
                        self._tasks[tid] = task
                        self._order.append(tid)
                        self._cancel_events[tid] = threading.Event()
                    created.append(self._public(task))
            except BiliError as exc:
                parse_errors.append(f"{raw_url}: {exc}")

        if not created and parse_errors:
            raise BiliError(parse_errors[0])
        self._persist()
        self._broadcast({"type": "tasks_snapshot", "tasks": self.get_all()})
        self._pump()
        return created

    def retry(self, tid: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(tid)
            if not task:
                return None
            if task.get("status") == "downloading":
                raise BiliError("任务正在下载，无法重试")
            task.update(
                {
                    "status": "queued",
                    "progress": 0.0,
                    "downloaded_bytes": 0,
                    "total_bytes": 0,
                    "speed": 0.0,
                    "eta": None,
                    "error": "",
                    "stage": "等待下载",
                    "started_at": None,
                    "finished_at": None,
                    "attempts": int(task.get("attempts", 0)) + 1,
                    "_file_downloaded": {},
                    "_file_totals": {},
                }
            )
            self._cancel_events[tid] = threading.Event()
            public = self._public(task)
        self._persist()
        self._broadcast({"type": "task_update", "task": public})
        self._pump()
        return public

    def cancel(self, tid: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(tid)
            if not task:
                return None
            event = self._cancel_events.get(tid)
            if event:
                event.set()
            if task.get("status") == "queued":
                task["status"] = "cancelled"
                task["stage"] = "已取消"
                task["finished_at"] = now_iso()
            public = self._public(task)
        self._persist()
        self._broadcast({"type": "task_update", "task": public})
        return public

    def delete(self, tid: str, delete_file: bool = False) -> bool:
        with self._lock:
            task = self._tasks.pop(tid, None)
            if task is None:
                return False
            self._order = [x for x in self._order if x != tid]
            event = self._cancel_events.pop(tid, None)
            if event and task.get("status") == "downloading":
                event.set()  # 让 worker 尽快停手
            self._last_broadcast.pop(tid, None)
        if delete_file and task.get("status") == "completed":
            _safe_unlink(task.get("filepath"))
        self._persist()
        self._broadcast({"type": "task_deleted", "id": tid})
        self._pump()
        return True

    def open_folder(self, tid: str) -> Path | None:
        task = self.get(tid)
        if not task:
            return None
        path = Path(task.get("filepath")) if task.get("filepath") else None
        folder = path.parent if path and path.exists() else Path(self.config.get_settings().get("download_dir") or "")
        folder = folder.expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            raise BiliError(f"无法打开文件夹：{exc}") from exc
        return folder

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------
    def _pump(self) -> None:
        with self._lock:
            if self._executor is None:
                return
            settings = self.config.get_settings()
            limit = max(1, min(3, int(settings.get("max_concurrent") or 2)))
            queued = [tid for tid in self._order if self._tasks.get(tid, {}).get("status") == "queued"]
            for tid in queued:
                if self._running >= limit:
                    break
                task = self._tasks[tid]
                task["status"] = "downloading"
                task["stage"] = "准备下载"
                task["started_at"] = now_iso()
                self._running += 1
                public = self._public(task)
                self._broadcast({"type": "task_update", "task": public})
                self._executor.submit(self._run, tid)

    def _progress_hook(self, tid: str, event: threading.Event, d: dict[str, Any]) -> None:
        if event.is_set():
            raise DownloadCancelled()
        status = d.get("status")
        with self._lock:
            task = self._tasks.get(tid)
            if not task:
                if event.is_set():
                    raise DownloadCancelled()
                return
            if status == "downloading":
                downloaded = float(d.get("downloaded_bytes") or 0)
                total = float(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
                fname = str(d.get("filename") or "file")
                fd = task.setdefault("_file_downloaded", {})
                ft = task.setdefault("_file_totals", {})
                if total > 0:
                    ft[fname] = max(float(ft.get(fname, 0)), total)
                fd[fname] = downloaded
                sum_total = sum(float(v) for v in ft.values())
                sum_downloaded = sum(float(v) for v in fd.values())
                if sum_total > 0:
                    progress = min(100.0, sum_downloaded / sum_total * 100.0)
                else:
                    progress = task.get("progress", 0.0)
                task.update(
                    {
                        "progress": round(progress, 2),
                        "downloaded_bytes": int(sum_downloaded),
                        "total_bytes": int(sum_total),
                        "speed": float(d.get("speed") or 0),
                        "eta": d.get("eta"),
                        "filename": Path(fname).name,
                        "stage": "下载中",
                    }
                )
                public = self._public(task)
            elif status == "finished":
                fname = str(d.get("filename") or "file")
                fd = task.setdefault("_file_downloaded", {})
                ft = task.setdefault("_file_totals", {})
                total = float(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
                if total > 0:
                    ft[fname] = max(float(ft.get(fname, 0)), total)
                fd[fname] = total or float(ft.get(fname, 0))
                task["filename"] = Path(fname).name
                task["stage"] = "文件已下载，等待处理"
                public = self._public(task)
            else:
                return
        now = time.monotonic()
        if now - self._last_broadcast.get(tid, 0) >= 0.3:
            self._last_broadcast[tid] = now
            self._broadcast({"type": "task_update", "task": public})
            if now - self._last_persist > 1.5:
                self._last_persist = now
                self._persist()

    def _postprocessor_hook(self, tid: str, d: dict[str, Any]) -> None:
        status = d.get("status")
        pp = str(d.get("postprocessor") or "")
        info = d.get("info_dict") or {}
        filepath = info.get("filepath") or ""
        with self._lock:
            task = self._tasks.get(tid)
            if not task:
                return
            if status == "started" and "Merger" in pp:
                task["stage"] = "正在合并音视频"
            if status == "finished":
                if filepath:
                    task["filepath"] = str(filepath)
                    task["filename"] = Path(filepath).name
                if "MoveFiles" not in pp:
                    task["progress"] = 100.0
                    task["stage"] = "合并完成"
            public = self._public(task)
        self._broadcast({"type": "task_update", "task": public})
        self._persist()

    def _run(self, tid: str) -> None:
        try:
            self._run_inner(tid)
        except Exception as exc:  # noqa: BLE001
            self._update(tid, status="failed", error=_friendly_error(exc), stage="失败", finished_at=now_iso())
        finally:
            with self._lock:
                self._running = max(0, self._running - 1)
            self._persist()
            self._pump()

    def _run_inner(self, tid: str) -> None:
        with self._lock:
            task = self._tasks.get(tid)
            if not task:
                return
            event = self._cancel_events.get(tid) or threading.Event()
        settings = self.config.get_settings()
        download_dir = Path(settings.get("download_dir") or "").expanduser()
        try:
            download_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BiliError(f"无法创建下载目录：{exc}") from exc

        cookie = self.config.get_cookie()
        cookie_file = None
        if cookie:
            cookie_file = self.config.cookie_file_path()
            try:
                cookie_file.write_text(cookie_to_netscape(cookie), encoding="utf-8")
                os.chmod(cookie_file, 0o600)
            except OSError as exc:
                raise BiliError("Cookie 临时文件写入失败，请检查数据目录权限") from exc

        selector = build_format_selector(task.get("quality") or 0, task.get("codec") or "auto")
        if not (task.get("quality")):
            selector = "bestvideo+bestaudio/best"

        def progress_hook(d: dict[str, Any]) -> None:
            self._progress_hook(tid, event, d)

        def pp_hook(d: dict[str, Any]) -> None:
            self._postprocessor_hook(tid, d)

        subtitles = bool(task.get("download_subtitles"))
        danmaku = bool(task.get("download_danmaku"))
        sub_langs = ["all"] if danmaku else ["all", "-danmaku"]

        opts: dict[str, Any] = {
            "format": selector,
            "outtmpl": str(download_dir / settings.get("filename_template", "%(title)s.%(ext)s")),
            "merge_output_format": task.get("output_format") or "mp4",
            "noplaylist": True,
            "continuedl": True,
            "retries": 5,
            "fragment_retries": 8,
            "socket_timeout": 30,
            "concurrent_fragment_downloads": 3,
            "buffersize": 1024 * 1024,
            "quiet": True,
            "no_warnings": True,
            "logger": SilentLogger(),
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [pp_hook],
            "http_headers": {
                "User-Agent": USER_AGENT,
                "Referer": "https://www.bilibili.com/",
            },
            "writethumbnail": bool(task.get("download_thumbnail")),
            "writesubtitles": subtitles or danmaku,
            "subtitleslangs": sub_langs if (subtitles or danmaku) else None,
        }
        if cookie_file:
            opts["cookiefile"] = str(cookie_file)
        ff_dir = ffmpeg_dir()
        if ff_dir:
            opts["ffmpeg_location"] = ff_dir
        proxy = str(settings.get("proxy") or "").strip()
        if proxy:
            opts["proxy"] = proxy
        if os.name == "nt":
            opts["windowsfilenames"] = True

        self._update(tid, status="downloading", stage="解析视频流…", attempts=int(task.get("attempts", 0)))
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(str(task.get("page_url")), download=True)
                filepath = self._final_filepath(ydl, info, task)
                task["filepath"] = filepath
                task["filename"] = Path(filepath).name if filepath else task.get("filename", "")
        except DownloadCancelled:
            self._update(tid, status="cancelled", stage="已取消", finished_at=now_iso())
            return
        except Exception as exc:
            self._update(tid, status="failed", error=_friendly_error(exc), stage="失败", finished_at=now_iso())
            raise

        self._update(
            tid,
            status="completed",
            progress=100.0,
            speed=0.0,
            eta=None,
            stage="下载完成",
            finished_at=now_iso(),
            filename=task.get("filename") or "",
            filepath=task.get("filepath") or "",
        )
        if settings.get("auto_open_folder"):
            try:
                self.open_folder(tid)
            except Exception:
                pass

    @staticmethod
    def _final_filepath(ydl: yt_dlp.YoutubeDL, info: dict[str, Any], task: dict[str, Any]) -> str:
        candidates: list[str] = []
        for rd in info.get("requested_downloads") or []:
            fp = rd.get("filepath")
            if fp:
                candidates.append(str(fp))
        if info.get("filepath"):
            candidates.append(str(info["filepath"]))
        try:
            candidates.append(str(ydl.prepare_filename(info)))
        except Exception:
            pass
        for fp in candidates:
            p = Path(fp)
            if p.exists() or p.with_suffix("").exists():
                return str(p)
        folder = Path(str(ydl.params.get("outtmpl") or "")).parent
        ext = f".{task.get('output_format') or 'mp4'}"
        best = None
        try:
            cutoff = time.time() - 600
            for p in folder.iterdir():
                if p.is_file() and p.name.endswith(ext) and p.stat().st_mtime >= cutoff:
                    if best is None or p.stat().st_mtime > best.stat().st_mtime:
                        best = p
        except OSError:
            pass
        return str(best) if best else (candidates[0] if candidates else "")


import sys  # noqa: E402 - 供 open_folder 判断 macOS 使用
