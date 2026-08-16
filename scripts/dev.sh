#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
python3 -m pip install -r requirements.txt -q
npm --prefix frontend install
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 7860 --reload &
BACK_PID=$!
npm --prefix frontend run dev
trap 'kill $BACK_PID' EXIT
