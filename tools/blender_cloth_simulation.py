#!/usr/bin/env python3
"""Bake native Blender Cloth evidence for one GenWorks outfit.

This script runs inside the pinned Blender runtime. It intentionally uses the
native Cloth API so the cache and settled mesh can be reproduced without an
unversioned third-party add-on.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bmesh
import bpy


ROOT = Path(__file__).resolve().parents[1]

COMPONENTS: dict[str, tuple[str, ...]] = {
    "siroino-cyber-kawaii-large": (
        "Black_Pink_Plaid_Pleated_Skirt",
        "White_Ruffle_Underskirt",
    ),
    "siroino-heather-hooded-bodysuit": ("Heather_Hood_Folded_Roll",),
    "siroino-lace-halter-large": ("Long_Sheer_Front_Panel",),
    "siroino-military-sheer-romper-large": (
        "Military_Asymmetric_Front_Flap",
        "Military_Sheer_Back",
    ),
    "siroino-nocturne-angel-set": ("Nocturne_Cloth_Skirt",),
    "siroino-wide-cargo": ("Cargo_Continuous_Pants",),
}

FRAME_END = {
    "siroino-cyber-kawaii-large": 24,
    "siroino-heather-hooded-bodysuit": 18,
    "siroino-lace-halter-large": 24,
    "siroino-military-sheer-romper-large": 20,
    "siroino-nocturne-angel-set": 24,
    "siroino-wide-cargo": 18,
}


def parse_args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(values)


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"path escapes repository: {value}")
    return resolved


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def mesh_hash(obj: bpy.types.Object, *, evaluated: bool = False) -> str:
    evaluated_object = None
    mesh = obj.data
    if evaluated:
        evaluated_object = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated_object.to_mesh()
    try:
        payload = {
            "vertices": [
                [round(float(value), 7) for value in vertex.co]
                for vertex in mesh.vertices
            ],
            "polygons": [list(polygon.vertices) for polygon in mesh.polygons],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    finally:
        if evaluated_object is not None:
            evaluated_object.to_mesh_clear()


def find_object(name: str) -> bpy.types.Object:
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "MESH":
        raise RuntimeError(f"required cloth mesh is missing: {name}")
    return obj


def find_body(product_id: str, names: tuple[str, ...]) -> bpy.types.Object:
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and (
            obj.name.startswith("SiroinoSotai_PC")
            or obj.name.startswith("SiroinoSotai_Large_ValidationBody")
        ):
            return obj
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12)
    proxy = bpy.context.object
    proxy.name = "Image2Outfit Collision Proxy"
    selected = [find_object(name) for name in names]
    coordinates = [
        obj.matrix_world @ vertex.co for obj in selected for vertex in obj.data.vertices
    ]
    minimum = [min(point[index] for point in coordinates) for index in range(3)]
    maximum = [max(point[index] for point in coordinates) for index in range(3)]
    centre = tuple((minimum[index] + maximum[index]) * 0.5 for index in range(3))
    span = [max(0.02, maximum[index] - minimum[index]) for index in range(3)]
    proxy.location = centre
    proxy.scale = (span[0] * 0.55, span[1] * 0.55, span[2] * 0.55)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    proxy.hide_render = True
    proxy.display_type = "WIRE"
    proxy["image2outfit_role"] = "cloth-collision-proxy"
    return proxy


def pin_vertices(obj: bpy.types.Object) -> list[int]:
    coordinates = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    if len(coordinates) < 4:
        raise RuntimeError(f"cloth mesh is too small to pin: {obj.name}")
    minimum = min(point.z for point in coordinates)
    maximum = max(point.z for point in coordinates)
    threshold = maximum - max(1e-6, maximum - minimum) * 0.16
    selected = [
        vertex.index
        for vertex, point in zip(obj.data.vertices, coordinates)
        if point.z >= threshold
    ]
    if len(selected) < 2:
        ordered = sorted(
            obj.data.vertices, key=lambda vertex: vertex.co.z, reverse=True
        )
        selected = [vertex.index for vertex in ordered[: max(2, len(ordered) // 20)]]
    if len(selected) >= len(obj.data.vertices):
        selected = [
            vertex.index
            for vertex in sorted(
                obj.data.vertices, key=lambda vertex: vertex.co.z, reverse=True
            )[:2]
        ]
    return selected


def ensure_collision(body: bpy.types.Object) -> None:
    if not any(modifier.type == "COLLISION" for modifier in body.modifiers):
        body.modifiers.new("Image2Outfit Body Collision", "COLLISION")
    body.collision.thickness_outer = 0.004
    body.collision.damping = 0.5


def configure_cloth(obj: bpy.types.Object, frame_end: int) -> dict[str, object]:
    for modifier in list(obj.modifiers):
        if modifier.name.startswith("Image2Outfit Cloth"):
            obj.modifiers.remove(modifier)
    pin = obj.vertex_groups.get("Image2Outfit Cloth Pin")
    if pin is None:
        pin = obj.vertex_groups.new(name="Image2Outfit Cloth Pin")
    else:
        pin.remove(range(len(obj.data.vertices)))
    vertices = pin_vertices(obj)
    pin.add(vertices, 1.0, "REPLACE")
    cloth = obj.modifiers.new("Image2Outfit Cloth", "CLOTH")
    cloth.settings.quality = 6
    cloth.settings.mass = 0.20
    cloth.settings.tension_stiffness = 25.0
    cloth.settings.compression_stiffness = 25.0
    cloth.settings.shear_stiffness = 10.0
    cloth.settings.bending_stiffness = 0.45
    cloth.settings.air_damping = 3.0
    cloth.settings.vertex_group_mass = pin.name
    cloth.settings.pin_stiffness = 1.0
    cloth.collision_settings.use_collision = True
    cloth.collision_settings.collision_quality = 5
    cloth.collision_settings.distance_min = 0.003
    if hasattr(cloth.collision_settings, "use_self_collision"):
        cloth.collision_settings.use_self_collision = False
    cloth.point_cache.frame_start = 1
    cloth.point_cache.frame_end = frame_end
    return {
        "object": obj.name,
        "modifier": cloth.name,
        "pinVertexCount": len(vertices),
        "frameStart": 1,
        "frameEnd": frame_end,
    }


def bake_components(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    names: tuple[str, ...],
    frame_end: int,
) -> list[dict[str, object]]:
    objects = [find_object(name) for name in names]
    ensure_collision(body)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = frame_end
    scene.gravity = (0.0, 0.0, -4.5)
    contracts = []
    before = {}
    for obj in objects:
        before[obj.name] = mesh_hash(obj)
        contracts.append(configure_cloth(obj, frame_end))
    bpy.ops.object.select_all(action="DESELECT")
    objects[0].select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.ptcache.bake_all(bake=True)
    scene.frame_set(frame_end)
    bpy.context.view_layer.update()
    for contract, obj in zip(contracts, objects):
        cloth = obj.modifiers.get("Image2Outfit Cloth")
        if cloth is None or not cloth.point_cache.is_baked:
            raise RuntimeError(f"Blender cloth cache did not bake: {obj.name}")
        contract.update(
            {
                "cacheBakedActual": True,
                "cacheInfo": str(cloth.point_cache.info or ""),
                "preBakeMeshSha256": before[obj.name],
                "evaluatedFrameMeshSha256": mesh_hash(obj, evaluated=True),
            }
        )
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        if obj.data.shape_keys is not None:
            bpy.ops.object.convert(target="MESH", keep_original=False)
            if not any(modifier.type == "ARMATURE" for modifier in obj.modifiers):
                armature_modifier = obj.modifiers.new(
                    "SiroinoSotai Armature", "ARMATURE"
                )
                armature_modifier.object = armature
        else:
            bpy.ops.object.modifier_apply(modifier=cloth.name)
        settled = mesh_hash(obj)
        sanitize_mesh(obj)
        settled = mesh_hash(obj)
        contract["settledMeshSha256"] = settled
        contract["geometryChanged"] = settled != before[obj.name]
        if not contract["geometryChanged"]:
            raise RuntimeError(f"cloth solve did not change mesh geometry: {obj.name}")
        obj.select_set(False)
    return contracts


def sanitize_mesh(obj: bpy.types.Object) -> None:
    if obj.type != "MESH":
        return
    mesh = obj.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        if bm.verts:
            bmesh.ops.dissolve_degenerate(
                bm,
                dist=1e-7,
                edges=list(bm.edges),
            )
        bm.faces.ensure_lookup_table()
        degenerate = [face for face in bm.faces if face.calc_area() <= 1e-12]
        if degenerate:
            bmesh.ops.delete(bm, geom=degenerate, context="FACES")
            bm.faces.ensure_lookup_table()
        if bm.faces:
            bmesh.ops.triangulate(bm, faces=list(bm.faces))
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update(calc_edges=True)
    mesh.validate(verbose=False, clean_customdata=False)


def export_settled_fbx(
    path: Path, armature: bpy.types.Object, objects: list[bpy.types.Object]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.fbx(
        filepath=str(path),
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        apply_scale_options="FBX_SCALE_ALL",
        use_space_transform=True,
        bake_space_transform=False,
        mesh_smooth_type="OFF",
        use_subsurf=False,
        use_mesh_modifiers=True,
        use_mesh_edges=False,
        use_tspace=False,
        use_armature_deform_only=True,
        add_leaf_bones=False,
        primary_bone_axis="Y",
        secondary_bone_axis="X",
        armature_nodetype="NULL",
        bake_anim=False,
        apply_unit_scale=True,
        path_mode="RELATIVE",
        embed_textures=False,
    )


def main() -> int:
    options = parse_args()
    job = read_json(repo_path(options.job))
    product_id = str(job.get("id", ""))
    if product_id not in COMPONENTS:
        raise ValueError(f"no cloth component contract for {product_id}")
    report_path = (
        repo_path(str(job["productRoot"]))
        / "Evidence"
        / "Build"
        / "cloth-simulation.json"
    )
    fbx = repo_path(str(job["fbxAssetPath"]))
    if not options.force and report_path.is_file() and fbx.is_file():
        existing = read_json(report_path)
        if (
            existing.get("status") == "PASS"
            and existing.get("blenderVersion") == "4.4.3"
            and existing.get("cacheBaked") is True
        ):
            print(json.dumps(existing, ensure_ascii=False, indent=2))
            return 0
    blend = repo_path(str(job["blendPath"]))
    bpy.ops.wm.open_mainfile(filepath=str(blend), load_ui=False)
    armature = next(
        (obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"), None
    )
    if armature is None:
        raise RuntimeError("Siroino armature is missing")
    names = COMPONENTS[product_id]
    body = find_body(product_id, names)
    contracts = bake_components(body, armature, names, FRAME_END[product_id])
    objects = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        and obj.name != body.name
        and obj.name != "Image2Outfit Collision Proxy"
        and "floor" not in obj.name.lower()
    ]
    for obj in objects:
        sanitize_mesh(obj)
    bpy.ops.wm.save_as_mainfile(
        filepath=str(blend), check_existing=False, compress=True
    )
    export_settled_fbx(fbx, armature, objects)
    report = {
        "schemaVersion": 1,
        "productId": product_id,
        "status": "PASS",
        "engine": "Blender Cloth",
        "blenderVersion": bpy.app.version_string,
        "applicability": "REQUIRED",
        "frameStart": 1,
        "frameEnd": FRAME_END[product_id],
        "cacheBaked": all(bool(item.get("cacheBakedActual")) for item in contracts),
        "geometryChanged": all(bool(item.get("geometryChanged")) for item in contracts),
        "gravity": list(bpy.context.scene.gravity),
        "contracts": contracts,
        "bodyCollisionThicknessM": 0.004,
        "collisionObject": body.name,
        "settledFbx": str(fbx.relative_to(ROOT)).replace("\\", "/"),
    }
    write_json(report_path, report)
    build_report = (
        repo_path(str(job["productRoot"]))
        / "Evidence"
        / "Build"
        / "product-build-report.json"
    )
    if build_report.is_file():
        current = read_json(build_report)
        current["clothSimulation"] = str(report_path.relative_to(ROOT)).replace(
            "\\", "/"
        )
        current["blenderVersion"] = bpy.app.version_string
        write_json(build_report, current)
    manifest_path = repo_path(str(job["productManifestPath"]))
    if manifest_path.is_file():
        manifest = read_json(manifest_path)
        gates = manifest.get("technicalGates")
        if isinstance(gates, dict):
            gates["clothSimulation"] = "PASS"
        outputs = manifest.get("outputs")
        if isinstance(outputs, dict):
            outputs["clothSimulation"] = str(report_path.relative_to(ROOT)).replace(
                "\\", "/"
            )
        report_relative = str(report_path.relative_to(ROOT)).replace("\\", "/")
        if isinstance(manifest.get("clothSimulation"), list):
            manifest["clothSimulationEvidence"] = report_relative
        else:
            manifest["clothSimulation"] = report_relative
        write_json(manifest_path, manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
