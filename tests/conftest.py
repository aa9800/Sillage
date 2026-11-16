"""테스트 공통 설정.

- 실제 OpenAI 키를 쓰지 않도록 LLM 설정을 비운다(.env보다 먼저 정해 두면 load_dotenv가 덮어쓰지 않는다).
- 날씨 테스트는 offline 픽스처로 '연결 실패'를 흉내 내서 인터넷 없이 돈다.
"""
import os
import sys
from pathlib import Path

import httpx
import pytest

for name in ("LLM_CHAT_URL", "LLM_MODEL", "LLM_API_KEY"):
    os.environ[name] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class OfflineClient:
    """httpx.AsyncClient 대신 쓰는 가짜: 모든 요청이 연결 실패한다."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        raise httpx.ConnectError("offline (test)")


@pytest.fixture
def offline(monkeypatch):
    import mcp_server
    monkeypatch.setattr(mcp_server.httpx, "AsyncClient", OfflineClient)
