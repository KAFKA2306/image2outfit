#!/usr/bin/env python3
"""Fit the military sheer-back romper to the actual SiroinoSotai_PC body."""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
from PIL import Image, ImageDraw

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_military_sheer_romper_refine as legacy  # noqa: E402

base = legacy.base
PRODUCT_ID = "siroino-military-sheer-romper-large"
PRODUCT_NAME = "Military Sheer-Back Romper for Siroino _Large"
REVISION = "siroino-pc-surface-fit-v7"
SHAPE_KEYS = (
    "All_Slim",
    "Chest_Slim",
    "Hips_Slim",
    "UpperLeg_Slim",
    "Breasts_flat",
    "All_M",
    "Chest_M",
    "All_L",
    "Chest_L",
    "Hips_01_L",
    "UpperLeg_L",
    "Breasts_L",
    "Breasts_LL",
    "Breasts_LLL",
    "Breasts_In",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def repo_path(value: str) -> Path:
    return base.repo_path(value)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def profile(job: dict) -> dict[str, float]:
    return {
        str(name): float(value)
        for name, value in job.get("bodyShapeProfile", {}).items()
    }


def set_shape_values(obj: bpy.types.Object, values: dict[str, float]) -> None:
    keys = getattr(obj.data, "shape_keys", None)
    if keys is None:
        return
    for key in keys.key_blocks:
        key.value = values.get(key.name, 0.0)


def import_target(job: dict) -> tuple[bpy.types.Object, bpy.types.Object, list[bpy.types.Object]]:
    source = repo_path(job["targetSourcePath"])
    if not source.is_file():
        raise FileNotFoundError(
            f"SiroinoSotai_PC source is required for target fitting: {source}"
        )
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    imported = [obj for obj in bpy.data.objects if obj not in before]
    armatures = [obj for obj in imported if obj.type == "ARMATURE"]
    meshes = [obj for obj in imported if obj.type == "MESH"]
    if not armatures or not meshes:
        raise RuntimeError("SiroinoSotai_PC import did not produce an armature and meshes")
    armature = max(
        armatures,
        key=lambda obj: sum(len(child.data.vertices) for child in obj.children if child.type == "MESH"),
    )
    preferred = [
        obj for obj in meshes
        if obj.name.startswith("SiroinoSotai_PC") and len(obj.data.vertices) > 0
    ]
    body = max(preferred or meshes, key=lambda obj: len(obj.data.vertices))
    armature.name = "SiroinoSotai_Armature"
    body["image2outfit_role"] = "target-avatar"
    body["image2outfit_target_source"] = job["targetSourcePath"]
    for obj in meshes:
        if obj is not body:
            obj.hide_render = True
            obj.hide_viewport = True
            obj["image2outfit_role"] = "target-avatar-hidden"
    return body, armature, imported


def make_skin_material() -> bpy.types.Material:
    material = base.simple_material(
        "MAT_SiroinoSotai_Review_Skin",
        (0.73, 0.47, 0.34, 1.0),
        0.55,
    )
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader is not None and "Subsurface Weight" in shader.inputs:
        shader.inputs["Subsurface Weight"].default_value = 0.06
    return material


def assign_review_skin(body: bpy.types.Object) -> None:
    body.data.materials.clear()
    body.data.materials.append(make_skin_material())


def clean_mesh(obj: bpy.types.Object) -> None:
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    bmesh.ops.remove_doubles(mesh, verts=list(mesh.verts), dist=1e-7)
    bmesh.ops.dissolve_degenerate(mesh, edges=list(mesh.edges), dist=1e-8)
    if mesh.faces:
        bmesh.ops.recalc_face_normals(mesh, faces=list(mesh.faces))
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.update(calc_edges=True)


def transfer_nearest_weights(
    obj: bpy.types.Object,
    body: bpy.types.Object,
) -> list[int]:
    tree = KDTree(len(body.data.vertices))
    for vertex in body.data.vertices:
        tree.insert(body.matrix_world @ vertex.co, vertex.index)
    tree.balance()
    groups = {
        group.name: obj.vertex_groups.new(name=group.name)
        for group in body.vertex_groups
    }
    nearest: list[int] = []
    for vertex in obj.data.vertices:
        world = obj.matrix_world @ vertex.co
        _, source_index, _ = tree.find(world)
        nearest.append(source_index)
        assignments = body.data.vertices[source_index].groups
        total = sum(item.weight for item in assignments)
        if total <= 0.0:
            continue
        for assignment in assignments:
            source_group = body.vertex_groups[assignment.group]
            groups[source_group.name].add(
                [vertex.index],
                assignment.weight / total,
                "REPLACE",
            )
    return nearest


def add_nearest_shape_keys(
    obj: bpy.types.Object,
    body: bpy.types.Object,
    nearest: list[int],
    values: dict[str, float],
) -> None:
    source_keys = getattr(body.data, "shape_keys", None)
    if source_keys is None:
        return
    source_basis = source_keys.key_blocks.get("Basis")
    if source_basis is None:
        return
    obj.shape_key_add(name="Basis")
    inverse = obj.matrix_world.inverted()
    for name in SHAPE_KEYS:
        source_key = source_keys.key_blocks.get(name)
        if source_key is None:
            continue
        target_key = obj.shape_key_add(name=name)
        for vertex, source_index in zip(obj.data.vertices, nearest):
            basis_world = body.matrix_world @ source_basis.data[source_index].co
            key_world = body.matrix_world @ source_key.data[source_index].co
            target_key.data[vertex.index].co = (
                vertex.co + inverse.to_3x3() @ (key_world - basis_world)
            )
        target_key.value = values.get(name, 0.0)


def finish_skinned(
    obj: bpy.types.Object,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    values: dict[str, float],
    *,
    fit_audit: bool,
) -> bpy.types.Object:
    clean_mesh(obj)
    nearest = transfer_nearest_weights(obj, body)
    add_nearest_shape_keys(obj, body, nearest, values)
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    obj["image2outfit_role"] = "garment"
    obj["image2outfit_fit_audit"] = fit_audit
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def extract_surface(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    name: str,
    predicate: Callable[[Vector], bool],
    material: bpy.types.Material,
    values: dict[str, float],
    *,
    offset: float,
    thickness: float,
    fit_audit: bool = True,
) -> bpy.types.Object:
    source_uv = body.data.uv_layers.active
    used: dict[int, int] = {}
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    face_uvs: list[list[tuple[float, float]]] = []
    for polygon in body.data.polygons:
        center = body.matrix_world @ polygon.center
        if not predicate(center):
            continue
        face: list[int] = []
        uvs: list[tuple[float, float]] = []
        for loop_index in polygon.loop_indices:
            source_index = body.data.loops[loop_index].vertex_index
            if source_index not in used:
                source = body.data.vertices[source_index]
                used[source_index] = len(vertices)
                vertices.append(tuple(source.co + source.normal.normalized() * offset))
            face.append(used[source_index])
            if source_uv is not None:
                uv = source_uv.data[loop_index].uv
                uvs.append((float(uv.x), float(uv.y)))
            else:
                uvs.append((0.0, 0.0))
        faces.append(face)
        face_uvs.append(uvs)
    if not faces:
        raise RuntimeError(f"target surface selection produced no faces: {name}")
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon, uvs in zip(mesh.polygons, face_uvs):
        for loop_index, uv in zip(polygon.loop_indices, uvs):
            uv_layer.data[loop_index].uv = uv
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.matrix_world = body.matrix_world.copy()
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    solidify = obj.modifiers.new("Fabric thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 1.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    bevel = obj.modifiers.new("Finished edge", "BEVEL")
    bevel.width = min(0.0012, thickness * 0.45)
    bevel.segments = 2
    bevel.limit_method = "ANGLE"
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    return finish_skinned(
        obj,
        body,
        armature,
        values,
        fit_audit=fit_audit,
    )


def add_box(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    material: bpy.types.Material,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    values: dict[str, float],
    *,
    bevel: float = 0.004,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    if bevel > 0.0:
        modifier = obj.modifiers.new("Rounded edges", "BEVEL")
        modifier.width = bevel
        modifier.segments = 3
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    return finish_skinned(
        obj,
        body,
        armature,
        values,
        fit_audit=False,
    )


def add_button(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    material: bpy.types.Material,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    values: dict[str, float],
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    return finish_skinned(
        obj,
        body,
        armature,
        values,
        fit_audit=False,
    )


def add_chain(
    name: str,
    points: list[tuple[float, float, float]],
    material: bpy.types.Material,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    values: dict[str, float],
) -> bpy.types.Object:
    curve = bpy.data.curves.new(f"{name}_Curve", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.0034
    curve.bevel_resolution = 3
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for point, coordinate in zip(spline.bezier_points, points):
        point.co = coordinate
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.convert(target="MESH")
    return finish_skinned(
        bpy.context.object,
        body,
        armature,
        values,
        fit_audit=False,
    )


def build_outfit(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    sheer: bpy.types.Material,
    gold: bpy.types.Material,
    values: dict[str, float],
) -> list[bpy.types.Object]:
    objects: list[bpy.types.Object] = []
    objects.append(
        extract_surface(
            body,
            armature,
            "Military_Opaque_Bodice",
            lambda co: (
                0.72 <= co.z <= 1.235
                and (
                    co.y <= 0.012
                    or co.z <= 0.825
                    or abs(co.x) >= 0.165
                )
            ),
            fabric,
            values,
            offset=0.0085,
            thickness=0.0022,
        )
    )
    objects.append(
        extract_surface(
            body,
            armature,
            "Military_Sheer_Back",
            lambda co: (
                0.815 <= co.z <= 1.225
                and co.y > 0.005
                and abs(co.x) < 0.205
            ),
            sheer,
            values,
            offset=0.0090,
            thickness=0.0007,
        )
    )
    objects.append(
        extract_surface(
            body,
            armature,
            "Military_Romper_Lower",
            lambda co: 0.445 <= co.z <= 0.795 and abs(co.x) <= 0.245,
            fabric,
            values,
            offset=0.0105,
            thickness=0.0024,
        )
    )
    objects.append(
        extract_surface(
            body,
            armature,
            "Military_Asymmetric_Front_Flap",
            lambda co: (
                0.465 <= co.z <= 0.785
                and co.y < -0.01
                and co.x <= 0.13
            ),
            fabric,
            values,
            offset=0.0155,
            thickness=0.0020,
        )
    )
    objects.append(
        extract_surface(
            body,
            armature,
            "Military_Standing_Collar",
            lambda co: (
                1.215 <= co.z <= 1.335
                and abs(co.x) <= 0.125
                and abs(co.y) <= 0.105
            ),
            fabric,
            values,
            offset=0.0075,
            thickness=0.0020,
        )
    )
    for side, sign in (("L", 1.0), ("R", -1.0)):
        objects.append(
            extract_surface(
                body,
                armature,
                f"Military_Sleeve_{side}",
                lambda co, sign=sign: (
                    0.99 <= co.z <= 1.285
                    and sign * co.x >= 0.17
                    and sign * co.x <= 0.48
                ),
                fabric,
                values,
                offset=0.0085,
                thickness=0.0020,
            )
        )
    objects.append(
        extract_surface(
            body,
            armature,
            "Military_Waist_Belt",
            lambda co: 0.735 <= co.z <= 0.782 and abs(co.x) <= 0.235,
            fabric,
            values,
            offset=0.0140,
            thickness=0.0028,
            fit_audit=False,
        )
    )

    for side, sign in (("L", 1.0), ("R", -1.0)):
        objects.append(
            add_box(
                f"Military_Epaulette_{side}",
                (sign * 0.205, -0.004, 1.245),
                (0.082, 0.048, 0.009),
                fabric,
                body,
                armature,
                values,
            )
        )
        objects.append(
            add_button(
                f"Military_Epaulette_Button_{side}",
                (sign * 0.215, -0.055, 1.255),
                (0.014, 0.008, 0.014),
                gold,
                body,
                armature,
                values,
            )
        )
    objects.append(
        add_box(
            "Military_Gold_Nameplate",
            (0.082, -0.143, 1.055),
            (0.052, 0.007, 0.016),
            gold,
            body,
            armature,
            values,
            bevel=0.005,
        )
    )
    objects.append(
        add_box(
            "Military_Belt_Buckle",
            (0.042, -0.148, 0.758),
            (0.032, 0.008, 0.034),
            gold,
            body,
            armature,
            values,
            bevel=0.005,
        )
    )
    for index, (x, z) in enumerate(
        ((-0.12, 1.19), (-0.105, 1.08), (-0.078, 0.93)),
        start=1,
    ):
        objects.append(
            add_button(
                f"Military_Front_Button_{index}",
                (x, -0.143, z),
                (0.012, 0.007, 0.012),
                gold,
                body,
                armature,
                values,
            )
        )
    for index, points in enumerate(
        (
            [(0.205, -0.065, 1.245), (0.245, -0.145, 1.13), (0.195, -0.148, 1.00)],
            [(0.185, -0.064, 1.245), (0.225, -0.151, 1.10), (0.155, -0.150, 0.975)],
            [(0.165, -0.063, 1.245), (0.205, -0.155, 1.075), (0.115, -0.151, 0.955)],
        ),
        start=1,
    ):
        objects.append(
            add_chain(
                f"Military_Shoulder_Chain_{index}",
                points,
                gold,
                body,
                armature,
                values,
            )
        )
    return objects


def evaluated_bounds(body: bpy.types.Object) -> tuple[Vector, Vector]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()
    minimum = Vector((
        min(point.x for point in points),
        min(point.y for point in points),
        min(point.z for point in points),
    ))
    maximum = Vector((
        max(point.x for point in points),
        max(point.y for point in points),
        max(point.z for point in points),
    ))
    return minimum, maximum


def configure_scene(body: bpy.types.Object) -> bpy.types.Object:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 720
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.view_settings.look = "AgX - Medium High Contrast"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("SiroinoReviewWorld")
    scene.world.color = (0.055, 0.060, 0.072)
    minimum, maximum = evaluated_bounds(body)
    center = (minimum + maximum) * 0.5
    height = max(1.0, maximum.z - minimum.z)
    camera_data = bpy.data.cameras.new("ReviewCamera")
    camera_data.lens = 62
    camera = bpy.data.objects.new("ReviewCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera

    def look_at(obj: bpy.types.Object, target: Vector = center) -> None:
        obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()

    for name, location, energy, size in (
        ("Key", center + Vector((height * 1.4, -height * 1.8, height * 1.3)), 1150, height * 1.6),
        ("Fill", center + Vector((-height * 1.5, -height * 1.2, height * 0.8)), 680, height * 1.5),
        ("Rim", center + Vector((height * 0.7, height * 1.5, height * 1.1)), 950, height * 1.3),
    ):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.shape = "DISK"
        data.size = size
        light = bpy.data.objects.new(name, data)
        light.location = location
        bpy.context.collection.objects.link(light)
        look_at(light)
    floor_material = base.simple_material(
        "MAT_Review_Floor",
        (0.12, 0.13, 0.16, 1.0),
        0.82,
    )
    bpy.ops.mesh.primitive_cube_add(
        location=(center.x, center.y, minimum.z - 0.035),
        scale=(height, height, 0.035),
    )
    floor = bpy.context.object
    floor.name = "Review_Floor"
    floor.data.materials.append(floor_material)
    floor["image2outfit_role"] = "review-stage"
    return camera


def render_views(
    camera: bpy.types.Object,
    body: bpy.types.Object,
    directory: Path,
) -> dict[str, Path]:
    minimum, maximum = evaluated_bounds(body)
    center = (minimum + maximum) * 0.5
    height = max(1.0, maximum.z - minimum.z)
    distance = height * 1.75
    positions = {
        "front": center + Vector((0.0, -distance, 0.02 * height)),
        "back": center + Vector((0.0, distance, 0.02 * height)),
        "left": center + Vector((distance, 0.0, 0.02 * height)),
        "right": center + Vector((-distance, 0.0, 0.02 * height)),
        "three-quarter": center + Vector((distance * 0.72, -distance * 0.72, 0.05 * height)),
    }
    outputs: dict[str, Path] = {}
    for name, position in positions.items():
        camera.location = position
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        path = directory / f"{name}.png"
        bpy.context.scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        outputs[name] = path
    return outputs


def compose_multiview(inputs: dict[str, Path], output: Path) -> None:
    cell = (400, 400)
    canvas = Image.new("RGB", (1200, 800), (238, 239, 242))
    draw = ImageDraw.Draw(canvas)
    for index, name in enumerate(("front", "three-quarter", "back", "left", "right")):
        image = Image.open(inputs[name]).convert("RGB")
        image.thumbnail(cell, Image.Resampling.LANCZOS)
        x = (index % 3) * cell[0]
        y = (index // 3) * cell[1]
        canvas.paste(
            image,
            (x + (cell[0] - image.width) // 2, y + (cell[1] - image.height) // 2),
        )
        draw.text((x + 12, y + 12), name, fill=(34, 36, 42))
    canvas.save(output, "WEBP", quality=92, method=6)


def export_fbx(
    job: dict,
    armature: bpy.types.Object,
    garments: list[bpy.types.Object],
) -> Path:
    path = repo_path(job["fbxAssetPath"])
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    for obj in garments:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.fbx(
        filepath=str(path),
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",
        use_space_transform=True,
        add_leaf_bones=False,
        primary_bone_axis="Y",
        secondary_bone_axis="X",
        mesh_smooth_type="FACE",
        use_mesh_modifiers=True,
        bake_anim=False,
        path_mode="AUTO",
    )
    return path


def target_fit_audit(
    body: bpy.types.Object,
    garments: list[bpy.types.Object],
) -> dict[str, object]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    tree = BVHTree.FromObject(body, depsgraph)
    body_inverse = body.matrix_world.inverted()
    clearances: list[float] = []
    per_object: dict[str, dict[str, object]] = {}
    total_penetrating = 0
    total_vertices = 0
    for obj in garments:
        if not bool(obj.get("image2outfit_fit_audit", False)):
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        local_clearances: list[float] = []
        try:
            for vertex in mesh.vertices:
                point = body_inverse @ (evaluated.matrix_world @ vertex.co)
                nearest = tree.find_nearest(point)
                if nearest[0] is None or nearest[1] is None:
                    continue
                signed = float((point - nearest[0]).dot(nearest[1]))
                local_clearances.append(signed)
        finally:
            evaluated.to_mesh_clear()
        penetrating = sum(value < -0.0015 for value in local_clearances)
        total_penetrating += penetrating
        total_vertices += len(local_clearances)
        clearances.extend(local_clearances)
        per_object[obj.name] = {
            "vertices": len(local_clearances),
            "penetratingVertices": penetrating,
            "minimumClearanceMeters": min(local_clearances) if local_clearances else None,
            "medianClearanceMeters": statistics.median(local_clearances) if local_clearances else None,
        }
    ratio = total_penetrating / max(1, total_vertices)
    minimum = min(clearances) if clearances else None
    passed = (
        bool(clearances)
        and ratio <= 0.005
        and minimum is not None
        and minimum >= -0.003
    )
    return {
        "schemaVersion": 1,
        "target": "SiroinoSotai_PC",
        "usesActualTargetSource": True,
        "auditedVertices": total_vertices,
        "penetratingVertices": total_penetrating,
        "penetrationRatio": ratio,
        "minimumClearanceMeters": minimum,
        "medianClearanceMeters": statistics.median(clearances) if clearances else None,
        "maximumClearanceMeters": max(clearances) if clearances else None,
        "objects": per_object,
        "passed": passed,
    }


def mesh_metrics(garments: list[bpy.types.Object]) -> dict[str, int]:
    result = {
        "meshObjects": 0,
        "vertices": 0,
        "triangles": 0,
        "degenerateTriangles": 0,
        "unweightedVertices": 0,
        "shapeKeys": 0,
    }
    for obj in garments:
        if obj.type != "MESH":
            continue
        result["meshObjects"] += 1
        obj.data.calc_loop_triangles()
        result["vertices"] += len(obj.data.vertices)
        result["triangles"] += len(obj.data.loop_triangles)
        result["unweightedVertices"] += sum(
            1 for vertex in obj.data.vertices if not vertex.groups
        )
        result["shapeKeys"] += (
            0
            if obj.data.shape_keys is None
            else max(0, len(obj.data.shape_keys.key_blocks) - 1)
        )
        for triangle in obj.data.loop_triangles:
            a, b, c = (obj.data.vertices[index].co for index in triangle.vertices)
            if (b - a).cross(c - a).length_squared <= 1e-20:
                result["degenerateTriangles"] += 1
    return result


def write_contracts(
    job_path: Path,
    job: dict,
    directories: dict[str, Path],
    body: bpy.types.Object,
    armature: bpy.types.Object,
    garments: list[bpy.types.Object],
    previews: dict[str, Path],
    fbx: Path,
    fit: dict[str, object],
) -> None:
    evidence = directories["evidence"] / "target-fit.json"
    evidence.write_text(
        json.dumps(fit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    metrics = mesh_metrics(garments)
    manifest = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "productName": PRODUCT_NAME,
        "status": "WORKING",
        "classification": "ACTUAL_TARGET_FITTED_PREFAB_CHECKPOINT",
        "targetAdapterId": job["adapterId"],
        "targetAvatarAssetPath": job["targetAvatarAssetPath"],
        "targetSourcePath": job["targetSourcePath"],
        "targetBodyObject": body.name,
        "targetArmatureObject": armature.name,
        "bodyShapeProfile": profile(job),
        "productRoot": job["productRoot"],
        "outfitPrefabPath": job["prefabAssetPath"],
        "integratedPrefabPath": job["integratedPrefabAssetPath"],
        "previewPath": job["previewPaths"]["front"],
        "documentationPath": f"{job['productRoot']}/README.md",
        "sourceJobPath": job_path.relative_to(ROOT).as_posix(),
        "generatedAt": utc_now(),
        "blenderVersion": bpy.app.version_string,
        "constructionProfile": "target-surface-panel-sewn",
        "designRevision": REVISION,
        "metrics": metrics,
        "targetFitAudit": fit,
        "technicalGates": {
            "actualTargetSourceImport": "PASS",
            "actualTargetBodyRender": "PASS",
            "bodySurfacePanelFit": "PASS" if fit["passed"] else "FAIL",
            "armatureWeightTransfer": "PASS" if metrics["unweightedVertices"] == 0 else "FAIL",
            "bodyShapeKeyTransfer": "PASS" if metrics["shapeKeys"] > 0 else "FAIL",
            "fbxExport": "PASS",
            "fiveViewRender": "PASS",
            "unityPrefabYamlGenerated": "PASS",
            "unityImport": "PENDING",
            "prefabReload": "PENDING",
            "modularAvatar": "PENDING",
            "ndmf": "PENDING",
            "vrchatBuildAndTest": "PENDING",
            "humanVisualReview": "PENDING",
            "humanPoseReview": "PENDING",
            "humanRuntimeReview": "PENDING",
        },
        "handoff": {
            "resumable": True,
            "canonicalWorkspace": job["productRoot"],
            "resumeFrom": job["blendPath"],
            "doNotRebuildFromZero": True,
            "blockers": [
                "Run the actual SiroinoSotai_PC pose suite and review penetration evidence.",
                "Import, save, and reload the generated Prefabs in Unity 2022.3.22f1.",
                "Validate Modular Avatar/NDMF integration against SiroinoSotai_PC.prefab.",
                "Run VRChat Build & Test and capture runtime evidence.",
            ],
        },
        "hashes": {
            "fbxSha256": sha256(fbx),
            "frontPreviewSha256": sha256(previews["front"]),
            "targetFitEvidenceSha256": sha256(evidence),
        },
    }
    repo_path(job["productManifestPath"]).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    readme = f"""# {PRODUCT_NAME}

`WORKING` — the garment is generated from and rendered on the actual `SiroinoSotai_PC.fbx` surface. Weight groups and supported Siroino body-size shape keys are transferred from the target body. Unity import/reload, Modular Avatar/NDMF, VRChat Build & Test, and human approval remain pending.

## Target-fit evidence

- Target source: `{job['targetSourcePath']}`
- Target Prefab: `{job['targetAvatarAssetPath']}`
- Body shape profile: `{json.dumps(profile(job), ensure_ascii=False)}`
- Fit audit: `{job['productRoot']}/Evidence/target-fit.json`
- Five-view review: `{job['productRoot']}/Previews/{PRODUCT_ID}-multiview.webp`
- Pose review: `{job['productRoot']}/Previews/{PRODUCT_ID}-pose-review.webp`

## Unity entry points

- Outfit Prefab: `{job['prefabAssetPath']}`
- Integration checkpoint: `{job['integratedPrefabAssetPath']}`
- FBX: `{job['fbxAssetPath']}`
- Blend: `{job['blendPath']}`

The generated integration Prefab remains a checkpoint until Unity imports, saves, reloads, and validates it against `SiroinoSotai_PC.prefab`.
"""
    (directories["root"] / "README.md").write_text(readme, encoding="utf-8")
    update_hashes(directories["root"])


def update_hashes(root: Path) -> None:
    lines = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "SOURCE_HASHES.txt":
            lines.append(f"{sha256(path)}  {path.relative_to(root).as_posix()}")
    (root / "SOURCE_HASHES.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def fallback_hosted_build(job: dict) -> int:
    # GitHub-hosted runners intentionally do not contain the private target FBX.
    # Preserve a non-release checkpoint there; the self-hosted runner performs
    # the authoritative fit build using SiroinoSotai_PC.
    legacy.base.REVISION = "target-fit-awaiting-private-source-v7"
    return legacy.base.main()


def main() -> int:
    job_path, job = base.load_job()
    source = repo_path(job["targetSourcePath"])
    if not source.is_file():
        return fallback_hosted_build(job)

    directories = base.prepare_directories(job)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    body, armature, _ = import_target(job)
    values = profile(job)
    set_shape_values(body, values)
    assign_review_skin(body)

    textures = base.create_textures(directories["textures"])
    fabric = base.fabric_material(textures)
    sheer = base.sheer_material(textures["sheer"])
    gold = base.simple_material(
        "MAT_Brushed_Gold",
        (0.61, 0.39, 0.09, 1.0),
        0.22,
        0.92,
    )
    garments = build_outfit(body, armature, fabric, sheer, gold, values)
    for obj in garments:
        set_shape_values(obj, values)
    bpy.context.view_layer.update()

    camera = configure_scene(body)
    previews = render_views(camera, body, directories["previews"])
    compose_multiview(
        previews,
        directories["previews"] / f"{PRODUCT_ID}-multiview.webp",
    )
    fit = target_fit_audit(body, garments)
    if not fit["passed"]:
        raise RuntimeError(f"SiroinoSotai_PC target-fit audit failed: {fit}")

    fbx = export_fbx(job, armature, garments)
    base.write_unity_prefabs(job)
    blend = repo_path(job["blendPath"])
    blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), compress=True)
    write_contracts(
        job_path,
        job,
        directories,
        body,
        armature,
        garments,
        previews,
        fbx,
        fit,
    )
    print(
        json.dumps(
            {
                "productId": PRODUCT_ID,
                "status": "WORKING",
                "actualTarget": job["targetSourcePath"],
                "fitAudit": fit,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
