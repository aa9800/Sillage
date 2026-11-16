#!/bin/sh
# Sillage 실행 (macOS / Linux). Python 3.10+ 필요.
cd "$(dirname "$0")"
if [ ! -f dist/index.html ]; then echo "dist 폴더가 없어요. npm ci && npm run build 를 먼저 실행하세요."; exit 1; fi
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv || exit 1; fi
# 패키지가 하나라도 없으면 설치(첫 설치가 중간에 끊겼을 때도 다시 설치)
if ! .venv/bin/python -c "import fastapi, uvicorn, httpx, dotenv, pydantic, mcp" 2>/dev/null; then
  .venv/bin/python -m pip install -q -r requirements.txt || { echo "패키지 설치에 실패했어요. 인터넷 연결을 확인하고 다시 실행하세요."; exit 1; }
fi
echo "http://127.0.0.1:8765 를 브라우저에서 여세요 (Ctrl+C로 종료)"
.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8765
