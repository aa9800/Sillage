"""향수 DB 구축 스크립트.

원칙: 노트 정보는 '실제로 내려받은 페이지 본문'에서만 뽑는다.
1) 제공된 OpenAI 키의 웹 검색으로 향수의 공식(또는 신뢰할 만한) 상품 페이지 주소를 찾는다.
2) 그 페이지를 직접 내려받아 본문 글자만 남긴다.
3) gpt-4o-mini가 '본문 안에서' 탑/미들/베이스 노트를 추출한다.
4) 추출된 노트가 본문에 실제로 들어 있는지 코드로 다시 대조하고, 없는 노트는 버린다.
5) 결과를 data/perfumes.json 에 쌓는다(중간 결과는 data/build-cache.json 에 저장해 이어서 실행 가능).

실행: .venv/Scripts/python.exe scripts/build_catalog.py [향수 id ...]
"""
import html
import json
import os
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
load_dotenv(ROOT / ".env")
URL, MODEL, KEY = (os.getenv(k) for k in ("LLM_CHAT_URL", "LLM_MODEL", "LLM_API_KEY"))
CACHE = DATA / "build-cache.json"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

SEEDS = [
    ("Jo Malone London", "Wood Sage & Sea Salt"), ("Jo Malone London", "English Pear & Freesia"),
    ("Jo Malone London", "Lime Basil & Mandarin"), ("Jo Malone London", "Peony & Blush Suede"),
    ("Jo Malone London", "Blackberry & Bay"), ("Jo Malone London", "Myrrh & Tonka"),
    ("Jo Malone London", "Velvet Rose & Oud"), ("Jo Malone London", "Nectarine Blossom & Honey"),
    ("Diptyque", "Philosykos"), ("Diptyque", "Tam Dao"), ("Diptyque", "Do Son"), ("Diptyque", "Eau Rose"),
    ("Diptyque", "Orphéon"), ("Diptyque", "Fleur de Peau"), ("Diptyque", "Eau des Sens"), ("Diptyque", "Oyédo"),
    ("Le Labo", "Santal 33"), ("Le Labo", "Another 13"), ("Le Labo", "Rose 31"), ("Le Labo", "Thé Noir 29"),
    ("Le Labo", "Bergamote 22"),
    ("Byredo", "Gypsy Water"), ("Byredo", "Mojave Ghost"), ("Byredo", "Blanche"), ("Byredo", "Bal d'Afrique"),
    ("Byredo", "Rose of No Man's Land"),
    ("Maison Margiela", "Replica Lazy Sunday Morning"), ("Maison Margiela", "Replica Jazz Club"),
    ("Maison Margiela", "Replica By the Fireplace"), ("Maison Margiela", "Replica Beach Walk"),
    ("Maison Margiela", "Replica When the Rain Stops"),
    ("Aesop", "Hwyl"), ("Aesop", "Tacit"), ("Aesop", "Marrakech Intense"), ("Aesop", "Eremia"),
    ("Chanel", "Chance Eau Tendre"), ("Chanel", "Coco Mademoiselle"), ("Chanel", "Bleu de Chanel"),
    ("Dior", "Sauvage"), ("Dior", "Miss Dior"), ("Dior", "J'adore"),
    ("Hermès", "Un Jardin sur le Nil"), ("Hermès", "Terre d'Hermès"), ("Hermès", "Twilly d'Hermès"),
    ("Tom Ford", "Lost Cherry"), ("Tom Ford", "Neroli Portofino"), ("Tom Ford", "Tobacco Vanille"),
    ("Acqua di Parma", "Colonia"), ("Acqua di Parma", "Blu Mediterraneo Fico di Amalfi"),
    ("Yves Saint Laurent", "Libre"), ("Yves Saint Laurent", "Black Opium"),
    ("Creed", "Aventus"), ("Creed", "Silver Mountain Water"),
    ("Kilian", "Love, Don't Be Shy"), ("Penhaligon's", "Luna"),
]

slug = lambda s: re.sub(r"[^a-z0-9]+", "-", html.unescape(s).lower().replace("é", "e").replace("è", "e")).strip("-")


class TextOnly(HTMLParser):
    """script/style를 뺀 본문 글자와 JSON-LD(상품 설명이 들어 있는 경우가 많다)를 모은다."""
    def __init__(self):
        super().__init__()
        self.parts, self.skip, self.jsonld = [], 0, []
        self._in_ld = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and "ld+json" in (a.get("type") or ""):
            self._in_ld = True
        elif tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        if tag == "meta" and (a.get("name") or a.get("property") or "").lower() in ("description", "og:description"):
            self.parts.append(a.get("content") or "")

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self._in_ld = False
        elif tag in ("script", "style", "noscript", "svg") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if self._in_ld:
            self.jsonld.append(data)
        elif not self.skip and data.strip():
            self.parts.append(data.strip())


def fetch(url):
    r = httpx.get(url, headers={"User-Agent": BROWSER_UA, "Accept-Language": "en,ko;q=0.8"},
                  follow_redirects=True, timeout=30)
    r.raise_for_status()
    return r


def page_text(url):
    """원래 페이지가 봇 차단(403 등)이면 인터넷 아카이브에 저장된 같은 페이지 사본을 쓴다."""
    r = fetch(url)
    p = TextOnly()
    p.feed(r.text)
    text = " ".join(p.parts + p.jsonld)
    return url, re.sub(r"\s+", " ", html.unescape(text))


def responses(payload):
    r = httpx.post(URL, headers={"Authorization": f"Bearer {KEY}"}, json=payload, timeout=90)
    r.raise_for_status()
    data = r.json()
    return "".join(part["text"] for item in data["output"] if item.get("type") == "message"
                   for part in item["content"] if part.get("type") == "output_text")


def find_urls(brand, name):
    schema = {"type": "object", "additionalProperties": False, "required": ["urls"],
              "properties": {"urls": {"type": "array", "items": {"type": "string"}}}}
    text = responses({
        "model": MODEL, "store": False, "max_output_tokens": 400,
        "tools": [{"type": "web_search_preview", "search_context_size": "low"}],
        "input": f"Find web pages that list the fragrance notes (top/heart/base) of the perfume \"{name}\" by {brand}. "
                 f"Prefer the brand's official product page, then retailers such as Notino, Luckyscent, Mecca, Douglas, Lookfantastic, "
                 f"Cult Beauty, Space NK, Liberty, Selfridges, Nordstrom. Return up to 6 direct product page URLs you actually found in search results.",
        "text": {"format": {"type": "json_schema", "name": "urls", "schema": schema, "strict": True}},
    })
    return [u for u in json.loads(text)["urls"] if u.startswith("http")]


EXTRACT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["found", "concentration", "top", "heart", "base", "family", "description_ko"],
    "properties": {
        "found": {"type": "boolean"},
        "concentration": {"type": "string"},
        "top": {"type": "array", "items": {"type": "string"}},
        "heart": {"type": "array", "items": {"type": "string"}},
        "base": {"type": "array", "items": {"type": "string"}},
        "family": {"type": "array", "items": {"type": "string", "enum": ["citrus", "green", "aquatic", "floral", "fruity", "musk", "amber", "woody", "spicy", "gourmand", "leather"]}},
        "description_ko": {"type": "string"},
    },
}


def extract(brand, name, text):
    out = responses({
        "model": MODEL, "store": False, "max_output_tokens": 600,
        "input": [
            {"role": "developer", "content":
                "You extract perfume notes ONLY from the provided page text. Copy note names exactly as written in the text "
                "(English), ingredients only — never adjectives like spicy, woody, musky, leathery, fresh. If the text does not list notes for this exact perfume, set found=false and leave arrays empty. "
                "If notes are listed without top/heart/base split, put them in heart. Never add notes that are not in the text. "
                "family: 1-3 olfactive families inferred from the listed notes. "
                "description_ko: one natural Korean sentence (<=60 chars) describing the scent, based only on the text."},
            {"role": "user", "content": f"Perfume: {name} by {brand}\n\nPAGE TEXT:\n{text[:14000]}"},
        ],
        "text": {"format": {"type": "json_schema", "name": "notes", "schema": EXTRACT_SCHEMA, "strict": True}},
    })
    return json.loads(out)


def verify(notes, text):
    """본문에 실제로 들어 있는 노트만 남긴다(대소문자·악센트 무시)."""
    norm = lambda s: re.sub(r"\s+", " ", html.unescape(s).lower().replace("é", "e").replace("è", "e")).strip()
    body = norm(text)
    adjectives = {"spicy", "woody", "musky", "leathery", "fresh", "floral", "fruity", "powdery", "smoky", "sweet", "green", "aquatic", "citrus", "warm"}
    return [n for n in notes if len(n) > 2 and norm(n) not in adjectives and norm(n) in body]


def from_pages():
    """Chrome으로 직접 열어 저장한 페이지 본문(data/pages/{id}.json: {url, text})으로 추출·검증한다.
    자동 수집이 봇 차단(403)으로 실패한 향수용."""
    cache = json.loads(CACHE.read_text("utf-8")) if CACHE.exists() else {}
    seeds = {slug(f"{b} {n}"): (b, n) for b, n in SEEDS}
    for path in sorted((DATA / "pages").glob("*.json")):
        pid = path.stem
        if pid not in seeds or cache.get(pid, {}).get("status") == "ok":
            continue
        brand, name = seeds[pid]
        page = json.loads(path.read_text("utf-8"))
        got = extract(brand, name, page["text"])
        stages = {st: verify(got[st], page["text"]) for st in ("top", "heart", "base")}
        total = sum(len(v) for v in stages.values())
        entry = cache.get(pid, {"id": pid, "brand": brand, "name": name, "tried": []})
        entry["tried"].append({"url": page["url"], "via": "chrome", "found": got["found"], "kept": total})
        if got["found"] and total >= 2:
            entry.update(status="ok", source=page["url"], concentration=got["concentration"], notes=stages,
                         family=got["family"], description_ko=got["description_ko"])
        cache[pid] = entry
        print(pid, entry.get("status"), total, flush=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), "utf-8")
    write_db(cache)


def write_db(cache):
    ok = [v for v in cache.values() if v.get("status") == "ok"]
    keep = ("id", "brand", "name", "concentration", "notes", "family", "description_ko", "source")
    (DATA / "perfumes.json").write_text(json.dumps([{k: v[k] for k in keep} for v in ok], ensure_ascii=False, indent=1), "utf-8")
    print(f"ok {len(ok)} / {len(cache)}")


def main(only):
    cache = json.loads(CACHE.read_text("utf-8")) if CACHE.exists() else {}
    for brand, name in SEEDS:
        pid = slug(f"{brand} {name}")
        if only and pid not in only:
            continue
        if cache.get(pid, {}).get("status") == "ok":
            continue
        entry = {"id": pid, "brand": brand, "name": name, "status": "fail", "tried": []}
        try:
            urls = find_urls(brand, name)
        except Exception as e:
            entry["error"] = f"search: {e}"
            urls = []
        for url in urls:
            try:
                final, text = page_text(url)
            except Exception as e:
                entry["tried"].append({"url": url, "error": str(e)[:120]})
                continue
            if name.split()[-1].lower()[:4] not in text.lower():
                entry["tried"].append({"url": url, "error": "name not in page"})
                continue
            try:
                got = extract(brand, name, text)
            except Exception as e:
                entry["tried"].append({"url": url, "error": f"extract: {e}"[:120]})
                continue
            stages = {st: verify(got[st], text) for st in ("top", "heart", "base")}
            dropped = sum(len(got[st]) - len(stages[st]) for st in stages)
            total = sum(len(v) for v in stages.values())
            entry["tried"].append({"url": final, "found": got["found"], "kept": total, "dropped": dropped})
            if got["found"] and total >= 3:
                entry.update(status="ok", source=final, concentration=got["concentration"], notes=stages,
                             family=got["family"], description_ko=got["description_ko"], dropped=dropped)
                break
        cache[pid] = entry
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), "utf-8")
        print(pid, entry["status"], entry.get("source", ""), flush=True)
        time.sleep(.5)
    ok = [v for v in cache.values() if v.get("status") == "ok"]
    keep = ("id", "brand", "name", "concentration", "notes", "family", "description_ko", "source")
    (DATA / "perfumes.json").write_text(json.dumps([{k: v[k] for k in keep} for v in ok], ensure_ascii=False, indent=1), "utf-8")
    print(f"ok {len(ok)} / {len(cache)}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--from-pages"]:
        from_pages()
    else:
        main(set(sys.argv[1:]))
