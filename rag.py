"""향수 DB 검색(RAG).

- data/perfumes.json: build_catalog.py가 실제 페이지에서 확인한 노트만 담은 향수 목록
- 사용자가 고른 노트(우리 노트 id)와 향수의 실제 노트를 사전(LEXICON)으로 맞춰 겹침을 계산한다.
- 임베딩(text-embedding-3-small, 제공된 키 사용)으로 분위기 유사도를 더한다.
- 겹치는 노트는 코드가 계산하므로 LLM이 지어낼 수 없다. LLM은 이 후보 안에서 고르고 이유만 쓴다.
"""
import json
import math
import os
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
DATA = ROOT / "data"
EMB_PATH = DATA / "perfume-embeddings.json"

# 우리 노트 id → 향수 노트에 쓰이는 영어 표기
LEXICON = {
    "lime": ["lime"], "salt": ["sea salt", "salt", "sea notes", "marine notes", "seaweed", "sea water"],
    "fig-leaf": ["fig leaf", "fig leaves", "fig tree leaves", "fig tree"], "pear": ["pear"], "bergamot": ["bergamot"],
    "grapefruit": ["grapefruit"], "pink-pepper": ["pink pepper", "pink peppercorn", "pinkberries", "pink pepper berries"],
    "green-tea": ["green tea"], "freesia": ["freesia"], "sage": ["sage", "clary sage"],
    "cypress": ["cypress"], "iris": ["iris", "orris"], "rose": ["rose", "roses"], "jasmine": ["jasmine"],
    "lavender": ["lavender", "lavandin"], "neroli": ["neroli", "orange blossom", "orange flower"],
    "sandalwood": ["sandalwood"], "musk": ["musk", "musks"], "vanilla": ["vanilla"],
    "patchouli": ["patchouli"], "vetiver": ["vetiver"],
    "amber": ["amber", "labdanum", "benzoin"],
    "cedarwood": ["cedar", "cedarwood"], "tonka": ["tonka"],
    "mandarin": ["mandarin", "tangerine"], "cardamom": ["cardamom"], "violet": ["violet"],
    "tuberose": ["tuberose"], "incense": ["incense", "olibanum", "frankincense"], "coconut": ["coconut"],
    "lemon": ["lemon", "italian lemon"], "ginger": ["ginger"], "peony": ["peony", "peonies"],
    "blackcurrant": ["blackcurrant", "black currant", "cassis", "blackcurrant bud", "blackcurrant leaves"],
    "tobacco": ["tobacco", "tobacco leaf", "tobacco leaves"],
}

# 우리 노트에 똑같은 게 없는 향수 노트 → 향이 가장 가까운 우리 노트(조향에서 흔히 같은 갈래로 묶는 것).
# '같은 노트'가 아니라 '비슷한 노트'로만 쓰고, 화면과 답변에서 그렇게 밝힌다.
NEAR = [
    # 시트러스
    ("yuzu", "grapefruit"), ("citron", "lemon"), ("verbena", "lemon"), ("bitter orange", "mandarin"),
    ("sweet orange", "mandarin"), ("orange water", "neroli"), ("petitgrain", "neroli"),
    # 과일
    ("green mango", "pear"), ("mango", "pear"), ("apple", "pear"), ("peach", "pear"), ("pineapple", "pear"),
    ("quince", "pear"), ("litchi", "pear"), ("lychee", "pear"), ("naseberry", "pear"), ("fruit accord", "pear"),
    ("blackberry", "blackcurrant"), ("raspberry", "blackcurrant"), ("buchu", "blackcurrant"),
    ("fig", "fig-leaf"), ("galbanum", "fig-leaf"), ("artichoke", "fig-leaf"), ("african marigold", "fig-leaf"),
    # 꽃
    ("lotus", "freesia"), ("cyclamen", "freesia"), ("lily of the valley", "freesia"),
    ("magnolia", "jasmine"), ("honeysuckle", "jasmine"), ("white flowers", "jasmine"),
    ("ylang", "tuberose"), ("geranium", "rose"), ("mimosa", "violet"),
    # 허브·향신료
    ("basil", "sage"), ("bay lea", "sage"), ("rosemary", "sage"), ("thyme", "sage"), ("angelica", "sage"),
    ("shiso", "sage"), ("chamomile", "lavender"), ("aspic", "lavender"), ("mint", "green-tea"),
    ("clove", "cardamom"), ("coriander", "cardamom"), ("nutmeg", "cardamom"), ("cumin", "cardamom"),
    ("fennel", "cardamom"), ("pepper", "pink-pepper"), ("spice", "pink-pepper"),
    # 나무·초록 숲
    ("juniper", "cypress"), ("hinoki", "cypress"), ("pine", "cypress"), ("fir", "cypress"),
    ("sycamore", "cedarwood"), ("guaiac", "cedarwood"), ("gaïac", "cedarwood"), ("rosewood", "sandalwood"),
    ("papyrus", "vetiver"), ("oakmoss", "patchouli"), ("moss", "patchouli"), ("wood", "cedarwood"),
    # 수지·스모키
    ("myrrh", "incense"), ("elemi", "incense"), ("birch", "incense"), ("oud", "incense"), ("leather", "incense"),
    ("ambergris", "amber"), ("amberwood", "amber"), ("ambery", "amber"), ("cistus", "amber"),
    ("styrax", "amber"), ("peru balsam", "amber"),
    # 머스크·파우더
    ("ambroxan", "musk"), ("ambroxyde", "musk"), ("cashmeran", "musk"), ("ambrette", "musk"),
    ("aldehyde", "musk"), ("suede", "musk"), ("aquatic", "salt"),
    # 달콤함
    ("honey", "tonka"), ("bitter almond", "tonka"), ("chestnut", "tonka"), ("rum", "tonka"), ("coffee", "tonka"),
    ("cocoa", "vanilla"), ("caramel", "vanilla"),
]


def near_id(note):
    """같은 노트가 없을 때 가장 가까운 우리 노트 id(없으면 None)."""
    n = note.lower()
    for word, nid in NEAR:
        if re.search(rf"\b{re.escape(word)}", n):
            return nid
    return None

# 화면에 보여 줄 한국어 이름(자주 나오는 노트)
KO = {
    "lemon": "레몬", "mandarin": "만다린", "orange": "오렌지", "yuzu": "유자", "basil": "바질", "mint": "민트",
    "juniper": "주니퍼", "juniper berries": "주니퍼 베리", "cardamom": "카다멈", "violet": "바이올렛", "pine": "소나무",
    "pine needle": "솔잎", "incense": "인센스", "leather": "레더", "oud": "우드(침향)", "myrrh": "몰약", "tobacco": "담배잎",
    "cherry": "체리", "honey": "꿀", "peony": "작약", "blackberry": "블랙베리", "bay": "월계수", "suede": "스웨이드",
    "tuberose": "튜베로즈", "magnolia": "목련", "lily of the valley": "은방울꽃", "cotton": "코튼", "almond": "아몬드",
    "coffee": "커피", "cinnamon": "시나몬", "clove": "정향", "ginger": "생강", "pink pepper": "핑크 페퍼", "pepper": "후추",
    "black pepper": "흑후추", "sea salt": "바다 소금", "salt": "소금", "fig": "무화과", "fig leaf": "무화과 잎",
    "pear": "서양 배", "bergamot": "베르가못", "grapefruit": "자몽", "green tea": "녹차", "tea": "차", "freesia": "프리지아",
    "sage": "세이지", "clary sage": "클라리 세이지", "cypress": "사이프러스", "iris": "아이리스", "orris": "오리스",
    "rose": "장미", "jasmine": "재스민", "lavender": "라벤더", "neroli": "네롤리", "orange blossom": "오렌지 블로섬",
    "sandalwood": "샌달우드", "musk": "머스크", "white musk": "화이트 머스크", "ambrette": "암브레트", "vanilla": "바닐라",
    "patchouli": "파촐리", "vetiver": "베티버", "amber": "앰버", "ambroxan": "앰브록산", "ambergris": "앰버그리스",
    "labdanum": "랍다넘", "benzoin": "벤조인", "cedar": "시더", "cedarwood": "시더우드", "tonka": "통카", "tonka bean": "통카 빈",
    "lime": "라임", "coriander": "고수 씨", "litchi": "리치", "chamomile": "캐모마일", "artichoke": "아티초크",
    "petitgrain": "페티그레인", "aldehydes": "알데하이드", "aldehyde": "알데하이드", "ylang-ylang": "일랑일랑", "lotus": "연꽃",
    "mango": "망고", "sycamore": "시카모어", "hinoki": "히노키", "shiso": "차조기", "rum": "럼", "olibanum": "유향",
    "cumin": "커민", "cistus": "시스투스", "gaiac": "과이악 우드", "gaïac": "과이악 우드", "papyrus": "파피루스",
    "honeysuckle": "인동꽃", "birch": "자작나무", "pineapple": "파인애플", "fir": "전나무", "bitter orange": "비터 오렌지",
    "tangerine": "탠저린", "ambroxyde": "앰브록사이드", "angelica": "안젤리카", "aspic": "스파이크 라벤더",
    "marigold": "메리골드", "cyclamen": "시클라멘", "wood": "우드", "coconut milk": "코코넛 밀크", "naseberry": "사포딜라",
    "buchu": "부쿠", "citron": "시트론", "timut": "티무트 후추", "sichuan pepper": "쓰촨 후추", "ambrette seeds": "암브레트 씨",
    "lemon": "레몬", "black tea": "홍차", "musks": "머스크", "roses": "장미", "white cedar": "화이트 시더",
    "fig tree leaves": "무화과 잎", "fig leaves": "무화과 잎",
    "moss": "모스", "oakmoss": "오크모스", "seaweed": "해초", "driftwood": "유목", "apple": "사과", "blackcurrant": "블랙커런트",
    "raspberry": "라즈베리", "peach": "복숭아", "plum": "자두", "coconut": "코코넛", "caramel": "캐러멜", "praline": "프랄린",
    "geranium": "제라늄", "rosemary": "로즈마리", "thyme": "타임", "elemi": "엘레미", "frankincense": "유향", "nutmeg": "육두구",
}
NOTE_FAMILY = {"citrus": {"citrus"}, "marine": {"aquatic"}, "forest": {"woody", "green"},
               "floral": {"floral", "fruity"}, "linen": {"musk"}, "amber": {"amber", "gourmand", "spicy"}}
# 단맛이 두드러지는 노트(이 중 하나라도 있거나 gourmand 계열이면 '달콤한 향수'로 본다)
SWEET_WORDS = ["vanilla", "tonka", "caramel", "praline", "honey", "coconut", "cherry", "sugar", "chocolate",
               "cocoa", "almond", "benzoin", "marshmallow", "candy", "liquorice", "licorice", "cotton candy"]


def is_sweet(p):
    text = " ".join(n.lower() for st in ("top", "heart", "base") for n in p["notes"][st])
    return "gourmand" in p["family"] or any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in SWEET_WORDS)


def note_ids(note):
    n = note.lower()
    return {nid for nid, words in LEXICON.items() if any(re.search(rf"\b{re.escape(w)}\b", n) for w in words)}


def ko_name(note):
    n = re.sub(r"\s+", " ", note.lower()).strip()
    if n in KO:
        return KO[n]
    for word, ko in sorted(KO.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(word)}\b", n):
            return ko
    return note


def load_perfumes():
    path = DATA / "perfumes.json"
    perfumes = json.loads(path.read_text("utf-8")) if path.exists() else []
    for p in perfumes:
        p["ids_by_stage"] = {st: set().union(*(note_ids(n) for n in p["notes"][st])) if p["notes"][st] else set()
                             for st in ("top", "heart", "base")}
        p["ids"] = set().union(*p["ids_by_stage"].values())
        # 비슷한 노트: (우리 노트 id, 원래 노트) — 같은 노트로 이미 잡힌 원래 노트는 제외
        p["near"] = [(near_id(n), n) for st in ("top", "heart", "base") for n in p["notes"][st]
                     if not note_ids(n) and near_id(n)]
        p["near_ids"] = {nid for nid, _ in p["near"]} - p["ids"]
        p["sweet"] = is_sweet(p)
    return perfumes


def doc_text(p):
    notes = ", ".join(n for st in ("top", "heart", "base") for n in p["notes"][st])
    return f"{p['brand']} {p['name']}. Notes: {notes}. Family: {', '.join(p['family'])}. {p['description_ko']}"


def embeddings_url():
    url = os.getenv("LLM_CHAT_URL") or "https://api.openai.com/v1/responses"
    return re.sub(r"/(responses|chat/completions)/?$", "/embeddings", url)


def embed(texts):
    key = os.getenv("LLM_API_KEY")
    r = httpx.post(embeddings_url(), headers={"Authorization": f"Bearer {key}"},
                   json={"model": "text-embedding-3-small", "input": texts}, timeout=40)
    r.raise_for_status()
    return [d["embedding"] for d in r.json()["data"]]


async def aembed(text, key=None):
    key = key or os.getenv("LLM_API_KEY")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(embeddings_url(), headers={"Authorization": f"Bearer {key}"},
                              json={"model": "text-embedding-3-small", "input": [text]})
        r.raise_for_status()
        return r.json()["data"][0]["embedding"]


def ensure_embeddings(perfumes):
    """향수 문서 임베딩을 파일에 저장해 두고 재사용한다. 키가 없으면 임베딩 없이 동작한다."""
    cache = json.loads(EMB_PATH.read_text("utf-8")) if EMB_PATH.exists() else {}
    missing = [p for p in perfumes if cache.get(p["id"], {}).get("text") != doc_text(p)]
    if missing and os.getenv("LLM_API_KEY"):
        try:
            vectors = embed([doc_text(p) for p in missing])
            for p, v in zip(missing, vectors):
                cache[p["id"]] = {"text": doc_text(p), "vector": v}
            EMB_PATH.write_text(json.dumps(cache), "utf-8")
        except httpx.HTTPError:
            pass
    for p in perfumes:
        p["vector"] = cache.get(p["id"], {}).get("vector")


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) + 1e-9)


def score(p, selected, qvec=None, family=None):
    """selected: {stage: [노트 dict]}  →  (점수, 겹친 우리 노트 id 목록)
    family: 대화에서 읽은 전체 분위기(forest, marine ...). 맞는 향수에 가산점을 준다."""
    total, matched, near = 0.0, [], []
    if family and NOTE_FAMILY.get(family, set()) & set(p["family"]):
        total += 1.5
    for stage, notes in selected.items():
        for n in notes:
            if n["id"] in p["ids_by_stage"].get(stage, ()):
                total += 3.0
                matched.append(n["id"])
            elif n["id"] in p["ids"]:
                total += 2.0
                matched.append(n["id"])
            elif n["id"] in p["near_ids"]:
                total += 1.0  # 비슷한 노트는 같은 노트보다 낮게
                near.extend(raw for nid, raw in p["near"] if nid == n["id"])
            if NOTE_FAMILY.get(n["family"], set()) & set(p["family"]):
                total += .5
    if qvec is not None and p.get("vector"):
        total += 4.0 * max(0.0, cosine(qvec, p["vector"]) - .2)
    return total, matched, near


def retrieve(perfumes, selected, qvec=None, k=8, avoid_sweet=False, family=None):
    """avoid_sweet=True면 달콤한 향수(바닐라, 통카, 꿀, 체리 등)는 후보에서 뺀다."""
    ranked = []
    for p in perfumes:
        if avoid_sweet and p["sweet"]:
            continue
        s, matched, near = score(p, selected, qvec, family)
        if s > 0:
            ranked.append((s, matched, {**p, "near_matched": near}))
    ranked.sort(key=lambda r: -r[0])
    return ranked[:k]


def card(p, matched_ids, names, why=""):
    """화면용 카드. 노트는 한국어로 바꾸고, 겹친 노트는 사용자가 고른 이름 그대로 보여 준다."""
    notes = [ko_name(n) for st in ("top", "heart", "base") for n in p["notes"][st]]
    seen, display = set(), []
    for n in notes:
        if n not in seen:
            seen.add(n)
            display.append(n)
    return {
        "id": p["id"], "brand": p["brand"].upper(), "name": p["name"], "concentration": p.get("concentration", ""),
        "description": p["description_ko"], "notes": display[:8], "url": p["source"],
        "matching_notes": [names[i] for i in dict.fromkeys(matched_ids) if i in names], "why": why,
        # 비슷한 노트: 향수의 원래 노트 ≈ 사용자가 고른 우리 노트 (예: 유자 ≈ 자몽)
        "near_notes": [f"{ko_name(raw)} ≈ {names.get(near_id(raw), '')}" for raw in dict.fromkeys(p.get("near_matched", []))][:3],
        "pyramid": {st: [ko_name(n) for n in p["notes"][st]] for st in ("top", "heart", "base")},
    }
