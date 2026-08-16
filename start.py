"""nnkBiliDown 跨平台启动器。

负责：
1. 检查 Python 版本（>= 3.10）
2. 自动创建 .venv（如不存在）
3. 自动安装后端依赖
4. 检测 ffmpeg 并给出安装提示
5. 启动 uvicorn，等服务端口就绪后自动打开浏览器
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"


def _venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def in_venv() -> bool:
    try:
        return sys.prefix != sys.base_prefix
    except AttributeError:
        return False


def step(msg: str) -> None:
    print(f"\n[步骤] {msg}", flush=True)


def ensure_venv() -> Path:
    """返回用于运行后端的 Python 解释器。"""
    if in_venv():
        step("检测到当前已在虚拟环境中，直接使用当前解释器")
        return Path(sys.executable)

    py = _venv_python()
    if py.exists():
        step("虚拟环境已存在")
        return py

    step("创建 Python 虚拟环境 .venv ...（通常几秒到十几秒）")
    try:
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
    except subprocess.CalledProcessError:
        print("[错误] 虚拟环境创建失败。", flush=True)
        print("        请确认已安装 Python 3.10+，并且安装时勾选了 Add python.exe to PATH。")
        print("        也可以手动运行：python -m venv .venv")
        sys.exit(1)
    py = _venv_python()
    if not py.exists():
        print("[错误] 虚拟环境创建后未找到解释器：", py, flush=True)
        sys.exit(1)
    return py


def ensure_dependencies(py: Path) -> None:
    probe = [str(py), "-c", "import fastapi, yt_dlp, httpx, qrcode"]
    ok = subprocess.run(probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if ok:
        step("后端依赖已就绪")
        return
    step("安装后端依赖（首次运行需要 1-2 分钟，请保持网络畅通）...")
    ret = subprocess.run(
        [str(py), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        check=False,
    ).returncode
    if ret != 0:
        print("[错误] 依赖安装失败。", flush=True)
        print("        请检查网络，或手动运行：")
        print(f"        {py} -m pip install -r requirements.txt")
        sys.exit(1)
    step("依赖安装完成")


def check_ffmpeg() -> None:
    path = shutil.which("ffmpeg")
    if path:
        step(f"ffmpeg 已就绪：{path}")
        return
    if sys.platform == "win32":
        hint = "winget install Gyan.FFmpeg   或   choco install ffmpeg"
    elif sys.platform == "darwin":
        hint = "brew install ffmpeg"
    else:
        hint = "sudo apt install ffmpeg"
    print("[警告] 未检测到 ffmpeg！", flush=True)
    print(f"        安装方法：{hint}", flush=True)
    print("        Web 页面的“设置”里也会显示安装提示。", flush=True)


def wait_for_port(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def open_browser(url: str, no_browser: bool) -> None:
    if no_browser or os.environ.get("NNKBILIDOWN_NO_BROWSER") == "1" or os.environ.get("BILIDL_NO_BROWSER") == "1":
        return
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="nnkBiliDown")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    print("=" * 46, flush=True)
    print("  nnkBiliDown - Bilibili 视频下载器", flush=True)
    print("=" * 46, flush=True)

    if sys.version_info < (3, 10):
        print(f"[错误] 当前 Python 版本为 {sys.version.split()[0]}，需要 Python 3.10+。")
        sys.exit(1)
    print(f"[信息] 当前 Python：{sys.version.split()[0]}  ->  {sys.executable}", flush=True)

    py = ensure_venv()
    ensure_dependencies(py)
    check_ffmpeg()

    url = f"http://localhost:{args.port}"
    print(f"\n[启动] 正在启动服务：{url}", flush=True)
    print("[提示] 看到这个光标是正常的，表示本地服务正在运行。", flush=True)
    print("        按 Ctrl+C 可停止服务。\n", flush=True)

    cmd = [
        str(py),
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--access-log",
    ]
    proc = subprocess.Popen(cmd, cwd=str(ROOT))

    if not wait_for_port(args.host, args.port):
        print("[警告] 服务端口迟迟未就绪，仍会继续等待；请查看上方错误信息。", flush=True)
    else:
        print(f"[就绪] 服务已启动，正在打开浏览器：{url}", flush=True)
        open_browser(url, args.no_browser)

    try:
        returncode = proc.wait()
    except KeyboardInterrupt:
        print("\n[停止] 正在停止 nnkBiliDown...", flush=True)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        returncode = 0
    if returncode != 0:
        print(f"[错误] 服务退出，代码：{returncode}", flush=True)
        sys.exit(returncode)


if __name__ == "__main__":
    main()
