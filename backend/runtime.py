"""打包（PyInstaller）与源码两种运行模式下的运行时资源定位。

为什么需要这个模块：
- 源码运行时，前端产物在 <repo>/frontend/dist，ffmpeg 由系统 PATH 提供；
- 打包成客户端后，进程被冻结（``sys.frozen``），仓库目录不复存在，
  frontend/dist 与 ffmpeg 都在 PyInstaller 的解包目录 ``sys._MEIPASS`` 里。

对外只暴露三件事：
- ``resource_path(*parts)``  读取只读捆绑资源（前端产物、图标等）
- ``frontend_dist()``        前端产物目录
- ``ffmpeg_exe()`` / ``ffprobe_exe()`` / ``ffmpeg_dir()`` / ``ensure_ffmpeg_on_path()``
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

IS_FROZEN = bool(getattr(sys, "frozen", False))

# 客户端内置的 ffmpeg 相对解包目录的位置
BUNDLED_FFMPEG_DIR = "tools/ffmpeg"

# 允许用环境变量覆盖，方便测试与高级用户自带 ffmpeg
ENV_FFMPEG = "NNKBILIDOWN_FFMPEG"

_ffmpeg_cache: dict[str, str | None] = {}


def resource_root() -> Path:
    """只读资源的根目录。

    冻结运行时是 PyInstaller 的解包目录；源码运行时是仓库根目录。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    if IS_FROZEN:
        # 兜底：PyInstaller 6 把资源放在可执行文件旁的 _internal；
        # py2app 等其它冻结器会放在 Contents/MacOS 或 Contents/Resources。
        exe_dir = Path(sys.executable).resolve().parent
        for candidate in (
            exe_dir,
            exe_dir / "_internal",
            exe_dir.parent / "Resources",
            exe_dir.parent / "Resources" / exe_dir.name / "_internal",
            exe_dir.parent,
        ):
            if (candidate / "frontend" / "dist").is_dir():
                return candidate
        return exe_dir
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    return resource_root().joinpath(*parts)


def frontend_dist() -> Path:
    """前端静态产物目录，优先捆绑资源。"""
    bundled = resource_path("frontend", "dist")
    if bundled.is_dir():
        return bundled
    return Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _sibling_candidates(name: str) -> list[Path]:
    """候选可执行文件名（Windows 需要 .exe 后缀）。"""
    if os.name == "nt":
        return [Path(f"{name}.exe"), Path(name)]
    return [Path(name)]


def _bundled_dirs() -> list[Path]:
    dirs = [resource_path(*BUNDLED_FFMPEG_DIR.split("/"))]
    # 开发场景：把可执行文件手工放进 tools/ffmpeg 后也能被识别
    dirs.append(Path(__file__).resolve().parent.parent / "tools" / "ffmpeg")
    seen: list[Path] = []
    for d in dirs:
        if d not in seen:
            seen.append(d)
    return seen


def ffmpeg_exe() -> str | None:
    """定位 ffmpeg 可执行文件。

    顺序：环境变量覆盖 → 客户端内置 → 系统 PATH。
    """
    if "ffmpeg" in _ffmpeg_cache:
        return _ffmpeg_cache["ffmpeg"]

    found: str | None = None
    override = (os.environ.get(ENV_FFMPEG) or "").strip()
    if override:
        candidate = Path(override).expanduser()
        # 允许直接指向 ffmpeg 本体，也允许指向所在目录
        if candidate.is_dir():
            for name in _sibling_candidates("ffmpeg"):
                if (candidate / name).is_file():
                    found = str(candidate / name)
                    break
        elif candidate.is_file():
            found = str(candidate)

    if not found:
        for directory in _bundled_dirs():
            if not directory.is_dir():
                continue
            for name in _sibling_candidates("ffmpeg"):
                candidate = directory / name
                if candidate.is_file():
                    found = str(candidate)
                    break
            if found:
                break

    if not found:
        found = shutil.which("ffmpeg")

    _ffmpeg_cache["ffmpeg"] = found
    return found


def ffprobe_exe() -> str | None:
    """定位 ffprobe；优先与 ffmpeg 同目录，避免版本错配。"""
    if "ffprobe" in _ffmpeg_cache:
        return _ffmpeg_cache["ffprobe"]

    found: str | None = None
    ff = ffmpeg_exe()
    if ff:
        directory = Path(ff).parent
        for name in _sibling_candidates("ffprobe"):
            candidate = directory / name
            if candidate.is_file():
                found = str(candidate)
                break

    if not found:
        for directory in _bundled_dirs():
            if not directory.is_dir():
                continue
            for name in _sibling_candidates("ffprobe"):
                candidate = directory / name
                if candidate.is_file():
                    found = str(candidate)
                    break
            if found:
                break

    if not found:
        found = shutil.which("ffprobe")

    _ffmpeg_cache["ffprobe"] = found
    return found


def ffmpeg_dir() -> str | None:
    """返回可作为 yt-dlp ``ffmpeg_location`` 的目录。"""
    ff = ffmpeg_exe()
    return str(Path(ff).parent) if ff else None


def ensure_ffmpeg_on_path() -> str | None:
    """把 ffmpeg 所在目录加入 PATH，让 subprocess / yt-dlp 直接找到它。

    返回注入的目录（没有内置 ffmpeg 时返回 None）。
    """
    directory = ffmpeg_dir()
    if not directory:
        return None
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    if directory not in parts:
        os.environ["PATH"] = directory + os.pathsep + current if current else directory
    return directory


def reset_cache() -> None:
    """测试用：清空定位缓存。"""
    _ffmpeg_cache.clear()
