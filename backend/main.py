"""FastAPI 应用入口：REST API + WebSocket + 静态前端。"""
from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yt_dlp
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .bilibili import BASE_HEADERS, BiliClient, BiliError, BiliResolver, mask_cookie
from .config import ConfigManager, HistoryStore, SettingsValidationError
from .downloader import DownloadManager
from .models import CookieTestRequest, ParseRequest, SettingsUpdateRequest, TaskCreateRequest
from .qr_login import QRLoginManager

logger = logging.getLogger("nnkbilidown")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

config = ConfigManager()
history = HistoryStore()
downloader = DownloadManager(config, history)
qr_manager = QRLoginManager()
ws_sockets: set[WebSocket] = set()

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    downloader.attach_ws(loop, ws_sockets)
    logger.info("数据目录: %s", config.data_dir)
    ff = ffmpeg_status()
    if ff["ok"]:
        logger.info("ffmpeg: %s", ff["version"])
    else:
        logger.warning("未检测到 ffmpeg，下载高画质/合并音视频将不可用")
    yield
    qr_manager.close()
    # 不主动 shutdown 下载线程池，保证任务跑完；进程退出时由 OS 回收


def ffmpeg_status() -> dict[str, Any]:
    path = shutil.which("ffmpeg")
    if not path:
        hint = {
            "Windows": "winget install Gyan.FFmpeg  或  choco install ffmpeg",
            "Darwin": "brew install ffmpeg",
            "Linux": "sudo apt install ffmpeg",
        }.get(platform.system(), "请从 https://ffmpeg.org 下载并加入 PATH")
        return {"ok": False, "path": None, "version": None, "hint": hint}
    try:
        proc = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=10, check=False)
        first = proc.stdout.splitlines()[0] if proc.stdout else "ffmpeg"
    except Exception:
        first = "ffmpeg"
    return {"ok": True, "path": path, "version": first}


app = FastAPI(
    title="nnkBiliDown",
    version="1.0.0",
    description="nnkBiliDown - 本地运行的 Bilibili 视频下载器",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:7860",
        "http://127.0.0.1:7860",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BiliError)
async def bili_error_handler(_, exc: BiliError):
    return JSONResponse(status_code=400, content={"detail": str(exc), "code": exc.code})


@app.exception_handler(SettingsValidationError)
async def settings_error_handler(_, exc: SettingsValidationError):
    return JSONResponse(status_code=400, content={"detail": "设置校验失败", "errors": exc.errors})


@app.exception_handler(Exception)
async def generic_error_handler(_, exc: Exception):
    logger.exception("未处理异常: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请查看控制台日志"})


# ---------------------------------------------------------------------------
# 健康检查 / 设置 / Cookie
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    ff = ffmpeg_status()
    return {
        "ok": True,
        "platform": platform.system(),
        "python": platform.python_version(),
        "yt_dlp": getattr(yt_dlp.version, "__version__", "unknown"),
        "ffmpeg": ff,
        "data_dir": str(config.data_dir),
        "frontend_built": FRONTEND_DIST.exists(),
    }


@app.get("/api/settings")
def get_settings():
    return config.get_settings()


@app.put("/api/settings")
def put_settings(payload: SettingsUpdateRequest):
    patch = payload.model_dump(exclude_unset=True)
    return config.update_settings(patch)


@app.get("/api/cookie/status")
def cookie_status():
    cookie = config.get_cookie()
    if not cookie:
        return {"has_cookie": False, "logged_in": False, "user": None}
    try:
        with BiliClient(cookie=cookie) as client:
            data = client.account_info()
    except BiliError as exc:
        return {"has_cookie": True, "logged_in": False, "user": None, "message": str(exc)}
    return {
        "has_cookie": True,
        "logged_in": bool(data.get("isLogin")),
        "user": {
            "uname": data.get("uname") or "",
            "mid": data.get("mid") or 0,
            "vip_status": int(data.get("vipStatus") or 0),
            "vip_label": data.get("vip_label") or {},
        },
    }


@app.post("/api/cookie/test")
def cookie_test(payload: CookieTestRequest):
    raw = payload.cookie.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Cookie 不能为空")
    try:
        with BiliClient(cookie=raw) as client:
            data = client.account_info()
    except BiliError as exc:
        raise HTTPException(status_code=401, detail=f"Cookie 无效：{exc}") from exc
    if not data.get("isLogin"):
        raise HTTPException(status_code=401, detail="Cookie 已过期或未包含 SESSDATA，请重新从浏览器复制")
    user = {
        "uname": data.get("uname") or "",
        "mid": data.get("mid") or 0,
        "vip_status": int(data.get("vipStatus") or 0),
        "vip_label": data.get("vip_label") or {},
    }
    if payload.save:
        config.set_cookie(raw)
        logger.info("Cookie 已保存: %s | 账号=%s", mask_cookie(raw), user.get("uname"))
    else:
        logger.info("Cookie 测试成功（未保存）: %s", mask_cookie(raw))
    return {"ok": True, "saved": payload.save, "user": user}


@app.delete("/api/cookie")
def delete_cookie():
    had = config.has_cookie()
    config.clear_cookie()
    if had:
        logger.info("Cookie 已清除")
    return {"ok": True, "cleared": had}


# ---------------------------------------------------------------------------
# 扫码登录
# ---------------------------------------------------------------------------
@app.get("/api/qr/generate")
def qr_generate():
    return qr_manager.generate()


@app.get("/api/qr/status")
def qr_status(key: str = Query(..., min_length=8, max_length=128)):
    result = qr_manager.poll(key)
    if result.get("status") == "success":
        cookie = result.pop("cookie")
        try:
            with BiliClient(cookie=cookie) as client:
                data = client.account_info()
        except BiliError as exc:
            raise HTTPException(status_code=401, detail=f"扫码返回的 Cookie 校验失败：{exc}") from exc
        if not data.get("isLogin"):
            raise HTTPException(status_code=401, detail="扫码返回的 Cookie 无效")
        config.set_cookie(cookie)
        result["user"] = {
            "uname": data.get("uname") or "",
            "mid": data.get("mid") or 0,
            "vip_status": int(data.get("vipStatus") or 0),
        }
        logger.info("扫码登录成功，Cookie 已保存: %s | 账号=%s", mask_cookie(cookie), result["user"]["uname"])
    return result


# ---------------------------------------------------------------------------
# 视频解析
# ---------------------------------------------------------------------------
@app.post("/api/video/parse")
def parse_video(payload: ParseRequest):
    settings = config.get_settings()
    resolver = BiliResolver(cookie=config.get_cookie(), proxy=settings.get("proxy") or "")
    try:
        return resolver.parse(payload.url)
    finally:
        resolver.close()


# ---------------------------------------------------------------------------
# 下载任务
# ---------------------------------------------------------------------------
@app.post("/api/tasks")
def create_tasks(payload: TaskCreateRequest):
    data = payload.model_dump(exclude_unset=False)
    created = downloader.create_tasks(data)
    return {"ok": True, "created": len(created), "tasks": created}


@app.get("/api/tasks")
def list_tasks():
    return {"tasks": downloader.get_all()}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    task = downloader.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.get("/api/tasks/{task_id}/progress")
def get_task_progress(task_id: str):
    task = downloader.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "id": task["id"],
        "status": task["status"],
        "progress": task["progress"],
        "downloaded_bytes": task["downloaded_bytes"],
        "total_bytes": task["total_bytes"],
        "speed": task["speed"],
        "eta": task["eta"],
        "stage": task["stage"],
        "filename": task["filename"],
        "filepath": task["filepath"],
        "error": task["error"],
    }


@app.post("/api/tasks/{task_id}/retry")
def retry_task(task_id: str):
    try:
        task = downloader.retry(task_id)
    except BiliError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    task = downloader.cancel(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str, delete_file: bool = False):
    if not downloader.delete(task_id, delete_file=delete_file):
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True}


@app.post("/api/tasks/{task_id}/open-folder")
def open_task_folder(task_id: str):
    try:
        folder = downloader.open_folder(task_id)
    except BiliError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if folder is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True, "folder": str(folder)}


# ---------------------------------------------------------------------------
# 图片代理（B 站图片有防盗链，后端代取后交给 <img>）
# ---------------------------------------------------------------------------
@app.get("/api/proxy/image")
def proxy_image(url: str = Query(..., max_length=2048)):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not (host.endswith("hdslb.com") or host.endswith("biliimg.com")):
        raise HTTPException(status_code=400, detail="仅允许代理 B 站图片域名")
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="图片 URL 协议不合法")
    try:
        current = url
        for _ in range(3):
            resp = httpx.get(
                current,
                headers={"User-Agent": BASE_HEADERS["User-Agent"], "Referer": "https://www.bilibili.com/"},
                timeout=15,
                follow_redirects=False,
            )
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    raise HTTPException(status_code=502, detail="图片拉取失败")
                current = str(resp.url.join(location))
                redirected = urlparse(current)
                rhost = (redirected.hostname or "").lower()
                if not (rhost.endswith("hdslb.com") or rhost.endswith("biliimg.com")):
                    raise HTTPException(status_code=502, detail="图片跳转域名不合法")
                continue
            resp.raise_for_status()
            break
        else:
            raise HTTPException(status_code=502, detail="图片重定向次数过多")
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="图片拉取失败") from exc
    content_type = resp.headers.get("content-type", "image/jpeg")
    return Response(content=resp.content, media_type=content_type.split(";")[0])


# ---------------------------------------------------------------------------
# WebSocket：任务状态实时推送
# ---------------------------------------------------------------------------
@app.websocket("/api/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_sockets.add(ws)
    loop = asyncio.get_running_loop()
    downloader.attach_ws(loop, ws_sockets)
    await ws.send_json({"type": "tasks_snapshot", "tasks": downloader.get_all()})
    try:
        while True:
            # 客户端可发 ping；不处理具体内容，保持连接
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        ws_sockets.discard(ws)


# ---------------------------------------------------------------------------
# 静态前端（生产构建）；开发时可用 npm run dev + Vite 代理
# ---------------------------------------------------------------------------
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
else:
    @app.get("/")
    def dev_hint():
        return JSONResponse(
            {
                "detail": "前端尚未构建。开发模式请运行 scripts/dev.sh (npm run dev)，"
                          "或运行 npm --prefix frontend install && npm --prefix frontend run build 后重启。"
            }
        )
