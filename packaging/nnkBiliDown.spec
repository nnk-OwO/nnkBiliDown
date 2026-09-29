# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（Windows / macOS / Linux 通用）。

用法： pyinstaller --noconfirm --clean packaging/nnkBiliDown.spec

产物形态：
- Windows / Linux: 单目录（onedir），启动快、可用 --console 排障
- macOS:           .app 应用包（onedir 变体，双击即用）

关键点：
1. 前端产物 frontend/dist 必须打进包内，否则页面打不开
2. ffmpeg / ffprobe 放在 tools/ffmpeg，由 scripts/fetch_ffmpeg.py 提前下载
3. 窗口形态：
   - Windows / macOS / Linux 默认用 Chromium 内核浏览器的 --app 模式开独立窗口，
     系统自带、无需 .NET，避免 pythonnet 这类桥接层带来的兼容性问题；
   - Linux 额外保留 pywebview(GTK) 作为兜底。
4. console=True：保留控制台。
   - Windows 下若做成纯无界面（console=False），stdout/stderr 为 None，
     uvicorn / logging 的 StreamHandler 会抛异常导致进程静默退出；
   - 主界面是应用窗口，控制台仅作为日志与排障出口。
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

APP_NAME = "nnkBiliDown"
ENTRY = str(ROOT / "desktop.py")

# ---------------------------------------------------------------------------
# 1. 静态资源：前端产物 + 内置 ffmpeg
# ---------------------------------------------------------------------------
datas = []
frontend_dist = ROOT / "frontend" / "dist"
if not frontend_dist.is_dir():
    raise SystemExit(
        f"[打包失败] 未找到前端产物：{frontend_dist}\n"
        "           请在项目根目录执行：\n"
        "             python packaging/build.py frontend\n"
        "           或在 frontend/ 下执行 npm install && npm run build"
    )
datas.append((str(frontend_dist), "frontend/dist"))

# 后端源码随包一份（约 100 KB）：
# 1) 用户排障时能直接看到具体实现；
# 2) 高级用户可在不解包 PyInstaller 归档的情况下了解/微调逻辑；
# 运行时代码来自 PYZ 归档，这里的副本不参与导入。
datas.append((str(ROOT / "backend"), "backend"))
for doc in ("README.md", "LICENSE"):
    if (ROOT / doc).is_file():
        datas.append((str(ROOT / doc), "."))


def _binary_toc(files: list[Path], dest: str) -> list[tuple[str, str]]:
    return [(str(path), dest) for path in files if path.is_file()]


ffmpeg_dir = ROOT / "tools" / "ffmpeg"
ffmpeg_files = [ffmpeg_dir / "ffmpeg", ffmpeg_dir / "ffprobe"]
if IS_WINDOWS:
    ffmpeg_files = [ffmpeg_dir / "ffmpeg.exe", ffmpeg_dir / "ffprobe.exe"]
binaries = _binary_toc(ffmpeg_files, "tools/ffmpeg")

if not binaries:
    print(
        "[警告] tools/ffmpeg 下没有找到 ffmpeg/ffprobe，客户端将依赖系统 PATH：\n"
        f"       期望位置：{ffmpeg_dir}\n"
        "       可执行：python packaging/fetch_ffmpeg.py  （自动下载对应平台版本）"
    )

# 随包附带 ffmpeg 的许可证说明（GPL 构建需要保留版权声明）
for extra in (ffmpeg_dir / "LICENSE.txt", ffmpeg_dir / "README.txt"):
    if extra.is_file():
        datas.append((str(extra), "tools/ffmpeg"))

# 图标
icon_png = ROOT / "assets" / "icon.png"
icon_ico = ROOT / "assets" / "icon.ico"
icon_icns = ROOT / "assets" / "icon.icns"
if IS_WINDOWS:
    icon_file = str(icon_ico) if icon_ico.is_file() else None
elif IS_MACOS:
    icon_file = str(icon_icns) if icon_icns.is_file() else (str(icon_png) if icon_png.is_file() else None)
else:
    icon_file = str(icon_png) if icon_png.is_file() else None

# ---------------------------------------------------------------------------
# 2. 收集动态导入的依赖（yt-dlp 提取器、uvicorn 协议实现等）
# ---------------------------------------------------------------------------
hiddenimports: list[str] = []
_collect_targets = [
    "yt_dlp",          # 提取器全部是动态加载的
    "uvicorn",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_settings",
    "anyio",
    "httpx",
    "httpcore",
    "h11",
    "qrcode",
    "PIL",
    "websockets",
    "webview",
    "brotli",
    "multipart",
    "email_validator",
    "annotated_types",
]
for target in _collect_targets:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(target)
    except Exception as exc:  # 该依赖在当前平台不存在时跳过
        print(f"[信息] 跳过 collect_all({target}): {exc}")
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

for module in ("backend", "backend.main", "backend.config", "backend.downloader",
               "backend.bilibili", "backend.qr_login", "backend.models", "backend.runtime"):
    hiddenimports.append(module)

# 后端同目录下的模块（异常处理器等用字符串引用）
hiddenimports += collect_submodules("backend")

# 平台相关：Windows 用 EdgeChromium(.NET)，macOS 用 Cocoa，Linux 用 GTK/Qt
if IS_WINDOWS:
    # Windows 不需要 pywebview/pythonnet：窗口由 WebView2/Edge 的 --app 模式提供
    pass
elif IS_MACOS:
    hiddenimports += [
        "webview.platforms.cocoa",
        "objc",
        "Foundation",
        "AppKit",
        "WebKit",
        "PyObjCTools",
        "Quartz",
    ]
else:
    hiddenimports += [
        "webview.platforms.gtk",
        "webview.platforms.qt",
        "gi",
    ]
    for mod in ("gi",):
        try:
            d, b, h = collect_all(mod)
            datas += d
            binaries += b
            hiddenimports += h
        except Exception:
            pass

# uvicorn 的 loop / http 协议实现是按字符串导入的，必须显式声明
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]
if IS_LINUX:
    # uvicorn[standard] 在 Linux 上会尝试 uvloop；未安装时被 Analysis 自动忽略
    hiddenimports += ["uvicorn.loops.uvloop", "uvloop"]

excludes = [
    "tkinter",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "pytest",
    "setuptools._distutils",
    "test",
    "unittest",
    "pydoc_data",
]

# ---------------------------------------------------------------------------
# 3. 生成
# ---------------------------------------------------------------------------
a = Analysis(
    [ENTRY],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # 见文件头说明：保留控制台，避免窗口/无流模式崩溃
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

if IS_MACOS:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon_file,
        bundle_identifier="com.nnkbilidown.app",
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.15",
            # 未签名分发的自述：仅本地工具，不做网络服务端
            "NSHumanReadableCopyright": "MIT License - nnk-OwO",
            "LSApplicationCategoryType": "public.app-category.utilities",
            "NSRequiresAquaSystemAppearance": False,
        },
    )
