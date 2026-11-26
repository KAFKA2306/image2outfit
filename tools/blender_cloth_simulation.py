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
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import bmesh
    import bpy
except ImportError:
    bmesh = None
    bpy = None


ROOT = Path(__file__).resolve().parents[1]
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
CONTENT_HASH_SUFFIX_RE = re.compile(r"-[0-9a-f]{16}$")
PROSE_ONLY_POSE_KEYS = frozenset({"method", "evidenceBoundary", "observation", "reason"})
GLOBAL_ASSEMBLY_POSE_KEYS = frozenset(
    {
        "schemaVersion",
        "productId",
        "status",
        "coordinateSystem",
        "targetSourceSha256",
        "measurementEvidencePath",
        "measurementEvidenceSha256",
    }
)
GLOBAL_PATTERN_KEYS = frozenset(
    {
        "schemaVersion",
        "productId",
        "units",
        "coordinateSystem",
        "sourceReference",
        "measurementBasis",
    }
)

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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    if argv is not None:
        values = list(argv)
    elif "--" in sys.argv:
        values = sys.argv[sys.argv.index("--") + 1 :]
    elif bpy is None:
        values = sys.argv[1:]
    else:
        values = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--prototype", action="store_true")
    parser.add_argument("--rebind-bending-component")
    parser.add_argument("--baseline-revision")
    parser.add_argument("--baseline-pattern-current-if-evidence-matches", action="store_true")
    return parser.parse_args(values)


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def parse_json_bytes(raw: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {label}")
    return value


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def repo_path(value: str | Path, *, root: Path | None = None) -> Path:
    base = (root or ROOT).resolve()
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (base / path).resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError(f"path escapes repository: {value}")
    return resolved


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


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
            a, b = rows[lo], rows[lo + 1]
            t = (z - a["zM"]) / (b["zM"] - a["zM"])
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


def _require_blender() -> None:
    if bpy is None or bmesh is None:
        raise RuntimeError(
            "Blender runtime (bpy/bmesh) is required for cloth simulation"
        )


def _require_non_empty_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def validate_component_bending_evidence(
    job: dict[str, Any],
    declared: dict[str, Any],
    *,
    frame_end: int,
    blender_version: str | None,
    bending_model: str | None,
    stiffness_min: float,
    stiffness_max: float,
    root: Path | None = None,
) -> tuple[float, dict[str, Any]]:
    if not isinstance(declared, dict):
        raise ValueError("Bending declaration must be a JSON object")
    value = declared.get("stiffness")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError("Finite numeric bending stiffness is required")
    if not stiffness_min <= value <= stiffness_max:
        raise ValueError("Declared bending stiffness exceeds native Blender limits")
    evidence_rel = _require_non_empty_str(declared.get("evidencePath"), "evidencePath")
    evidence_sha = _require_non_empty_str(
        declared.get("evidenceSha256"), "evidenceSha256"
    )
    if not HEX64_RE.fullmatch(evidence_sha):
        raise ValueError("Bending comparison evidence sha256 must be 64 lowercase hex")
    _require_non_empty_str(declared.get("evidenceBoundary"), "evidenceBoundary")
    evidence_path = repo_path(evidence_rel, root=root)
    if not evidence_path.is_file():
        raise ValueError(f"Bending comparison evidence file is missing: {evidence_rel}")
    if sha256_bytes(evidence_path.read_bytes()) != evidence_sha:
        raise ValueError("Bending comparison evidence hash mismatch")
    evidence = read_json(evidence_path)
    if (
        evidence.get("productId") != job.get("id")
        or (
            blender_version is not None
            and evidence.get("blenderVersion") != blender_version
        )
        or evidence.get("bendingStiffness") != value
        or (
            bending_model is not None
            and evidence.get("bendingModel") != bending_model
        )
        or evidence.get("frameEnd") != frame_end
        or evidence.get("cacheBaked") is not True
    ):
        raise ValueError("Bending comparison is incompatible with this solve")
    pipeline = job.get("garmentPipeline")
    if not isinstance(pipeline, dict):
        raise ValueError("job.garmentPipeline is required")
    for key, rel_path in (
        ("assemblyPoseSha256", pipeline.get("assemblyPosePath")),
        ("patternSha256", pipeline.get("patternContractPath")),
        ("targetSourceSha256", job.get("targetSourcePath")),
    ):
        rel = _require_non_empty_str(rel_path, key)
        resolved = repo_path(rel, root=root)
        if not resolved.is_file():
            raise ValueError(f"Required bending input file is missing: {rel}")
        if evidence.get(key) != sha256_bytes(resolved.read_bytes()):
            raise ValueError("Bending comparison inputs are stale: " + key)
    return float(value), evidence


def _resolve_git_commit(baseline_revision: str, repo_root: Path) -> str:
    rev = _require_non_empty_str(baseline_revision, "baseline-revision")
    if rev.startswith("-"):
        raise ValueError(f"Invalid baseline git revision: {baseline_revision}")
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    commit = proc.stdout.strip()
    if proc.returncode != 0 or not HEX40_RE.fullmatch(commit):
        detail = proc.stderr.strip() or f"exit code {proc.returncode}"
        raise ValueError(
            f"Invalid baseline git revision '{baseline_revision}': {detail}"
        )
    return commit


def _read_git_file_bytes(commit: str, rel_path: str, repo_root: Path) -> bytes:
    posix_rel = rel_path.replace("\\", "/")
    proc = subprocess.run(
        ["git", "show", f"{commit}:{posix_rel}"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"Baseline revision {commit} is missing '{posix_rel}': {detail}"
        )
    return proc.stdout


def _index_pattern_pieces(pattern: dict[str, Any], label: str) -> dict[str, Any]:
    pieces = pattern.get("pieces")
    if not isinstance(pieces, list) or not pieces:
        raise ValueError(f"Pattern pieces list is missing or empty in {label}")
    indexed: dict[str, Any] = {}
    for item in pieces:
        if not isinstance(item, dict):
            raise ValueError(f"Pattern piece must be an object in {label}")
        pid = _require_non_empty_str(item.get("pieceId"), f"{label}.pieceId")
        if pid in indexed:
            raise ValueError(f"Duplicate pieceId '{pid}' in {label}")
        indexed[pid] = item
    return indexed


def _extract_component_stitches(
    stitch_doc: dict[str, Any], piece_set: set[str], label: str
) -> tuple[list[str], set[str]]:
    stitches = stitch_doc.get("stitches")
    if not isinstance(stitches, list):
        raise ValueError(f"Stitch graph 'stitches' must be a list in {label}")
    touched: list[str] = []
    neighbors: set[str] = set()
    for entry in stitches:
        if not isinstance(entry, dict):
            raise ValueError(f"Stitch entry must be an object in {label}")
        first = entry.get("first")
        second = entry.get("second")
        if not isinstance(first, dict) or not isinstance(second, dict):
            raise ValueError(f"Stitch endpoints must be objects in {label}")
        p1 = _require_non_empty_str(first.get("pieceId"), f"{label}.first.pieceId")
        p2 = _require_non_empty_str(second.get("pieceId"), f"{label}.second.pieceId")
        if p1 in piece_set or p2 in piece_set:
            touched.append(json.dumps(entry, sort_keys=True, separators=(",", ":")))
            neighbors.add(p1)
            neighbors.add(p2)
    touched.sort()
    return touched, neighbors


def _validate_cloth_policy_invariance(
    baseline_construction: dict[str, Any],
    current_construction: dict[str, Any],
    component: str,
) -> None:
    base_policy = baseline_construction.get("clothSimulation")
    cur_policy = current_construction.get("clothSimulation")
    if not isinstance(base_policy, dict) or not isinstance(cur_policy, dict):
        raise ValueError("clothSimulation policy is required in baseline and current construction")
    if base_policy.get("prototypeFrameEnd") != cur_policy.get("prototypeFrameEnd"):
        raise ValueError(
            "Cloth prototypeFrameEnd changed since baseline; remeasure bending evidence"
        )
    base_groups = base_policy.get("prototypePanelGroups")
    cur_groups = cur_policy.get("prototypePanelGroups")
    if not isinstance(base_groups, dict) or base_groups.get(component) != cur_groups.get(
        component
    ):
        raise ValueError(
            f"Cloth prototypePanelGroups changed for '{component}'; remeasure bending evidence"
        )
    base_bending = base_policy.get("prototypeComponentBending")
    cur_bending = cur_policy.get("prototypeComponentBending")
    if (
        not isinstance(base_bending, dict)
        or not isinstance(base_bending.get(component), dict)
        or base_bending[component].get("stiffness")
        != cur_bending[component].get("stiffness")
    ):
        raise ValueError(
            f"Declared bending stiffness changed for '{component}'; remeasure bending evidence"
        )
    base_rest = (
        base_policy.get("prototypeRestShape", {}).get(component)
        if isinstance(base_policy.get("prototypeRestShape"), dict)
        else None
    )
    cur_rest = (
        cur_policy.get("prototypeRestShape", {}).get(component)
        if isinstance(cur_policy.get("prototypeRestShape"), dict)
        else None
    )
    if base_rest != cur_rest:
        raise ValueError(
            f"Cloth prototypeRestShape changed for '{component}'; remeasure bending evidence"
        )
    if base_policy.get("prototypeWaistPinBoundary") != cur_policy.get(
        "prototypeWaistPinBoundary"
    ) or base_policy.get("prototypeWaistPinUpperFraction") != cur_policy.get(
        "prototypeWaistPinUpperFraction"
    ):
        raise ValueError(
            "Cloth waist pin policy changed since baseline; remeasure bending evidence"
        )


def _block_referenced_pieces(block: dict[str, Any]) -> set[str] | None:
    piece_ids = block.get("pieceIds")
    if (
        not isinstance(piece_ids, list)
        or not piece_ids
        or not all(isinstance(item, str) and item for item in piece_ids)
    ):
        return None
    referenced = set(piece_ids)
    for extra_key in ("seamContinuationPieceIds", "preserveSharedPieceIds"):
        extra = block.get(extra_key)
        if isinstance(extra, list):
            referenced.update(item for item in extra if isinstance(item, str))
    return referenced


def _validate_assembly_pose_invariance(
    baseline_pose: dict[str, Any],
    current_pose: dict[str, Any],
    protected_piece_ids: set[str],
    component: str,
) -> tuple[list[str], list[str]]:
    base_poses = baseline_pose.get("poses")
    cur_poses = current_pose.get("poses")
    if not isinstance(base_poses, dict) or not isinstance(cur_poses, dict):
        raise ValueError("Assembly pose 'poses' must be an object")
    for pid in sorted(protected_piece_ids):
        if pid not in base_poses or pid not in cur_poses:
            raise ValueError(
                f"Assembly pose is missing component-relevant piece '{pid}'"
            )
        if base_poses[pid] != cur_poses[pid]:
            raise ValueError(
                f"Assembly pose changed for component-relevant piece '{pid}'; "
                "remeasure bending evidence instead of rebinding"
            )
    changed_pose_pieces = sorted(
        pid
        for pid in set(base_poses) | set(cur_poses)
        if base_poses.get(pid) != cur_poses.get(pid)
    )
    if set(baseline_pose.keys()) != set(current_pose.keys()):
        raise ValueError(
            "Assembly pose top-level keys changed; remeasure bending evidence instead of rebinding"
        )
    known_pieces = set(base_poses) | set(cur_poses)
    changed_blocks: list[str] = []
    protected_tokens = set(protected_piece_ids) | {component}
    for key in sorted(k for k in baseline_pose if k != "poses"):
        base_val = baseline_pose[key]
        cur_val = current_pose[key]
        if base_val == cur_val:
            continue
        if key in GLOBAL_ASSEMBLY_POSE_KEYS:
            raise ValueError(
                f"Assembly pose global key '{key}' changed; "
                "remeasure bending evidence instead of rebinding"
            )
        if isinstance(base_val, dict) and isinstance(cur_val, dict):
            base_refs = _block_referenced_pieces(base_val)
            cur_refs = _block_referenced_pieces(cur_val)
            if base_refs is not None and cur_refs is not None:
                if (base_refs | cur_refs).isdisjoint(protected_piece_ids):
                    changed_blocks.append(key)
                    continue
                raise ValueError(
                    f"Assembly pose block '{key}' affects component-relevant pieces; "
                    "remeasure bending evidence instead of rebinding"
                )
            if (
                base_val
                and cur_val
                and set(base_val).issubset(known_pieces)
                and set(cur_val).issubset(known_pieces)
            ):
                changed_subkeys = {
                    sub
                    for sub in set(base_val) | set(cur_val)
                    if base_val.get(sub) != cur_val.get(sub)
                }
                if changed_subkeys.isdisjoint(protected_piece_ids):
                    changed_blocks.append(key)
                    continue
                raise ValueError(
                    f"Assembly pose per-piece block '{key}' changed component-relevant pieces; "
                    "remeasure bending evidence instead of rebinding"
                )
            if set(base_val.keys()) == set(cur_val.keys()):
                changed_subkeys = {
                    sub for sub in base_val if base_val[sub] != cur_val[sub]
                }
                blob = key + "\n" + json.dumps(base_val) + "\n" + json.dumps(cur_val)
                if (
                    changed_subkeys
                    and changed_subkeys.issubset(PROSE_ONLY_POSE_KEYS)
                    and all(
                        isinstance(base_val[sub], str) and isinstance(cur_val[sub], str)
                        for sub in changed_subkeys
                    )
                    and not any(token in blob for token in protected_tokens)
                ):
                    changed_blocks.append(key)
                    continue
        raise ValueError(
            f"Assembly pose block '{key}' changed non-prose or component-relevant data; "
            "remeasure bending evidence instead of rebinding"
        )
    return changed_pose_pieces, changed_blocks


def _verify_component_mesh_in_blender(
    job: dict[str, Any],
    groups: dict[str, list[str]],
    component: str,
    old_evidence: dict[str, Any],
    repo_root: Path,
) -> bool:
    if bpy is None:
        return False
    blend_rel = job.get("manufacturingBlendPath", job.get("blendPath"))
    if not isinstance(blend_rel, str) or not blend_rel.strip():
        return False
    blend_path = repo_path(blend_rel, root=repo_root)
    if not blend_path.is_file():
        raise ValueError(f"Prototype .blend file is missing: {blend_rel}")
    bpy.ops.wm.open_mainfile(filepath=str(blend_path), load_ui=False)
    original = bpy.data.objects.get(str(job["id"]))
    if original is None or original.type != "MESH":
        raise ValueError("canonical sewn prototype is missing")
    pieces = json.loads(original["canonicalPieceIds"])
    owners = original.data.attributes["canonical_piece_index"]
    faces = [list(face.vertices) for face in original.data.polygons]
    group = groups[component]
    indices = [i for i, owner in enumerate(owners.data) if pieces[owner.value] in group]
    if not indices:
        raise ValueError(f"Cloth component '{component}' has no faces in .blend")
    ids = sorted({v for i in indices for v in faces[i]})
    remap = {value: index for index, value in enumerate(ids)}
    data = bpy.data.meshes.new(component + "-rebind-check")
    data.from_pydata(
        [original.data.vertices[i].co[:] for i in ids],
        [],
        [[remap[v] for v in faces[i]] for i in indices],
    )
    data.update()
    probe = bpy.data.objects.new(component + "-rebind-check", data)
    bpy.context.collection.objects.link(probe)
    probe.matrix_world = original.matrix_world.copy()
    try:
        actual_mesh_sha = mesh_hash(probe)
    finally:
        bpy.data.objects.remove(probe, do_unlink=True)
        bpy.data.meshes.remove(data, do_unlink=True)
    expected_mesh_sha = old_evidence.get("sourceComponentMeshSha256") or old_evidence.get(
        "sourceSkirtMeshSha256"
    )
    if expected_mesh_sha is not None and actual_mesh_sha != expected_mesh_sha:
        raise ValueError(
            f"Blender component mesh changed for '{component}'; "
            "remeasure bending evidence instead of rebinding"
        )
    return True


def verify_component_bending_rebind_preconditions(
    job: dict[str, Any],
    component: str,
    baseline_revision: str,
    *,
    baseline_pattern_current_if_evidence_matches: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    base_root = (root or ROOT).resolve()
    comp = _require_non_empty_str(component, "rebind-bending-component")
    rev_input = _require_non_empty_str(baseline_revision, "baseline-revision")
    product_id = _require_non_empty_str(job.get("id"), "job.id")
    pipeline = job.get("garmentPipeline")
    if not isinstance(pipeline, dict):
        raise ValueError("job.garmentPipeline is required")

    construction_rel = _require_non_empty_str(
        pipeline.get("constructionPath"), "garmentPipeline.constructionPath"
    )
    assembly_pose_rel = _require_non_empty_str(
        pipeline.get("assemblyPosePath"), "garmentPipeline.assemblyPosePath"
    )
    pattern_rel = _require_non_empty_str(
        pipeline.get("patternContractPath"), "garmentPipeline.patternContractPath"
    )
    target_rel = _require_non_empty_str(
        job.get("targetSourcePath"), "job.targetSourcePath"
    )
    stitch_rel = pipeline.get("stitchGraphPath")
    if stitch_rel is not None:
        stitch_rel = _require_non_empty_str(stitch_rel, "garmentPipeline.stitchGraphPath")

    construction_path = repo_path(construction_rel, root=base_root)
    assembly_pose_path = repo_path(assembly_pose_rel, root=base_root)
    pattern_path = repo_path(pattern_rel, root=base_root)
    target_path = repo_path(target_rel, root=base_root)
    for label, path in (
        ("constructionPath", construction_path),
        ("assemblyPosePath", assembly_pose_path),
        ("patternContractPath", pattern_path),
        ("targetSourcePath", target_path),
    ):
        if not path.is_file():
            raise ValueError(f"Required input file is missing ({label}): {path}")

    current_construction_bytes = construction_path.read_bytes()
    current_construction = parse_json_bytes(current_construction_bytes, construction_rel)
    policy = current_construction.get("clothSimulation")
    if not isinstance(policy, dict):
        raise ValueError("construction.clothSimulation is required")
    groups = policy.get("prototypePanelGroups")
    bending = policy.get("prototypeComponentBending")
    if not isinstance(groups, dict) or not isinstance(bending, dict):
        raise ValueError(
            "construction.clothSimulation requires prototypePanelGroups and prototypeComponentBending"
        )
    if comp not in groups or comp not in bending:
        raise ValueError(f"Unknown or undeclared bending component: {comp}")
    piece_ids = groups[comp]
    if (
        not isinstance(piece_ids, list)
        or not piece_ids
        or not all(isinstance(pid, str) and pid for pid in piece_ids)
        or len(set(piece_ids)) != len(piece_ids)
    ):
        raise ValueError(f"Invalid prototypePanelGroups declaration for '{comp}'")
    frame_end = policy.get("prototypeFrameEnd")
    if isinstance(frame_end, bool) or not isinstance(frame_end, int) or not 2 <= frame_end <= 120:
        raise ValueError("bounded prototype frame range is required")

    declared = bending[comp]
    if not isinstance(declared, dict):
        raise ValueError(f"Bending declaration for '{comp}' must be an object")
    stiffness = declared.get("stiffness")
    if (
        isinstance(stiffness, bool)
        or not isinstance(stiffness, (int, float))
        or not math.isfinite(stiffness)
        or not 0 <= stiffness <= 10000
    ):
        raise ValueError("Finite numeric bending stiffness in [0, 10000] is required")
    old_evidence_rel = _require_non_empty_str(
        declared.get("evidencePath"), "evidencePath"
    )
    old_evidence_sha = _require_non_empty_str(
        declared.get("evidenceSha256"), "evidenceSha256"
    )
    if not HEX64_RE.fullmatch(old_evidence_sha):
        raise ValueError("Bending comparison evidence sha256 must be 64 lowercase hex")
    _require_non_empty_str(declared.get("evidenceBoundary"), "evidenceBoundary")

    old_evidence_path = repo_path(old_evidence_rel, root=base_root)
    if not old_evidence_path.is_file():
        raise ValueError(
            f"Bending comparison evidence file is missing: {old_evidence_rel}"
        )
    old_evidence_bytes = old_evidence_path.read_bytes()
    if sha256_bytes(old_evidence_bytes) != old_evidence_sha:
        raise ValueError("Bending comparison evidence hash mismatch")
    old_evidence = parse_json_bytes(old_evidence_bytes, old_evidence_rel)
    if (
        old_evidence.get("productId") != product_id
        or old_evidence.get("bendingStiffness") != stiffness
        or old_evidence.get("frameEnd") != frame_end
        or old_evidence.get("cacheBaked") is not True
        or not isinstance(old_evidence.get("blenderVersion"), str)
        or not old_evidence["blenderVersion"]
        or not isinstance(old_evidence.get("bendingModel"), str)
        or not old_evidence["bendingModel"]
    ):
        raise ValueError("Bending comparison is incompatible with this solve")
    if bpy is not None and old_evidence.get("blenderVersion") != bpy.app.version_string:
        raise ValueError("Bending comparison is incompatible with this solve")

    resolved_commit = _resolve_git_commit(rev_input, base_root)
    baseline_pose_bytes = _read_git_file_bytes(
        resolved_commit, assembly_pose_rel, base_root
    )
    baseline_pattern_bytes = _read_git_file_bytes(
        resolved_commit, pattern_rel, base_root
    )
    baseline_construction_bytes = _read_git_file_bytes(
        resolved_commit, construction_rel, base_root
    )

    baseline_pose_sha = sha256_bytes(baseline_pose_bytes)
    baseline_pattern_sha = sha256_bytes(baseline_pattern_bytes)
    current_pose_bytes = assembly_pose_path.read_bytes()
    current_pattern_bytes = pattern_path.read_bytes()
    current_target_bytes = target_path.read_bytes()
    current_pose_sha = sha256_bytes(current_pose_bytes)
    current_pattern_sha = sha256_bytes(current_pattern_bytes)
    current_target_sha = sha256_bytes(current_target_bytes)

    if old_evidence.get("assemblyPoseSha256") != baseline_pose_sha:
        raise ValueError(
            "Baseline revision does not match existing bending comparison evidence: assemblyPoseSha256"
        )
    baseline_pattern_source = "baseline-revision"
    if old_evidence.get("patternSha256") != baseline_pattern_sha:
        if (
            baseline_pattern_current_if_evidence_matches
            and sha256_bytes(current_pattern_bytes) == old_evidence.get("patternSha256")
        ):
            # The prior measurement is itself hash-bound to this exact generated
            # pattern input. Use those bytes as the invariant baseline instead of
            # inventing a different committed pattern revision.
            baseline_pattern_bytes = current_pattern_bytes
            baseline_pattern_sha = sha256_bytes(baseline_pattern_bytes)
            baseline_pattern_source = "current-pattern-matching-prior-evidence-sha256"
        else:
            raise ValueError(
                "Baseline revision does not match existing bending comparison evidence: patternSha256"
            )
    if old_evidence.get("targetSourceSha256") != current_target_sha:
        raise ValueError(
            "Target source changed; bending comparison must be remeasured"
        )

    baseline_construction = parse_json_bytes(
        baseline_construction_bytes, f"{resolved_commit}:{construction_rel}"
    )
    _validate_cloth_policy_invariance(baseline_construction, current_construction, comp)

    protected_piece_ids = set(piece_ids)
    if stitch_rel is not None:
        stitch_path = repo_path(stitch_rel, root=base_root)
        if not stitch_path.is_file():
            raise ValueError(f"Required input file is missing (stitchGraphPath): {stitch_path}")
        baseline_stitch_bytes = _read_git_file_bytes(
            resolved_commit, stitch_rel, base_root
        )
        baseline_stitch = parse_json_bytes(
            baseline_stitch_bytes, f"{resolved_commit}:{stitch_rel}"
        )
        current_stitch = parse_json_bytes(stitch_path.read_bytes(), stitch_rel)
        base_touched, base_neighbors = _extract_component_stitches(
            baseline_stitch, set(piece_ids), f"{resolved_commit}:{stitch_rel}"
        )
        cur_touched, cur_neighbors = _extract_component_stitches(
            current_stitch, set(piece_ids), stitch_rel
        )
        if base_touched != cur_touched:
            raise ValueError(
                f"Stitch graph changed for '{comp}'; remeasure bending evidence instead of rebinding"
            )
        protected_piece_ids.update(base_neighbors | cur_neighbors)

    baseline_pattern = parse_json_bytes(
        baseline_pattern_bytes, f"{resolved_commit}:{pattern_rel}"
    )
    current_pattern = parse_json_bytes(current_pattern_bytes, pattern_rel)
    for key in GLOBAL_PATTERN_KEYS:
        if baseline_pattern.get(key) != current_pattern.get(key):
            raise ValueError(
                f"Pattern global field '{key}' changed; remeasure bending evidence instead of rebinding"
            )
    base_pieces = _index_pattern_pieces(
        baseline_pattern, f"{resolved_commit}:{pattern_rel}"
    )
    cur_pieces = _index_pattern_pieces(current_pattern, pattern_rel)
    for pid in sorted(protected_piece_ids):
        if pid not in base_pieces or pid not in cur_pieces:
            raise ValueError(
                f"Pattern is missing component-relevant piece '{pid}'"
            )
        if base_pieces[pid] != cur_pieces[pid]:
            raise ValueError(
                f"Pattern changed for component-relevant piece '{pid}'; "
                "remeasure bending evidence instead of rebinding"
            )
    changed_pattern_pieces = sorted(
        pid
        for pid in set(base_pieces) | set(cur_pieces)
        if base_pieces.get(pid) != cur_pieces.get(pid)
    )

    baseline_pose = parse_json_bytes(
        baseline_pose_bytes, f"{resolved_commit}:{assembly_pose_rel}"
    )
    current_pose = parse_json_bytes(current_pose_bytes, assembly_pose_rel)
    changed_pose_pieces, changed_pose_blocks = _validate_assembly_pose_invariance(
        baseline_pose, current_pose, protected_piece_ids, comp
    )

    mesh_verified = _verify_component_mesh_in_blender(
        job, groups, comp, old_evidence, base_root
    )

    return {
        "root": base_root,
        "productId": product_id,
        "component": comp,
        "pieceIds": list(piece_ids),
        "protectedPieceIds": sorted(protected_piece_ids),
        "baselineRevisionInput": rev_input,
        "baselineRevision": resolved_commit,
        "constructionPath": construction_path,
        "constructionBytes": current_construction_bytes,
        "construction": current_construction,
        "oldEvidencePath": old_evidence_path,
        "oldEvidenceRel": old_evidence_rel,
        "oldEvidenceSha256": old_evidence_sha,
        "oldEvidence": old_evidence,
        "baselineAssemblyPoseSha256": baseline_pose_sha,
        "baselinePatternSha256": baseline_pattern_sha,
        "baselinePatternSource": baseline_pattern_source,
        "currentAssemblyPoseSha256": current_pose_sha,
        "currentPatternSha256": current_pattern_sha,
        "currentTargetSha256": current_target_sha,
        "changedPatternPieces": changed_pattern_pieces,
        "changedPosePieces": changed_pose_pieces,
        "changedPoseBlocks": changed_pose_blocks,
        "meshHashVerifiedInBlender": mesh_verified,
    }


def _content_addressed_evidence_path(
    base_root: Path,
    product_id: str,
    component: str,
    old_evidence_path: Path,
    new_sha256: str,
) -> Path:
    stem = old_evidence_path.stem
    if CONTENT_HASH_SUFFIX_RE.search(stem):
        prefix = CONTENT_HASH_SUFFIX_RE.sub("", stem)
    else:
        prefix = f"{component}-bending"
    return (
        base_root
        / ".image2outfit"
        / "products"
        / product_id
        / "evidence"
        / f"{prefix}-{new_sha256[:16]}.json"
    )


def rebind_component_bending(
    job: dict[str, Any],
    component: str,
    baseline_revision: str,
    *,
    baseline_pattern_current_if_evidence_matches: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    checked = verify_component_bending_rebind_preconditions(
        job,
        component,
        baseline_revision,
        baseline_pattern_current_if_evidence_matches=baseline_pattern_current_if_evidence_matches,
        root=root,
    )
    if (
        checked["currentAssemblyPoseSha256"] == checked["baselineAssemblyPoseSha256"]
        and checked["currentPatternSha256"] == checked["baselinePatternSha256"]
    ):
        return {
            "status": "UNCHANGED",
            "productId": checked["productId"],
            "component": checked["component"],
            "baselineRevision": checked["baselineRevision"],
            "evidencePath": checked["oldEvidenceRel"],
            "evidenceSha256": checked["oldEvidenceSha256"],
            "meshHashVerifiedInBlender": checked["meshHashVerifiedInBlender"],
        }

    rebound_evidence = json.loads(json.dumps(checked["oldEvidence"]))
    rebound_evidence["assemblyPoseSha256"] = checked["currentAssemblyPoseSha256"]
    rebound_evidence["patternSha256"] = checked["currentPatternSha256"]
    rebound_evidence["targetSourceSha256"] = checked["currentTargetSha256"]
    rebound_evidence["constructionSha256"] = sha256_bytes(checked["constructionBytes"])
    rebound_evidence["clothImplementationSha256"] = sha256_bytes(
        Path(__file__).read_bytes()
    )
    blend_rel = job.get("manufacturingBlendPath", job.get("blendPath"))
    if isinstance(blend_rel, str) and blend_rel.strip():
        blend_path = repo_path(blend_rel, root=checked["root"])
        if blend_path.is_file():
            rebound_evidence["sourceBlendSha256"] = sha256_bytes(blend_path.read_bytes())
    rebound_evidence["grantsFitAcceptance"] = False
    rebound_evidence["grantsVisualAcceptance"] = False
    rebound_evidence["rebindProvenance"] = {
        "method": "baseline-component-invariance-rebind",
        "component": checked["component"],
        "pieceIds": checked["pieceIds"],
        "protectedPieceIds": checked["protectedPieceIds"],
        "baselineRevision": checked["baselineRevision"],
        "baselineRevisionInput": checked["baselineRevisionInput"],
        "baselineEvidencePath": checked["oldEvidenceRel"],
        "baselineEvidenceSha256": checked["oldEvidenceSha256"],
        "baselineAssemblyPoseSha256": checked["baselineAssemblyPoseSha256"],
        "baselinePatternSha256": checked["baselinePatternSha256"],
        "baselinePatternSource": checked["baselinePatternSource"],
        "unchangedTargetSourceSha256": checked["currentTargetSha256"],
        "changedNonComponentPatternPieces": checked["changedPatternPieces"],
        "changedNonComponentPosePieces": checked["changedPosePieces"],
        "changedNonComponentPoseBlocks": checked["changedPoseBlocks"],
        "meshHashVerifiedInBlender": checked["meshHashVerifiedInBlender"],
        "grantsFitAcceptance": False,
        "grantsVisualAcceptance": False,
        "evidenceBoundary": (
            "Rebound from verified baseline bending evidence after proving all "
            "component pieces, directly stitched neighbor pieces, component "
            "placement blocks, cloth policy, and target source are unchanged "
            "between baselineRevision and current inputs. Does not re-run "
            "Blender Cloth or grant fit, pose, or visual acceptance."
        ),
    }

    evidence_bytes = (
        json.dumps(rebound_evidence, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    new_sha256 = sha256_bytes(evidence_bytes)
    new_evidence_path = _content_addressed_evidence_path(
        checked["root"],
        checked["productId"],
        checked["component"],
        checked["oldEvidencePath"],
        new_sha256,
    )
    atomic_write_bytes(new_evidence_path, evidence_bytes)
    if sha256_bytes(new_evidence_path.read_bytes()) != new_sha256:
        raise RuntimeError("Written rebound bending evidence hash mismatch")

    new_evidence_rel = str(
        new_evidence_path.relative_to(checked["root"])
    ).replace("\\", "/")
    updated_construction = json.loads(json.dumps(checked["construction"]))
    declared = updated_construction["clothSimulation"]["prototypeComponentBending"][
        checked["component"]
    ]
    declared["evidencePath"] = new_evidence_rel
    declared["evidenceSha256"] = new_sha256
    declared["evidenceBoundary"] = (
        f"Pattern-bound native Blender {rebound_evidence['blenderVersion']}, "
        f"{rebound_evidence['frameEnd']}-frame isolated {checked['component']} "
        f"bending comparison at stiffness {declared['stiffness']}, rebound from "
        f"baseline {checked['baselineRevision'][:7]} "
        f"({checked['oldEvidenceSha256'][:16]}) after verifying component and "
        "stitched-seam invariance. Diagnostic geometry only; no fit, pose, or "
        "visual acceptance."
    )
    construction_bytes = (
        json.dumps(updated_construction, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    atomic_write_bytes(checked["constructionPath"], construction_bytes)

    return {
        "status": "REBOUND",
        "productId": checked["productId"],
        "component": checked["component"],
        "baselineRevision": checked["baselineRevision"],
        "previousEvidencePath": checked["oldEvidenceRel"],
        "previousEvidenceSha256": checked["oldEvidenceSha256"],
        "evidencePath": new_evidence_rel,
        "evidenceSha256": new_sha256,
        "changedNonComponentPatternPieces": checked["changedPatternPieces"],
        "changedNonComponentPosePieces": checked["changedPosePieces"],
        "changedNonComponentPoseBlocks": checked["changedPoseBlocks"],
        "meshHashVerifiedInBlender": checked["meshHashVerifiedInBlender"],
    }


def bake_sewn_prototype(job: dict[str, object]) -> int:
    """Run a bounded solve on attributed panels, preserving the input .blend."""
    _require_blender()
    blend = repo_path(str(job.get("manufacturingBlendPath", job["blendPath"])))
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
            modifier = obj.modifiers["Image2Outfit Cloth"]
            limits = modifier.settings.bl_rna.properties["bending_stiffness"]
            value, _ = validate_component_bending_evidence(
                job,
                declared,
                frame_end=frame_end,
                blender_version=bpy.app.version_string,
                bending_model=modifier.settings.bending_model,
                stiffness_min=limits.hard_min,
                stiffness_max=limits.hard_max,
            )
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


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    options = parse_args(argv)
    job = read_json(repo_path(options.job, root=root))
    if options.baseline_pattern_current_if_evidence_matches and (
        options.rebind_bending_component is None
        or options.baseline_revision is None
    ):
        raise ValueError(
            "--baseline-pattern-current-if-evidence-matches requires a bending rebind"
        )
    if (
        options.rebind_bending_component is not None
        or options.baseline_revision is not None
    ):
        if (
            options.rebind_bending_component is None
            or options.baseline_revision is None
            or not options.rebind_bending_component.strip()
            or not options.baseline_revision.strip()
        ):
            raise ValueError(
                "--rebind-bending-component and --baseline-revision must be provided together"
            )
        if options.prototype or options.force:
            raise ValueError(
                "--rebind-bending-component cannot be combined with --prototype or --force"
            )
        result = rebind_component_bending(
            job,
            options.rebind_bending_component,
            options.baseline_revision,
            baseline_pattern_current_if_evidence_matches=(
                options.baseline_pattern_current_if_evidence_matches
            ),
            root=root,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    _require_blender()
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
    blend = repo_path(str(job.get("manufacturingBlendPath", job["blendPath"])))
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
