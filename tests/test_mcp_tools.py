"""MCP 서버 도구 테스트: MCP 클라이언트로 실제 프로토콜을 거쳐 호출한다."""
import asyncio
import json

from mcp import Client

import mcp_server
import rag


def call(name, args):
    async def run():
        async with Client(mcp_server.mcp) as client:
            result = await client.call_tool(name, args)
            return json.loads("".join(getattr(part, "text", "") for part in result.content))
    return asyncio.run(run())


def test_four_tools_are_listed():
    async def run():
        async with Client(mcp_server.mcp) as client:
            return sorted(t.name for t in (await client.list_tools()).tools)
    assert asyncio.run(run()) == ["describe_note", "find_perfume", "get_weather", "search_perfumes"]


def test_find_perfume_by_korean_nickname():
    data = call("find_perfume", {"name": "탐다오"})
    assert data["found"] and data["perfume"] == "Diptyque Tam Dao"
    assert "lime" in data["our_notes"]["top"]
    assert "sandalwood" in data["our_notes"]["base"]  # 향수의 미들에 있어도 우리 노트의 원래 단계(베이스)로 옮긴다
    assert all(len(ids) <= 3 for ids in data["our_notes"].values())


def test_find_perfume_unknown_lists_available():
    data = call("find_perfume", {"name": "없는 향수 이름"})
    assert data["found"] is False and len(data["available"]) == len(mcp_server.PERFUMES)


def test_our_notes_really_exist_in_the_perfume():
    """우리 노트로 옮긴 결과는 그 향수의 실제(검증된) 노트에서만 나온다 = 지어낸 노트가 없다."""
    for p in mcp_server.PERFUMES:
        data = call("find_perfume", {"name": f"{p['brand']} {p['name']}"})
        assert data["id"] == p["id"]
        for ids in data["our_notes"].values():
            assert set(ids) <= p["ids"], p["name"]


def test_search_avoid_sweet_excludes_sweet_perfumes():
    data = call("search_perfumes", {"notes": ["vanilla", "tonka", "sandalwood"], "avoid_sweet": True, "limit": 8})
    ids = {r["id"] for r in data["results"]}
    sweet = {p["id"] for p in mcp_server.PERFUMES if p["sweet"]}
    assert ids and not ids & sweet


def test_search_shared_notes_are_from_query():
    data = call("search_perfumes", {"notes": ["베티버", "cypress"], "limit": 5})
    assert data["results"]
    for r in data["results"]:
        assert set(r["shared_notes"]) <= {"베티버", "사이프러스"}


def test_describe_note():
    data = call("describe_note", {"note": "베티버"})
    assert data["id"] == "vetiver" and data["stage"] == "베이스" and data["count"] >= 1


def test_weather_offline_falls_back_to_season(offline):
    data = call("get_weather", {"city": "서울"})
    assert data["fallback"] is True and "평년" in data["note"]
    assert any(data["suggested_notes"].values())


def test_season_fallback_every_month_gives_notes():
    for month in range(1, 13):
        data = mcp_server.season_fallback("Seoul", month)
        for stage, ids in data["suggested_notes"].items():
            assert all(mcp_server.NOTES[i]["stage"] == stage for i in ids)


def test_sweet_detection():
    by_name = {p["name"]: p for p in rag.load_perfumes()}
    assert by_name["Tobacco Vanille"]["sweet"] is True
    assert by_name["Wood Sage & Sea Salt"]["sweet"] is False
