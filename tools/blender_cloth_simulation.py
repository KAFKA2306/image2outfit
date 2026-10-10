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
import math
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
    "siroino-lunar-tech-hoodie": (
        "Lunar_Overskirt_Left",
        "Lunar_Overskirt_Right",
    ),
    "siroino-verdant-ranger-explorer-set": (
        "Verdant_Tunic_Front",
        "Verdant_Tunic_Back",
        "Verdant_Tunic_Side_L",
        "Verdant_Tunic_Side_R",
    ),
}

FRAME_END = {
    "siroino-cyber-kawaii-large": 24,
    "siroino-heather-hooded-bodysuit": 18,
    "siroino-lace-halter-large": 24,
    "siroino-military-sheer-romper-large": 20,
    "siroino-nocturne-angel-set": 24,
    "siroino-wide-cargo": 18,
    "siroino-lunar-tech-hoodie": 30,
    "siroino-verdant-ranger-explorer-set": 30,
}


def parse_args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--prototype", action="store_true")
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


def bind_canonical_row_rest_shape(obj, job, declaration):
    """Bind explicit prototype spring lengths; keep the initial visible mesh unchanged."""
    if declaration["method"] != "canonical-row-circumference-rest-springs":
        raise ValueError("Unknown canonical cloth rest method")
    count, inset = declaration["sampleRowCount"], declaration["sectionBoundaryInsetM"]
    if isinstance(count, bool) or not isinstance(count, int) or not 8 <= count <= 128:
        raise ValueError("Rest row sample count must be bounded")
    if not math.isfinite(inset) or not 0 < inset < .001:
        raise ValueError("Rest section boundary inset is invalid")
    pipeline = job["garmentPipeline"]
    pose_path = repo_path(pipeline["assemblyPosePath"])
    pattern_path = repo_path(pipeline["patternContractPath"])
    pose, pattern = read_json(pose_path), read_json(pattern_path)
    fold = pose["skirtPleatPlacement"]
    names = json.loads(obj["canonicalPieceIds"])
    owners = obj.data.attributes["canonical_piece_index"]
    if {names[x.value] for x in owners.data} != set(fold["pieceIds"]):
        raise ValueError("Rest shape must cover exactly the declared skirt panels")
    waist, hem = fold["waistZM"], fold["hemZM"]
    origin = fold["axisOriginBlenderXYM"]
    curves = []
    for pid in fold["pieceIds"]:
        panel = next(p for p in pattern["pieces"] if p["pieceId"] == pid)
        curve = pose["poses"][pid]["skirtWrap"]["widthQuadraticControlM"]
        side = next(e for e in panel["edges"] if e["edgeId"] == "side-right")
        a, b = [panel["boundary"][side[k]] for k in ["startVertex", "endVertex"]]
        u, v = side["curvature"]["params"][0]
        dx, dy = b[0]-a[0], b[1]-a[1]
        control = [a[0]+u*dx-v*dy, a[1]+u*dy+v*dx]
        if (len(curve) != 3 or not all(math.isfinite(x) and x > 0 for x in curve)
                or abs(a[0]-curve[0]) > 1e-8 or abs(b[0]-curve[2]) > 1e-8
                or abs(control[0]-curve[1]) > 1e-8 or abs(control[1]-(hem-waist)/2) > 1e-8):
            raise ValueError("Rest row quadratic controls differ from canonical pattern")
        curves.append(curve)
    points = [tuple(obj.matrix_world @ v.co) for v in obj.data.vertices]
    if any(len(f.vertices) != 3 for f in obj.data.polygons):
        raise ValueError("Rest row measurement requires triangles")
    rows = []
    for i in range(count):
        z = hem+inset+(waist-hem-2*inset)*i/(count-1)
        circumference = 0.0
        segment_count = 0
        for face in obj.data.polygons:
            tri = [points[j] for j in face.vertices]
            hits = []
            for a, b in zip(tri, tri[1:]+tri[:1]):
                if (a[2] <= z < b[2]) or (b[2] <= z < a[2]):
                    t = (z-a[2])/(b[2]-a[2])
                    hits.append([a[j]+t*(b[j]-a[j]) for j in range(2)])
            if len(hits) == 2:
                circumference += math.dist(*hits)
                segment_count += 1
        if circumference <= 1e-6 or segment_count < 3:
            raise ValueError("Rest row source section is missing")
        t = (waist-z)/(waist-hem)
        rest = sum(2*((1-t)**2*c[0]+2*t*(1-t)*c[1]+t*t*c[2]) for c in curves)
        rows.append({"zM": z, "sourceSectionCircumferenceM": circumference,
                     "canonicalFlatCircumferenceM": rest, "radialRestScale": rest/circumference})
    if obj.data.shape_keys:
        raise ValueError("Prototype rest shape cannot replace existing garment Shape Keys")
    obj.shape_key_add(name="Basis")
    key = obj.shape_key_add(name="Canonical Fabric Rest Springs")
    key.value = 0.0
    inverse = obj.matrix_world.inverted()
    moved = 0
    for vertex, point in zip(key.data, points):
        x, y, z = point
        if abs(z-waist) <= 1e-6:
            continue
        if not hem-1e-6 <= z <= waist+1e-6:
            raise ValueError("Rest shape vertex outside canonical skirt height")
        lo = next((j for j in range(len(rows)-1) if rows[j]["zM"] <= z <= rows[j+1]["zM"]), None)
        if lo is None:
            scale = rows[0 if z < rows[0]["zM"] else -1]["radialRestScale"]
        else:
            a, b = rows[lo], rows[lo+1]; t = (z-a["zM"])/(b["zM"]-a["zM"])
            scale = (1-t)*a["radialRestScale"]+t*b["radialRestScale"]
        from mathutils import Vector
        vertex.co = inverse @ Vector((origin[0]+(x-origin[0])*scale,
                                       origin[1]+(y-origin[1])*scale, z))
        moved += 1
    ratios = []
    for edge in obj.data.edges:
        a, b = edge.vertices
        initial = (obj.data.vertices[a].co-obj.data.vertices[b].co).length
        rest = (key.data[a].co-key.data[b].co).length
        if initial <= 1e-10 or rest <= 1e-10:
            raise ValueError("Rest spring collapsed")
        ratios.append(rest/initial)
    return {"method": declaration["method"], "shapeKey": key.name, "shapeKeyValue": key.value,
            "movedRestVertexCount": moved,
            "sewnWaistRestDisplacementM": 0, "rows": rows,
            "restToInitialEdgeRatio": {"minimum": min(ratios), "maximum": max(ratios),
                                       "mean": sum(ratios)/len(ratios), "edgeCount": len(ratios)},
            "restCoordinatesSha256": hashlib.sha256(json.dumps([list(v.co) for v in key.data]).encode()).hexdigest(),
            "patternSha256": hashlib.sha256(pattern_path.read_bytes()).hexdigest(),
            "assemblyPoseSha256": hashlib.sha256(pose_path.read_bytes()).hexdigest(),
            "grantsFitAcceptance": False, "evidenceBoundary": declaration["evidenceBoundary"]}


def bake_sewn_prototype(job: dict[str, object]) -> int:
    """Run a bounded solve on attributed panels, preserving the input .blend."""
    blend = repo_path(str(job["blendPath"]))
    source_hash = hashlib.sha256(blend.read_bytes()).hexdigest()
    construction_path = repo_path(job["garmentPipeline"]["constructionPath"])
    construction = read_json(construction_path)
    policy = construction["clothSimulation"]
    groups = policy["prototypePanelGroups"]
    if set(groups) != set(policy["components"]):
        raise ValueError("prototype panel groups must cover the cloth policy")
    frame_end = policy["prototypeFrameEnd"]
    if not isinstance(frame_end, int) or not 2 <= frame_end <= 120:
        raise ValueError("bounded prototype frame range is required")
    bpy.ops.wm.open_mainfile(filepath=str(blend), load_ui=False)
    original = bpy.data.objects.get(str(job["id"]))
    if original is None or original.type != "MESH":
        raise ValueError("canonical sewn prototype is missing")
    pieces = json.loads(original["canonicalPieceIds"])
    owners = original.data.attributes["canonical_piece_index"]
    faces = [list(face.vertices) for face in original.data.polygons]
    selected_faces = {}
    claimed = set()
    for name, group in groups.items():
        if not group or not set(group) <= set(pieces):
            raise ValueError("cloth panel group contains an unknown piece")
        indices = [i for i, owner in enumerate(owners.data) if pieces[owner.value] in group]
        if not indices or claimed.intersection(indices):
            raise ValueError("cloth group is empty or overlaps another group")
        selected_faces[name] = indices
        claimed.update(indices)
    selected_faces[str(job["id"]) + "-static"] = [i for i in range(len(faces)) if i not in claimed]
    objects = {}
    pin_methods = {}
    vertex_sets = {name: {v for i in ids for v in faces[i]} for name, ids in selected_faces.items()}
    for name, indices in selected_faces.items():
        ids = sorted(vertex_sets[name])
        remap = {value: index for index, value in enumerate(ids)}
        data = bpy.data.meshes.new(name)
        data.from_pydata([original.data.vertices[i].co[:] for i in ids], [],
                         [[remap[v] for v in faces[i]] for i in indices])
        data.update()
        obj = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(obj)
        obj.matrix_world = original.matrix_world.copy()
        obj["canonicalPieceIds"] = json.dumps(pieces)
        source_ids = data.attributes.new("canonical_sewn_vertex_index", "INT", "POINT")
        for item, source_id in zip(source_ids.data, ids):
            item.value = source_id
        ownership = data.attributes.new("canonical_piece_index", "INT", "FACE")
        for face, original_index in zip(ownership.data, indices):
            face.value = owners.data[original_index].value
        for material in original.data.materials:
            obj.data.materials.append(material)
        objects[name] = obj
        if name in groups:
            shared = vertex_sets[name].intersection(set().union(*(s for key, s in vertex_sets.items() if key != name)))
            pin_ids = [remap[v] for v in shared]
            pin_methods[name] = "canonical shared seam vertices"
            if not shared:
                if name != "pleated-overskirt":
                    raise ValueError(f"cloth component has no sewn attachment: {name}")
                boundary = policy.get("prototypeWaistPinBoundary")
                if boundary is not None:
                    if boundary["component"] != name or boundary["method"] != "open-boundary-at-declared-waist-height":
                        raise ValueError("Explicit waist boundary does not match cloth component")
                    from collections import Counter
                    counts = Counter(tuple(sorted((a, b))) for face in data.polygons
                                     for a, b in zip(face.vertices, list(face.vertices[1:])+[face.vertices[0]]))
                    edges = [edge for edge, count in counts.items() if count == 1]
                    z, tolerance = boundary["heightM"], boundary["toleranceM"]
                    waist_edges = [edge for edge in edges if all(abs(data.vertices[i].co.z-z) <= tolerance for i in edge)]
                    pin_ids = sorted({i for edge in waist_edges for i in edge})
                    if len(pin_ids) < 3 or len(waist_edges) != len(pin_ids):
                        raise ValueError("Declared waist boundary is not a closed open-edge loop")
                    pattern = read_json(repo_path(job["garmentPipeline"]["patternContractPath"]))
                    for piece in groups[name]:
                        panel = next(p for p in pattern["pieces"] if p["pieceId"] == piece)
                        edge = next(e for e in panel["edges"] if e["edgeId"] == boundary["edgeId"])
                        if any(abs(panel["boundary"][edge[k]][1]) > tolerance for k in ["startVertex", "endVertex"]):
                            raise ValueError("Waist edge is not at the declared local zero height")
                    pin_methods[name] = "canonical open waist boundary; provisional static support only"
                else:
                    fraction = policy["prototypeWaistPinUpperFraction"]
                    if not isinstance(fraction, (int, float)) or not 0 < fraction < 1:
                        raise ValueError("explicit provisional waist pin fraction is required")
                    heights = [v.co.z for v in data.vertices]
                    threshold = max(heights) - (max(heights) - min(heights)) * fraction
                    pin_ids = [v.index for v in data.vertices if v.co.z >= threshold]
                    pin_methods[name] = "unapproved upper-height-band waist attachment hypothesis"
            pins = obj.vertex_groups.new(name="Image2Outfit Cloth Pin")
            pins.add(pin_ids, 1.0, "REPLACE")
    bpy.data.objects.remove(original, do_unlink=True)
    bodies = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"
              and obj.get("prototypeRole") == "target-avatar-reference-only"]
    if not bodies:
        raise ValueError("real imported target collision meshes are missing")
    for body in bodies:
        ensure_collision(body)
    from mathutils.bvhtree import BVHTree
    if len(bodies) != 1:
        raise ValueError("Cloth surface diagnostics require one explicit body")
    body = bodies[0]
    body.data.calc_loop_triangles()
    tree = BVHTree.FromPolygons([body.matrix_world @ v.co for v in body.data.vertices],
                               [tuple(t.vertices) for t in body.data.loop_triangles], all_triangles=True)
    def surface_diagnostics(obj):
        signed, heights = [], []
        for vertex in obj.data.vertices:
            point = obj.matrix_world @ vertex.co
            nearest, normal, triangle, distance = tree.find_nearest(point)
            if triangle is None:
                raise ValueError("Body surface diagnostic failed")
            signed.append(float((point-nearest).dot(normal)))
            heights.append(float(point.z))
        return {"heightRangeM": [min(heights), max(heights)],
                "nearestNormalSignedDistanceM": {"minimum": min(signed), "maximum": max(signed)},
                "negativeSignedVertexCount": sum(v < -1e-6 for v in signed),
                "belowCombinedCollisionMarginVertexCount": sum(v < .007 for v in signed),
                "distanceMethod": "nearest raw rest-body triangle normal; diagnostic only, not penetration acceptance"}
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, frame_end
    scene.gravity = (0, 0, -4.5)
    before, contracts = {}, []
    rest_controls = {}
    for name in groups:
        obj = objects[name]
        pin_ids = [v.index for v in obj.data.vertices if v.groups]
        before[name] = mesh_hash(obj)
        rest = policy.get("prototypeRestShape", {}).get(name)
        rest_contract = bind_canonical_row_rest_shape(obj, job, rest) if rest is not None else None
        contract = configure_cloth(obj, frame_end)
        bending = policy.get("prototypeComponentBending", {})
        if not set(bending).issubset(groups):
            raise ValueError("Bending declaration references an unknown cloth component")
        if name in bending:
            declared = bending[name]
            value = declared["stiffness"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Finite numeric bending stiffness is required")
            modifier = obj.modifiers["Image2Outfit Cloth"]
            limits = modifier.settings.bl_rna.properties["bending_stiffness"]
            if not limits.hard_min <= value <= limits.hard_max:
                raise ValueError("Declared bending stiffness exceeds native Blender limits")
            evidence_path = repo_path(declared["evidencePath"])
            if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != declared["evidenceSha256"]:
                raise ValueError("Bending comparison evidence hash mismatch")
            evidence = read_json(evidence_path)
            if (evidence.get("productId") != job["id"]
                    or evidence.get("blenderVersion") != bpy.app.version_string
                    or evidence.get("bendingStiffness") != value
                    or evidence.get("bendingModel") != modifier.settings.bending_model
                    or evidence.get("frameEnd") != frame_end
                    or evidence.get("cacheBaked") is not True):
                raise ValueError("Bending comparison is incompatible with this solve")
            for key, path in (("assemblyPoseSha256", job["garmentPipeline"]["assemblyPosePath"]),
                              ("patternSha256", job["garmentPipeline"]["patternContractPath"]),
                              ("targetSourceSha256", job["targetSourcePath"])):
                if evidence.get(key) != hashlib.sha256(repo_path(path).read_bytes()).hexdigest():
                    raise ValueError("Bending comparison inputs are stale: " + key)
            modifier.settings.bending_stiffness = value
            contract["componentBending"] = {
                "stiffness": modifier.settings.bending_stiffness,
                "maximum": modifier.settings.bending_stiffness_max,
                "model": modifier.settings.bending_model,
                "evidencePath": declared["evidencePath"], "evidenceSha256": declared["evidenceSha256"],
                "evidenceBoundary": declared["evidenceBoundary"], "grantsFitAcceptance": False}
        if rest is not None:
            key = obj.data.shape_keys.key_blocks[rest_contract["shapeKey"]]
            modifier = obj.modifiers["Image2Outfit Cloth"]
            modifier.settings.rest_shape_key = key
            if modifier.settings.rest_shape_key != key:
                raise ValueError("Native cloth did not bind the declared rest key")
            rest_contract["nativeRestShapeKeyBound"] = True
            rest_contract["initializationOrder"] = "rest key created before Cloth modifier"
            contract["canonicalRestShape"] = rest_contract
        pin = obj.vertex_groups["Image2Outfit Cloth Pin"]
        pin.remove(range(len(obj.data.vertices)))
        pin.add(pin_ids, 1.0, "REPLACE")
        contract["pinVertexCount"] = len(pin_ids)
        contract["pinMethod"] = pin_methods[name]
        contract["preBakeBodySurfaceDiagnostic"] = surface_diagnostics(obj)
        contracts.append(contract)
        if rest is not None:
            # A bound RNA key is not evidence that Cloth consumed its spring
            # coordinates. Solve an otherwise identical Basis-rest control.
            control = obj.copy()
            control.data = obj.data.copy()
            control.name = name + "-basis-rest-control"
            bpy.context.collection.objects.link(control)
            configure_cloth(control, frame_end)
            control_modifier = control.modifiers["Image2Outfit Cloth"]
            control_modifier.settings.rest_shape_key = control.data.shape_keys.key_blocks[0]
            if control_modifier.settings.rest_shape_key != control.data.shape_keys.key_blocks[0]:
                raise ValueError("Native cloth did not bind the Basis control key")
            control_pin = control.vertex_groups["Image2Outfit Cloth Pin"]
            control_pin.remove(range(len(control.data.vertices)))
            control_pin.add(pin_ids, 1.0, "REPLACE")
            rest_controls[name] = control
    scene.frame_set(0)
    scene.frame_set(1)
    bpy.context.view_layer.update()
    bpy.ops.ptcache.bake_all(bake=True)
    scene.frame_set(frame_end)
    bpy.context.view_layer.update()
    for name, control in rest_controls.items():
        modifier = control.modifiers["Image2Outfit Cloth"]
        if not modifier.point_cache.is_baked:
            raise RuntimeError("Basis-rest response control did not bake")
        declared_hash = mesh_hash(objects[name], evaluated=True)
        control_hash = mesh_hash(control, evaluated=True)
        response = {"method": "same-input-native-cloth-declared-vs-basis-rest",
                    "declaredEvaluatedMeshSha256": declared_hash,
                    "basisEvaluatedMeshSha256": control_hash,
                    "coordinateRoundingDecimalPlaces": 7,
                    "measurableResponse": declared_hash != control_hash,
                    "controlCacheBakedActual": True,
                    "useDynamicMesh": objects[name].modifiers["Image2Outfit Cloth"].settings.use_dynamic_mesh,
                    "grantsFitAcceptance": False}
        contract = next(item for item in contracts if item["object"] == name)
        contract["canonicalRestShape"]["solverResponse"] = response
        if not response["measurableResponse"]:
            report = {"schemaVersion": 1, "productId": job["id"], "status": "FAIL",
                      "engine": "Blender Cloth", "blenderVersion": bpy.app.version_string,
                      "applicability": "REQUIRED", "frameStart": 1, "frameEnd": frame_end,
                      "sourceBlendSha256": source_hash,
                      "constructionSha256": hashlib.sha256(construction_path.read_bytes()).hexdigest(),
                      "contracts": contracts, "qualityDecision": "UNVERIFIED",
                      "grantsFitAcceptance": False,
                      "failureCode": "REST_SHAPE_NO_MEASURABLE_SOLVER_RESPONSE",
                      "evidenceBoundary": "Declared and Basis-rest controls produced identical evaluated coordinates; intended rest-spring linkage is unverified. Existing settled candidate is preserved."}
            write_json(ROOT / ".image2outfit" / "products" / str(job["id"]) / "reports/cloth-rest-response-failure.json", report)
            raise RuntimeError("Declared rest shape produced no measurable native Cloth response")
        bpy.data.objects.remove(control, do_unlink=True)
    for contract in contracts:
        obj = objects[contract["object"]]
        modifier = obj.modifiers["Image2Outfit Cloth"]
        if not modifier.point_cache.is_baked:
            raise RuntimeError("native cloth cache did not bake")
        evaluated = mesh_hash(obj, evaluated=True)
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        if "canonicalRestShape" in contract:
            # Blender cannot apply Cloth to a mesh with Shape Keys. Capture the
            # actual evaluated solve, including canonical face attributes.
            depsgraph = bpy.context.evaluated_depsgraph_get()
            settled_data = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph),
                                                         preserve_all_data_layers=True, depsgraph=depsgraph)
            if len(settled_data.vertices) != len(obj.data.vertices) or len(settled_data.polygons) != len(obj.data.polygons):
                raise ValueError("Rest-shape cloth changed canonical topology")
            if settled_data.attributes.get("canonical_piece_index") is None:
                raise ValueError("Rest-shape cloth lost canonical face ownership")
            obj.modifiers.remove(modifier)
            obj.data = settled_data
            contract["canonicalRestShape"]["settledCapture"] = "actual evaluated native Cloth mesh"
        else:
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        settled = mesh_hash(obj)
        contract["postBakeBodySurfaceDiagnostic"] = surface_diagnostics(obj)
        contract.update(cacheBakedActual=True, preBakeMeshSha256=before[obj.name],
                        evaluatedFrameMeshSha256=evaluated, settledMeshSha256=settled,
                        geometryChanged=settled != before[obj.name])
    runtime = ROOT / ".image2outfit" / "products" / str(job["id"]) / "cloth"
    runtime.mkdir(parents=True, exist_ok=True)
    candidate = runtime / "settled-prototype.blend"
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(candidate), check_existing=False)
    report = {
        "schemaVersion": 1, "productId": job["id"], "status": "PASS",
        "engine": "Blender Cloth", "blenderVersion": bpy.app.version_string,
        "applicability": "REQUIRED", "frameStart": 1, "frameEnd": frame_end,
        "cacheBaked": True, "geometryChanged": all(c["geometryChanged"] for c in contracts),
        "contracts": contracts, "sourceBlendSha256": source_hash,
        "constructionSha256": hashlib.sha256(construction_path.read_bytes()).hexdigest(),
        "candidatePath": str(candidate.relative_to(ROOT)).replace("\\", "/"),
        "candidateSha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "collisionObjects": [body.name for body in bodies],
        "qualityDecision": "UNVERIFIED", "grantsFitAcceptance": False,
        "evidenceBoundary": "Bounded neutral cloth experiment only; no fit, motion, weights, or rendered appearance acceptance.",
    }
    write_json(repo_path(str(job["productRoot"])) / "Evidence/Build/cloth-simulation.json", report)
    return 0


def main() -> int:
    options = parse_args()
    job = read_json(repo_path(options.job))
    product_id = str(job.get("id", ""))
    if options.prototype:
        return bake_sewn_prototype(job)
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
