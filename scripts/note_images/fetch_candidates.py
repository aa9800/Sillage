"""Wikimedia Commons에서 노트별 후보 사진을 모으고 대조용 시트를 만든다."""
import json, sys, time, io, pathlib, urllib.parse, urllib.request, urllib.error
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "candidates"
OUT.mkdir(exist_ok=True)
UA = "SillageEduImageFetcher/0.1 (educational student project; https://github.com/)"
API = "https://commons.wikimedia.org/w/api.php"

QUERIES = {
    "lime": "lime fruit",
    "salt": "sea salt",
    "fig-leaf": "fig leaf",
    "pear": "pear fruit white background",
    "bergamot": "bergamot orange fruit",
    "grapefruit": "grapefruit fruit",
    "pink-pepper": "pink peppercorns",
    "green-tea": "green tea leaves fresh",
    "freesia": "Freesia flower",
    "sage": "sage leaves white background",
    "cypress": "cypress cones",
    "iris": "iris flower isolated white background",
    "rose": "pink rose flower",
    "jasmine": "Jasminum flower",
    "lavender": "Lavandula angustifolia flowers",
    "neroli": "orange blossom",
    "sandalwood": "Santalum album wood",
    "musk": "Gossypium boll",
    "vanilla": "vanilla pods",
    "patchouli": "Pogostemon cablin",
    "vetiver": "vetiver",
    "amber": "benzoin resin",
    "cedarwood": "wood log white background",
    "tonka": "tonka beans",
}

def get(url, tries=5):
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == tries - 1:
                raise
            time.sleep(float(e.headers.get("Retry-After") or 3 * (attempt + 1)))

def search(q, n=6):
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"filetype:bitmap {q}", "gsrlimit": n * 2, "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 900,
    }
    data = json.loads(get(API + "?" + urllib.parse.urlencode(params)))
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        if min(info.get("width", 0), info.get("height", 0)) < 600:
            continue
        meta = info.get("extmetadata", {})
        out.append({
            "title": p["title"], "thumb": info["thumburl"], "page": info["descriptionurl"],
            "license": meta.get("LicenseShortName", {}).get("value", ""),
            "artist": meta.get("Artist", {}).get("value", ""),
        })
        if len(out) >= n:
            break
    return out

def main(ids):
    manifest_path = ROOT / "candidates.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    for nid in ids:
        items = search(QUERIES[nid])
        tiles = []
        for i, item in enumerate(items):
            path = OUT / f"{nid}-{i}.jpg"
            try:
                img = Image.open(io.BytesIO(get(item["thumb"]))).convert("RGB")
                img.save(path, quality=90)
                item["file"] = path.name
                tiles.append(img)
            except Exception as e:
                item["error"] = str(e)
            time.sleep(.3)
        manifest[nid] = items
        # 대조 시트: 6칸, 번호 표시
        sheet = Image.new("RGB", (6 * 220, 250), "white")
        d = ImageDraw.Draw(sheet)
        for i, img in enumerate(tiles):
            img.thumbnail((210, 210))
            sheet.paste(img, (i * 220 + 5 + (210 - img.width) // 2, 5 + (210 - img.height) // 2))
            d.text((i * 220 + 8, 222), f"{nid} #{i}", fill="black")
        sheet.save(OUT / f"_sheet-{nid}.jpg", quality=85)
        print(nid, len(tiles), flush=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")

if __name__ == "__main__":
    main(sys.argv[1:] or list(QUERIES))
