#!/usr/bin/env bash
# 用真实的 dist 目录结构验证 workflow 中「列出产物」与「失败诊断」两步的
# 精确 shell 代码：必须 (a) 跑完返回 0，(b) 两种平台都能用（不用 GNU 专有选项）。
#
# 用法： bash packaging/test_workflow_ls.sh
set -uo pipefail

fail=0
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

step_list() { # 与 workflow「列出产物」步骤一致
  echo "--- dist 顶层 ---"
  ls -lh dist/ 2>/dev/null || echo "(dist 不存在)"
  echo "--- 归档文件大小 ---"
  found=0
  for f in dist/*.zip dist/*.tar.gz; do
    [ -f "$f" ] || continue
    found=1
    printf '  %10s 字节  %s\n' "$(wc -c < "$f" | tr -d ' ')" "$f"
  done
  [ "$found" -eq 1 ] || echo "(未找到归档文件)"
}

step_diag() { # 与 workflow「失败诊断」步骤一致
  echo "===== python / pip ====="
  python -V || true
  python -m pip -V || true
  echo "===== 内置 ffmpeg ====="
  ls -lh tools/ffmpeg 2>/dev/null || echo "(无 tools/ffmpeg)"
  echo "===== 前端产物 ====="
  ls -lh frontend/dist 2>/dev/null || echo "(无 frontend/dist)"
  echo "===== dist 结构（二层）====="
  find dist -maxdepth 2 > /tmp/nnk_tree.txt 2>/dev/null || true
  head -40 /tmp/nnk_tree.txt 2>/dev/null || echo "(dist 不存在)"
  echo "===== PyInstaller warn 文件 ====="
  find build -name 'warn-*.txt' -exec sh -c 'echo "--- {}"; tail -40 "{}"' \; 2>/dev/null || true
}

check() {
  local desc="$1" code="$2"
  if [ "$code" -eq 0 ]; then printf '  [OK]   %s (exit=0)\n' "$desc"
  else printf '  [FAIL] %s (exit=%s)\n' "$desc" "$code"; fail=$((fail + 1)); fi
}

run_in() { # run_in <目录> <函数名>
  ( cd "$1" || exit 1; set -o pipefail; "$2" >/dev/null 2>&1 )
}

# ---- 场景 A：像 runner 一样，dist 里有归档（含很长的深层 _internal 树）------
mkdir -p "$work/A/dist/nnkBiliDown/_internal/frontend/dist/assets" \
         "$work/A/dist/nnkBiliDown/_internal/tools/ffmpeg" \
         "$work/A/dist/nnkBiliDown/_internal/backend" \
         "$work/A/tools/ffmpeg" "$work/A/frontend/dist" "$work/A/build/work/nnkBiliDown"
for i in $(seq 1 2000); do : > "$work/A/dist/nnkBiliDown/_internal/deep_file_$i.bin"; done
head -c 2048 /dev/zero > "$work/A/dist/nnkBiliDown-Windows-x64.zip"
head -c 4096 /dev/zero > "$work/A/dist/nnkBiliDown-Linux-x64.tar.gz"
: > "$work/A/tools/ffmpeg/ffmpeg"
: > "$work/A/frontend/dist/index.html"
echo "missing module named foo - imported by bar" > "$work/A/build/work/nnkBiliDown/warn-nnkBiliDown.txt"

echo "== 场景 A：真实 runner 结构（2000+ 文件）=="
run_in "$work/A" step_list; check "列出产物" "$?"
run_in "$work/A" step_diag; check "失败诊断" "$?"

# ---- 场景 B：dist 不存在（构建早期就失败）----------------------------------
mkdir -p "$work/B"
echo
echo "== 场景 B：dist 不存在 =="
run_in "$work/B" step_list; check "列出产物" "$?"
run_in "$work/B" step_diag; check "失败诊断" "$?"

# ---- 场景 C：dist 存在但为空 -------------------------------------------------
mkdir -p "$work/C/dist"
echo
echo "== 场景 C：dist 为空 =="
run_in "$work/C" step_list; check "列出产物" "$?"
run_in "$work/C" step_diag; check "失败诊断" "$?"

# ---- 对照：确认旧写法在同样场景下会失败 --------------------------------------
echo
echo "== 对照：旧写法（ls -lhR dist/ | head -60）=="
( cd "$work/A" || exit 1; set -o pipefail; ls -lhR dist/ 2>/dev/null | head -60 >/dev/null )
old=$?
if [ "$old" -ne 0 ]; then
  printf '  [复现成功] 旧写法 exit=%s（%s = 128+13 SIGPIPE）\n' "$old" "$old"
else
  printf '  [注意] 旧写法本次 exit=0（SIGPIPE 有时序性，但 GitHub 上已确认会失败）\n'
fi

# ---- 输出样例，确认诊断内容可读 ---------------------------------------------
echo
echo "== 新写法输出样例（场景 A 的「列出产物」）=="
( cd "$work/A" && step_list )
echo
echo "== 新写法输出样例（场景 A 的「失败诊断」前 12 行）=="
( cd "$work/A" && step_diag ) | head -12

echo
if [ "$fail" -eq 0 ]; then
  echo "[结果] 全部通过：两步在 pipefail 下均为 exit 0，且不依赖 GNU 专有选项"
else
  echo "[结果] 有 $fail 项失败"
fi
exit "$fail"
