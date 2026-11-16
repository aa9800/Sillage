"""웹 API 테스트(키 없는 체험 모드). OpenAI는 부르지 않는다."""
from fastapi.testclient import TestClient

import server

client = TestClient(server.app)


def chat(text, blend=None):
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": text}], "blend": blend or {}})
    assert r.status_code == 200, r.text
    return r.json()


def test_status_is_demo_without_key():
    assert client.get("/api/status").json()["mode"] == "demo"


def test_similar_perfume_fills_blend_with_real_notes():
    data = chat("탐다오 같은 향으로 만들어 줘")
    assert data["blend"]["top"] == ["lime"]
    assert "sandalwood" in data["blend"]["base"]
    assert data["tools"][0]["label"] == "향수 조회"


def test_compare_keeps_blend():
    data = chat("상탈 33이랑 어나더 13 비교해 줘", {"top": ["lime"]})
    assert data["blend"] == {"top": ["lime"]}
    assert "Santal 33" in data["reply"] and "Another 13" in data["reply"]


def test_weather_offline_reply_says_fallback(offline):
    data = chat("오늘 서울 날씨에 맞는 향")
    assert "평년" in data["reply"] and data["blend"]
    assert data["tools"][0]["label"] == "날씨(평년값)"


def test_recommend_respects_avoid_sweet():
    blend = {"heart": ["iris"], "base": ["vanilla", "tonka", "sandalwood"]}
    sweet = {p["id"] for p in server.PERFUMES if p["sweet"]}
    plain = client.post("/api/recommend", json={"blend": blend}).json()
    strict = client.post("/api/recommend", json={"blend": blend, "intent": {"avoid_sweet": True}}).json()
    assert {p["id"] for p in plain["picks"]} & sweet  # 바닐라·통카를 고르면 원래는 단 향수가 나오고
    assert strict["picks"] and not {p["id"] for p in strict["picks"]} & sweet  # 단 향을 피하면 빠진다


def test_recommend_matching_notes_are_selected_notes():
    blend = {"top": ["bergamot"], "heart": ["lavender"], "base": ["vetiver"]}
    data = client.post("/api/recommend", json={"blend": blend}).json()
    chosen = {"베르가못", "라벤더", "베티버"}
    for p in data["picks"]:
        assert set(p["matching_notes"]) <= chosen


def test_rejects_note_in_wrong_stage():
    r = client.post("/api/blend", json={"blend": {"top": ["vanilla"]}})
    assert r.status_code == 422


def test_webp_served_as_image():
    r = client.get("/notes/iris.webp")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"


def test_demo_weather_needs_weather_word():
    data = chat("오늘 탐다오 같은 향")
    assert data["tools"][0]["tool"] == "find_perfume"


def test_demo_direct_change_reply_matches(offline):
    data = chat("베이스는 바닐라 말고 샌달우드로", {"base": ["vanilla"]})
    assert data["blend"] == {"base": ["sandalwood"]}
    assert data["reply"] == "베이스에서 바닐라를 빼고 샌달우드를 넣었어요."
