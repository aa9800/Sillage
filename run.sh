#!/bin/sh
# Sillage 실행 (macOS / Linux). Python 3.10+ 필요.
cd "$(dirname "$0")"
if [ ! -f dist/index.html ]; then echo "dist 폴더가 없어요. npm ci && npm run build 를 먼저 실행하세요."; exit 1; fi
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && .venv/bin/python -m pip install -q -r requirements.txt
fi
echo "http://127.0.0.1:8765 를 브라우저에서 여세요 (Ctrl+C로 종료)"
.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8765
