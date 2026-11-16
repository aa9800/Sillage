import os
import re
import json
from pathlib import Path
from typing import Literal

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
app = FastAPI(title="Sillage")
catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
blend_notes = {item["id"]: item for item in json.loads((ROOT / "blend-notes.json").read_text(encoding="utf-8"))}

PALETTES = {
    "forest": ("숲의 잔향", "#286d57", "#85ecc1", "#17464d"),
    "marine": ("물결의 잔향", "#145d99", "#81edf7", "#203a9b"),
    "amber": ("호박빛 잔향", "#9b4227", "#ffd08b", "#783b26"),
    "floral": ("꽃잎의 잔향", "#973b77", "#ffadd8", "#713b93"),
    "linen": ("린넨의 잔향", "#575a99", "#d8dcff", "#576b91"),
    "citrus": ("햇살의 잔향", "#7a7b29", "#ffe77e", "#32674e"),
    "violet": ("향을 기다리는 중", "#8c806c", "#f4e8d0", "#5b6360"),
}
Stage = Literal["top", "heart", "base"]
KEYWORDS = {
    "forest": r"숲|이끼|풀잎|나무|우디|그린|흙|사이프러스|삼나무|샌달우드",
    "marine": r"바다|바닷|소금|물결|아쿠아|마린|파도",
    "amber": r"달콤|달달|바닐라|앰버|장작|난로|스모키",
    "floral": r"꽃|장미|플로럴|프리지아|자스민|재스민|작약",
    "linen": r"린넨|셔츠|비누|코튼|머스크|깨끗|빨래|파우더",
    "citrus": r"시트러스|레몬|라임|상큼|귤|베르가못|오렌지",
}
NOTES = {
    "forest": ["우디", "그린", "흙내음"], "marine": ["미네랄", "아쿠아틱", "바다 소금"],
    "amber": ["앰버", "스모키", "바닐라"], "floral": ["플로럴", "꽃잎", "프리지아"],
    "linen": ["머스크", "린넨", "파우더"], "citrus": ["시트러스", "라임", "허브"],
}
STAGE_WORDS = {"top": r"탑|톱|top", "heart": r"미들|하트|middle|heart", "base": r"베이스|base"}

class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)

MAX_PER_STAGE = 3

class Blend(BaseModel):
    # 단계마다 여러 노트를 섞을 수 있다. 예전 형식(문자열 하나)도 받는다.
    blend: dict[Stage, list[str] | str] = Field(default_factory=dict, max_length=3)

def normalized(blend):
    result = {}
    for stage in ("top", "heart", "base"):
        ids = blend.get(stage)
        ids = [ids] if isinstance(ids, str) else list(ids or [])
        ids = list(dict.fromkeys(ids))[-MAX_PER_STAGE:]
        if ids:
            result[stage] = ids
    return result

IMAGE_DATA_URL = r"^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$"

class Chat(Blend):
    messages: list[Turn] = Field(min_length=1, max_length=15)
    # 마지막 사용자 메시지와 함께 보낸 사진(브라우저에서 1024px 이하로 줄인 data URL). 서버에 저장하지 않는다.
    image: str | None = Field(default=None, max_length=3_000_000, pattern=IMAGE_DATA_URL)

class Direction(BaseModel):
    family: Literal["forest", "marine", "amber", "floral", "linen", "citrus", "violet"]
    temperature: Literal["cool", "warm", "neutral"]
    airy: bool
    avoid_sweet: bool
    notes: list[str] = Field(max_length=5)
    ready: bool
    reply: str = Field(min_length=1, max_length=500)
    changes: list[dict] = Field(default_factory=list)

STAGE_KO = {"top": "탑", "heart": "미들", "base": "베이스"}

def chat_schema():
    """대화 응답 스키마. changes로 화면의 노트 선택을 직접 바꾼다(우리 24개 노트 id만 허용)."""
    return {
        "type": "object", "additionalProperties": False,
        "required": ["family", "temperature", "airy", "avoid_sweet", "notes", "ready", "reply", "changes"],
        "properties": {
            "family": {"type": "string", "enum": ["forest", "marine", "amber", "floral", "linen", "citrus", "violet"]},
            "temperature": {"type": "string", "enum": ["cool", "warm", "neutral"]},
            "airy": {"type": "boolean"}, "avoid_sweet": {"type": "boolean"},
            "notes": {"type": "array", "items": {"type": "string"}},
            "ready": {"type": "boolean"}, "reply": {"type": "string"},
            "changes": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["stage", "action", "notes"],
                "properties": {
                    "stage": {"type": "string", "enum": ["top", "heart", "base"]},
                    "action": {"type": "string", "enum": ["add", "remove", "replace"]},
                    "notes": {"type": "array", "items": {"type": "string", "enum": list(blend_notes)}},
                }}},
        },
    }

def note_menu():
    lines = []
    for stage in ("top", "heart", "base"):
        items = [f"{n['id']}({n['name']}: {n['feel']})" for n in blend_notes.values() if n["stage"] == stage]
        lines.append(f"{STAGE_KO[stage]}[{stage}]: " + ", ".join(items))
    return "\n".join(lines)

def diff_blend(before, after):
    """바뀐 내용을 화면에 보여 줄 형태로 계산한다(LLM 말이 아니라 실제 적용 결과)."""
    out = []
    for stage in ("top", "heart", "base"):
        b, a = before.get(stage, []), after.get(stage, [])
        added = [blend_notes[i]["name"] for i in a if i not in b]
        removed = [blend_notes[i]["name"] for i in b if i not in a]
        if added or removed:
            out.append({"stage": stage, "label": STAGE_KO[stage], "added": added, "removed": removed})
    return out

def demo_direction(user_texts):
    family = "violet"
    temperature = "neutral"
    airy = False
    avoid_sweet = False
    for message in user_texts:
        for clause in re.split(r"(?<=말고)|(?<=빼고)|[,.!?，]|하지만|인데|지만", message):
            negative = re.search(r"싫|제외|없이|말아|부담|빼|말고|않[게은아]|향은 없", clause)
            if negative and re.search(r"단 향|단맛|달콤|달달|달지|바닐라", clause):
                avoid_sweet = True
            elif re.search(r"(달콤|달달|단맛|단 향).{0,12}(괜찮|좋아|원해)", clause):
                avoid_sweet = False
            if negative:
                continue
            # A temperature adjective can change the lighting without replacing the scent family.
            matches = [name for name, pattern in KEYWORDS.items() if re.search(pattern, clause)]
            if matches:
                family = max(matches, key=lambda name: len(re.findall(KEYWORDS[name], clause)))
            if re.search(r"차갑|서늘|차가운|비 온|차가워|푸른|시원", clause):
                temperature = "cool"
            elif re.search(r"따뜻|온기|포근", clause):
                temperature = "warm"
            if re.search(r"묵직|진한|깊은|강렬", clause):
                airy = False
            elif re.search(r"맑|가벼|은은|출근|매일|깔끔|투명", clause):
                airy = True
    ready = family != "violet" and (len(user_texts) >= 3 or (
        len(user_texts) >= 2 and bool(re.search(r"출근|매일|저녁|데이트|외출|추천", user_texts[-1]))
    ))
    label = PALETTES[family][0].split()[0]
    if family == "violet":
        reply = "어떤 향의 장면이 떠오르세요? 비 온 숲이나 햇볕에 마른 셔츠처럼 말해도 좋아요."
    elif ready:
        reply = f"{label}의 분위기를 중심으로 시향해 볼 향수를 골랐어요."
    elif len(user_texts) == 1:
        reply = f"{label}의 분위기가 느껴져요. 차갑고 맑은 쪽과 따뜻하고 포근한 쪽 중 어디가 더 좋아요?"
    else:
        reply = f"{label}의 향이 조금 더 선명해졌어요. 매일 가볍게 쓸 향인가요, 특별한 날의 잔향을 찾고 있나요?"
    return Direction(family=family, temperature=temperature, airy=airy,
                     avoid_sweet=avoid_sweet, notes=NOTES.get(family, []), ready=ready, reply=reply)

USER_KEY = re.compile(r"^sk-[A-Za-z0-9_\-]{20,200}$")
DEFAULT_URL, DEFAULT_MODEL = "https://api.openai.com/v1/responses", "gpt-4o-mini"

def user_key(request):
    """화면에서 사용자가 넣은 OpenAI 키(요청 헤더). 서버에 저장하거나 기록하지 않고 OpenAI 호출에만 쓴다."""
    key = (request.headers.get("x-openai-key") or "").strip() if request is not None else ""
    return key if USER_KEY.match(key) else None

def llm_config(request=None):
    """사용자 키가 있으면 그 키로, 없으면 .env 설정으로, 둘 다 없으면 데모 모드."""
    key = user_key(request)
    if key:
        return [os.getenv("LLM_CHAT_URL") or DEFAULT_URL, os.getenv("LLM_MODEL") or DEFAULT_MODEL, key]
    return [os.getenv(name) for name in ("LLM_CHAT_URL", "LLM_MODEL", "LLM_API_KEY")]

@app.get("/api/status")
def status(request: Request):
    config = llm_config(request)
    source = "user" if user_key(request) else "server" if all(config) else None
    return {"mode": "llm" if all(config) else "incomplete" if any(config) else "demo", "key": source}

def selected_notes(body: Blend):
    """단계별로 고른 노트 목록 {stage: [note, ...]}"""
    selected = {}
    for stage, ids in normalized(body.blend).items():
        notes = []
        for note_id in ids:
            note = blend_notes.get(note_id)
            if not note or note["stage"] != stage:
                raise HTTPException(422, "이 단계에서 고를 수 있는 노트를 선택해 주세요.")
            notes.append(note)
        selected[stage] = notes
    return selected

def flat(selected):
    return [note for stage in ("top", "heart", "base") for note in selected.get(stage, [])]

def explicit_note_updates(message):
    stage_pattern = "|".join(STAGE_WORDS.values())
    updates = {}
    for stage, words in STAGE_WORDS.items():
        section = re.search(rf"(?:{words})\s*(?:노트)?((?:(?!(?:{stage_pattern})\s*(?:노트)?).)*)",
                            message, re.IGNORECASE)
        if not section:
            continue
        detail = section.group(1)
        if re.search(r"빼|지워|제거|취소", detail):
            removed = [note["id"] for note in blend_notes.values() if note["stage"] == stage and note["name"] in detail]
            updates[stage] = ("remove", removed) if removed else None
        elif re.search(r"바꿔|넣어|골라|선택|추가|정해|해\s*줘|해\s*주세요|로[.!\s]*$", detail):
            desired = re.split(r"말고|대신", detail)[-1]
            if not re.search(r"싫|제외|않", desired):
                alternatives = [note for note in blend_notes.values()
                                if note["stage"] == stage and note["name"] in desired]
                if alternatives:
                    ids = [note["id"] for note in sorted(alternatives, key=lambda note: desired.find(note["name"]))]
                    updates[stage] = ("add" if re.search(r"추가|더|같이|섞", detail) else "set", ids)
    return updates

def apply_updates(blend, updates):
    result = normalized(blend)
    for stage, update in updates.items():
        if update is None:
            result.pop(stage, None)
            continue
        action, ids = update
        ids = [i for i in ids if i in blend_notes and blend_notes[i]["stage"] == stage]
        current = result.get(stage, [])
        if action == "remove":
            current = [i for i in current if i not in ids]
        elif action == "add":
            current = list(dict.fromkeys(current + ids))[-MAX_PER_STAGE:]
        else:
            current = ids[-MAX_PER_STAGE:]
        if current:
            result[stage] = current
        else:
            result.pop(stage, None)
    return result

def blend_family(selected):
    """고른 노트에서 가장 많이 나온 계열. 동률이면 미들 → 베이스 → 탑 순서로 앞선 노트의 계열."""
    ordered = [note["family"] for stage in ("heart", "base", "top") for note in selected.get(stage, [])]
    if not ordered:
        return "violet"
    return max(dict.fromkeys(ordered), key=ordered.count)

@app.post("/api/blend")
def blend(body: Blend):
    selected = selected_notes(body)
    notes = [note["name"] for note in flat(selected)][:5]
    family = blend_family(selected)
    direction = Direction(
        family=family, temperature="neutral", airy=family in {"marine", "citrus", "linen"},
        avoid_sweet=False, notes=notes, ready=len(selected) == 3,
        reply="선택한 노트와 가까운 향을 골랐어요.",
    )
    return present(direction, 0, selected)

@app.post("/api/chat")
async def chat(body: Chat, request: Request):
    selected_notes(body)
    user_texts = [turn.content for turn in body.messages if turn.role == "user"]
    if not user_texts or body.messages[-1].role != "user":
        raise HTTPException(422, "마지막 메시지는 사용자의 입력이어야 해요.")
    explicit = explicit_note_updates(user_texts[-1])
    updated = apply_updates(body.blend, explicit)
    selected = selected_notes(Blend(blend=updated))
    config = llm_config(request)
    before = normalized(body.blend)
    if all(config):
        url, model, key = config
        current = ", ".join(f"{STAGE_KO[st]}={'+'.join(n['name'] for n in notes)}" for st, notes in selected.items()) or "아직 없음"
        prompt = (
            "너는 한국어로 상담하는 조향사이고, 사용자 화면의 노트 선택을 직접 바꿀 수 있다.\n"
            f"지금 화면에서 선택된 노트: {current}\n"
            f"고를 수 있는 노트(단계[stage]: id(이름: 느낌)):\n{note_menu()}\n"
            "규칙:\n"
            "1) 사용자의 최신 메시지(분위기, 장면, 계절, 싫은 향, 원하는 강도)를 지금 선택과 비교해라. 어울리지 않는 노트는 remove하거나 "
            "replace하고, 어울리는 노트는 add해라. 단계마다 최대 3개, 위 목록의 id만, 그 단계의 노트만 쓴다. 바꿀 이유가 없으면 changes=[]. 특정 노트만 바꿀 때는 remove와 add를 쓰고, replace는 그 단계 전체를 새로 정할 때만 써라.\n"
            "2) 선택이 비어 있으면 요청에 맞게 단계마다 1~2개씩 골라 add해서 채워라.\n"
            "3) reply는 2~3문장. 바꿀 때는 먼저 지금 선택을 짧게 짚고, changes에 넣은 모든 변경(빼는 노트와 더하는 노트)을 빠짐없이 말하고 이유를 붙여라. "
            "예: '지금 베이스가 바닐라라 꽤 달콤한 편이에요. 달지 않은 숲 느낌을 원하시니 베티버로 바꿔 볼게요.' "
            "향수 상품명은 쓰지 말고, 질문은 많아야 하나만 해라.\n"
            "4) notes에는 대화에서 드러난 향의 인상을 짧은 한국어 단어로 넣어라. 차갑거나 따뜻함은 temperature, 단맛 회피는 avoid_sweet에 반영해라. "
            "방향이 충분하거나 추천을 원하면 ready=true. 아직 방향이 없으면 family=violet."
        )
        if body.image:
            prompt += (
                "\n5) 사용자가 사진을 보냈다. 사진 속 장면의 색, 빛, 계절, 온도, 습도, 사물과 재질, 분위기를 읽어 향으로 번역해라. "
                "reply 첫 문장에서 사진에서 읽은 것을 구체적으로 짧게 말하고(예: '해 질 녘 젖은 돌길과 따뜻한 가로등 빛이 보여요'), "
                "그 인상에 맞는 노트를 단계별로 changes에 넣어라. 사진 속 사람의 신원이나 외모는 평가하지 마라."
            )
        try:
            turns = [turn.model_dump() for turn in body.messages]
            responses_api = httpx.URL(url).path.rstrip("/").endswith("/responses")
            if body.image:
                # 마지막 사용자 메시지에 사진을 붙인다(Responses API와 Chat Completions의 형식이 다르다)
                last = turns[-1]["content"]
                turns[-1] = {"role": "user", "content": (
                    [{"type": "input_text", "text": last}, {"type": "input_image", "image_url": body.image, "detail": "low"}]
                    if responses_api else
                    [{"type": "text", "text": last}, {"type": "image_url", "image_url": {"url": body.image, "detail": "low"}}]
                )}
            payload = (
                {"model": model, "input": [{"role": "developer", "content": prompt}, *turns], "store": False,
                 "max_output_tokens": 800, "text": {"format": {"type": "json_schema", "name": "consult", "schema": chat_schema(), "strict": True}}}
                if responses_api else
                {"model": model, "messages": [{"role": "system", "content": prompt + "\nJSON만 출력: " + json.dumps(chat_schema(), ensure_ascii=False)}, *turns],
                 "response_format": {"type": "json_object"}}
            )
            async with httpx.AsyncClient(timeout=25) as client:
                result = await client.post(url, headers={"Authorization": f"Bearer {key}"}, json=payload)
                result.raise_for_status()
                data = result.json()
                content = (
                    "".join(part["text"] for item in data["output"] if item.get("type") == "message"
                            for part in item["content"] if part.get("type") == "output_text")
                    if responses_api else data["choices"][0]["message"]["content"]
                ).strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0]
                direction = Direction.model_validate_json(content)
        except httpx.HTTPStatusError as error:
            detail = {
                401: "LLM API 키가 인증되지 않았어요. 서버 설정의 키를 확인해 주세요.",
                403: "이 키에 모델을 사용할 권한이 없어요.",
                429: "LLM 요청 한도나 잔액을 확인해 주세요.",
            }.get(error.response.status_code, "LLM 서버가 요청을 처리하지 못했어요.")
            raise HTTPException(502, detail) from error
        except (httpx.HTTPError, ValueError, KeyError, IndexError, AttributeError, TypeError):
            raise HTTPException(502, "향을 해석하는 중 연결이 끊겼어요. 잠시 뒤 다시 시도해 주세요.")
        # LLM이 정한 노트 변경을 적용한다. 단계를 잘못 지정한 노트는 버리지 않고 그 노트의 원래 단계로 옮긴다.
        for change in direction.changes:
            stage, action = change.get("stage"), change.get("action")
            ids = [i for i in change.get("notes", []) if i in blend_notes]
            right = [i for i in ids if blend_notes[i]["stage"] == stage]
            if stage in STAGE_KO and right:
                updated = apply_updates(updated, {stage: ({"replace": "set"}.get(action, action), right)})
            for i in ids:
                if blend_notes[i]["stage"] != stage:
                    own = blend_notes[i]["stage"]
                    updated = apply_updates(updated, {own: ("remove" if action == "remove" else "add", [i])})
        selected = selected_notes(Blend(blend=updated))
    elif any(config):
        raise HTTPException(503, "LLM 연결 설정을 확인해 주세요.")
    else:
        direction = demo_direction(user_texts)

    after = normalized(updated)
    return {**present(direction, len(user_texts), selected), "blend": after, "changes": diff_blend(before, after),
            "demo": not all(config)}


def present_products(direction, selected):
    """검증된 향수 DB가 있으면 거기서 고른다. 대화에서 나온 노트도 단계 없이 함께 반영한다."""
    if not PERFUMES:
        return []
    chosen = {n["id"] for notes in selected.values() for n in notes}
    extra = [n for n in notes_from_words(direction.notes) if n["id"] not in chosen]
    query = {**selected, **({"any": extra} if extra else {})}
    if not query:
        return []
    return db_cards(query)

def present(direction, turns, selected):
    family = blend_family(selected) if direction.family == "violet" else direction.family
    ready = direction.ready or len(selected) == 3
    label, base, highlight, shadow = PALETTES[family]
    if family == "forest" and direction.temperature == "cool":
        base, highlight, shadow = "#126362", "#8affdf", "#163b69"
    elif family == "forest" and direction.temperature == "warm":
        base, highlight, shadow = "#64612c", "#f2d295", "#68402e"
    elif direction.temperature == "cool" and family not in {"violet", "marine"}:
        shadow = "#233b72"
    elif direction.temperature == "warm" and family not in {"violet", "amber"}:
        highlight = "#ffcd99"
    products = []
    for item in catalog:
        if direction.avoid_sweet and item["sweet"]:
            continue
        chosen = flat(selected)
        matching_notes = [note["name"] for note in chosen if set(note["matches"]) & set(item["notes"])]
        related = sum(bool(set(note["matches"]) & set(item["notes"])) for note in chosen)
        related += sum(note["family"] in item["families"] for note in chosen)
        text_matches = sum(any(note in actual or actual in note for actual in item["notes"])
                           for note in direction.notes if len(note) > 1)
        score = 5 * len(matching_notes) + related + 3 * text_matches + 3 * (family in item["families"])
        if score:
            products.append((score, item["airy"] == direction.airy, {**item, "matching_notes": matching_notes}))
    products.sort(key=lambda ranked: ranked[:2], reverse=True)
    level = max(min(68, 33 * turns) if family != "violet" else 0,
                min(84, 24 * len(selected) + 4 * len(flat(selected))) if selected else 0)
    return {
        "reply": direction.reply, "notes": direction.notes, "ready": ready,
        "level": 88 if ready else level,
        "palette": {"label": label, "base": base, "highlight": highlight, "shadow": shadow,
                    "family": family, "temperature": direction.temperature, "airy": direction.airy},
        "products": present_products(direction, selected) or [item for _, _, item in products[:3]],
    }

# ───────── RAG 큐레이션: 검증된 향수 DB에서 후보를 찾고, LLM은 그 안에서 고르고 이유만 쓴다 ─────────
import rag

PERFUMES = rag.load_perfumes()
rag.ensure_embeddings(PERFUMES)
recommend_cache = {}
NOTE_NAMES = {nid: note["name"] for nid, note in blend_notes.items()}

def db_cards(selected, qvec=None, k=3):
    ranked = rag.retrieve(PERFUMES, selected, qvec, k=k)
    return [rag.card(p, matched, NOTE_NAMES) for _, matched, p in ranked]

def notes_from_words(words):
    """LLM이 뽑은 한국어 노트 단어를 우리 노트 id로 맞춘다(이름이나 동의어가 들어 있으면)."""
    found = []
    for word in words:
        for note in blend_notes.values():
            if note["name"] in word or word in note["name"] or any(m in word for m in note["matches"]):
                found.append(note)
    return list({n["id"]: n for n in found}.values())

class Recommend(BaseModel):
    blend: dict[Stage, list[str] | str] = Field(default_factory=dict, max_length=3)

@app.post("/api/recommend")
async def recommend(body: Recommend, request: Request):
    selected = selected_notes(Blend(blend=body.blend))
    if not selected:
        raise HTTPException(422, "노트를 하나 이상 골라 주세요.")
    key_id = json.dumps(normalized(body.blend), sort_keys=True)
    if key_id in recommend_cache:
        return recommend_cache[key_id]
    url, model, key = llm_config(request)
    labels = {"top": "탑", "heart": "미들", "base": "베이스"}
    blend_text = " / ".join(f"{labels[st]}: {', '.join(n['name'] + '(' + n['english'] + ')' for n in notes)}"
                            for st, notes in selected.items())
    try:
        qvec = await rag.aembed(blend_text, key) if key else None
    except httpx.HTTPError:
        qvec = None
    ranked = rag.retrieve(PERFUMES, selected, qvec, k=8)
    if not ranked:
        return {"summary": "", "picks": [], "ai": False, "ready": len(selected) == 3}
    if not all((url, model, key)) or not httpx.URL(url).path.rstrip("/").endswith("/responses"):
        picks = [rag.card(p, m, NOTE_NAMES) for _, m, p in ranked[:3]]
        return {"summary": "", "picks": picks, "ai": False, "ready": len(selected) == 3}
    candidates = [{
        "id": p["id"], "perfume": f"{p['brand']} {p['name']}",
        "top": p["notes"]["top"], "heart": p["notes"]["heart"], "base": p["notes"]["base"],
        "shared_with_user": [NOTE_NAMES[i] for i in dict.fromkeys(m)],
    } for _, m, p in ranked]
    schema = {
        "type": "object", "additionalProperties": False, "required": ["summary", "picks"],
        "properties": {
            "summary": {"type": "string"},
            "picks": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["id", "why"],
                "properties": {"id": {"type": "string", "enum": [c["id"] for c in candidates]}, "why": {"type": "string"}}}},
        },
    }
    prompt = (
        "너는 한국어로 답하는 향수 큐레이터다. 사용자가 고른 노트 조합과, 실제 상품 페이지에서 확인한 노트만 담긴 후보 향수 목록을 받는다. "
        "후보 중에서 이 조합과 가장 잘 어울리는 향수 3개를 골라라(후보가 3개보다 적으면 있는 만큼). "
        "후보 목록 밖의 향수나 노트를 말하지 마라. 각 이유(why)는 후보에 적힌 실제 노트만 근거로 한국어 한두 문장(70자 내외)으로 쓰고, "
        "사용자가 고른 노트와 어떻게 이어지는지 말해라. summary는 사용자의 조합이 어떤 인상인지 한국어 한 문장(40자 내외)."
        f"\n사용자 조합: {blend_text}\n후보: {json.dumps(candidates, ensure_ascii=False)}"
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            result = await client.post(url, headers={"Authorization": f"Bearer {key}"}, json={
                "model": model, "store": False, "input": prompt, "max_output_tokens": 700,
                "text": {"format": {"type": "json_schema", "name": "curation", "schema": schema, "strict": True}},
            })
            result.raise_for_status()
            data = result.json()
        text = "".join(part["text"] for item in data["output"] if item.get("type") == "message"
                       for part in item["content"] if part.get("type") == "output_text")
        curation = json.loads(text)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        picks = [rag.card(p, m, NOTE_NAMES) for _, m, p in ranked[:3]]
        return {"summary": "", "picks": picks, "ai": False, "ready": len(selected) == 3}
    by_id = {p["id"]: (m, p) for _, m, p in ranked}
    picks, used = [], set()
    for pick in curation["picks"]:
        if pick["id"] in by_id and pick["id"] not in used:
            used.add(pick["id"])
            m, p = by_id[pick["id"]]
            picks.append(rag.card(p, m, NOTE_NAMES, why=pick["why"]))
    for _, m, p in ranked:  # LLM이 3개를 못 채우면 점수 순으로 채운다
        if len(picks) >= 3:
            break
        if p["id"] not in used:
            used.add(p["id"])
            picks.append(rag.card(p, m, NOTE_NAMES))
    response = {"summary": curation.get("summary", ""), "picks": picks[:3], "ai": True, "ready": len(selected) == 3}
    if len(recommend_cache) > 300:
        recommend_cache.clear()
    recommend_cache[key_id] = response
    return response

@app.middleware("http")
async def fresh_pages(request, call_next):
    # 빌드 파일 이름이 바뀌어도 브라우저가 옛 index.html을 붙잡지 않게 한다
    response = await call_next(request)
    if not request.url.path.startswith(("/api", "/assets")):
        response.headers["Cache-Control"] = "no-cache"
    return response

if (ROOT / "dist").is_dir():
    app.mount("/", StaticFiles(directory=ROOT / "dist", html=True), name="frontend")
