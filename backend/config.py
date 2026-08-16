"""本地配置与历史记录存储。

默认数据目录：~/.nnkbilidown（旧版本 ~/.bili_downloader 会自动迁移）
可用环境变量覆盖：
- NNKBILIDOWN_HOME             数据目录（兼容旧变量 BILIDL_HOME）
- NNKBILIDOWN_DOWNLOAD_DIR     下载根目录（兼容旧变量 BILIDL_DOWNLOAD_DIR）

- config.json : 设置 + Cookie（文件权限 0600，目录 0700）
- history.json: 下载历史

采用原子写入（临时文件 + os.replace），避免进程被强杀时损坏 JSON。
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import tempfile
import threading

try:
    import winreg
except ImportError:  # macOS / Linux 没有 winreg
    winreg = None
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

APP_NAME = "nnkBiliDown"
LEGACY_DATA_DIR_NAME = ".bili_downloader"


def _secure_chmod(path: Path, mode: int) -> None:
    """POSIX 下收紧权限；Windows 上 os.chmod 能力有限，静默忽略。"""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _default_data_dir() -> Path:
    """新版本数据目录，并尽可能把旧版数据无损迁移过来。"""
    new_dir = Path.home() / ".nnkbilidown"
    legacy_dir = Path.home() / LEGACY_DATA_DIR_NAME
    if legacy_dir.is_dir() and not new_dir.is_dir():
        try:
            new_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            for name in ("config.json", "history.json", "cookies.txt", "config.json.bak"):
                src = legacy_dir / name
                if src.is_file():
                    shutil.copy2(src, new_dir / name)
                    _secure_chmod(new_dir / name, 0o600)
        except OSError:
            return legacy_dir
    return new_dir


DATA_DIR = Path(
    os.environ.get("NNKBILIDOWN_HOME")
    or os.environ.get("BILIDL_HOME")
    or _default_data_dir()
).expanduser()


def _read_windows_known_folder(reg_path: str, folder_id: str) -> Path | None:
    """读取 Windows 注册表中被用户移动过的“下载”文件夹真实位置。"""
    if platform.system() != "Windows" or winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
            value, _ = winreg.QueryValueEx(key, folder_id)
        expanded = os.path.expandvars(str(value))
        path = Path(expanded).expanduser()
        if str(path).strip():
            return path
    except OSError:
        return None
    return None


def get_user_downloads_dir() -> Path:
    """跨平台定位系统“下载”文件夹。

    Windows 用户如果已把“下载”移动到 D 盘，注册表 Known Folder 会指向新位置；
    不会再回 C: 建 Downloads。
    """
    home = Path.home()

    if platform.system() == "Windows":
        path = _read_windows_known_folder(
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            "{374DE290-123F-4565-9164-39C4925E467B}",
        )
        if path:
            return path
        path = _read_windows_known_folder(
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            "{374DE290-123F-4565-9164-39C4925E467B}",
        )
        if path:
            return path
        if os.environ.get("USERPROFILE"):
            return Path(os.environ["USERPROFILE"]) / "Downloads"
        if os.environ.get("HOMEDRIVE") and os.environ.get("HOMEPATH"):
            return Path(os.environ["HOMEDRIVE"] + os.environ["HOMEPATH"]) / "Downloads"
        return home / "Downloads"

    if platform.system() == "Linux":
        user_dirs = home / ".config" / "user-dirs.dirs"
        try:
            for line in user_dirs.read_text(encoding="utf-8").splitlines():
                m = re.match(r'^\s*XDG_DOWNLOAD_DIR\s*=\s*"([^"]+)"', line)
                if m:
                    raw = m.group(1).replace("$HOME", str(home))
                    path = Path(os.path.expandvars(raw)).expanduser()
                    if str(path).strip():
                        return path
        except OSError:
            pass
        return home / "Downloads"

    return home / "Downloads"


def get_default_download_dir() -> Path:
    """应用默认下载目录 = 系统下载文件夹 / nnkBiliDown。

    最优先支持显式环境变量（跨平台通用）：
      NNKBILIDOWN_DOWNLOAD_DIR=D:/Videos/bili
    兼容旧变量名 BILIDL_DOWNLOAD_DIR。
    """
    override = os.environ.get("NNKBILIDOWN_DOWNLOAD_DIR") or os.environ.get("BILIDL_DOWNLOAD_DIR")
    if override:
        return Path(override).expanduser()
    return get_user_downloads_dir() / "nnkBiliDown"


DEFAULT_SETTINGS: dict[str, Any] = {
    "download_dir": str(get_default_download_dir()),
    "filename_template": "%(uploader)s/%(title)s [%(id)s].%(ext)s",
    "default_quality": "best",  # best 或具体质量号（如 80）
    "preferred_codec": "auto",  # auto / avc / hevc / av1
    "output_format": "mp4",     # mp4 / mkv
    "max_concurrent": 2,        # 1-3
    "proxy": "",
    "download_subtitles": False,
    "download_danmaku": False,
    "download_thumbnail": False,
    "auto_parse_on_paste": True,
    "auto_open_folder": False,
}

SETTING_TYPES = {
    "download_dir": (str,),
    "filename_template": (str,),
    "default_quality": (str, int),
    "preferred_codec": (str,),
    "output_format": (str,),
    "max_concurrent": (int,),
    "proxy": (str,),
    "download_subtitles": (bool,),
    "download_danmaku": (bool,),
    "download_thumbnail": (bool,),
    "auto_parse_on_paste": (bool,),
    "auto_open_folder": (bool,),
}


def _same_path(a: str, b: str) -> bool:
    """跨平台、大小写不敏感地比较两个路径。"""
    try:
        pa = Path(a).expanduser().resolve(strict=False)
        pb = Path(b).expanduser().resolve(strict=False)
        return os.path.normcase(str(pa)) == os.path.normcase(str(pb))
    except OSError:
        return str(a).strip().rstrip("/\\") == str(b).strip().rstrip("/\\")


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _secure_chmod(Path(tmp_name), 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass


class ConfigManager:
    """设置 + Cookie 管理，进程内只有一个实例。"""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir or DATA_DIR).expanduser()
        self.config_path = self.data_dir / "config.json"
        self._lock = threading.RLock()
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            _secure_chmod(self.data_dir, 0o700)
        except OSError:
            # Windows 某些目录受限时仍尝试继续
            pass
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        data: dict[str, Any] = {"settings": {}, "cookie": ""}
        if self.config_path.exists():
            try:
                loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data.update(loaded)
            except (json.JSONDecodeError, OSError):
                # 配置损坏时保留一份备份，避免把用户 Cookie 静默弄丢
                backup = self.config_path.with_suffix(".json.bak")
                try:
                    self.config_path.replace(backup)
                except OSError:
                    pass
        if not isinstance(data.get("settings"), dict):
            data["settings"] = {}
        # 无论配置是否为新文件，都补齐默认值
        data["settings"] = {**DEFAULT_SETTINGS, **data["settings"]}
        # 旧版本默认目录 ~/Downloads/BiliDL 自动迁移到新版默认目录。
        # 这能解决“用户把系统下载文件夹移动到 D 盘，但旧配置还指向 C 盘”的问题。
        legacy_default = str(Path.home() / "Downloads" / "BiliDL")
        current_download = str(data["settings"].get("download_dir") or "")
        if _same_path(current_download, legacy_default):
            data["settings"]["download_dir"] = str(get_default_download_dir())
        if not isinstance(data.get("cookie"), str):
            data["cookie"] = ""
        if not self.config_path.exists():
            self._save_locked(data)
        return data

    def _save_locked(self, data: dict[str, Any]) -> None:
        _atomic_write_json(self.config_path, data)

    def save(self) -> None:
        with self._lock:
            self._save_locked(self._data)

    # ---- settings ----
    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data["settings"])

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            settings = self._data["settings"]
            errors: dict[str, str] = {}
            for key, value in patch.items():
                if key not in DEFAULT_SETTINGS:
                    continue
                expected = SETTING_TYPES[key]
                if value is not None and not isinstance(value, expected):
                    errors[key] = f"类型错误，应为 {'/'.join(t.__name__ for t in expected)}"
                    continue
                settings[key] = value
            # 业务校验
            if settings.get("max_concurrent") not in (1, 2, 3):
                errors["max_concurrent"] = "并发数只能是 1-3"
                settings["max_concurrent"] = 2
            if settings.get("output_format") not in ("mp4", "mkv"):
                errors["output_format"] = "输出格式只能是 mp4 或 mkv"
                settings["output_format"] = "mp4"
            if settings.get("preferred_codec") not in ("auto", "avc", "hevc", "av1"):
                errors["preferred_codec"] = "编码偏好只能是 auto/avc/hevc/av1"
                settings["preferred_codec"] = "auto"
            if not str(settings.get("proxy", "")).strip():
                settings["proxy"] = ""
            if not str(settings.get("download_dir", "")).strip():
                errors["download_dir"] = "下载目录不能为空"
                settings["download_dir"] = DEFAULT_SETTINGS["download_dir"]
            if not str(settings.get("filename_template", "")).strip():
                errors["filename_template"] = "文件名模板不能为空"
                settings["filename_template"] = DEFAULT_SETTINGS["filename_template"]
            self._save_locked(self._data)
            if errors:
                raise SettingsValidationError(errors)
            return self.get_settings()

    # ---- cookie ----
    def get_cookie(self) -> str:
        with self._lock:
            return str(self._data.get("cookie") or "").strip()

    def has_cookie(self) -> bool:
        return bool(self.get_cookie())

    def set_cookie(self, cookie: str) -> None:
        with self._lock:
            self._data["cookie"] = str(cookie).strip()
            self._save_locked(self._data)

    def clear_cookie(self) -> None:
        self.set_cookie("")
        # 同时删除 yt-dlp 使用的临时 Cookie 文件，避免残留敏感信息
        try:
            self.cookie_file_path().unlink(missing_ok=True)
        except OSError:
            pass

    # ---- data dir helpers ----
    def cookie_file_path(self) -> Path:
        return self.data_dir / "cookies.txt"


class SettingsValidationError(ValueError):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("设置校验失败")


class HistoryStore:
    """下载历史，JSON 持久化，最多保留 800 条。"""

    MAX_RECORDS = 800

    def __init__(self, data_dir: Path | None = None):
        self.path = Path(data_dir or DATA_DIR).expanduser() / "history.json"
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def save(self, records: list[dict[str, Any]]) -> None:
        with self._lock:
            records = records[-self.MAX_RECORDS:]
            self._records = records
            _atomic_write_json(self.path, records)

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(reversed(self._records)))

    def count(self) -> int:
        with self._lock:
            return len(self._records)


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
