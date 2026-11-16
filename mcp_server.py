"""Sillage MCP 서버.

향수 상담 LLM이 쓰는 도구를 MCP(Model Context Protocol) 서버로 제공한다.

- 웹 서버(server.py)는 이 서버에 MCP 클라이언트로 연결해 도구 목록을 받고, LLM이 고른 도구를 MCP로 호출한다.
- 같은 서버를 Claude Desktop, Claude Code 같은 다른 MCP 클라이언트에서도 쓸 수 있다.
  예: `python mcp_server.py` (stdio). 설정 방법은 README의 'MCP' 절을 본다.

도구
- search_perfumes : 노트 조합으로 검증된 향수 DB(55종)를 검색한다.
- find_perfume    : 향수 이름으로 DB에서 찾아 실제 노트 피라미드와 그에 해당하는 우리 노트를 돌려준다.
- describe_note   : 노트 하나의 느낌, 계열, 그 노트가 들어간 DB 향수를 알려 준다.
- get_weather     : Open-Meteo(키 필요 없음)로 도시의 현재 날씨를 받아 어울리는 향의 방향을 제안한다.
"""
import json
import re
from pathlib import Path

import httpx
from mcp.server.mcpserver import MCPServer

import rag

ROOT = Path(__file__).parent
NOTES = {n["id"]: n for n in json.loads((ROOT / "blend-notes.json").read_text("utf-8"))}
PERFUMES = rag.load_perfumes()
STAGE_KO = {"top": "탑", "heart": "미들", "base": "베이스"}
FAMILY_KO = {"forest": "숲·우디", "marine": "바다", "amber": "앰버·스파이시", "floral": "꽃",
             "linen": "머스크·파우더", "citrus": "시트러스"}

mcp = MCPServer(
    "sillage",
    instructions="Sillage 향수 아틀리에의 도구. 검증된 향수 DB 검색, 향수 이름 조회, 노트 설명, 날씨 기반 향 제안을 제공한다. "
                 "노트 id는 blend-notes.json의 30개(lime, salt, fig-leaf, ... coconut)다.",
)


def _note(word):
    """노트 id, 한국어 이름, 영어 이름 어느 것으로 불러도 우리 노트를 찾는다."""
    w = word.strip().lower()
    for n in NOTES.values():
        if w in (n["id"], n["name"].lower(), n["english"].lower()) or n["name"] in word:
            return n
    return None


def _summary(p, matched=()):
    return {
        "id": p["id"], "perfume": f"{p['brand']} {p['name']}", "concentration": p.get("concentration", ""),
        "pyramid": {STAGE_KO[st]: [rag.ko_name(n) for n in p["notes"][st]] for st in ("top", "heart", "base")},
        "family": p["family"], "sweet": p["sweet"], "source": p["source"],
        **({"shared_notes": [NOTES[i]["name"] for i in dict.fromkeys(matched) if i in NOTES]} if matched else {}),
    }


def _norm(text):
    return re.sub(r"[^a-z0-9가-힣]", "", text.lower())


@mcp.tool()
def search_perfumes(notes: list[str], avoid_sweet: bool = False, family: str = "", limit: int = 5) -> str:
    """노트 조합과 겹치는 실제 향수를 검증된 DB에서 찾는다.

    notes: 우리 노트 id나 이름 목록(예: ["vetiver", "cypress", "라임"]).
    avoid_sweet: true면 바닐라·통카·꿀 같은 단 향이 든 향수를 뺀다.
    family: 전체 분위기 forest|marine|amber|floral|linen|citrus (선택).
    """
    picked = [n for n in (_note(w) for w in notes) if n]
    selected = {}
    for n in picked:
        selected.setdefault(n["stage"], []).append(n)
    if not selected and not family:
        return json.dumps({"error": "알 수 있는 노트가 없어요. 노트 id나 이름을 넣어 주세요."}, ensure_ascii=False)
    ranked = rag.retrieve(PERFUMES, selected, k=max(1, min(limit, 8)), avoid_sweet=avoid_sweet,
                          family=family or None)
    return json.dumps({"query": [n["name"] for n in picked], "results": [_summary(p, m) for _, m, p in ranked]},
                      ensure_ascii=False)


# 한국에서 흔히 부르는 이름 → DB의 영어 이름 (띄어쓰기 없이 비교)
KO_ALIASES = {
    "탐다오": "Tam Dao", "상탈33": "Santal 33", "상탈": "Santal 33", "어나더13": "Another 13", "어나더": "Another 13",
    "필로시코스": "Philosykos", "도손": "Do Son", "오로즈": "Eau Rose", "오르페옹": "Orphéon", "플레르드뽀": "Fleur de Peau",
    "오데썽": "Eau des Sens", "오예도": "Oyédo", "소바쥬": "Sauvage", "소바주": "Sauvage", "블루드샤넬": "Bleu de Chanel",
    "코코마드모아젤": "Coco Mademoiselle", "샹스오땅드르": "Chance Eau Tendre", "샹스": "Chance Eau Tendre",
    "미스디올": "Miss Dior", "쟈도르": "J'adore", "자도르": "J'adore", "집시워터": "Gypsy Water", "블랑쉬": "Blanche",
    "모하비고스트": "Mojave Ghost", "발다프리크": "Bal d'Afrique", "로즈오브노맨즈랜드": "Rose of No Man's Land",
    "우드세이지": "Wood Sage & Sea Salt", "잉글리쉬페어": "English Pear & Freesia", "잉글리시페어": "English Pear & Freesia",
    "라임바질": "Lime Basil & Mandarin", "피오니": "Peony & Blush Suede", "블랙베리앤베이": "Blackberry & Bay",
    "머르앤통카": "Myrrh & Tonka", "벨벳로즈": "Velvet Rose & Oud", "넥타린": "Nectarine Blossom & Honey",
    "레이지선데이모닝": "Lazy Sunday Morning", "재즈클럽": "Jazz Club", "바이더파이어플레이스": "By the Fireplace",
    "비치워크": "Beach Walk", "웬더레인스탑스": "When the Rain Stops", "테누아": "Thé Noir 29", "떼누아": "Thé Noir 29",
    "베르가못22": "Bergamote 22", "로즈31": "Rose 31", "휠": "Hwyl", "테싯": "Tacit", "마라케시": "Marrakech Intense",
    "에레미아": "Eremia", "운자르댕": "Un Jardin sur le Nil", "떼르데르메스": "Terre d'Hermès", "테르데르메스": "Terre d'Hermès",
    "트윌리": "Twilly d'Hermès", "로스트체리": "Lost Cherry", "네롤리포르토피노": "Neroli Portofino",
    "타바코바닐": "Tobacco Vanille", "콜로니아": "Colonia", "피코디아말피": "Fico di Amalfi", "리브르": "Libre",
    "블랙오피움": "Black Opium", "어벤투스": "Aventus", "실버마운틴워터": "Silver Mountain Water",
    "러브돈비샤이": "Love, Don't Be Shy", "루나": "Luna",
}


def perfumes_in(text):
    """문장에 나온 DB 향수들(한글 통칭, 영어 이름 모두). 나온 순서대로."""
    compact = re.sub(r"\s", "", text).lower()
    hits = []
    for alias in sorted(KO_ALIASES, key=len, reverse=True):
        at = compact.find(alias)
        if at >= 0:
            compact = compact.replace(alias, " " * len(alias))  # 짧은 별칭이 다시 잡히지 않게
            hits.append((at, KO_ALIASES[alias].lower()))
    for p in PERFUMES:
        at = compact.find(re.sub(r"\s", "", p["name"]).lower())
        if at >= 0:
            hits.append((at, p["name"].lower()))
    found = []
    for _, name in sorted(hits):
        p = next((p for p in PERFUMES if p["name"].lower() == name), None) or \
            next((p for p in PERFUMES if name in p["name"].lower()), None)
        if p and p not in found:
            found.append(p)
    return found


def resolve_alias(text):
    """문장 속 한글 향수 이름을 영어 이름으로 바꾼다(가장 긴 별칭부터)."""
    compact = re.sub(r"\s", "", text)
    for alias in sorted(KO_ALIASES, key=len, reverse=True):
        if alias in compact:
            return KO_ALIASES[alias]
    return None


@mcp.tool()
def find_perfume(name: str) -> str:
    """향수 이름(브랜드 포함 가능, 영어 또는 한국어 통칭)으로 DB에서 찾아 실제 노트와, 그에 해당하는 우리 노트 id를 단계별로 돌려준다.
    사용자가 '○○ 같은 향'을 원하면 our_notes로 블렌드를 채울 수 있다."""
    name = resolve_alias(name) or name
    q = _norm(name)
    best, best_score = None, 0
    for p in PERFUMES:
        full, short = _norm(p["brand"] + p["name"]), _norm(p["name"])
        s = 3 if q in (full, short) else 2 if (short and short in q) or q in full else 0
        if not s:
            words = [w for w in re.split(r"\s+", name.lower()) if len(w) > 2]
            s = sum(w in (p["brand"] + " " + p["name"]).lower() for w in words) / max(1, len(words))
        if s > best_score:
            best, best_score = p, s
    if not best or best_score < .5:
        return json.dumps({"found": False, "available": [f"{p['brand']} {p['name']}" for p in PERFUMES]},
                          ensure_ascii=False)
    # 향수에 적힌 순서(탑 → 미들 → 베이스, 앞에 적힌 것 먼저)대로 우리 노트를 모은다.
    # 우리 노트의 단계가 향수와 다르면(예: 향수 미들의 샌달우드) 우리 노트의 원래 단계에 넣는다. 단계마다 최대 3개.
    ours = {"top": [], "heart": [], "base": []}
    for st in ("top", "heart", "base"):
        for note in best["notes"][st]:
            for i in sorted(rag.note_ids(note)):
                stage = NOTES[i]["stage"] if i in NOTES else None
                if stage and i not in ours[stage] and len(ours[stage]) < 3:
                    ours[stage].append(i)
    return json.dumps({"found": True, **_summary(best), "our_notes": ours,
                       "our_notes_ko": {STAGE_KO[st]: [NOTES[i]["name"] for i in ids] for st, ids in ours.items()}},
                      ensure_ascii=False)


@mcp.tool()
def describe_note(note: str) -> str:
    """노트 하나(id나 이름)의 느낌, 단계, 계열과 그 노트가 실제로 들어간 DB 향수를 알려 준다."""
    n = _note(note)
    if not n:
        return json.dumps({"error": "모르는 노트예요.", "notes": [x["name"] for x in NOTES.values()]}, ensure_ascii=False)
    found = [f"{p['brand']} {p['name']}" for p in PERFUMES if n["id"] in p["ids"]]
    return json.dumps({"id": n["id"], "name": n["name"], "english": n["english"], "stage": STAGE_KO[n["stage"]],
                       "feel": n["feel"], "family": FAMILY_KO.get(n["family"], n["family"]),
                       "perfumes_with_it": found[:8], "count": len(found)}, ensure_ascii=False)


WEATHER_CODES = {0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림", 45: "안개", 48: "안개", 51: "이슬비", 53: "이슬비",
                 55: "이슬비", 61: "비", 63: "비", 65: "강한 비", 66: "언 비", 67: "언 비", 71: "눈", 73: "눈", 75: "많은 눈",
                 77: "싸락눈", 80: "소나기", 81: "소나기", 82: "강한 소나기", 85: "눈 소나기", 86: "눈 소나기",
                 95: "뇌우", 96: "뇌우", 99: "뇌우"}


def weather_direction(temp, humidity, code):
    """날씨에서 향의 방향을 고른다(조향에서 흔히 쓰는 기준: 덥고 습하면 가볍게, 추우면 따뜻하고 깊게)."""
    rainy = code in {51, 53, 55, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
    if rainy:
        return "forest", "cool", ["cypress", "vetiver", "green-tea"], "비 오는 날엔 젖은 숲과 흙 같은 그린·우디가 잘 어울려요."
    if code in {71, 73, 75, 77, 85, 86} or temp < 5:
        return "amber", "warm", ["cardamom", "incense", "amber", "sandalwood"], "추운 날엔 따뜻한 수지와 나무 향이 오래 남아요."
    if temp >= 25 and humidity >= 60:
        return "marine", "cool", ["salt", "grapefruit", "sage", "musk"], "덥고 습한 날엔 무거운 향보다 가볍고 시원한 향이 좋아요."
    if temp >= 22:
        return "citrus", "cool", ["lime", "bergamot", "neroli", "cedarwood"], "따뜻한 날엔 상큼한 시트러스가 산뜻해요."
    if temp < 14:
        return "forest", "warm", ["fig-leaf", "iris", "cedarwood", "sandalwood"], "선선한 날엔 부드러운 나무와 파우더리한 향이 어울려요."
    return "floral", "neutral", ["pear", "freesia", "musk"], "온화한 날엔 맑은 꽃과 머스크가 무난해요."


# Open-Meteo 지명 검색은 한글 이름을 잘 못 찾아서 자주 쓰는 도시는 영어로 바꿔 찾는다
CITY_EN = {"서울": "Seoul", "부산": "Busan", "인천": "Incheon", "대구": "Daegu", "대전": "Daejeon", "광주": "Gwangju",
           "울산": "Ulsan", "수원": "Suwon", "세종": "Sejong", "제주": "Jeju", "제주도": "Jeju", "강릉": "Gangneung",
           "춘천": "Chuncheon", "전주": "Jeonju", "포항": "Pohang", "창원": "Changwon", "성남": "Seongnam", "고양": "Goyang",
           "용인": "Yongin", "청주": "Cheongju", "천안": "Cheonan", "여수": "Yeosu", "경주": "Gyeongju", "속초": "Sokcho",
           "도쿄": "Tokyo", "오사카": "Osaka", "파리": "Paris", "런던": "London", "뉴욕": "New York"}


@mcp.tool()
async def get_weather(city: str = "Seoul") -> str:
    """도시의 현재 날씨(기온, 습도, 하늘)를 Open-Meteo에서 받아 오늘 어울리는 향의 방향과 추천 노트 id를 제안한다.
    city는 영어 도시 이름이 가장 정확하다(예: Seoul, Busan). 모르면 Seoul."""
    name = city.strip().removesuffix("시").strip() or "Seoul"
    async with httpx.AsyncClient(timeout=10) as client:
        place = None
        for query in dict.fromkeys([CITY_EN.get(name, name), name]):
            geo = (await client.get("https://geocoding-api.open-meteo.com/v1/search",
                                    params={"name": query, "count": 1, "language": "ko"})).json()
            if geo.get("results"):
                place = geo["results"][0]
                break
        if not place:
            return json.dumps({"error": f"'{city}'를 찾지 못했어요. 영어 도시 이름으로 다시 찾아 주세요."}, ensure_ascii=False)
        now = (await client.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto",
            "current": "temperature_2m,relative_humidity_2m,weather_code,apparent_temperature",
        })).json()["current"]
    family, temperature, notes, why = weather_direction(now["temperature_2m"], now["relative_humidity_2m"], now["weather_code"])
    return json.dumps({
        "city": place.get("name", city), "temperature_c": now["temperature_2m"], "feels_like_c": now["apparent_temperature"],
        "humidity": now["relative_humidity_2m"], "sky": WEATHER_CODES.get(now["weather_code"], "알 수 없음"),
        "suggested_family": family, "suggested_temperature": temperature,
        "suggested_notes": {st: [i for i in notes if NOTES[i]["stage"] == st] for st in ("top", "heart", "base")},
        "why": why, "source": "Open-Meteo",
    }, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()  # stdio
