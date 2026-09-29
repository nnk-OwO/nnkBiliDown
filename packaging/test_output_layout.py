"""产物布局定位逻辑的自测（任何平台都能跑）。

为什么需要它：
包在三个平台上的资源落点并不一样，而校验代码一旦写死路径，就会
出现「打包成功、却报产物缺少文件」的假失败——macOS 就踩过这个坑：

    [失败] 产物缺少 前端 index.html：
      …/dist/nnkBiliDown.app/Contents/Resources/nnkBiliDown/frontend/dist/index.html

真实布局是 PyInstaller 把 COLLECT 目录挪到了 Contents/Frameworks/<NAME>/，
并从 Contents/Resources、Contents/MacOS 互相做符号链接。

本脚本用合成目录树覆盖四种布局，验证 build.py 的定位函数都能命中：
1. Windows onedir  : dist/<NAME>/<NAME>.exe + _internal/
2. macOS .app      : Contents/{MacOS,Frameworks,Resources} + 交叉符号链接
3. Linux onedir    : dist/<NAME>/<NAME> + _internal/
4. 老版 PyInstaller: 资源直接散在应用目录（无 _internal）
并额外验证：缺少文件时**必须**报失败（防止校验形同虚设）。

用法： python packaging/test_macos_layout.py
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build  # noqa: E402

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"    {'[OK]  ' if ok else '[FAIL]'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def _symlink_or_copy(src: Path, dst: Path) -> str:
    """优先建符号链接；Windows 无权限时退化为复制（仍能验证查找逻辑）。"""
    try:
        os.symlink(src, dst, target_is_directory=True)
        return "symlink"
    except (OSError, NotImplementedError):
        shutil.copytree(src, dst)
        return "copy"


def _populate(internal: Path) -> None:
    """造出前端 / 后端 / 内置 ffmpeg 三项关键产物。

    两种 ffmpeg 文件名都建出来：真实构建只会有一个，
    但测试要在同一台机器上模拟多平台，避免文件名干扰判断。
    """
    (internal / "frontend" / "dist" / "assets").mkdir(parents=True, exist_ok=True)
    (internal / "frontend" / "dist" / "index.html").write_text(
        '<!doctype html><script src="assets/index-abc.js"></script>', encoding="utf-8"
    )
    (internal / "frontend" / "dist" / "assets" / "index-abc.js").write_text("//js", encoding="utf-8")
    (internal / "backend").mkdir(parents=True, exist_ok=True)
    (internal / "backend" / "main.py").write_text("# backend", encoding="utf-8")
    ffdir = internal / "tools" / "ffmpeg"
    ffdir.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffmpeg.exe"):
        (ffdir / name).write_bytes(b"x" * 1024)
    for name in ("ffprobe", "ffprobe.exe"):
        (ffdir / name).write_bytes(b"y" * 1024)


def _locate(files: list[Path], rel: Path) -> Path | None:
    for candidate in files:
        if candidate.parts[-len(rel.parts):] == rel.parts:
            return candidate
    return None


def _assert_layout(
    name: str,
    dist_dir: Path,
    is_macos: bool,
    is_windows: bool | None = None,
    expect_ok: bool = True,
) -> None:
    """用 build.py 的真实函数跑一遍定位，检查三样产物 + 资源引用完整性。

    is_windows 默认沿用宿主平台；模拟其它平台时必须显式传入，
    否则 build.IS_WINDOWS 会残留成宿主值（这正是本测试曾经踩到的坑）。
    """
    print(f"  [{name}]")
    build.IS_MACOS = is_macos
    if is_windows is not None:
        build.IS_WINDOWS = is_windows
    build.DIST = dist_dir
    ffmpeg_rel = Path("tools/ffmpeg") / ("ffmpeg.exe" if build.IS_WINDOWS else "ffmpeg")

    exe, search_root = build._app_layout()
    check("可执行文件路径解析", exe.exists(), str(exe))

    files = list(build._walk_files(search_root, max_depth=14))
    check("遍历产物树（不跟随符号链接）", len(files) > 0, f"{len(files)} 个文件")

    idx = _locate(files, Path("frontend/dist/index.html"))
    backend = _locate(files, Path("backend/main.py"))
    ffmpeg = _locate(files, ffmpeg_rel)

    if expect_ok:
        check("找到 frontend/dist/index.html", idx is not None,
              str(idx.relative_to(search_root)) if idx else "未找到")
        check("找到 backend/main.py", backend is not None,
              str(backend.relative_to(search_root)) if backend else "未找到")
        check(f"找到 {ffmpeg_rel}", ffmpeg is not None,
              str(ffmpeg.relative_to(search_root)) if ffmpeg else "未找到")
        if idx:
            html = idx.read_text(encoding="utf-8")
            missing = [
                a for a in re.findall(r'(?:src|href)="([^"]+)"', html)
                if not a.startswith(("http://", "https://", "data:", "#", "/"))
                and not (idx.parent / a.lstrip("./")).exists()
            ]
            check("前端资源引用完整", not missing, str(missing))
    else:
        check("缺少 index.html 时能被检出", idx is None)
        check("缺少 ffmpeg 时能被检出", ffmpeg is None)

    dump = build._tree_dump(search_root, limit=10)
    check("失败诊断能列出产物内容", len(dump) > 0 and "frontend" in dump)


def main() -> int:
    root = Path(__file__).resolve().parent.parent / "build" / "applayout-test"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    original_macos = build.IS_MACOS
    original_windows = build.IS_WINDOWS
    original_dist = build.DIST
    try:
        # --- 1. Windows onedir -------------------------------------------------
        win = root / "win"
        win_internal = win / "nnkBiliDown" / "_internal"
        _populate(win_internal)
        (win / "nnkBiliDown" / "nnkBiliDown.exe").write_bytes(b"stub")
        _assert_layout("Windows onedir", win, is_macos=False, is_windows=True)

        # --- 2. macOS .app（含交叉符号链接，可能形成环路）---------------------
        app = root / "mac" / "nnkBiliDown.app"
        contents = app / "Contents"
        macos, resources, frameworks = contents / "MacOS", contents / "Resources", contents / "Frameworks"
        macos.mkdir(parents=True)
        resources.mkdir(parents=True)
        collect_internal = frameworks / "nnkBiliDown" / "_internal"
        _populate(collect_internal)
        (macos / "nnkBiliDown").write_bytes(b"stub")
        inner = frameworks / "nnkBiliDown" / "_internal"
        for part in ("frontend", "backend", "tools"):
            _symlink_or_copy(inner / part, resources / part)
        _symlink_or_copy(resources / "frontend", macos / "frontend")
        _assert_layout("macOS .app", root / "mac", is_macos=True, is_windows=False)

        # --- 3. Linux onedir ---------------------------------------------------
        lin = root / "linux"
        _populate(lin / "nnkBiliDown" / "_internal")
        (lin / "nnkBiliDown" / "nnkBiliDown").write_bytes(b"stub")
        _assert_layout("Linux onedir", lin, is_macos=False, is_windows=False)

        # --- 4. 老版 PyInstaller（资源散在应用目录，无 _internal）------------
        legacy = root / "legacy"
        _populate(legacy / "nnkBiliDown")
        (legacy / "nnkBiliDown" / "nnkBiliDown.exe").write_bytes(b"stub")
        _assert_layout("旧版布局（无 _internal）", legacy, is_macos=False, is_windows=True)

        # --- 5. 负面用例：少了文件必须报失败 ---------------------------------
        broken = root / "broken"
        _populate(broken / "nnkBiliDown" / "_internal")
        (broken / "nnkBiliDown" / "_internal" / "frontend" / "dist" / "index.html").unlink()
        (broken / "nnkBiliDown" / "_internal" / "tools" / "ffmpeg" / "ffmpeg.exe").unlink()
        (broken / "nnkBiliDown" / "nnkBiliDown.exe").write_bytes(b"stub")
        _assert_layout("负面用例（缺文件）", broken, is_macos=False, is_windows=True, expect_ok=False)

        # --- 6. 复现 macOS 原故障：旧代码写死的路径必然找不到 -----------------
        print("  [回归] macOS 旧路径假设")
        old_guess = app / "Contents" / "Resources" / "nnkBiliDown" / "_internal" / "frontend" / "dist" / "index.html"
        check("旧代码硬编码路径确实不存在（复现原故障）", not old_guess.exists(), str(old_guess))
    finally:
        build.IS_MACOS = original_macos
        build.IS_WINDOWS = original_windows
        build.DIST = original_dist
        shutil.rmtree(root, ignore_errors=True)

    print()
    if FAILURES:
        print(f"[结果] 失败 {len(FAILURES)} 项：")
        for item in FAILURES:
            print(f"       - {item}")
        return 1
    print("[结果] 全部通过：四种产物布局的定位逻辑均正确")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
