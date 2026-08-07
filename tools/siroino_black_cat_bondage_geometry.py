#!/usr/bin/env python3
"""Deterministic Blender build for siroino-black-cat-bondage."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

PRODUCT_ID = "siroino-black-cat-bondage"


def args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(values)


def path(value: str) -> Path:
    return (Path.cwd() / value).resolve()


def clean() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def mat(name: str, rgba: tuple[float, float, float, float], metallic=0.0, roughness=0.4):
    value = bpy.data.materials.new(name)
    value.use_nodes = True
    bsdf = value.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    return value


def mesh(name, vertices, faces, material, thickness=0.002):
    data = bpy.data.meshes.new(name)
    data.from_pydata(vertices, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    solid = obj.modifiers.new("Garment Solidify", "SOLIDIFY")
    solid.thickness = thickness
    solid.offset = 0.0
    bevel = obj.modifiers.new("Garment Bevel", "BEVEL")
    bevel.width = 0.001
    bevel.segments = 2
    return obj


def cube(name, location, scale, material, rotation=(0.0, 0.0, 0.0), bevel=0.002):
    bpy.ops.mesh.primitive_cube_add(location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    if bevel:
        mod = obj.modifiers.new("Edge Bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 2
    return obj


def torus(name, location, major, minor, material, rotation=(math.pi / 2.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_torus_add(
        major_radius=major,
        minor_radius=minor,
        major_segments=32,
        minor_segments=8,
        location=location,
        rotation=rotation,
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def line(name, points, radius, material, cyclic=False):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    data.bevel_depth = radius
    data.bevel_resolution = 2
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for target, value in zip(spline.points, points):
        target.co = (*value, 1.0)
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def import_avatar(job):
    source = path(job["targetSourcePath"])
    if not source.is_file():
        return []
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=True)
    imported = [obj for obj in bpy.data.objects if obj not in before]
    for obj in imported:
        obj["image2outfitRole"] = "target-avatar"
    return [obj.name for obj in imported]


def build(leather, fabric, metal):
    result = []
    edges = (-0.165, -0.095, -0.035, 0.035, 0.095, 0.165)
    for i, (x0, x1) in enumerate(zip(edges, edges[1:])):
        xc = (x0 + x1) / 2
        y = -0.092 - 0.030 * (1 - abs(xc) / 0.165)
        z0 = 0.760 + 0.020 * abs(xc) / 0.165
        z1 = 1.005 - 0.055 * abs(xc) / 0.165
        result.append(mesh(f"Corset_Front_{i:02d}", [(x0,y,z0),(x1,y,z0),(x1,y,z1),(x0,y,z1)], [(0,1,2,3)], leather))
    result += [
        cube("Corset_Back", (0,0.092,0.875), (0.158,0.012,0.112), leather),
        cube("Corset_Top_Binding", (0,-0.112,1.002), (0.170,0.009,0.009), fabric),
        cube("Corset_Bottom_Binding", (0,-0.112,0.762), (0.170,0.009,0.009), fabric),
    ]
    for sign, side in ((-1,"L"),(1,"R")):
        result.append(mesh(
            f"Bust_Cup_{side}",
            [(sign*0.020,-0.126,0.935),(sign*0.148,-0.102,0.930),
             (sign*0.128,-0.112,1.045),(sign*0.045,-0.132,1.060)],
            [(0,1,2,3)], leather
        ))
        result.append(line(f"Shoulder_Strap_{side}",
            [(sign*0.085,-0.110,1.030),(sign*0.130,-0.015,1.115),(sign*0.100,0.080,1.020)],0.007,leather))
        result.append(line(f"Chest_Harness_{side}",
            [(0,-0.073,1.120),(sign*0.085,-0.125,1.020),(sign*0.145,-0.100,0.955)],0.005,leather))
    eyelet_z = [0.785 + i*0.036 for i in range(7)]
    for row, z in enumerate(eyelet_z):
        for sign, side in ((-1,"L"),(1,"R")):
            result.append(torus(f"Eyelet_{side}_{row:02d}",(sign*0.023,-0.132,z),0.008,0.0018,metal))
    for row, (z0, z1) in enumerate(zip(eyelet_z, eyelet_z[1:])):
        result.append(line(f"Lace_A_{row:02d}",[(-0.023,-0.136,z0),(0.023,-0.136,z1)],0.0022,leather))
        result.append(line(f"Lace_B_{row:02d}",[(0.023,-0.137,z0),(-0.023,-0.137,z1)],0.0022,leather))
    result += [
        torus("Choker",(0,-0.002,1.145),0.057,0.008,leather,(0,0,0)),
        torus("Choker_Ring",(0,-0.066,1.120),0.015,0.003,metal),
        torus("Waist_Belt",(0,0,0.720),0.175,0.010,leather,(0,0,0)),
    ]
    count, rt, rb, zt, zb = 24, 0.166, 0.235, 0.710, 0.555
    for i in range(count):
        a0, a1 = math.tau*i/count, math.tau*(i+1)/count
        ridge = 0.010 if i%2 == 0 else -0.006
        verts = [(rt*math.cos(a0),rt*math.sin(a0),zt),(rt*math.cos(a1),rt*math.sin(a1),zt),
                 ((rb+ridge)*math.cos(a1),(rb+ridge)*math.sin(a1),zb),
                 ((rb+ridge)*math.cos(a0),(rb+ridge)*math.sin(a0),zb)]
        result.append(mesh(f"Skirt_Pleat_{i:02d}",verts,[(0,1,2,3)],fabric,0.0015))
    ring_x = (-0.135,-0.080,-0.025,0.030,0.085,0.140)
    for i, x in enumerate(ring_x):
        result.append(torus(f"Waist_Ring_{i:02d}",(x,-0.183,0.700),0.022,0.0035,metal))
        if i < len(ring_x)-1:
            x2 = ring_x[i+1]
            result.append(line(f"Waist_Chain_{i:02d}",[(x,-0.187,0.680),((x+x2)/2,-0.192,0.645),(x2,-0.187,0.680)],0.002,metal))
    for sign, side in ((-1,"L"),(1,"R")):
        x = sign*0.275
        result += [
            torus(f"UpperArm_Band_{side}",(x,0,0.995),0.050,0.010,leather,(0,math.pi/2,0)),
            cube(f"Gauntlet_{side}",(x,-0.005,0.800),(0.046,0.035,0.145),leather,bevel=0.009),
            torus(f"Gauntlet_Ring_{side}",(x,-0.045,0.805),0.013,0.003,metal),
            torus(f"Thigh_Garter_{side}",(sign*0.115,0,0.445),0.082,0.008,leather,(0,math.pi/2,0)),
            line(f"Thigh_Chain_{side}",[(sign*0.150,-0.030,0.510),(sign*0.185,-0.090,0.470),(sign*0.150,-0.090,0.420)],0.002,metal),
        ]
        for j, z in enumerate((0.710,0.770,0.835,0.900)):
            result.append(torus(f"Gauntlet_Strap_{side}_{j}",(x,-0.004,z),0.050,0.004,fabric,(0,math.pi/2,0)))
    result.append(torus("CatEar_Headband",(0,0,1.455),0.115,0.008,leather,(0,0,0)))
    for sign, side in ((-1,"L"),(1,"R")):
        x = sign*0.065
        outer=[(x-sign*0.055,-0.015,1.455),(x+sign*0.055,-0.015,1.455),(x,-0.010,1.575)]
        inner=[(x-sign*0.035,-0.020,1.468),(x+sign*0.035,-0.020,1.468),(x,-0.018,1.545)]
        result += [mesh(f"CatEar_Outer_{side}",outer,[(0,1,2)],leather,0.003),
                   mesh(f"CatEar_Inner_{side}",inner,[(0,1,2)],fabric,0.0015)]
    return result


def bind(objects):
    arms = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if not arms:
        return None
    arm = next((obj for obj in arms if "Siroino" in obj.name), arms[0])
    for obj in objects:
        if obj.type == "MESH":
            mod = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
            mod.object = arm
            mod.use_deform_preserve_volume = True
    return arm.name


def camera():
    bpy.ops.object.light_add(type="AREA", location=(2.5,-3.5,3.0))
    bpy.context.object.data.energy = 900
    bpy.context.object.data.size = 3
    bpy.ops.object.light_add(type="AREA", location=(-2,-1,2))
    bpy.context.object.data.energy = 450
    bpy.context.object.data.size = 2
    bpy.ops.object.camera_add(location=(0,-3.3,1.05))
    cam = bpy.context.object
    cam.data.lens = 58
    cam.rotation_euler = (Vector((0,0,0.95))-cam.location).to_track_quat("-Z","Y").to_euler()
    bpy.context.scene.camera = cam


def main() -> int:
    job = json.loads(path(args().job).read_text(encoding="utf-8"))
    if job.get("id") != PRODUCT_ID:
        raise RuntimeError(f"job id must be {PRODUCT_ID}")
    clean()
    imported = import_avatar(job)
    leather = mat("BCB_FauxLeather",(0.012,0.014,0.018,1),0.05,0.22)
    fabric = mat("BCB_MatteFabric",(0.025,0.022,0.028,1),0.0,0.62)
    metal = mat("BCB_DarkMetal",(0.12,0.13,0.15,1),0.92,0.20)
    objects = build(leather,fabric,metal)
    armature = bind(objects)
    for obj in objects:
        obj["productId"], obj["targetAvatar"], obj["sourceRedistributed"] = PRODUCT_ID, "SiroinoSotai_PC", False
    camera()
    blend, fbx = path(job["blendPath"]), path(job["fbxAssetPath"])
    preview, report = path(job["previewPaths"]["front"]), path(job["buildReportPath"])
    for target in (blend,fbx,preview,report):
        target.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.export_scene.fbx(filepath=str(fbx),use_selection=True,apply_unit_scale=True,add_leaf_bones=False)
    scene = bpy.context.scene
    scene.render.engine, scene.render.resolution_x, scene.render.resolution_y = "BLENDER_EEVEE_NEXT", 768, 1024
    scene.render.resolution_percentage, scene.render.film_transparent = 100, True
    scene.render.image_settings.file_format, scene.render.filepath = "PNG", str(preview)
    bpy.ops.render.render(write_still=True)
    result = {
        "schemaVersion":1,"productId":PRODUCT_ID,"status":"WORKING","objectCount":len(objects),
        "armatureResolved":armature,"importedTargetObjects":imported,
        "blendPath":job["blendPath"],"fbxAssetPath":job["fbxAssetPath"],
        "renderedPreview":job["previewPaths"]["front"],
        "pending":["bone-weight transfer audit","five-view render set","six-pose penetration review",
                   "Unity prefab and Modular Avatar integration","direct visual review"],
    }
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
