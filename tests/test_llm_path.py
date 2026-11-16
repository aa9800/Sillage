"""AI 대화 경로 테스트. OpenAI 대신 가짜 응답을 넣어, 서버가 사실을 지키는 코드가 제대로 도는지 본다."""
import json

import pytest
from fastapi.testclient import TestClient

import mcp_server
import server

client = TestClient(server.app)


def direction(**over):
    base = {"family": "forest", "temperature": "cool", "airy": False, "avoid_sweet": False,
            "notes": ["숲"], "ready": True, "reply": "숲 느낌으로 골랐어요.", "changes": []}
    return {**base, **over}


@pytest.fixture
def fake_llm(monkeypatch):
    """llm_config는 '키 있음'으로, consult_with_tools는 정해 둔 응답과 도구 결과를 돌려주게 바꾼다."""
    state = {}
    monkeypatch.setattr(server, "llm_config", lambda request=None: ["https://example.invalid/v1/responses", "gpt-4o-mini", "sk-test"])

    async def consult(url, model, key, prompt, turns, max_rounds=3):
        state["prompt"] = prompt
        return json.dumps(state["reply"], ensure_ascii=False), state.get("used", []), state.get("data", [])
    monkeypatch.setattr(server, "consult_with_tools", consult)
    return state


def chat(text, blend=None):
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": text}], "blend": blend or {}})
    assert r.status_code == 200, r.text
    return r.json()


def test_similar_perfume_without_exact_notes_uses_near_notes(fake_llm):
    """운자르댕처럼 같은 노트가 없어도 가장 가까운 노트로 세 단계를 채우고, 답변은 사실대로 쓴다."""
    data = json.loads(mcp_server.find_perfume("운자르댕"))
    fake_llm["reply"] = direction(reply="프리지아를 유지할게요.")  # LLM이 사실과 다른 말을 해도
    fake_llm["data"] = [("find_perfume", data)]
    out = chat("운자르댕 같은 향으로 만들어 줘")
    assert out["blend"] == {"top": ["pear"], "heart": ["freesia"], "base": ["cedarwood"]}
    assert "망고 ≈ 서양 배" in out["reply"] and "프리지아를 유지" not in out["reply"]
    assert out["anchor"] == "hermes-un-jardin-sur-le-nil"


def test_recommend_pins_anchor_first():
    blend = {"top": ["pear"], "heart": ["freesia"], "base": ["cedarwood"]}
    data = client.post("/api/recommend", json={"blend": blend, "anchor": "hermes-un-jardin-sur-le-nil"}).json()
    assert data["picks"][0]["id"] == "hermes-un-jardin-sur-le-nil" and data["picks"][0]["anchor"] is True
    assert len(data["picks"]) == 3 and len({p["id"] for p in data["picks"]}) == 3


def test_near_notes_cover_almost_everything():
    import rag
    ps = rag.load_perfumes()
    raw = [n for p in ps for st in ("top", "heart", "base") for n in p["notes"][st]]
    left = [n for n in raw if not rag.note_ids(n) and not rag.near_id(n)]
    assert len(left) <= 3  # 체리처럼 가까운 노트가 마땅치 않은 것만 남는다
    assert all(p["ids"] or p["near_ids"] for p in ps)


def test_avoid_sweet_only_when_user_said_it(fake_llm):
    fake_llm["reply"] = direction(avoid_sweet=True)  # LLM이 단맛 회피를 지어내도
    assert chat("비 온 뒤 숲 같은 향")["intent"]["avoid_sweet"] is False
    assert chat("비 온 뒤 숲, 너무 달지 않게")["intent"]["avoid_sweet"] is True


@pytest.mark.parametrize("text", ["이번 달 출근용 향", "취향이 달라서 고민이야", "달리기 끝나고 뿌릴 향"])
def test_sweet_regex_ignores_other_words(text):
    assert not server.SWEET_AVOID.search(text)


def test_empty_stages_filled_for_scene(fake_llm):
    fake_llm["reply"] = direction(changes=[{"stage": "top", "action": "add", "notes": ["fig-leaf"]}])
    out = chat("비 온 뒤 숲")
    assert set(out["blend"]) == {"top", "heart", "base"}
    assert all(server.blend_notes[i]["stage"] == st for st, ids in out["blend"].items() for i in ids)


def test_note_in_wrong_stage_moves_to_its_own_stage(fake_llm):
    fake_llm["reply"] = direction(changes=[{"stage": "top", "action": "add", "notes": ["cypress"]}])
    out = chat("사이프러스 넣어 줘")
    assert "cypress" in out["blend"]["heart"] and "cypress" not in out["blend"].get("top", [])


def test_weird_llm_output_does_not_crash(fake_llm):
    fake_llm["reply"] = direction(reply="가" * 900, notes=["a"] * 9,
                                  changes=[{"stage": ["top"], "action": "add", "notes": [["lime"]]}, "이상한 값"])
    out = chat("아무거나")
    assert len(out["reply"]) <= 500 and len(out["notes"]) <= 5


def test_weather_fills_empty_stages(fake_llm):
    weather = mcp_server.season_fallback("Seoul", 7)
    fake_llm["reply"] = direction(family="marine", changes=[])
    fake_llm["data"] = [("get_weather", weather)]
    out = chat("오늘 서울 날씨에 맞는 향")
    for stage, ids in weather["suggested_notes"].items():
        if ids:
            assert out["blend"][stage] == ids[:3]


def test_saved_perfumes_reach_the_prompt(fake_llm):
    fake_llm["reply"] = direction()
    client.post("/api/chat", json={"messages": [{"role": "user", "content": "추천해 줘"}], "blend": {},
                                   "liked": ["diptyque-tam-dao"]})
    assert "Diptyque Tam Dao" in fake_llm["prompt"]


def test_short_alias_does_not_match_inside_words():
    assert mcp_server.perfumes_in("휠체어 타고 갈 때 뿌릴 향") == []
    assert [p["name"] for p in mcp_server.perfumes_in("휠 같은 향")] == ["Hwyl"]


def test_find_perfume_rejects_empty_name():
    assert json.loads(mcp_server.find_perfume("!!!"))["found"] is False
