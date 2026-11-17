"""향수병 5종을 Blender(Cycles)로 각도별 렌더 → 화면에서 프레임을 넘겨 돌아가는 병을 만든다.

실행: blender -b -P scripts/render_bottles.py -- OUT_DIR [design ...] [--frames 31] [--samples 160]
  - 각 병마다 OUT_DIR/{design}/glass_XX.png (유리·마개, 투명 배경)과 mask_XX.png(병 속 액체가 차는 자리)를 만든다.
  - 액체 색은 사용자가 고른 노트마다 바뀌므로 렌더하지 않고, 화면에서 mask 자리에 칠한다.
조립: python scripts/pack_bottles.py OUT_DIR public/atelier/frames
"""
import math
import sys

import bpy
import bmesh
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = argv[0]
opts = {"--frames": 31, "--samples": 160, "--height": 960, "--sweep": 30}
names = []
i = 1
while i < len(argv):
    if argv[i] in opts:
        opts[argv[i]] = int(argv[i + 1]); i += 2
    else:
        names.append(argv[i]); i += 1

# ───────── 병 설계: 옆모습 윤곽 [반지름, 높이] + 단면 모양 ─────────
def ring(n, phase=0.0, sx=1.0, sy=1.0):
    return [(math.cos(phase + 2 * math.pi * k / n) * sx, math.sin(phase + 2 * math.pi * k / n) * sy) for k in range(n)]


def chamfer_rect(w=1.0, d=.6, c=.2):
    return [(w, -d + c), (w, d - c), (w - c, d), (-w + c, d), (-w, d - c), (-w, -d + c), (-w + c, -d), (w - c, -d)]


DESIGNS = {
    "crystal": dict(section=ring(8, math.pi / 8), neck=1.42, wall=.035, base=.16,
                    profile=[(0, 0), (.26, 0), (.31, .05), (.52, .72), (.34, 1.42), (.15, 1.7), (.12, 1.74), (.12, 1.86)],
                    cap=dict(kind="gem", y=1.86), collar=dict(r=.145, h=.07, y=1.8, metal="silver")),
    "ribbon": dict(round=True, section=ring(96, 0, 1, .82), neck=1.0, wall=.04, base=.14,
                   profile=[(0, 0), (.48, 0), (.56, .03), (.74, .18), (.8, .5), (.73, .84), (.46, 1.02), (.2, 1.1), (.18, 1.13), (.18, 1.24)],
                   cap=dict(kind="cylinder", r=.27, h=.3, y=1.24, metal="gold"), ribbon=dict(r=.21, tube=.032, y=1.2)),
    "column": dict(round=True, section=ring(96, 0, 1, .74), neck=1.6, wall=.035, base=.18,
                   profile=[(0, 0), (.3, 0), (.35, .04), (.35, 1.58), (.29, 1.7), (.13, 1.76), (.13, 1.86)],
                   cap=dict(kind="dome", r=.2, h=.26, y=1.86, metal="silver")),
    "emerald": dict(section=chamfer_rect(1, .58, .2), neck=1.16, wall=.05, base=.2,
                    profile=[(0, 0), (.78, 0), (.86, .06), (.86, 1.12), (.76, 1.22), (.26, 1.3), (.24, 1.33), (.24, 1.42)],
                    cap=dict(kind="box", w=.36, d=.3, h=.42, y=1.42, metal="black"), collar=dict(r=.25, h=.08, y=1.36, metal="gold")),
    "oval": dict(round=True, section=ring(96, 0, 1, .6), neck=1.18, wall=.045, base=.18,
                 profile=[(0, 0), (.42, 0), (.52, .04), (.68, .3), (.72, .62), (.66, .98), (.48, 1.2), (.22, 1.3), (.17, 1.33), (.17, 1.46)],
                 cap=dict(kind="box", w=.34, d=.3, h=.34, y=1.46, metal="silver"), collar=dict(r=.18, h=.06, y=1.4, metal="silver")),
}


def soften(profile, steps=6):
    """둥근 병의 윤곽 점 사이를 부드러운 곡선(Catmull-Rom)으로 채운다 → 어깨·허리에 꺾인 자국이 안 보이게."""
    out = [profile[0]]
    pts = [profile[0]] + profile + [profile[-1]]
    for k in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[k - 1], pts[k], pts[k + 1], pts[k + 2]
        for j in range(1, steps + 1):
            t = j / steps
            out.append(tuple(.5 * ((2 * p1[i]) + (-p0[i] + p2[i]) * t + (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * t * t
                                   + (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * t ** 3) for i in range(2)))
    return out


def radius_at(profile, y):
    for (r0, y0), (r1, y1) in zip(profile, profile[1:]):
        if y <= y1 and y1 > y0:
            return r0 + (r1 - r0) * max(0.0, (y - y0) / (y1 - y0))
    return profile[-1][0]


def loft(name, rings, section, cap_bottom=True, cap_top=True):
    """rings: [(반지름, 높이)] 아래→위. 단면(section)을 반지름만큼 키워 층층이 쌓아 닫힌 몸통을 만든다."""
    bm = bmesh.new()
    loops = []
    rings = [(r, z) for r, z in rings if r > 1e-3]  # 반지름 0인 꼭짓점 줄은 빼고 뚜껑 면으로 닫는다
    for r, z in rings:
        loops.append([bm.verts.new((x * r, y * r, z)) for x, y in section])
    n = len(section)
    for a, b in zip(loops, loops[1:]):
        for k in range(n):
            bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k]))
    if cap_bottom:
        bm.faces.new(list(reversed(loops[0])))
    if cap_top:
        bm.faces.new(loops[-1])
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    return ob


def smooth(ob, angle=32):
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True); bpy.context.view_layer.objects.active = ob
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(angle))


def boolean_diff(ob, cutter):
    m = ob.modifiers.new("cut", "BOOLEAN")
    m.operation = "DIFFERENCE"; m.object = cutter
    try:
        m.solver = "EXACT"
    except TypeError:
        pass
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True); bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=m.name)
    bpy.data.objects.remove(cutter)


# ───────── 재질 ─────────
def principled(name, **kw):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    for key, value in kw.items():
        bsdf.inputs[key].default_value = value
    return mat


def materials():
    return {
        "glass": principled("glass", **{"Base Color": (.97, .98, .98, 1), "Transmission Weight": 1.0, "IOR": 1.5, "Roughness": .015}),
        "gem": principled("gem", **{"Base Color": (.98, .98, 1, 1), "Transmission Weight": 1.0, "IOR": 1.62, "Roughness": .01}),
        "silver": principled("silver", **{"Base Color": (.86, .87, .9, 1), "Metallic": 1.0, "Roughness": .16}),
        "gold": principled("gold", **{"Base Color": (.95, .74, .42, 1), "Metallic": 1.0, "Roughness": .2}),
        "black": principled("black", **{"Base Color": (.008, .008, .008, 1), "Roughness": .12, "Coat Weight": 1.0, "Coat Roughness": .03}),
    }


# ───────── 장면: 어두운 스튜디오 + 소프트박스(카메라에는 안 보이고 유리에만 비친다) ─────────
def softbox(name, loc, size, strength, look=(0, 0, 1.0)):
    bpy.ops.mesh.primitive_plane_add(size=1, location=loc)
    ob = bpy.context.active_object; ob.name = name
    ob.scale = (size[0], size[1], 1)
    direction = Vector(look) - Vector(loc)
    ob.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    em = nodes.new("ShaderNodeEmission"); em.inputs["Strength"].default_value = strength
    out = nodes.new("ShaderNodeOutputMaterial")
    mat.node_tree.links.new(em.outputs[0], out.inputs[0])
    ob.data.materials.append(mat)
    ob.visible_camera = False
    ob.visible_shadow = False
    return ob


def setup_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            if any(d.type == kind for d in prefs.devices):
                for d in prefs.devices:
                    d.use = d.type == kind
                sc.cycles.device = "GPU"
                print("device:", kind)
                break
        except TypeError:
            continue
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 24
    sc.cycles.transmission_bounces = 24
    sc.cycles.glossy_bounces = 12
    sc.cycles.transparent_max_bounces = 24
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.render.film_transparent = True
    sc.cycles.film_transparent_glass = True
    sc.cycles.film_transparent_roughness = .1
    sc.view_settings.view_transform = "AgX" if "AgX" in [v.identifier for v in sc.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"
    sc.view_settings.look = "None"
    world = bpy.data.worlds.new("studio"); sc.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (.018, .018, .02, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    # 소프트박스: 왼쪽 길쭉한 주광, 오른쪽 좁은 띠, 위, 뒤에서 가장자리를 밝히는 띠 두 개
    softbox("key", (-3.2, -2.6, 1.1), (1.1, 3.6), 9.0)
    softbox("strip", (3.4, -1.8, 1.0), (.45, 3.4), 7.0)
    softbox("top", (0, -.6, 4.2), (2.6, 1.6), 3.0)
    softbox("rim_l", (-1.6, 3.0, 1.0), (.35, 3.2), 5.0)
    softbox("rim_r", (1.6, 3.0, 1.0), (.35, 3.2), 5.0)
    softbox("floor", (0, -2.0, -1.6), (3.0, 1.2), 1.2)
    return sc


# ───────── 병 만들기 ─────────
def build(design, mats):
    d = DESIGNS[design]
    sec, prof = d["section"], d["profile"]
    if d.get("round"):
        prof = soften(prof)
    top_y = prof[-1][1]
    parts = []
    # 1) 유리: 바깥 몸통 − 안쪽 빈 곳(벽 두께 wall, 바닥 두께 base)
    outer = loft("glass", [(r, y) for r, y in prof], sec)
    inner_rings = [(radius_at(prof, d["base"]) - d["wall"], d["base"])]
    inner_rings += [(max(r - d["wall"], .02), y) for r, y in prof if y > d["base"] + 1e-3]
    inner_rings += [(inner_rings[-1][0], top_y + .3)]
    inner = loft("inner", inner_rings, sec)
    boolean_diff(outer, inner)
    bm = bmesh.new(); bm.from_mesh(outer.data)
    print("glass manifold:", all(e.is_manifold for e in bm.edges), len(bm.faces)); bm.free()
    outer.data.materials.clear(); outer.data.materials.append(mats["glass"])
    smooth(outer)
    parts.append(outer)
    # 2) 액체 자리(마스크용): 안쪽보다 조금 작게, 목 높이까지
    gap = .008
    liq = [(radius_at(prof, d["base"] + gap) - d["wall"] - gap, d["base"] + gap)]
    liq += [(max(r - d["wall"] - gap, .015), y) for r, y in prof if d["base"] + gap < y < d["neck"]]
    liq += [(max(radius_at(prof, d["neck"]) - d["wall"] - gap, .015), d["neck"])]
    liquid = loft("liquid", liq, sec)
    smooth(liquid)
    # 3) 마개·목 장식
    cap = d["cap"]
    if cap["kind"] == "gem":  # 연꽃 봉오리 같은 크리스털 마개(8면)
        g = loft("cap", [(.07, 0), (.17, .1), (.21, .24), (.15, .4), (.05, .5), (.001, .53)], ring(8, math.pi / 8))
        g.location.z = cap["y"]; g.data.materials.append(mats["gem"]); smooth(g, 20); parts.append(g)
    elif cap["kind"] == "cylinder":
        c = loft("cap", [(cap["r"] * .96, 0), (cap["r"], .02), (cap["r"], cap["h"] - .02), (cap["r"] * .96, cap["h"])], ring(96))
        c.location.z = cap["y"]; c.data.materials.append(mats[cap["metal"]]); smooth(c); parts.append(c)
    elif cap["kind"] == "dome":
        pts = [(cap["r"], 0)] + [(cap["r"] * math.cos(a), cap["h"] * .35 + cap["h"] * .65 * math.sin(a)) for a in [k * math.pi / 2 / 10 for k in range(11)]]
        c = loft("cap", pts, ring(96))
        c.location.z = cap["y"]; c.data.materials.append(mats[cap["metal"]]); smooth(c); parts.append(c)
    elif cap["kind"] == "box":
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, cap["y"] + cap["h"] / 2))
        c = bpy.context.active_object; c.name = "cap"
        c.scale = (cap["w"] * 2, cap["d"] * 2, cap["h"])
        bpy.ops.object.transform_apply(scale=True)
        bev = c.modifiers.new("bevel", "BEVEL"); bev.width = .035; bev.segments = 6
        c.data.materials.append(mats[cap["metal"]]); smooth(c, 40); parts.append(c)
    if "collar" in d:
        co = d["collar"]
        c = loft("collar", [(co["r"], 0), (co["r"], co["h"])], ring(96))
        c.location.z = co["y"]; c.data.materials.append(mats[co["metal"]]); smooth(c); parts.append(c)
    if "ribbon" in d:
        rb = d["ribbon"]
        bpy.ops.mesh.primitive_torus_add(major_radius=rb["r"], minor_radius=rb["tube"], location=(0, 0, rb["y"]),
                                         major_segments=96, minor_segments=24)
        t = bpy.context.active_object; t.data.materials.append(mats["gold"]); smooth(t); parts.append(t)
    return parts, liquid, top_y + (.53 if cap["kind"] == "gem" else cap.get("h", 0)), max(r for r, _ in prof)


def frame_camera(sc, height, width_r, px_h):
    cam_data = bpy.data.cameras.new("cam"); cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("cam", cam_data); bpy.context.collection.objects.link(cam)
    sc.camera = cam
    tilt = math.radians(4)  # 살짝 위에서 내려다봐 바닥·어깨의 둥근 면이 읽히게
    margin = 1.08
    h = height * margin + .12
    w = width_r * 2 * 1.05 * margin
    cam.location = (0, -12 * math.cos(tilt), height / 2 + 12 * math.sin(tilt))
    cam.rotation_euler = (math.pi / 2 - tilt, 0, 0)
    cam_data.ortho_scale = max(h, w)
    sc.render.resolution_y = px_h
    sc.render.resolution_x = int(round(px_h * w / h / 2) * 2)
    cam_data.sensor_fit = "VERTICAL"
    cam_data.ortho_scale = h
    sc.render.resolution_percentage = 100
    return cam


def render_design(design):
    sc = setup_scene()
    mats = materials()
    parts, liquid, height, width_r = build(design, mats)
    pivot = bpy.data.objects.new("pivot", None); bpy.context.collection.objects.link(pivot)
    for p in parts + [liquid]:
        p.parent = pivot
    # 단면이 납작한 병은 회전하면 폭이 넓어지므로 대각선까지 고려
    section = DESIGNS[design]["section"]
    reach = max(math.hypot(x, y) for x, y in section)
    frame_camera(sc, height, width_r * reach, opts["--height"])
    white = bpy.data.materials.new("mask"); white.use_nodes = True
    nt = white.node_tree; nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission"); em.inputs["Strength"].default_value = 1.0
    out = nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(em.outputs[0], out.inputs[0])
    liquid.data.materials.append(white)
    n, sweep = opts["--frames"], opts["--sweep"]
    for f in range(n):
        angle = -sweep + 2 * sweep * f / max(1, n - 1)
        pivot.rotation_euler = (0, 0, math.radians(angle))
        # 유리·마개
        liquid.hide_render = True
        for p in parts:
            p.hide_render = False
        sc.cycles.samples = opts["--samples"]
        sc.view_settings.view_transform = "Standard" if False else sc.view_settings.view_transform
        sc.render.filepath = f"{OUT}/{design}/glass_{f:02d}.png"
        bpy.ops.render.render(write_still=True)
        # 액체 자리
        liquid.hide_render = False
        for p in parts:
            p.hide_render = True
        sc.cycles.samples = 8
        sc.render.filepath = f"{OUT}/{design}/mask_{f:02d}.png"
        bpy.ops.render.render(write_still=True)
        print(f"{design} {f + 1}/{n}", flush=True)


for name in names or list(DESIGNS):
    render_design(name)
print("done")
