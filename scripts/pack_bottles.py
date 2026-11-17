"""render_bottles.py가 만든 각도별 PNG를 병마다 스프라이트 한 장(유리)과 한 장(액체 자리)으로 묶는다.

실행: python scripts/pack_bottles.py RENDER_DIR public/atelier/frames
결과: {design}-glass.webp, {design}-mask.webp, frames.json(칸 수·크기·액체 자리 상자)
"""
import glob
import json
import os
import sys

from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
os.makedirs(dst, exist_ok=True)
COLS = 8
meta = {}
for design in sorted(os.listdir(src)):
    glass = sorted(glob.glob(f"{src}/{design}/glass_*.png"))
    masks = sorted(glob.glob(f"{src}/{design}/mask_*.png"))
    if not glass or len(glass) != len(masks):
        continue
    g_imgs = [Image.open(p).convert("RGBA") for p in glass]
    m_imgs = [Image.open(p).convert("RGBA").split()[3] for p in masks]
    # 모든 프레임에서 병이 차지하는 영역을 합쳐 여백을 잘라 낸다
    box = None
    for g, m in zip(g_imgs, m_imgs):
        for b in (g.split()[3].point(lambda v: 255 if v > 6 else 0).getbbox(), m.getbbox()):
            if b:
                box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    pad = 6
    W, H = g_imgs[0].size
    box = (max(0, box[0] - pad), max(0, box[1] - pad), min(W, box[2] + pad), min(H, box[3] + pad))
    fw, fh = box[2] - box[0], box[3] - box[1]
    # 액체 자리 상자(모든 프레임 합): 화면의 액체 캔버스를 이 상자에 맞춰 놓고, 마스크로 병 모양만 남긴다
    lb = None
    for m in m_imgs:
        b = m.getbbox()
        if b:
            lb = b if lb is None else (min(lb[0], b[0]), min(lb[1], b[1]), max(lb[2], b[2]), max(lb[3], b[3]))
    lb = (lb[0] - box[0], lb[1] - box[1], lb[2] - box[0], lb[3] - box[1])
    n = len(g_imgs)
    rows = -(-n // COLS)
    gs = Image.new("RGBA", (fw * COLS, fh * rows), (0, 0, 0, 0))
    ms = Image.new("RGBA", (fw * COLS, fh * rows), (255, 255, 255, 0))
    white = Image.new("RGBA", (fw, fh), (255, 255, 255, 255))
    for k, (g, m) in enumerate(zip(g_imgs, m_imgs)):
        x, y = (k % COLS) * fw, (k // COLS) * fh
        gs.paste(g.crop(box), (x, y))
        cell = white.copy(); cell.putalpha(m.crop(box))
        ms.paste(cell, (x, y))
    gs.save(f"{dst}/{design}-glass.webp", quality=86, method=6)
    ms.save(f"{dst}/{design}-mask.webp", quality=80, method=6)
    meta[design] = {
        "frames": n, "cols": COLS, "rows": rows, "w": fw, "h": fh,
        # 액체 자리 상자: 위·오른쪽·아래·왼쪽 여백(%)
        "chamber": [round(lb[1] / fh * 100, 2), round((fw - lb[2]) / fw * 100, 2),
                    round((fh - lb[3]) / fh * 100, 2), round(lb[0] / fw * 100, 2)],
    }
    print(design, n, fw, fh, os.path.getsize(f"{dst}/{design}-glass.webp") // 1024, "KB",
          os.path.getsize(f"{dst}/{design}-mask.webp") // 1024, "KB")
with open(f"{dst}/frames.json", "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=1)
