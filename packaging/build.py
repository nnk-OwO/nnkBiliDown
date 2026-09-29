#!/usr/bin/env python3
"""nnkBiliDown 客户端一键打包脚本（Windows / macOS / Linux 通用）。

流程：
  1. 校验 Python 版本与项目结构
  2. 生成图标（Pillow）
  3. 安装打包依赖（PyInstaller / pywebview）
  4. 构建前端（已有 frontend/dist 且未加 --build-frontend 时跳过）
  5. 下载并内置 ffmpeg / ffprobe
  6. PyInstaller 打包
  7. 校验产物内是否包含前端与 ffmpeg
  8. 归档为平台安装包（zip / tar.gz）

用法：
    python packaging/build.py                     # 全流程
    python packaging/build.py --skip-ffmpeg       # 不带 ffmpeg（依赖系统 PATH）
    python packaging/build.py --build-frontend    # 强制重新构建前端（需要 Node）
    python packaging/build.py --no-archive        # 只出目录，不压缩
    python packaging/build.py --ci                # CI 模式：带 ffmpeg + 前端
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP_NAME = "nnkBiliDown"
IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"


def log(msg: str) -> None:
    print(f"\n=== {msg}", flush=True)


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> int:
    log("执行：" + " ".join(str(c) for c in cmd))
    # 子进程同样强制 UTF-8，避免 Windows 控制台 GBK 编码下中文输出乱码/报错
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=False, env=env)
    if check and proc.returncode != 0:
        raise SystemExit(f"[失败] 命令退出码 {proc.returncode}：{' '.join(str(c) for c in cmd)}")
    return proc.returncode


def pip_install(*packages: str) -> None:
    run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", *packages])


# ---------------------------------------------------------------------------
def step_check_env() -> None:
    log("检查环境")
    if sys.version_info < (3, 10):
        raise SystemExit(f"[失败] 需要 Python 3.10+，当前 {sys.version.split()[0]}")
    print(f"Python  : {sys.version.split()[0]} ({sys.executable})")
    print(f"平台    : {sys.platform} / {platform.machine()}")

    missing = [p for p in ("backend", "frontend") if not (ROOT / p).is_dir()]
    if missing:
        raise SystemExit(f"[失败] 请在项目根目录运行；缺少目录：{missing}")
    print(f"项目根  : {ROOT}")


def step_icon() -> None:
    log("生成应用图标")
    try:
        import PIL  # noqa: F401
    except ImportError:
        pip_install("pillow")
    run([sys.executable, str(PACKAGING / "make_icon.py")])

    if IS_MACOS:
        step_icns()


def step_icns() -> None:
    """macOS 上把 icon.png 转成 icon.icns（sips + iconutil，系统自带）。"""
    png = ROOT / "assets" / "icon.png"
    icns = ROOT / "assets" / "icon.icns"
    if icns.is_file() and icns.stat().st_mtime >= png.stat().st_mtime:
        print(f"[跳过] {icns} 已是最新")
        return
    if shutil.which("sips") is None or shutil.which("iconutil") is None:
        print("[警告] 未找到 sips / iconutil，跳过 .icns 生成（应用将使用默认图标）")
        return
    iconset = BUILD / "icon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 64, 128, 256, 512):
        run(["sips", "-z", str(size), str(size), str(png), "--out", str(iconset / f"icon_{size}x{size}.png")])
        run([
            "sips", "-z", str(size * 2), str(size * 2), str(png),
            "--out", str(iconset / f"icon_{size}x{size}@2x.png"),
        ])
    run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)])
    print(f"[完成] {icns}")


def step_deps() -> None:
    log("安装打包依赖")
    pip_install("pyinstaller>=6.6")
    pip_install("-r", str(ROOT / "requirements.txt"))
    # pywebview 只是窗口兜底方案：Windows/macOS 主用浏览器 --app 模式，
    # Linux 在无 Chromium 时才会用到它。装不上不应中断打包。
    code = run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
         "--upgrade", "pywebview>=5.1"],
        check=False,
    )
    if code != 0:
        print("[警告] pywebview 安装失败，将不带该兜底方案；应用窗口仍可用")
        if sys.platform.startswith("linux"):
            print("       Linux 如需兜底窗口，请安装系统依赖：")
            print("       sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1")


def step_frontend(force: bool) -> None:
    log("准备前端产物")
    dist = ROOT / "frontend" / "dist"
    index = dist / "index.html"
    frontend = ROOT / "frontend"
    npm = shutil.which("npm") or shutil.which("npm.cmd")

    if index.is_file() and not force:
        print(f"[复用] 已存在构建好的前端：{dist}")
        print("       （需要重新构建请加 --build-frontend）")
        return

    if not npm:
        if index.is_file():
            print("[警告] 未找到 npm，沿用仓库里已有的 frontend/dist")
            return
        raise SystemExit(
            "[失败] 需要构建前端但没有找到 npm。\n"
            "       请安装 Node.js 18+，或从完整仓库获取已构建的 frontend/dist。"
        )

    # 避免打包工具把海量依赖塞进产物：构建完就还原 node_modules
    node_modules = frontend / "node_modules"
    stash = frontend / "_node_modules_packaging_stash"
    stashed = False
    if node_modules.is_dir() and not stash.exists():
        print("[信息] 临时移出 node_modules，避免影响 PyInstaller 收集")
        node_modules.rename(stash)
        stashed = True
    try:
        run([npm, "install", "--no-audit", "--no-fund"], cwd=frontend)
        run([npm, "run", "build"], cwd=frontend)
    finally:
        if stashed and stash.is_dir():
            if node_modules.is_dir():
                shutil.rmtree(node_modules)
            stash.rename(node_modules)

    if not index.is_file():
        raise SystemExit("[失败] 前端构建后仍未生成 frontend/dist/index.html")
    print(f"[完成] 前端产物：{dist}")


def step_ffmpeg(skip: bool) -> bool:
    """下载并内置 ffmpeg，返回是否成功内置。"""
    if skip:
        print("\n[跳过] 不内置 ffmpeg（客户端将使用系统 PATH 中的 ffmpeg）")
        return False
    log("下载并内置 ffmpeg")
    code = run([sys.executable, str(PACKAGING / "fetch_ffmpeg.py")], check=False)
    if code != 0:
        print("[警告] ffmpeg 内置失败，继续打包；客户端将回退到系统 PATH 的 ffmpeg")
        return False
    return True


def step_pyinstaller() -> Path:
    log("PyInstaller 打包")
    if DIST.exists():
        shutil.rmtree(DIST)
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        str(PACKAGING / f"{APP_NAME}.spec"),
    ])
    return DIST


def step_verify(require_ffmpeg: bool) -> None:
    log("校验产物")
    if IS_MACOS:
        bundle = DIST / f"{APP_NAME}.app"
        app_dir = bundle / "Contents" / "Resources" / APP_NAME
        exe = bundle / "Contents" / "MacOS" / APP_NAME
    else:
        app_dir = DIST / APP_NAME
        exe = app_dir / (f"{APP_NAME}.exe" if IS_WINDOWS else APP_NAME)

    if not exe.exists():
        raise SystemExit(f"[失败] 未找到可执行文件：{exe}")
    print(f"[就绪] 可执行文件：{exe}")

    # PyInstaller 6 把 datas 放进 _internal/（osx 是 Resources/<name>/_internal），
    # 旧版本则直接散在应用目录；两种布局都要能识别。
    search_bases = [
        app_dir,
        app_dir / "_internal",
        exe.parent,
        exe.parent / "_internal",
        app_dir.parent / "Resources" / APP_NAME / "_internal",
    ]
    ffmpeg_name = "ffmpeg.exe" if IS_WINDOWS else "ffmpeg"

    def locate(rel: Path) -> Path | None:
        for base in search_bases:
            candidate = base / rel
            if candidate.exists():
                return candidate
        return None

    required = {
        "前端 index.html": Path("frontend/dist/index.html"),
        "后端代码": Path("backend/main.py"),
    }
    for label, rel in required.items():
        found = locate(rel)
        if not found:
            raise SystemExit(f"[失败] 产物缺少 {label}：{app_dir / rel}")
        print(f"  [OK]   {label}: {rel} ({found.stat().st_size / 1024:.0f} KB)")

    ffmpeg_path = locate(Path("tools/ffmpeg") / ffmpeg_name)
    if ffmpeg_path:
        print(f"  [OK]   内置 ffmpeg: tools/ffmpeg/{ffmpeg_name} "
              f"({ffmpeg_path.stat().st_size / 1024 / 1024:.1f} MB)")
    elif require_ffmpeg:
        raise SystemExit(
            "[失败] 产物里没有内置 ffmpeg，但本次构建要求必须内置。\n"
            "       请检查 packaging/fetch_ffmpeg.py 的输出。"
        )
    else:
        print("  [警告] 未内置 ffmpeg（运行时需要系统 PATH 中存在）")

    # 前端资源完整性：index.html 引用的 assets 必须都在
    index = locate(Path("frontend/dist/index.html"))
    if index:
        import re
        frontend_dir = index.parent
        html = index.read_text(encoding="utf-8")
        for asset in re.findall(r'(?:src|href)="([^"]+)"', html):
            if asset.startswith(("http://", "https://", "data:", "#", "/")):
                continue
            if not (frontend_dir / asset.lstrip("./")).exists():
                raise SystemExit(f"[失败] 前端产物缺少资源：{asset}")
        print("  [OK]   前端静态资源引用完整")


def step_smoke_test() -> None:
    """真正启动一次打包产物，验证服务与内置 ffmpeg 可用。

    静态检查看不出「模块漏收集导致启动即崩」这类问题，所以这里跑一次真机冒烟：
    启动 -> 轮询 /api/health -> 校验 ffmpeg 来源 -> 结束进程。
    """
    log("冒烟测试：启动打包产物并请求 /api/health")
    import json
    import socket
    import tempfile
    import time
    import urllib.request

    if IS_MACOS:
        exe = DIST / f"{APP_NAME}.app" / "Contents" / "MacOS" / APP_NAME
    else:
        exe = DIST / APP_NAME / (f"{APP_NAME}.exe" if IS_WINDOWS else APP_NAME)
    if not exe.exists():
        print("[警告] 未找到可执行文件，跳过冒烟测试")
        return

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])

    env = {**os.environ, "PYTHONUTF8": "1"}
    with tempfile.TemporaryDirectory(prefix="nnk-smoke-") as data_dir:
        # 用独立数据目录，避免污染用户真实配置
        env["NNKBILIDOWN_HOME"] = data_dir
        env["NNKBILIDOWN_NO_BROWSER"] = "1"
        proc = subprocess.Popen(
            [str(exe), "--port", str(port), "--no-window", "--no-browser"],
            cwd=str(exe.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            url = f"http://127.0.0.1:{port}/api/health"
            payload = None
            deadline = time.time() + 90
            while time.time() < deadline:
                if proc.poll() is not None:
                    out = proc.stdout.read() if proc.stdout else ""
                    raise SystemExit(
                        f"[失败] 产物启动后立即退出（代码 {proc.returncode}）：\n{out[-4000:]}"
                    )
                try:
                    with urllib.request.urlopen(url, timeout=3) as resp:
                        payload = json.loads(resp.read().decode("utf-8"))
                    break
                except Exception:
                    time.sleep(0.5)

            if payload is None:
                raise SystemExit("[失败] 冒烟测试超时：90 秒内 /api/health 未就绪")

            print(f"  [OK]   服务启动成功，健康检查通过")
            print(f"  [OK]   前端已构建：{payload.get('frontend_built')}")
            print(f"  [OK]   yt-dlp：{payload.get('yt_dlp')}")
            ff = payload.get("ffmpeg") or {}
            if ff.get("ok"):
                print(f"  [OK]   ffmpeg 来源={ff.get('source')} 路径={ff.get('path')}")
                if ff.get("source") != "bundled":
                    print("  [警告] ffmpeg 不是内置版本，可能回退到了系统 PATH")
            else:
                print(f"  [警告] ffmpeg 不可用：{ff.get('hint')}")

            # 页面本身也要能打开
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            if "<div id=" not in html and "<script" not in html:
                raise SystemExit("[失败] 首页返回的内容不像前端页面")
            print("  [OK]   首页可访问")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def _zip_dir(src: Path, target: Path, root_prefix: str | None = None) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                arcname = Path(root_prefix or src.name) / path.relative_to(src)
                zf.write(path, str(arcname))
    print(f"[完成] {target} ({target.stat().st_size / 1024 / 1024:.1f} MB)")


def _targz_dir(src: Path, target: Path, root_prefix: str | None = None) -> None:
    with tarfile.open(target, "w:gz") as tf:
        tf.add(src, arcname=root_prefix or src.name)
    print(f"[完成] {target} ({target.stat().st_size / 1024 / 1024:.1f} MB)")


def step_archive() -> None:
    log("打包归档")
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"

    if IS_MACOS:
        src = DIST / f"{APP_NAME}.app"
        target = DIST / f"{APP_NAME}-macOS-{arch}.zip"
        # ditto 能保留 .app 内的符号链接、可执行权限与资源分叉（未签名分发必须）
        if shutil.which("ditto"):
            run(["ditto", "-c", "-k", "--sequesterRsrc", str(src), str(target)])
            print(f"[完成] {target} ({target.stat().st_size / 1024 / 1024:.1f} MB)")
        else:
            _zip_dir(src, target)
    elif IS_WINDOWS:
        src = DIST / APP_NAME
        target = DIST / f"{APP_NAME}-Windows-{arch}.zip"
        _zip_dir(src, target, root_prefix=APP_NAME)
    else:
        src = DIST / APP_NAME
        target = DIST / f"{APP_NAME}-Linux-{arch}.tar.gz"
        _targz_dir(src, target, root_prefix=APP_NAME)


def main() -> int:
    parser = argparse.ArgumentParser(description="nnkBiliDown 客户端打包")
    parser.add_argument("--skip-ffmpeg", action="store_true", help="不内置 ffmpeg")
    parser.add_argument("--build-frontend", action="store_true", help="强制重新构建前端")
    parser.add_argument("--no-archive", action="store_true", help="不生成压缩包")
    parser.add_argument("--icon-only", action="store_true", help="只生成图标后退出")
    parser.add_argument("--skip-smoke-test", action="store_true", help="跳过启动冒烟测试")
    parser.add_argument("--ci", action="store_true", help="CI 模式：内置 ffmpeg + 前端")
    args = parser.parse_args()

    os.environ.setdefault("PYTHONUTF8", "1")
    step_check_env()
    step_icon()
    if args.icon_only:
        return 0

    step_deps()
    step_frontend(force=args.build_frontend)
    bundled = step_ffmpeg(skip=args.skip_ffmpeg)
    step_pyinstaller()
    step_verify(require_ffmpeg=bundled or args.ci)
    if not args.skip_smoke_test:
        step_smoke_test()
    if not args.no_archive:
        step_archive()

    log("全部完成")
    print(f"产物目录：{DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
