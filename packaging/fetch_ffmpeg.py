#!/usr/bin/env python3
"""下载当前平台的 ffmpeg / ffprobe 到 tools/ffmpeg，供打包内置。

为什么要内置：DASH 音视频合并必须依赖 ffmpeg，客户端要做到「解压即用」，
就不能要求用户再装一次 ffmpeg。

来源（按顺序尝试，失败自动换源）：
- Windows : BtbN/FFmpeg-Builds  win64-gpl / winarm64-gpl
- Linux   : BtbN/FFmpeg-Builds  linux64-gpl / linuxarm64-gpl
            （该构建是静态链接，不挑发行版；仍会回退到系统 ffmpeg）
- macOS   : 依次尝试 zgrep、evermeet.cx、osxexperts.net 的静态/通用构建

用法：
    python packaging/fetch_ffmpeg.py              # 下载到 tools/ffmpeg
    python packaging/fetch_ffmpeg.py --force      # 覆盖已存在文件
    python packaging/fetch_ffmpeg.py --check      # 只检查现有文件是否可用
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "tools" / "ffmpeg"
IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
USER_AGENT = "nnkBiliDown-packaging/1.0"


def force_utf8_output() -> None:
    """避免 Windows cp1252 控制台下打印中文时抛 UnicodeEncodeError。

    该异常会让脚本以退出码 1 结束，且日志几乎为空（CI 上表现为
    「Process completed with exit code 1」）。
    """
    os.environ.setdefault("PYTHONUTF8", "1")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


force_utf8_output()

BTBN_API = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"

LICENSE_NOTE = """本目录下的 ffmpeg / ffprobe 为第三方预编译二进制，随 nnkBiliDown 客户端一同分发。

- 来源：BtbN/FFmpeg-Builds（Windows / Linux）、zgrep 或 evermeet.cx（macOS）
- 许可证：GPL v3（这些构建启用了 --enable-gpl）
- 项目主页：https://ffmpeg.org/
- 源代码：https://github.com/FFmpeg/FFmpeg

ffmpeg 是独立程序，通过命令行被 nnkBiliDown 调用，不与其链接。
GPL 要求分发时保留版权声明与许可证文本，故在此说明。
"""

README_NOTE = """此目录由 packaging/fetch_ffmpeg.py 自动生成，请勿手工提交二进制到版本库。
客户端从 tools/ffmpeg 读取 ffmpeg 与 ffprobe（见 backend/runtime.py）。
如果删除本目录，客户端仍可运行，但会回退到系统 PATH 中的 ffmpeg。
"""


def log(msg: str) -> None:
    print(msg, flush=True)


def target_binary_names() -> tuple[str, str]:
    if IS_WINDOWS:
        return "ffmpeg.exe", "ffprobe.exe"
    return "ffmpeg", "ffprobe"


def _request(url: str) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/vnd.github+json"
    return urllib.request.Request(url, headers=headers)


def http_json(url: str) -> dict:
    with urllib.request.urlopen(_request(url), timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download(url: str, dest: Path) -> Path:
    """流式下载到 dest，返回本地路径。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"  ↓ {url}")
    with urllib.request.urlopen(_request(url), timeout=180) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out, length=1024 * 512)
    size_mb = dest.stat().st_size / 1024 / 1024
    log(f"    已下载 {dest.name}（{size_mb:.1f} MB）")
    return dest


def extract_members(archive: Path, wanted: tuple[str, str], out_dir: Path) -> list[Path]:
    """从 zip / tar.gz 中抽取指定 basename 的文件（只取真实文件，忽略符号链接）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    wanted_set = set(wanted)

    def handle(name: str, reader) -> None:
        base = Path(name).name
        if base not in wanted_set:
            return
        target = out_dir / base
        with open(target, "wb") as fh:
            shutil.copyfileobj(reader, fh)
        extracted.append(target)

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                with zf.open(info) as reader:
                    handle(info.filename, reader)
    else:
        with tarfile.open(archive, "r:*") as tf:
            for member in tf.getmembers():
                # 符号链接会导致打包后指向不存在的目标，直接跳过（只收真实文件）
                if not member.isfile():
                    continue
                reader = tf.extractfile(member)
                if reader is None:
                    continue
                with reader:
                    handle(member.name, reader)

    return extracted


def make_executable(path: Path) -> None:
    if IS_WINDOWS:
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def verify(binary: Path) -> str | None:
    """运行 -version 校验二进制可执行，返回版本首行；失败返回 None。

    ffmpeg 的版本横幅输出到 stderr，必须合并两个流才能拿到。
    """
    try:
        proc = subprocess.run(
            [str(binary), "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    for line in (proc.stdout or "").splitlines():
        if line.strip():
            return line.strip()
    return None


# ---------------------------------------------------------------------------
# 各平台来源
# ---------------------------------------------------------------------------
def btbn_asset_pattern() -> str:
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if IS_WINDOWS:
        return "winarm64-gpl" if arm else "win64-gpl"
    return "linuxarm64-gpl" if arm else "linux64-gpl"


def fetch_from_btbn(tmp: Path) -> dict[str, Path]:
    """BtbN/FFmpeg-Builds：Windows 与 Linux 都提供静态 GPL 构建。"""
    log("[来源] BtbN/FFmpeg-Builds (GitHub)")
    release = http_json(BTBN_API)
    pattern = btbn_asset_pattern()
    asset = None
    for item in release.get("assets", []):
        name = item.get("name", "")
        # 只要完整包（含 ffprobe），不要 -shared 变体
        if pattern in name and name.endswith(".zip") and "shared" not in name:
            asset = item
            break
    if asset is None:
        raise RuntimeError(f"未在最新 release 中找到匹配 {pattern} 的 zip 资源")

    archive = download(asset["browser_download_url"], tmp / asset["name"])
    files = extract_members(archive, target_binary_names(), tmp / "out")
    return {path.name: path for path in files}


def fetch_macos_zgrep(tmp: Path) -> dict[str, Path]:
    """zgrep 的 macOS 通用（arm64 + x86_64）静态构建。"""
    log("[来源] zgrep static builds (macOS universal)")
    base = "https://zgrep.com/ffmpeg/ffmpeg-latest-macos-universal"
    result: dict[str, Path] = {}
    for name in ("ffmpeg", "ffprobe"):
        try:
            result[name] = download(f"{base}/{name}.zip", tmp / f"{name}.zip")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"zgrep 下载失败 ({exc.code})") from exc
    out: dict[str, Path] = {}
    for name, archive in result.items():
        files = extract_members(archive, (name,), tmp / "out")
        if not files:
            raise RuntimeError(f"{archive.name} 中未找到 {name}")
        out[name] = files[0]
    return out


def fetch_macos_evermeet(tmp: Path) -> dict[str, Path]:
    """evermeet.cx：分别提供 ffmpeg / ffprobe 的 7z 包，需要 7z 解压。"""
    log("[来源] evermeet.cx (macOS)")
    seven_zip = shutil.which("7z") or shutil.which("7za") or shutil.which("7zz")
    if not seven_zip:
        raise RuntimeError("evermeet.cx 提供 7z 包，但系统未安装 7z（brew install sevenzip）")
    out: dict[str, Path] = {}
    for name in ("ffmpeg", "ffprobe"):
        archive = download(f"https://evermeet.cx/ffmpeg/getrelease/{name}/7z", tmp / f"{name}.7z")
        subprocess.run([seven_zip, "x", "-y", f"-o{tmp / 'out'}", str(archive)], check=True,
                       capture_output=True)
        produced = tmp / "out" / name
        if not produced.is_file():
            raise RuntimeError(f"7z 解压后未找到 {name}")
        out[name] = produced
    return out


def sources_for_platform():
    if IS_WINDOWS or sys.platform.startswith("linux"):
        return [fetch_from_btbn]
    if IS_MACOS:
        return [fetch_macos_zgrep, fetch_macos_evermeet]
    raise RuntimeError(f"暂不支持的平台：{sys.platform}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def check_existing(verbose: bool = True) -> bool:
    ffmpeg_name, ffprobe_name = target_binary_names()
    ffmpeg_path = DEST / ffmpeg_name
    ffprobe_path = DEST / ffprobe_name
    ok = True
    for path in (ffmpeg_path, ffprobe_path):
        if not path.is_file():
            if verbose:
                log(f"[缺失] {path}")
            ok = False
            continue
        if verbose:
            version = verify(path)
            log(f"[就绪] {path.name}: {version or '无法执行'}")
        if verify(path) is None:
            ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="下载本平台 ffmpeg 供打包内置")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的文件")
    parser.add_argument("--check", action="store_true", help="只校验现有文件")
    args = parser.parse_args()

    if args.check:
        return 0 if check_existing() else 1

    DEST.mkdir(parents=True, exist_ok=True)
    ffmpeg_name, ffprobe_name = target_binary_names()
    if not args.force and (DEST / ffmpeg_name).is_file() and (DEST / ffprobe_name).is_file():
        if check_existing(verbose=False):
            log(f"[跳过] tools/ffmpeg 已存在可用二进制：{DEST}")
            log("       需要重新下载请加 --force")
            return 0

    log(f"[信息] 平台={sys.platform} 架构={platform.machine()} 目标目录={DEST}")
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="nnkffmpeg-") as tmp_name:
        tmp = Path(tmp_name)
        for source in sources_for_platform():
            try:
                found = source(tmp)
            except Exception as exc:
                log(f"[失败] {source.__name__}: {exc}")
                errors.append(f"{source.__name__}: {exc}")
                continue
            missing = [n for n in (ffmpeg_name, ffprobe_name) if n not in found]
            if missing:
                log(f"[失败] {source.__name__} 未提供：{', '.join(missing)}")
                errors.append(f"{source.__name__}: 缺少 {missing}")
                continue
            for name, path in found.items():
                target = DEST / name
                shutil.copy2(path, target)
                make_executable(target)
            if check_existing():
                (DEST / "LICENSE.txt").write_text(LICENSE_NOTE, encoding="utf-8")
                (DEST / "README.txt").write_text(README_NOTE, encoding="utf-8")
                log(f"[完成] ffmpeg 已就绪：{DEST}")
                return 0
            errors.append(f"{source.__name__}: 下载后校验失败")

    log("[错误] 所有来源都失败了：")
    for line in errors:
        log(f"       - {line}")
    log("       客户端仍可打包，但运行时需要系统 PATH 中存在 ffmpeg。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
