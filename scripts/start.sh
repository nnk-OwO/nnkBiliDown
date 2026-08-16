#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

echo "============================================"
echo "  nnkBiliDown - Bilibili 视频下载器"
echo "============================================"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[错误] 未找到 python3，请先安装 Python 3.10+"
  exit 1
fi

python3 -c "import sys; print('[信息] Python ' + sys.version.split()[0] + ' -> ' + sys.executable)"
exec python3 start.py "$@"
