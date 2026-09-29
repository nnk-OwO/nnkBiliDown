"""nnkBiliDown 客户端入口（打包后的主程序）。

职责：
1. 配置崩溃安全日志（窗口模式下 stderr 可能不存在）
2. 选一个空闲端口并启动 uvicorn（后台线程）
3. 等待服务就绪后弹出应用窗口
4. 窗口不可用时逐级回退：应用窗口 → pywebview 原生窗口 → 系统浏览器
5. 退出时通知 uvicorn 停机

关于「窗口」的实现选择：
- 默认使用 Chromium 内核浏览器的 --app 模式（Windows: Edge → Chrome；
  macOS: Chrome → Edge → Chromium；Linux: chromium → google-chrome → edge）。
  它给出的是无地址栏、无标签页的独立窗口，外观与原生客户端一致，系统自带、
  无需安装 .NET，也不依赖 pythonnet 这类易碎的桥接层。
- 所有浏览器都不可用时，退回 pywebview(GTK/Cocoa) 原生窗口。
- 再不行则由系统浏览器打开，保证功能可用。

命令行参数（打包后同样可用，便于排障）：
    nnkBiliDown.exe                 # 正常启动：应用窗口
    nnkBiliDown.exe --no-window     # 只起服务 + 打开浏览器（等同旧版行为）
    nnkBiliDown.exe --port 7861     # 指定端口
    nnkBiliDown.exe --window-mode chrome     # 指定窗口后端
    nnkBiliDown.exe --console       # 保留控制台输出细节
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

DEFAULT_PORT = 7860
DEFAULT_HOST = "127.0.0.1"
WINDOW_TITLE = "nnkBiliDown"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 860
APP_PROFILE_DIRNAME = "window-profile"


# ---------------------------------------------------------------------------
# 日志：窗口模式下 Windows 的 stderr 可能为 None，必须容错
# ---------------------------------------------------------------------------
class _NullStream:
    """替代缺失的 stdout / stderr，避免 logging 写入时抛异常。"""

    def write(self, _msg: str) -> int:
        return 0

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


def _secure_streams() -> None:
    # 中文日志 + cp1252 控制台会抛 UnicodeEncodeError，这里先把编码切到 UTF-8
    os.environ.setdefault("PYTHONUTF8", "1")
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            setattr(sys, name, _NullStream())
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
        try:
            stream.write("")
            stream.flush()
        except Exception:
            setattr(sys, name, _NullStream())


def setup_logging(verbose: bool = True) -> logging.Logger:
    """同时输出到控制台（若可用）和文件，便于用户反馈问题时取证。"""
    _secure_streams()
    from backend.config import DATA_DIR

    logger = logging.getLogger("nnkbilidown")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    if verbose:
        logger.addHandler(stream_handler)

    try:
        log_dir = DATA_DIR.expanduser()
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "nnkbilidown.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        if not logger.handlers:
            logger.addHandler(stream_handler)

    # uvicorn 自身的日志也走同一套 handler，避免窗口模式下报 No handler
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
    return logger


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    logging.getLogger("nnkbilidown").critical(
        "未捕获异常", exc_info=(exc_type, exc_value, exc_tb)
    )


# ---------------------------------------------------------------------------
# 端口 / 服务
# ---------------------------------------------------------------------------
def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def pick_port(host: str, preferred: int) -> int:
    """优选 7860；被占用时退回内核分配的随机空闲端口。"""
    if preferred and port_is_free(host, preferred):
        return preferred
    if preferred:
        logging.getLogger("nnkbilidown").warning("端口 %s 被占用，改用随机空闲端口", preferred)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def wait_for_server(host: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def start_server(host: str, port: int) -> tuple[threading.Thread, object]:
    import uvicorn

    from backend.main import app

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        reload=False,
    )
    server = uvicorn.Server(config)

    def run() -> None:
        try:
            server.run()
        except Exception:
            logging.getLogger("nnkbilidown").exception("服务异常退出")

    thread = threading.Thread(target=run, name="uvicorn", daemon=True)
    thread.start()
    return thread, server


# ---------------------------------------------------------------------------
# 应用窗口（Chromium --app 模式）
# ---------------------------------------------------------------------------
def _browser_candidates() -> list[tuple[str, Path]]:
    """返回 [(后端名, 可执行文件)]，按优先级排序，只保留真实存在的浏览器。

    注意：只收「浏览器」，不收 WebView2 Runtime（msedgewebview2.exe）。
    后者是渲染引擎宿主，不接受 --app，启动后会立刻退出（代码 13）。
    """
    found: list[tuple[str, Path]] = []
    env = os.environ

    def add(name: str, *paths: str | None) -> None:
        for raw in paths:
            if not raw:
                continue
            candidate = Path(raw)
            if candidate.is_file():
                found.append((name, candidate))
                return

    if sys.platform.startswith("win"):
        pf = env.get("ProgramFiles", r"C:\Program Files")
        pf86 = env.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = env.get("LOCALAPPDATA", "")
        # Edge 在 Windows 10/11 上基本必然存在，作为首选；Chrome 次之
        add(
            "edge",
            rf"{pf86}\Microsoft\Edge\Application\msedge.exe",
            rf"{pf}\Microsoft\Edge\Application\msedge.exe",
        )
        add(
            "chrome",
            rf"{pf}\Google\Chrome\Application\chrome.exe",
            rf"{pf86}\Google\Chrome\Application\chrome.exe",
            rf"{local}\Google\Chrome\Application\chrome.exe",
        )
    elif sys.platform == "darwin":
        add("chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        add("edge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
        add(
            "chromium",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        )
    else:
        for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
                     "microsoft-edge", "microsoft-edge-stable", "brave-browser"):
            path = shutil.which(name)
            if path:
                found.append((name, Path(path)))
    return found


def launch_app_window(url: str, logger: logging.Logger, preferred: str = "") -> tuple[subprocess.Popen | None, Path | None]:
    """用 Chromium 的 --app 模式开一个独立窗口（无地址栏/标签页）。

    返回 (启动进程, 用户数据目录)。注意 Chromium 在 Windows/macOS 上会把请求
    转交给浏览器主进程后立刻退出，所以不能只依赖这个进程的存活来判断窗口关闭，
    还需要配合 user-data-dir 下的 SingletonLock（内含真实主进程 PID）。
    """
    from backend.config import DATA_DIR

    profile = DATA_DIR / APP_PROFILE_DIRNAME
    try:
        profile.mkdir(parents=True, exist_ok=True)
    except OSError:
        profile = None

    candidates = _browser_candidates()
    if preferred and preferred not in ("", "auto"):
        filtered = [c for c in candidates if c[0] == preferred]
        if filtered:
            candidates = filtered
        else:
            logger.warning("指定的窗口后端 %s 不可用，改用自动选择", preferred)
    if not candidates:
        logger.info("未找到可用的 Chromium 内核浏览器")
        return None, profile

    for name, exe in candidates:
        size = f"--window-size={WINDOW_WIDTH},{WINDOW_HEIGHT}"
        args = [str(exe), f"--app={url}", size, "--window-position=80,60"]
        if profile is not None:
            args.append(f"--user-data-dir={profile}")
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError as exc:
            logger.info("以 %s 打开窗口失败：%s", name, exc)
            continue
        logger.info("应用窗口已启动（%s）：%s", name, exe)
        return proc, profile
    return None, profile


def _singleton_pid(profile: Path | None) -> int | None:
    """从 Chromium 的 SingletonLock 中读出浏览器主进程 PID。

    注意：Edge/Chrome 在 ``--app`` + 自定义 ``--user-data-dir`` 时不一定创建该文件，
    所以它只能作为「可用则更好」的辅助信号，不能作为唯一依据。
    """
    if profile is None:
        return None
    for name in ("SingletonLock", "SingletonCookie"):
        lock = profile / name
        try:
            raw = lock.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        for line in raw.splitlines():
            line = line.strip()
            if line.isdigit():
                return int(line)
    return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=15,
                check=False,
                stdin=subprocess.DEVNULL,
            ).stdout or ""
        except Exception:
            return False
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def run_until_window_closes(
    proc: subprocess.Popen | None,
    profile: Path | None,
    url: str,
    logger: logging.Logger,
    quit_with_window: bool = False,
) -> None:
    """窗口起来之后保持服务运行。

    默认**不**跟随窗口生命周期退出，原因：
    - Chromium 的启动器进程会把请求交接给浏览器主进程后立刻退出（Windows/macOS），
      而 SingletonLock 在 ``--app`` 模式下并不可靠；
    - 一旦误判「窗口已关闭」，用户正在进行的下载会被直接杀死。

    因此默认策略是「窗口 + 常驻服务」，退出方式见日志提示；
    需要旧行为时加 ``--quit-with-window``（仅在能明确跟踪到主进程时生效）。
    """
    if proc is None:
        return

    time.sleep(2.5)
    launcher_code = proc.poll()

    if not quit_with_window:
        if launcher_code is not None and launcher_code != 0:
            logger.warning("窗口启动器异常退出（代码 %s），尝试用系统浏览器打开", launcher_code)
            try:
                webbrowser.open(url)
            except Exception:
                pass
        logger.info("=" * 46)
        logger.info("应用窗口已就绪：%s", url)
        logger.info("提示：关闭窗口后本程序仍在后台运行。")
        if sys.platform.startswith("win"):
            logger.info("      退出方式：在任务管理器结束 nnkBiliDown.exe，或按 Ctrl+C（控制台模式）。")
        else:
            logger.info("      退出方式：关闭本终端窗口，或按 Ctrl+C。")
        logger.info("日志文件：数据目录/nnkbilidown.log")
        logger.info("=" * 46)
        wait_forever()
        return

    # --quit-with-window：只在能可靠跟踪主进程时才跟随退出
    if launcher_code is None:
        logger.info("等待窗口关闭…")
        try:
            proc.wait()
        except KeyboardInterrupt:
            raise
        logger.info("窗口已关闭")
        return

    pid = _singleton_pid(profile)
    if pid is None or not _pid_alive(pid):
        logger.warning("无法跟踪窗口进程，保持服务运行（不会自动退出）")
        wait_forever()
        return

    logger.info("跟踪窗口主进程 %s，窗口关闭后自动退出", pid)
    while _pid_alive(pid):
        time.sleep(2.0)
    logger.info("窗口主进程已退出")


def launch_pywebview(url: str, logger: logging.Logger) -> bool:
    """最后手段：pywebview 原生窗口（Linux/GTK 或 macOS/Cocoa）。"""
    try:
        import webview  # noqa: F401
    except Exception as exc:
        logger.info("pywebview 不可用：%s", exc)
        return False

    if sys.platform.startswith("linux"):
        os.environ.setdefault("PYWEBVIEW_GUI", "gtk")
    try:
        import webview

        window = webview.create_window(
            WINDOW_TITLE, url, width=WINDOW_WIDTH, height=WINDOW_HEIGHT, min_size=(900, 620)
        )
        del window
        webview.start()
        return True
    except Exception as exc:
        logger.info("pywebview 窗口启动失败：%s", exc)
        return False


def window_failure_hint() -> str:
    if sys.platform.startswith("win"):
        return "若窗口未出现，请安装 Microsoft Edge 或 Google Chrome。"
    if sys.platform == "darwin":
        return "若窗口未出现，请安装 Google Chrome 或 Microsoft Edge。"
    return (
        "若窗口未出现，请安装 Chromium/Chrome：\n"
        "  Debian/Ubuntu: sudo apt install chromium\n"
        "  Fedora:        sudo dnf install chromium\n"
        "  Arch:          sudo pacman -S chromium"
    )


def wait_forever() -> None:
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nnkBiliDown", description="nnkBiliDown 客户端")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-window", action="store_true", help="不弹应用窗口，改为打开系统浏览器")
    parser.add_argument("--no-browser", action="store_true", help="配合 --no-window：连浏览器也不打开")
    parser.add_argument(
        "--window-mode",
        default="auto",
        choices=["auto", "edge", "chrome", "chromium", "pywebview", "browser", "none"],
        help="窗口后端选择，默认 auto（自动挑选可用浏览器）",
    )
    parser.add_argument("--console", action="store_true", help="保留控制台日志输出")
    parser.add_argument(
        "--quit-with-window",
        action="store_true",
        help="关闭窗口时一并退出（默认关闭窗口后服务继续运行，避免中断下载）",
    )
    args = parser.parse_args(argv)

    verbose = args.console or not getattr(sys, "frozen", False)
    logger = setup_logging(verbose=verbose)
    sys.excepthook = _excepthook

    logger.info("=" * 46)
    logger.info("  nnkBiliDown - Bilibili 视频下载器")
    logger.info("=" * 46)

    from backend.main import BUNDLED_FFMPEG_DIR, ffmpeg_status

    if BUNDLED_FFMPEG_DIR:
        logger.info("内置 ffmpeg 目录：%s", BUNDLED_FFMPEG_DIR)
    ff = ffmpeg_status()
    if ff["ok"]:
        logger.info("ffmpeg 就绪：%s（来源：%s）", ff["version"], ff.get("source"))
    else:
        logger.warning("未检测到 ffmpeg：%s", ff.get("hint"))

    port = pick_port(args.host, args.port)
    url = f"http://{args.host}:{port}"
    _, server = start_server(args.host, port)

    if not wait_for_server(args.host, port):
        logger.error("服务启动超时，请查看日志：数据目录/nnkbilidown.log")
        return 1
    logger.info("服务已就绪：%s", url)

    window_proc: subprocess.Popen | None = None
    window_profile: Path | None = None
    try:
        if args.no_window or args.window_mode == "none":
            if args.no_browser:
                logger.info("已禁用浏览器，服务保持运行中…")
                wait_forever()
            else:
                logger.info("服务地址：%s（按 Ctrl+C 停止）", url)
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
                wait_forever()
            return 0

        if args.window_mode == "browser":
            logger.info("按参数要求使用系统浏览器")
            webbrowser.open(url)
            wait_forever()
            return 0

        if args.window_mode == "pywebview":
            if not launch_pywebview(url, logger):
                webbrowser.open(url)
                wait_forever()
            return 0

        window_proc, window_profile = launch_app_window(url, logger, preferred=args.window_mode)

        if window_proc is None:
            logger.warning("无法启动应用窗口，尝试 pywebview")
            if not launch_pywebview(url, logger):
                logger.warning("改为使用系统浏览器。%s", window_failure_hint())
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
                wait_forever()
            return 0

        run_until_window_closes(
            window_proc, window_profile, url, logger, quit_with_window=args.quit_with_window
        )
        return 0
    finally:
        try:
            server.should_exit = True
        except Exception:
            pass
        logger.info("nnkBiliDown 已退出")
        # 下载线程池为 daemon 线程，交给 OS 回收；避免解释器在关闭阶段卡住
        logging.shutdown()
        os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
