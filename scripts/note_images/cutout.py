"""고른 후보의 배경을 지우고 정사각형 투명 webp로 저장, 출처 크레딧을 남긴다."""
import json, re, sys, pathlib, html
from PIL import Image
from rembg import remove, new_session

ROOT = pathlib.Path(__file__).parent
PROJECT = pathlib.Path(sys.argv[1])
OUT = PROJECT / "public" / "notes"
OUT.mkdir(parents=True, exist_ok=True)

PICKS = {"lime": 3, "salt": 5, "fig-leaf": 0, "pear": 1, "bergamot": 3, "grapefruit": 2, "pink-pepper": 3,
         "green-tea": 2, "freesia": 1, "sage": 0, "cypress": 3, "iris": 0, "rose": 1, "jasmine": 5,
         "lavender": 3, "neroli": 0, "sandalwood": 1, "musk": 5, "vanilla": 3, "patchouli": 4, "vetiver": 2,
         "amber": 1, "cedarwood": 5, "tonka": 0, "mandarin": 1, "cardamom": 0, "violet": 0, "tuberose": 2, "incense": 1, "coconut": 0}
only = sys.argv[2:]

manifest = json.loads((ROOT / "candidates.json").read_text("utf-8"))
session = new_session("isnet-general-use")
credits_path = PROJECT / "public" / "notes" / "CREDITS.json"
credits = json.loads(credits_path.read_text("utf-8")) if credits_path.exists() else {}
clean = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()

SOURCE = {"fig-leaf": "figA", "patchouli": "patB", "coconut": "coconutB"}
for nid, idx in PICKS.items():
    if only and nid not in only:
        continue
    key = SOURCE.get(nid, nid)
    src = ROOT / "candidates" / f"{key}-{idx}.jpg"
    cut = remove(Image.open(src).convert("RGB"), session=session, post_process_mask=True)
    alpha = cut.getchannel("A").point(lambda a: 0 if a < 12 else a)
    cut.putalpha(alpha)
    box = alpha.getbbox()
    cut = cut.crop(box)
    side = int(max(cut.size) * 1.08)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(cut, ((side - cut.width) // 2, (side - cut.height) // 2), cut)
    canvas = canvas.resize((512, 512), Image.LANCZOS)
    canvas.save(OUT / f"{nid}.webp", "WEBP", quality=88, method=6)
    item = manifest[key][idx]
    credits[nid] = {"title": item["title"], "source": item["page"], "license": clean(item["license"]),
                    "author": clean(item["artist"]), "edit": "배경 제거, 자르기, 크기 조정"}
    print(nid, "ok", flush=True)

credits_path.write_text(json.dumps(credits, ensure_ascii=False, indent=1), "utf-8")

# 검수용: 사이트 바탕색 위에 올린 시트
ids = list(PICKS)
sheet = Image.new("RGB", (6 * 180, 5 * 180), (239, 235, 228))
for i, nid in enumerate(ids):
    im = Image.open(OUT / f"{nid}.webp").resize((160, 160))
    sheet.paste(im, ((i % 6) * 180 + 10, (i // 6) * 180 + 10), im)
sheet.save(ROOT / "cutouts.jpg", quality=88)
