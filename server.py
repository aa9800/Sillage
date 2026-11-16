import os
import re
import json
import mimetypes
from pathlib import Path

# Windows 레지스트리에 webp 형식이 없으면 이미지가 application/octet-stream으로 나가 브라우저가 못 그릴 수 있다
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("text/javascript", ".js")
from typing import Literal

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from mcp import Client as MCPClient

import mcp_server

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
    "amber": r"달콤|달달|바닐라|앰버|장작|난로|스모키|담배|타바코|생강",
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
    # 사용자가 '저장'한 향수 id(브라우저에만 보관). 취향 참고용으로 LLM에 알려 준다.
    liked: list[str] = Field(default_factory=list, max_length=20)
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
    """대화 응답 스키마. changes로 화면의 노트 선택을 직접 바꾼다(blend-notes.json의 노트 id만 허용)."""
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

FAMILY_WORDS = {"forest": "숲·나무·풀·흙", "marine": "바다·물·바람", "amber": "따뜻함·수지·향신료·단맛",
                "floral": "꽃·과일", "linen": "깨끗함·비누·파우더", "citrus": "상큼함·햇살"}

def note_menu():
    lines = []
    for stage in ("top", "heart", "base"):
        items = [f"{n['id']}({n['name']}·{n['family']}: {n['feel']})" for n in blend_notes.values() if n["stage"] == stage]
        lines.append(f"{STAGE_KO[stage]}[{stage}]: " + ", ".join(items))
    lines.append("계열별 노트(분위기를 노트로 옮길 때 참고):")
    for family, words in FAMILY_WORDS.items():
        ids = [f"{n['id']}({STAGE_KO[n['stage']]})" for n in blend_notes.values() if n["family"] == family]
        lines.append(f"- {family}({words}): " + ", ".join(ids))
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
    label = PALETTES[family][0].split()[0].removesuffix("의")
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
    tools_used, tool_data = [], []
    if all(config):
        url, model, key = config
        prompt = chat_prompt(selected, body)
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
            if responses_api:
                content, tools_used, tool_data = await consult_with_tools(url, model, key, prompt, turns)
                # 화면에는 사용자가 직접 말한 향수의 조회만 남긴다(AI가 혼자 찾아본 향수, 못 찾은 조회는 숨김)
                if not mcp_server.perfumes_in(user_texts[-1]):
                    tools_used = [t for t in tools_used if t["tool"] != "find_perfume"]
                # 사용자가 날씨를 말하지 않았는데 AI가 날씨를 본 경우: 표시하지 않고 블렌드에도 쓰지 않는다
                if not re.search(r"날씨|기온|오늘|비\s?오|눈\s?오|더운|추운|덥|춥", user_texts[-1]):
                    tools_used = [t for t in tools_used if t["tool"] != "get_weather"]
                    tool_data = [(name, d) for name, d in tool_data if name != "get_weather"]
            else:
                # Chat Completions 호환 API: 도구 없이 JSON만 받는다
                async with httpx.AsyncClient(timeout=25) as client:
                    result = await client.post(url, headers={"Authorization": f"Bearer {key}"}, json={
                        "model": model, "response_format": {"type": "json_object"},
                        "messages": [{"role": "system", "content": prompt + "\nJSON만 출력: " + json.dumps(chat_schema(), ensure_ascii=False)}, *turns],
                    })
                    result.raise_for_status()
                    content = result.json()["choices"][0]["message"]["content"].strip()
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
            raw = json.loads(content)
            raw["reply"] = str(raw.get("reply", ""))[:500] or "다시 한번 말해 주시겠어요?"
            raw["notes"] = [str(n)[:20] for n in raw.get("notes", []) if isinstance(n, (str, int))][:5]
            raw["changes"] = [c for c in raw.get("changes", []) if isinstance(c, dict)]
            direction = Direction.model_validate(raw)
        except httpx.HTTPStatusError as error:
            detail = {
                401: ("입력한 OpenAI 키가 맞지 않아요. 오른쪽 위에서 키를 다시 확인해 주세요." if user_key(request)
                      else "LLM API 키가 인증되지 않았어요. 서버 설정의 키를 확인해 주세요."),
                403: "이 키에 모델을 사용할 권한이 없어요.",
                429: "LLM 요청 한도나 잔액을 확인해 주세요.",
            }.get(error.response.status_code, "LLM 서버가 요청을 처리하지 못했어요.")
            raise HTTPException(502, detail) from error
        except (httpx.HTTPError, ValueError, KeyError, IndexError, AttributeError, TypeError):
            raise HTTPException(502, "향을 해석하는 중 연결이 끊겼어요. 잠시 뒤 다시 시도해 주세요.")
        # 사용자가 실제로 단 향을 싫다고 말했을 때만 단맛 회피를 켠다(LLM이 취향을 지어내는 것을 막는다)
        direction.avoid_sweet = any(SWEET_AVOID.search(text) for text in user_texts)
        updated = apply_llm_changes(updated, direction.changes)
        updated, copied = apply_tool_results(updated, tool_data, user_texts[-1])
        if copied:
            # '○○ 같은 향': 실제 노트로 채운 결과를 그대로 말한다(LLM 문장 대신 사실만)
            direction.reply = copy_reply(copied)
            tools_used = [{**t, "copied": True, "id": copied["id"]} if t["tool"] == "find_perfume" and t["detail"] == copied["perfume"] else t
                          for t in tools_used]
            if not any(t.get("copied") for t in tools_used):
                tools_used.append({"tool": "find_perfume", "label": "향수 조회", "detail": copied["perfume"], "copied": True, "id": copied["id"]})
            direction.changes = [{"stage": st} for st in updated]
        else:
            updated = fill_empty_stages(updated, direction)
        selected = selected_notes(Blend(blend=updated))
    elif any(config):
        raise HTTPException(503, "LLM 연결 설정을 확인해 주세요.")
    else:
        direction, updated, tools_used = await demo_with_tools(user_texts, updated)
        selected = selected_notes(Blend(blend=updated))
        changed = diff_blend(before, normalized(updated))
        if explicit and not tools_used and changed:
            direction.reply = " ".join(change_sentence(c) for c in changed)

    after = normalized(updated)
    anchor = next((t.get("id") for t in tools_used if t["tool"] == "find_perfume" and t.get("copied")), None)
    return {**present(direction, len(user_texts), selected), "blend": after, "changes": diff_blend(before, after),
            "tools": tools_used, "demo": not all(config), "anchor": anchor}


def chat_prompt(selected, body):
    current = ", ".join(f"{STAGE_KO[st]}={'+'.join(n['name'] for n in notes)}" for st, notes in selected.items()) or "아직 없음"
    liked = [f"{p['brand']} {p['name']}" for p in PERFUMES if p["id"] in set(body.liked)]
    prompt = (
        "너는 한국어로 상담하는 조향사다. 사용자 화면의 노트 선택을 changes로 직접 바꿀 수 있고, MCP 도구로 실제 정보를 확인할 수 있다.\n"
        f"지금 화면에서 선택된 노트: {current}\n"
        f"고를 수 있는 노트(단계[stage]: id(이름·계열: 느낌)):\n{note_menu()}\n"
        "도구 쓰는 법:\n"
        "- 향수 이름이 나오면(예: '탐다오 같은 향', '상탈 33이랑 비교') find_perfume을 영어 이름으로 호출해라. 결과의 실제 노트만 근거로 말하고, "
        "'같은 향', '비슷하게'를 원하면 our_notes(같은 노트)와 approx_notes(같은 노트가 없는 단계를 계열로 비슷하게 채운 노트)가 그대로 화면에 적용된다. 두 향수를 비교하면 각각 호출해 공통점과 차이를 말해라.\n"
        "- 날씨, 오늘, 출근길, 계절 날씨가 나오면 get_weather(영어 도시 이름, 말하지 않으면 Seoul)를 호출해라. reply 첫 문장에 도시, 기온, 하늘을 말하고 "
        "suggested_notes를 바탕으로 단계마다 replace해라. 결과에 fallback=true가 있으면 실제 오늘 날씨가 아니니 note의 내용(연결 실패, 평년 날씨 기준)을 첫 문장에서 그대로 알려라.\n"
        "- describe_note는 사용자가 노트의 뜻을 직접 물었을 때만 한 번 호출해라. 노트를 고를 때는 위 목록의 느낌으로 충분하니 부르지 마라.\n"
        "- 도구 결과에 없는 향수 정보(노트, 출시, 가격)는 지어내지 마라.\n"
        "- 비교나 노트 설명처럼 질문만 했으면 선택을 바꾸지 마라(changes=[], ready=false).\n"
        "규칙:\n"
        "1) 장면이나 분위기를 말하면 탑·미들·베이스 세 단계 모두에 그 분위기에 맞는 노트가 1개 이상 있게 해라. 빈 단계는 반드시 채워라. "
        "계열별 노트 목록을 참고해 분위기에 맞는 계열에서 골라라(예: 숲이면 forest 노트, 상쾌한 숲이면 forest+citrus).\n"
        "2) 이미 고른 노트가 요청과 어긋나면(예: 숲을 원하는데 바다 소금, '달지 않게'인데 바닐라·통카·코코넛) remove하고 이유를 말해라. "
        "어울리는 노트는 그대로 둔다.\n"
        "3) 단계마다 최대 3개, 위 목록의 id만, 그 단계의 노트만 쓴다. 특정 노트만 바꿀 때는 remove와 add, 단계 전체를 새로 정할 때만 replace. 바꿀 이유가 없으면 changes=[].\n"
        "4) reply는 2~4문장. 지금 선택을 짧게 짚고, changes의 모든 변경(빼는 노트와 더하는 노트)을 빠짐없이 이유와 함께 말해라. "
        "예: '지금 베이스가 바닐라라 꽤 달콤한 편이에요. 달지 않은 숲 느낌을 원하시니 베티버로 바꿔 볼게요.' 질문은 많아야 하나. 시향할 향수 추천은 화면 아래 'AI 큐레이션'이 따로 보여 주니 reply에서는 향수를 추천하지 마라. 향수 이름은 사용자가 향수를 직접 말했을 때만, 도구 결과에 나온 것만 쓴다. "
        "reply에서 노트는 영어 id(fig-leaf 등)가 아니라 한국어 이름(무화과 잎 등)으로 말해라.\n"
        "5) family는 전체 분위기, temperature는 차가움/따뜻함, airy는 가볍고 투명하면 true, avoid_sweet는 단 향을 피하면 true(대화 전체 기준). "
        "avoid_sweet는 사용자가 단 향을 싫다고 직접 말했을 때만 true로 하고, 사용자가 말하지 않은 취향을 지어내지 마라. "
        "notes에는 향의 인상을 짧은 한국어 단어로 넣어라. 방향이 잡혔거나 추천을 원하면 ready=true. 아직 방향이 없으면 family=violet."
    )
    if liked:
        prompt += f"\n참고: 사용자가 마음에 들어 저장한 향수는 {', '.join(liked)}이다. 취향을 짐작하는 데만 쓰고 억지로 맞추지 마라."
    if body.image:
        prompt += (
            "\n6) 사용자가 사진을 보냈다. 사진 속 장면의 색, 빛, 계절, 온도, 습도, 사물과 재질, 분위기를 읽어 향으로 번역해라. "
            "reply 첫 문장에서 사진에서 읽은 것을 구체적으로 짧게 말하고(예: '해 질 녘 젖은 돌길과 따뜻한 가로등 빛이 보여요'), "
            "그 인상에 맞는 노트를 단계별로 changes에 넣어라. 사진 속 사람의 신원이나 외모는 평가하지 마라."
        )
    return prompt


def response_text(data):
    return "".join(part["text"] for item in data["output"] if item.get("type") == "message"
                   for part in item["content"] if part.get("type") == "output_text").strip()


async def consult_with_tools(url, model, key, prompt, turns, max_rounds=3):
    """Responses API + MCP 도구. MCP 서버에서 도구 목록을 받아 LLM에 주고, LLM이 부른 도구를 MCP로 실행해 결과를 돌려준다."""
    inputs = [{"role": "developer", "content": prompt}, *turns]
    used, raw = [], []
    async with MCPClient(mcp_server.mcp) as mcp_client, httpx.AsyncClient(timeout=30) as client:
        listed = await mcp_client.list_tools()
        tools = [{"type": "function", "name": t.name, "description": t.description or "",
                  "parameters": t.input_schema, "strict": False} for t in listed.tools]
        for round_no in range(max_rounds + 1):
            payload = {"model": model, "input": inputs, "store": False, "max_output_tokens": 900,
                       "text": {"format": {"type": "json_schema", "name": "consult", "schema": chat_schema(), "strict": True}}}
            if round_no < max_rounds:
                payload["tools"] = tools
            result = await client.post(url, headers={"Authorization": f"Bearer {key}"}, json=payload)
            result.raise_for_status()
            data = result.json()
            calls = [item for item in data["output"] if item.get("type") == "function_call"]
            if not calls:
                return response_text(data), used, raw
            for call in calls:
                try:
                    args = json.loads(call.get("arguments") or "{}")
                    called = await mcp_client.call_tool(call["name"], args)
                    output = "".join(getattr(part, "text", "") for part in called.content)
                except Exception as error:  # 도구가 실패해도 대화는 이어 간다
                    args, output = {}, json.dumps({"error": f"도구 실행 실패: {type(error).__name__}"}, ensure_ascii=False)
                inputs.append({"type": "function_call", "call_id": call["call_id"], "name": call["name"],
                               "arguments": call.get("arguments") or "{}"})
                inputs.append({"type": "function_call_output", "call_id": call["call_id"], "output": output})
                used.append(tool_label(call["name"], args, output))
                try:
                    raw.append((call["name"], json.loads(output)))
                except ValueError:
                    pass
    raise ValueError("도구 호출이 끝나지 않았어요.")


def tool_label(name, args, output):
    """화면에 보여 줄 도구 사용 기록(무엇을 확인했는지)."""
    try:
        data = json.loads(output)
    except ValueError:
        data = {}
    if data.get("error"):
        return {"tool": name, "label": "확인 실패", "detail": data["error"]}
    if name == "get_weather" and data.get("fallback"):
        return {"tool": name, "label": "날씨(평년값)", "detail": f"연결 실패 · {data.get('sky')} 약 {data.get('temperature_c')}°C 기준"}
    if name == "get_weather":
        return {"tool": name, "label": "날씨", "detail": f"{data.get('city')} {data.get('temperature_c')}°C · {data.get('sky')} · 습도 {data.get('humidity')}%"}
    if name == "find_perfume":
        if not data.get("found"):
            return {"tool": name, "label": "확인 실패", "detail": f"'{args.get('name', '')}' 없음"}
        return {"tool": name, "label": "향수 조회", "detail": data.get("perfume"), "id": data.get("id")}
    if name == "search_perfumes":
        names = [r["perfume"] for r in data.get("results", [])][:3]
        return {"tool": name, "label": "DB 검색", "detail": ", ".join(names) or "결과 없음"}
    if name == "describe_note":
        return {"tool": name, "label": "노트 설명", "detail": f"{data.get('name')} · 향수 {data.get('count', 0)}종에 들어 있음"}
    return {"tool": name, "label": name, "detail": ""}


def apply_llm_changes(updated, changes):
    """LLM이 정한 노트 변경을 적용한다. 단계를 잘못 지정한 노트는 버리지 않고 그 노트의 원래 단계로 옮긴다."""
    for change in changes:
        stage, action = change.get("stage"), change.get("action")
        if not isinstance(stage, str) or action not in ("add", "remove", "replace"):
            continue
        notes = change.get("notes", [])
        ids = [i for i in (notes if isinstance(notes, list) else []) if isinstance(i, str) and i in blend_notes]
        right = [i for i in ids if blend_notes[i]["stage"] == stage]
        if stage in STAGE_KO and right:
            updated = apply_updates(updated, {stage: ({"replace": "set"}.get(action, action), right)})
        for i in ids:
            if blend_notes[i]["stage"] != stage:
                own = blend_notes[i]["stage"]
                updated = apply_updates(updated, {own: ("remove" if action == "remove" else "add", [i])})
    return updated


SWEET_AVOID = re.compile(r"(단\s?향|단맛|달콤|달달|바닐라|구르망).{0,10}(싫|않|말고|빼|없|별로|부담|피해|과하)"
                         r"|달지\s?않|안\s?달[게고아]|덜\s?달|너무\s?달[아고]|달아서|달아요|달게\s?(하지|말)")
SIMILAR = re.compile(r"같은|같이|비슷|처럼|느낌으로|만들어|따라|닮은")


def apply_tool_results(updated, tool_data, message):
    """도구 결과를 화면 선택에 확실히 반영한다(LLM이 빠뜨려도).
    - '○○ 같은 향'이면 그 향수의 실제 노트(우리 노트와 같은 것)로 단계마다 바꾼다.
    - 날씨를 확인했으면 비어 있는 단계를 날씨 제안 노트로 채운다."""
    result, copied = normalized(updated), None
    found = [d for name, d in tool_data if name == "find_perfume" and d.get("found")]
    if len({d["id"] for d in found}) == 1 and SIMILAR.search(message):
        copied = found[-1]
        result = copy_blend(copied)
    for name, data in tool_data:
        if name == "get_weather" and not data.get("error"):
            for stage, ids in data.get("suggested_notes", {}).items():
                if ids and not result.get(stage):
                    result[stage] = ids[:MAX_PER_STAGE]
    return result, copied


def copy_blend(data):
    """find_perfume 결과로 블렌드를 만든다: 같은 노트를 먼저, 같은 노트가 없는 단계는 계열이 가까운 노트로."""
    exact, near, approx = data.get("our_notes", {}), data.get("near_notes", {}), data.get("approx_notes", {})
    blend = {}
    for st in ("top", "heart", "base"):
        ids = list(dict.fromkeys(exact.get(st, []) + near.get(st, []))) or approx.get(st, [])
        if ids:
            blend[st] = ids[:MAX_PER_STAGE]
    return blend


def copy_reply(data):
    """'○○ 같은 향'의 답변. 같은 노트와 비슷하게 고른 노트를 나눠 사실대로 말한다."""
    exact, approx = data.get("our_notes", {}), data.get("approx_notes", {})
    blend = copy_blend(data)
    same = [blend_notes[i]["name"] for st in ("top", "heart", "base") for i in exact.get(st, [])]
    near = [f"{p['from']} ≈ {p['to']}" for p in data.get("near_pairs", [])
            if p["to"] in {blend_notes[i]["name"] for i in blend.get(p["stage"], [])}]
    family = [f"{STAGE_KO[st]} {blend_notes[i]['name']}" for st, ids in approx.items() for i in ids if ids == blend.get(st)]
    perfume = data["perfume"]
    parts = []
    if same:
        parts.append(f"{perfume}의 공식 노트 중 우리 노트와 같은 {', '.join(same)}{josa(same[-1], '을', '를')} 담았어요.")
    else:
        parts.append(f"{perfume}의 공식 노트는 우리 노트와 똑같은 게 없어요.")
    if near:
        parts.append(f"우리 목록에 없는 노트는 가장 가까운 노트로 옮겼어요: {', '.join(near)}.")
    if family:
        parts.append(f"그래도 빈 단계는 이 향수의 계열에 맞춰 채웠어요: {', '.join(family)}.")
    parts.append("아래 추천 맨 앞에 이 향수를 기준으로 두었어요. 더 가볍게, 더 따뜻하게처럼 말해 주시면 조정할게요.")
    return " ".join(parts)


def fill_empty_stages(updated, direction):
    """분위기가 잡혔는데 비어 있는 단계가 남으면, 그 분위기 계열의 노트로 하나 채운다(달지 않게면 단 노트는 피한다)."""
    if direction.family == "violet" or not (direction.ready or direction.changes):
        return updated
    sweet = {"vanilla", "tonka", "coconut", "amber", "pear", "mandarin"}
    result = normalized(updated)
    for stage in ("top", "heart", "base"):
        if result.get(stage):
            continue
        options = [n["id"] for n in blend_notes.values() if n["stage"] == stage and n["family"] == direction.family
                   and not (direction.avoid_sweet and n["id"] in sweet)]
        if options:
            result[stage] = [options[0]]
    return result


CITY_WORDS = sorted(mcp_server.CITY_EN, key=len, reverse=True)

async def demo_with_tools(user_texts, updated):
    """키 없는 데모 모드에서도 날씨와 향수 이름은 MCP 도구로 실제로 확인한다. 그 밖에는 키워드 규칙."""
    last = user_texts[-1]
    async with MCPClient(mcp_server.mcp) as mcp_client:
        if re.search(r"날씨|기온", last) and not mcp_server.perfumes_in(last):
            city = next((c for c in CITY_WORDS
                         if re.search(rf"(?<![가-힣]){c}(?=시|$|[^가-힣]|은|는|의|도|날씨)", last)), "서울")
            called = await mcp_client.call_tool("get_weather", {"city": city})
            output = "".join(getattr(part, "text", "") for part in called.content)
            data = json.loads(output)
            if not data.get("error"):
                blend = {st: ids for st, ids in data["suggested_notes"].items() if ids}
                names = ", ".join(blend_notes[i]["name"] for ids in blend.values() for i in ids)
                opening = (data["note"] if data.get("fallback") else
                           f"{data['city']}{josa(data['city'], '은', '는')} 지금 {data['temperature_c']}°C, {data['sky']}{josa(data['sky'], '이에요', '예요')}.")
                reply = f"{opening} {data['why']} 그래서 {names}{josa(names, '을', '를')} 골라 봤어요."
                direction = Direction(family=data["suggested_family"], temperature=data["suggested_temperature"],
                                      airy=data["suggested_family"] in {"marine", "citrus"}, avoid_sweet=False,
                                      notes=[blend_notes[i]["name"] for ids in blend.values() for i in ids][:5],
                                      ready=True, reply=reply)
                return direction, blend, [tool_label("get_weather", {"city": city}, output)]
        mentioned = mcp_server.perfumes_in(last)
        if len(mentioned) >= 2 and re.search(r"비교|차이|다른 점|vs", last, re.IGNORECASE):
            a, b = mentioned[:2]
            tools, notes = [], []
            for p in (a, b):
                called = await mcp_client.call_tool("find_perfume", {"name": p["name"]})
                output = "".join(getattr(part, "text", "") for part in called.content)
                tools.append(tool_label("find_perfume", {"name": p["name"]}, output))
                notes.append({rag.ko_name(n) for st in ("top", "heart", "base") for n in p["notes"][st]})
            both, only_a, only_b = notes[0] & notes[1], notes[0] - notes[1], notes[1] - notes[0]
            own_a, own_b = ", ".join(sorted(only_a)[:4]) or "없음", ", ".join(sorted(only_b)[:4]) or "없음"
            reply = (f"{a['name']}에만 있는 노트는 {own_a}, {b['name']}에만 있는 노트는 {own_b}{josa(own_b, '이에요', '예요')}. "
                     + (f"둘 다 {', '.join(sorted(both)[:3])}{josa(sorted(both)[min(2, len(both) - 1)], '이', '가')} 들어 있어요. " if both else "겹치는 노트는 없어요. ")
                     + "한쪽처럼 블렌드를 만들고 싶으면 '○○ 같은 향으로'라고 말해 주세요.")
            direction = Direction(family="violet", temperature="neutral", airy=False, avoid_sweet=False, notes=[],
                                  ready=False, reply=reply)
            return direction, updated, tools
        hit = mentioned[0] if mentioned else None
        if hit:
            called = await mcp_client.call_tool("find_perfume", {"name": hit["name"]})
            output = "".join(getattr(part, "text", "") for part in called.content)
            data = json.loads(output)
            blend = copy_blend(data)
            family = blend_family(selected_notes(Blend(blend=blend))) if blend else "violet"
            reply = copy_reply(data)
            direction = Direction(family=family, temperature="neutral", airy=False, avoid_sweet=False,
                                  notes=[], ready=bool(blend), reply=reply)
            return direction, blend or updated, [{**tool_label("find_perfume", {"name": hit["name"]}, output),
                                                  "copied": bool(blend), "id": data["id"]}]
    return demo_direction(user_texts), updated, []


def change_sentence(c):
    """바뀐 단계 하나를 한 문장으로. 예) 베이스에서 바닐라를 빼고 샌달우드를 넣었어요."""
    removed, added = ", ".join(c["removed"]), ", ".join(c["added"])
    if removed and added:
        return f"{c['label']}에서 {removed}{josa(removed, '을', '를')} 빼고 {added}{josa(added, '을', '를')} 넣었어요."
    if added:
        return f"{c['label']}에 {added}{josa(added, '을', '를')} 넣었어요."
    return f"{c['label']}에서 {removed}{josa(removed, '을', '를')} 뺐어요."


def josa(word, with_final, without_final):
    """마지막 글자에 받침이 있으면 with_final, 없으면 without_final."""
    if not word:
        return with_final
    code = ord(word[-1]) - 0xAC00
    return with_final if 0 <= code < 11172 and code % 28 else without_final


def present_products(direction, selected):
    """검증된 향수 DB가 있으면 거기서 고른다. 대화에서 나온 노트도 단계 없이 함께 반영한다."""
    if not PERFUMES:
        return []
    chosen = {n["id"] for notes in selected.values() for n in notes}
    extra = [n for n in notes_from_words(direction.notes) if n["id"] not in chosen]
    query = {**selected, **({"any": extra} if extra else {})}
    if not query:
        return []
    family = direction.family if direction.family != "violet" else None
    return db_cards(query, avoid_sweet=direction.avoid_sweet, family=family)

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
        # 대화에서 읽은 의도. 화면이 AI 큐레이션(/api/recommend)에 그대로 넘겨 추천에 반영한다.
        "intent": {"family": None if family == "violet" else family, "temperature": direction.temperature,
                   "airy": direction.airy, "avoid_sweet": direction.avoid_sweet, "mood": direction.notes[:5]},
        "products": present_products(direction, selected) or [item for _, _, item in products[:3]],
    }

# ───────── RAG 큐레이션: 검증된 향수 DB에서 후보를 찾고, LLM은 그 안에서 고르고 이유만 쓴다 ─────────
import rag

PERFUMES = rag.load_perfumes()
rag.ensure_embeddings(PERFUMES)
recommend_cache = {}
NOTE_NAMES = {nid: note["name"] for nid, note in blend_notes.items()}

def db_cards(selected, qvec=None, k=3, avoid_sweet=False, family=None):
    ranked = rag.retrieve(PERFUMES, selected, qvec, k=k, avoid_sweet=avoid_sweet, family=family)
    return [rag.card(p, matched, NOTE_NAMES) for _, matched, p in ranked]

def notes_from_words(words):
    """LLM이 뽑은 한국어 노트 단어를 우리 노트 id로 맞춘다(이름이나 동의어가 들어 있으면)."""
    found = []
    for word in words:
        for note in blend_notes.values():
            if note["name"] in word or word in note["name"] or any(m in word for m in note["matches"]):
                found.append(note)
    return list({n["id"]: n for n in found}.values())

class Intent(BaseModel):
    family: Literal["forest", "marine", "amber", "floral", "linen", "citrus"] | None = None
    temperature: Literal["cool", "warm", "neutral"] = "neutral"
    airy: bool = False
    avoid_sweet: bool = False
    mood: list[str] = Field(default_factory=list, max_length=5)

class Recommend(BaseModel):
    blend: dict[Stage, list[str] | str] = Field(default_factory=dict, max_length=3)
    intent: Intent | None = None
    anchor: str | None = Field(default=None, max_length=80)  # '○○ 같은 향'으로 만든 블렌드의 기준 향수 id
    liked: list[str] = Field(default_factory=list, max_length=20)

def intent_text(intent):
    """대화에서 읽은 의도를 큐레이션 프롬프트와 임베딩 질의에 붙일 한국어 문장으로 만든다."""
    if not intent:
        return ""
    parts = []
    if intent.family:
        parts.append(f"원하는 분위기: {FAMILY_WORDS[intent.family]}")
    if intent.temperature != "neutral":
        parts.append("차갑고 서늘한 느낌" if intent.temperature == "cool" else "따뜻하고 포근한 느낌")
    if intent.airy:
        parts.append("가볍고 투명하게")
    if intent.avoid_sweet:
        parts.append("단 향은 싫어함")
    if intent.mood:
        parts.append("인상: " + ", ".join(m[:12] for m in intent.mood))
    return " / ".join(parts)

@app.post("/api/recommend")
async def recommend(body: Recommend, request: Request):
    selected = selected_notes(Blend(blend=body.blend))
    if not selected:
        raise HTTPException(422, "노트를 하나 이상 골라 주세요.")
    intent = body.intent
    url, model, key = llm_config(request)
    key_id = json.dumps([normalized(body.blend), intent.model_dump() if intent else None, sorted(body.liked), bool(key), body.anchor],
                        sort_keys=True, ensure_ascii=False)
    if key_id in recommend_cache:
        return recommend_cache[key_id]
    labels = {"top": "탑", "heart": "미들", "base": "베이스"}
    blend_text = " / ".join(f"{labels[st]}: {', '.join(n['name'] + '(' + n['english'] + ')' for n in notes)}"
                            for st, notes in selected.items())
    wish = intent_text(intent)
    try:
        qvec = await rag.aembed(blend_text + (" / " + wish if wish else ""), key) if key else None
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        qvec = None
    ranked = rag.retrieve(PERFUMES, selected, qvec, k=9, avoid_sweet=bool(intent and intent.avoid_sweet),
                          family=intent.family if intent else None)
    base = next((p for p in PERFUMES if p["id"] == body.anchor), None)
    anchor_card = None
    if base:
        # 기준 향수는 맨 앞에 고정하고, 나머지 후보에서 비슷한 향수 2개를 고른다
        chosen_ids = {i for ids in normalized(body.blend).values() for i in ids}
        anchor_card = {**rag.card({**base, "near_matched": [raw for nid, raw in base["near"] if nid in chosen_ids]}, [i for ids in normalized(body.blend).values() for i in ids if i in base["ids"]], NOTE_NAMES,
                                  why="이 향수를 바탕으로 만든 블렌드예요. 아래는 이 블렌드와 비슷한 향수예요."), "anchor": True}
        ranked = [r for r in ranked if r[2]["id"] != base["id"]]
    ranked = ranked[:8]
    want = 2 if anchor_card else 3
    lead = [anchor_card] if anchor_card else []
    if not ranked:
        return {"summary": "", "picks": lead, "ai": False, "ready": len(selected) == 3}
    if not all((url, model, key)) or not httpx.URL(url).path.rstrip("/").endswith("/responses"):
        picks = lead + [rag.card(p, m, NOTE_NAMES) for _, m, p in ranked[:want]]
        return {"summary": "", "picks": picks, "ai": False, "ready": len(selected) == 3}
    candidates = [{
        "id": p["id"], "perfume": f"{p['brand']} {p['name']}",
        "top": p["notes"]["top"], "heart": p["notes"]["heart"], "base": p["notes"]["base"],
        "shared_with_user": [NOTE_NAMES[i] for i in dict.fromkeys(m)],
        "similar_to_user": [rag.ko_name(n) for n in dict.fromkeys(p.get("near_matched", []))],
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
        f"후보 중에서 이 조합과 가장 잘 어울리는 향수 {want}개를 골라라(후보가 {want}개보다 적으면 있는 만큼). "
        "similar_to_user는 사용자가 고른 노트와 같지는 않지만 비슷한 노트다. 이유에서 '같다'고 말하지 말고 '비슷하다'고 말해라. "
        "후보 목록 밖의 향수나 노트를 말하지 마라. 각 이유(why)는 후보에 적힌 실제 노트만 근거로 한국어 한두 문장(70자 내외)으로 쓰고, "
        "사용자가 고른 노트와 어떻게 이어지는지 말해라. summary는 사용자의 조합이 어떤 인상인지 한국어 한 문장(40자 내외)."
        f"\n사용자 조합: {blend_text}\n후보: {json.dumps(candidates, ensure_ascii=False)}"
    )
    if wish:
        prompt += f"\n대화에서 드러난 사용자의 바람: {wish}. 이 바람에 맞는 후보를 우선하고, 이유에도 반영해라."
    liked = [f"{p['brand']} {p['name']}" for p in PERFUMES if p["id"] in set(body.liked)]
    if liked:
        prompt += f"\n사용자가 저장해 둔(마음에 든) 향수: {', '.join(liked)}. 취향 참고용이며 이미 저장한 향수는 되도록 다시 고르지 마라."
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
        picks = lead + [rag.card(p, m, NOTE_NAMES) for _, m, p in ranked[:want]]
        return {"summary": "", "picks": picks, "ai": False, "ready": len(selected) == 3}
    by_id = {p["id"]: (m, p) for _, m, p in ranked}
    picks, used = [], set()
    for pick in curation["picks"]:
        if pick["id"] in by_id and pick["id"] not in used:
            used.add(pick["id"])
            m, p = by_id[pick["id"]]
            picks.append(rag.card(p, m, NOTE_NAMES, why=pick["why"]))
    for _, m, p in ranked:  # LLM이 3개를 못 채우면 점수 순으로 채운다
        if len(picks) >= want:
            break
        if p["id"] not in used:
            used.add(p["id"])
            picks.append(rag.card(p, m, NOTE_NAMES))
    response = {"summary": curation.get("summary", ""), "picks": lead + picks[:want], "ai": True, "ready": len(selected) == 3}
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
