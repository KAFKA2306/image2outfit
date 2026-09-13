#!/usr/bin/env python3
"""Manufacture the Rainveil Cape-Skort Set for SiroinoSotai_PC."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

import genworks_product_common as g
import siroino_strappy_knit_build as base
from tuxedo_halter_runtime import normalize_bone_weights

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-rainveil-cape-skort-set"


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument("--job", required=True)
    return p.parse_args(raw)


def repo_path(value: str | Path) -> Path:
    p = Path(value)
    out = p.resolve() if p.is_absolute() else (ROOT / p).resolve()
    if out != ROOT and ROOT not in out.parents:
        raise ValueError(f"path escapes repository: {value}")
    return out


def mesh_object(name: str, vertices, faces, material) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    uv = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        poly.use_smooth = True
        for li in poly.loop_indices:
            co = mesh.vertices[mesh.loops[li].vertex_index].co
            uv.data[li].uv = ((co.x + 0.36) / 0.72, (co.z - 0.42) / 0.72)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    solid = obj.modifiers.new("Rainveil fabric thickness", "SOLIDIFY")
    solid.thickness = 0.0016
    solid.offset = 0.0
    bevel = obj.modifiers.new("Rainveil finished edge", "BEVEL")
    bevel.width = 0.0008
    bevel.segments = 2
    return obj


def panel_grid(name, side: int, front: bool, material):
    rows, cols = 12, 8
    verts, faces = [], []
    for r in range(rows + 1):
        t = r / rows
        z_center = 0.80 + 0.27 * t
        for c in range(cols + 1):
            u = c / cols
            xmag = 0.025 + 0.205 * u
            x = side * xmag
            side_drop = 0.25 * (u ** 2.2) * (1.0 - t)
            z = z_center - side_drop
            depth = 0.105 - 0.010 * t
            y = (-1 if front else 1) * (depth - 0.018 * u * u)
            verts.append((x, y, z))
    stride = cols + 1
    for r in range(rows):
        for c in range(cols):
            a = r * stride + c
            face = (a, a + 1, a + 1 + stride, a + stride)
            faces.append(face if (front == (side > 0)) else tuple(reversed(face)))
    return mesh_object(name, verts, faces, material)


def back_panel(material):
    rows, cols = 12, 16
    verts, faces = [], []
    for r in range(rows + 1):
        t = r / rows
        zc = 0.80 + 0.27 * t
        for c in range(cols + 1):
            u = c / cols
            x = -0.23 + 0.46 * u
            side = abs(x) / 0.23
            z = zc - 0.25 * (side ** 2.2) * (1.0 - t)
            y = 0.102 - 0.020 * side * side
            verts.append((x, y, z))
    stride = cols + 1
    for r in range(rows):
        for c in range(cols):
            a = r * stride + c
            faces.append((a + 1, a, a + stride, a + 1 + stride))
    return mesh_object("Rainveil_Cape_Back", verts, faces, material)


def flat_quad(name, points, material):
    return mesh_object(name, points, [(0, 1, 2, 3)], material)


def ellipse_tube(name, center_x: float, material):
    rings, segs = 5, 12
    verts, faces = [], []
    for r in range(rings):
        t = r / (rings - 1)
        z = 0.69 - 0.18 * t
        rx = 0.082 - 0.010 * t
        ry = 0.105 - 0.018 * t
        for s in range(segs):
            a = math.tau * s / segs
            verts.append((center_x + rx * math.cos(a), ry * math.sin(a), z))
    for r in range(rings - 1):
        for s in range(segs):
            n = (s + 1) % segs
            a, b = r * segs + s, r * segs + n
            c, d = (r + 1) * segs + n, (r + 1) * segs + s
            faces.append((a, b, c, d))
    return mesh_object(name, verts, faces, material)


def collar(material):
    segs = 20
    verts, faces = [], []
    for ring, z in enumerate((1.045, 1.100)):
        for s in range(segs):
            a = math.tau * s / segs
            verts.append((0.074 * math.cos(a), 0.061 * math.sin(a), z))
    for s in range(segs):
        n = (s + 1) % segs
        faces.append((s, n, segs + n, segs + s))
    return mesh_object("Rainveil_Stand_Collar", verts, faces, material)


def add_snap(index: int, x: float, z: float, material):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=0.007, location=(x, -0.132, z))
    obj = bpy.context.object
    obj.name = f"Rainveil_Snap_{index:02d}"
    obj.data.materials.append(material)
    return obj


def look_at(obj, target: Vector):
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def render_views(product_root: Path):
    out = product_root / "Previews"
    out.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 720
    scene.render.resolution_y = 960
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.object.light_add(type="AREA", location=(1.6, -1.8, 2.1))
    key = bpy.context.object
    key.data.energy = 900
    key.data.shape = "DISK"
    key.data.size = 4.0
    look_at(key, Vector((0, 0, 0.78)))
    bpy.ops.object.light_add(type="AREA", location=(-1.4, 1.2, 1.5))
    fill = bpy.context.object
    fill.data.energy = 550
    fill.data.size = 3.0
    look_at(fill, Vector((0, 0, 0.75)))
    bpy.ops.object.camera_add()
    cam = bpy.context.object
    scene.camera = cam
    target = Vector((0, 0, 0.76))
    views = {
        "front": (0.0, -2.45, 0.80),
        "back": (0.0, 2.45, 0.80),
        "left": (-2.45, 0.0, 0.80),
        "right": (2.45, 0.0, 0.80),
        "three-quarter": (1.72, -1.72, 0.86),
    }
    for name, position in views.items():
        cam.location = position
        look_at(cam, target)
        scene.render.filepath = str(out / f"{name}.png")
        bpy.ops.render.render(write_still=True)


def main() -> int:
    args = parse_args()
    job = json.loads(repo_path(args.job).read_text(encoding="utf-8"))
    if job.get("id") != PRODUCT_ID:
        raise ValueError("job product identity mismatch")
    base.clean_scene()
    source = repo_path(job["targetSourcePath"])
    root = repo_path(job["productRoot"])
    blend_path = repo_path(job["blendPath"])
    fbx_path = repo_path(job["fbxAssetPath"])
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    fbx_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body, armature = g.select_body_and_armature()
    armature.name = "SiroinoSotai_Armature"
    base.set_skin_material(body)

    cape_mat = base.plain_material("MAT_Rainveil_Cape", (0.159, 0.202, 0.230, 1.0), roughness=0.64)
    skort_mat = base.plain_material("MAT_Rainveil_Skort", (0.034, 0.037, 0.040, 1.0), roughness=0.68)
    trim_mat = base.plain_material("MAT_Rainveil_LiningTrim", (0.555, 0.484, 0.348, 1.0), roughness=0.60)
    metal_mat = base.plain_material("MAT_Rainveil_Hardware", (0.060, 0.070, 0.072, 1.0), roughness=0.34)
    metal_mat.metallic = 0.82

    garments = [
        panel_grid("Rainveil_Cape_Front_L", -1, True, cape_mat),
        panel_grid("Rainveil_Cape_Front_R", 1, True, cape_mat),
        back_panel(cape_mat),
        collar(trim_mat),
        ellipse_tube("Rainveil_Shorts_L", -0.080, skort_mat),
        ellipse_tube("Rainveil_Shorts_R", 0.080, skort_mat),
        flat_quad("Rainveil_Wrap_Front", [(-0.165,-0.122,0.695),(0.155,-0.122,0.695),(0.115,-0.124,0.505),(-0.055,-0.124,0.505)], skort_mat),
        flat_quad("Rainveil_Skirt_Back", [(-0.160,0.116,0.695),(0.160,0.116,0.695),(0.145,0.116,0.515),(-0.145,0.116,0.515)], skort_mat),
        flat_quad("Rainveil_Storm_Flap", [(-0.170,-0.132,1.040),(0.155,-0.132,0.930),(0.145,-0.132,0.885),(-0.185,-0.132,0.995)], cape_mat),
    ]
    snaps = [add_snap(i, -0.135 + i * 0.058, 1.015 - i * 0.020, metal_mat) for i in range(5)]
    garments.extend(snaps)

    for obj in garments[:4]:
        base.rigid_mesh_weight(obj, armature, "Chest" if "Collar" not in obj.name else "Neck")
    base.rigid_mesh_weight(garments[4], armature, "UpperLeg_L")
    base.rigid_mesh_weight(garments[5], armature, "UpperLeg_R")
    for obj in garments[6:9]:
        base.rigid_mesh_weight(obj, armature, "Hips" if "Storm" not in obj.name else "Chest")
    for obj in snaps:
        base.rigid_mesh_weight(obj, armature, "Chest")
    normalize_bone_weights(garments, armature)

    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    base.export_fbx(fbx_path, armature, garments)
    render_views(root)
    report = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "designRevision": "v1-panel-sewn-rainveil",
        "meshObjects": len(garments),
        "vertices": sum(len(o.data.vertices) for o in garments if o.type == "MESH"),
        "triangles": sum(sum(max(1, len(p.vertices)-2) for p in o.data.polygons) for o in garments if o.type == "MESH"),
        "uvLayers": {o.name: len(o.data.uv_layers) for o in garments if o.type == "MESH"},
        "materials": sorted({slot.material.name for o in garments if o.type == "MESH" for slot in o.material_slots if slot.material}),
        "weights": "normalized by canonical tuxedo_halter_runtime.normalize_bone_weights",
        "remaining": ["required pose render/penetration audit", "Unity import/save/reload", "VRChat runtime"],
    }
    evidence = root / "Evidence" / "Build"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "product-build-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
