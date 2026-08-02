#!/usr/bin/env python3
"""Build the Cyber Kawaii set for the standard Siroino PC body.

The historical product slug retains ``-large`` for workspace continuity, but
this build intentionally targets the official unmodified SiroinoSotai PC body.
It replaces the rejected rigid first-pass geometry with body-weighted sleeves
and a closed, non-degenerate pelvis-weighted skirt shell.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

import siroino_cyber_kawaii_large_build as legacy
import siroino_strappy_knit_build as base

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_IMPROVE_CLEARANCE = legacy.g.improve_clearance


def repo_path(value: str) -> Path:
    return base.repo_path(value)


def apply_standard_profile(
    body: bpy.types.Object,
    requested: dict[str, float] | None = None,
) -> dict[str, object]:
    """Use the official neutral PC body without applying size shape keys."""

    keys = body.data.shape_keys.key_blocks if body.data.shape_keys else None
    if keys is not None:
        for block in keys:
            block.value = 0.0
    bpy.context.view_layer.update()
    return {
        "profile": "Siroino standard PC body",
        "appliedShapeKeys": {},
        "vertices": len(body.data.vertices),
    }


def bone_segment(armature: bpy.types.Object, bone_name: str) -> tuple[Vector, Vector]:
    bone = armature.data.bones.get(bone_name)
    if bone is None:
        raise RuntimeError(f"Required Siroino bone missing: {bone_name}")
    return armature.matrix_world @ bone.head_local, armature.matrix_world @ bone.tail_local


def near_segment(
    point: Vector,
    start: Vector,
    end: Vector,
    *,
    t0: float,
    t1: float,
    radius: float,
) -> bool:
    direction = end - start
    length_squared = direction.length_squared
    if length_squared <= 1e-12:
        return False
    t = (point - start).dot(direction) / length_squared
    if not t0 <= t <= t1:
        return False
    closest = start + direction * t
    return (point - closest).length <= radius


def stable_shell(
    name: str,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    rings: tuple[tuple[float, float, float], ...],
    *,
    pleats: int,
    thickness: float,
    group: str = "Hips",
    uv_repeats: float = 2.5,
    fold_strength: float = 0.024,
) -> bpy.types.Object:
    """Create a closed shell without bevel/solidify zero-area triangles."""

    if len(rings) < 2:
        raise ValueError("stable_shell requires at least two rings")
    segments = max(48, pleats * 4)
    outer_count = len(rings) * segments
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []

    def coordinate(
        z: float,
        rx: float,
        ry: float,
        index: int,
        inset: float,
    ) -> tuple[float, float, float]:
        angle = math.tau * index / segments
        fold = 1.0 + fold_strength * math.cos(angle * pleats)
        return (
            max(0.001, rx - inset) * fold * math.cos(angle),
            max(0.001, ry - inset) * fold * math.sin(angle),
            z,
        )

    for z, rx, ry in rings:
        vertices.extend(coordinate(z, rx, ry, index, 0.0) for index in range(segments))
    for z, rx, ry in rings:
        vertices.extend(
            coordinate(z, rx, ry, index, thickness) for index in range(segments)
        )

    ring_count = len(rings)
    for ring_index in range(ring_count - 1):
        outer_a = ring_index * segments
        outer_b = (ring_index + 1) * segments
        inner_a = outer_count + ring_index * segments
        inner_b = outer_count + (ring_index + 1) * segments
        for index in range(segments):
            nxt = (index + 1) % segments
            faces.append((outer_a + index, outer_a + nxt, outer_b + nxt, outer_b + index))
            faces.append((inner_a + index, inner_b + index, inner_b + nxt, inner_a + nxt))

    for ring_index in (0, ring_count - 1):
        outer = ring_index * segments
        inner = outer_count + ring_index * segments
        reverse = ring_index == 0
        for index in range(segments):
            nxt = (index + 1) % segments
            if reverse:
                faces.append((outer + index, inner + index, inner + nxt, outer + nxt))
            else:
                faces.append((outer + index, outer + nxt, inner + nxt, inner + index))

    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    z_top = rings[0][0]
    z_bottom = rings[-1][0]
    z_span = max(1e-6, abs(z_top - z_bottom))
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            local_index = vertex_index % segments
            z = mesh.vertices[vertex_index].co.z
            u = (local_index / segments) * uv_repeats
            if vertex_index >= outer_count:
                u = -u
            uv_layer.data[loop_index].uv = (u, abs(z_top - z) / z_span)
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    base.rigid_mesh_weight(obj, armature, group)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def box_ribbon(
    name: str,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    material: bpy.types.Material,
    armature: bpy.types.Object,
    group: str,
) -> bpy.types.Object:
    cx, cy, cz = center
    sx, sy, sz = size
    vertices = [
        (cx + dx * sx, cy + dy * sy, cz + dz * sz)
        for dz in (-1.0, 1.0)
        for dy in (-1.0, 1.0)
        for dx in (-1.0, 1.0)
    ]
    faces = [
        (0, 1, 3, 2),
        (4, 6, 7, 5),
        (0, 4, 5, 1),
        (2, 3, 7, 6),
        (0, 2, 6, 4),
        (1, 5, 7, 3),
    ]
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    base.rigid_mesh_weight(obj, armature, group)
    return obj


def chest_bow(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    pink: bpy.types.Material,
) -> list[bpy.types.Object]:
    y = base.body_front_y(body, 0.0, 0.958) - 0.016
    return [
        box_ribbon(
            "Pink_Collar_Bow_L",
            (-0.014, y, 0.958),
            (0.014, 0.0032, 0.008),
            pink,
            armature,
            "Chest",
        ),
        box_ribbon(
            "Pink_Collar_Bow_R",
            (0.014, y, 0.958),
            (0.014, 0.0032, 0.008),
            pink,
            armature,
            "Chest",
        ),
        box_ribbon(
            "Pink_Collar_Bow_Knot",
            (0.0, y - 0.001, 0.958),
            (0.006, 0.0040, 0.006),
            pink,
            armature,
            "Chest",
        ),
    ]


def create_outfit(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    materials: dict[str, bpy.types.Material],
) -> list[bpy.types.Object]:
    white = materials["white"]
    plaid = materials["plaid"]
    pink = materials["pink"]
    black = materials["black"]
    garments: list[bpy.types.Object] = []

    garments.extend(
        [
            base.extract_surface(
                body,
                armature,
                "White_Cropped_Blouse_Front",
                lambda c: 0.835 <= c.z <= 1.018 and c.y < 0.005 and abs(c.x) <= 0.145,
                white,
                0.0080,
            ),
            base.extract_surface(
                body,
                armature,
                "White_Cropped_Blouse_Back",
                lambda c: 0.842 <= c.z <= 0.990 and c.y >= -0.006 and abs(c.x) <= 0.143,
                white,
                0.0078,
            ),
            base.extract_surface(
                body,
                armature,
                "White_Waist_Base",
                lambda c: 0.708 <= c.z <= 0.795 and abs(c.x) <= 0.155,
                white,
                0.0070,
            ),
        ]
    )

    garments.extend(
        [
            stable_shell(
                "Black_Pink_Plaid_Pleated_Skirt",
                armature,
                plaid,
                ((0.790, 0.150, 0.110), (0.706, 0.174, 0.128), (0.625, 0.198, 0.147)),
                pleats=16,
                thickness=0.0015,
                uv_repeats=3.0,
                fold_strength=0.020,
            ),
            stable_shell(
                "White_Ruffle_Underskirt",
                armature,
                white,
                ((0.650, 0.184, 0.137), (0.595, 0.207, 0.154)),
                pleats=20,
                thickness=0.0013,
                uv_repeats=2.0,
                fold_strength=0.016,
            ),
            stable_shell(
                "Black_Skirt_Waistband",
                armature,
                black,
                ((0.795, 0.152, 0.112), (0.777, 0.155, 0.114)),
                pleats=16,
                thickness=0.0014,
                uv_repeats=1.0,
                fold_strength=0.008,
            ),
            stable_shell(
                "Pink_Underskirt_Hem",
                armature,
                pink,
                ((0.605, 0.202, 0.151), (0.590, 0.208, 0.155)),
                pleats=20,
                thickness=0.0012,
                uv_repeats=1.0,
                fold_strength=0.014,
            ),
        ]
    )

    garments.append(
        base.extract_surface(
            body,
            armature,
            "White_Thigh_High_Stockings",
            lambda c: 0.090 <= c.z <= 0.490 and abs(c.x) >= 0.016,
            white,
            0.0062,
        )
    )

    for side_name in ("L", "R"):
        upper_start, upper_end = bone_segment(armature, f"UpperArm_{side_name}")
        garments.append(
            base.extract_surface(
                body,
                armature,
                f"White_Puff_Sleeve_{side_name}",
                lambda c, a=upper_start, b=upper_end: near_segment(
                    c, a, b, t0=0.02, t1=0.32, radius=0.068
                ),
                white,
                0.0100,
            )
        )
        lower_start, lower_end = bone_segment(armature, f"LowerArm_{side_name}")
        garments.append(
            base.extract_surface(
                body,
                armature,
                f"White_Detached_Sleeve_{side_name}",
                lambda c, a=lower_start, b=lower_end: near_segment(
                    c, a, b, t0=0.10, t1=0.82, radius=0.050
                ),
                white,
                0.0075,
            )
        )

    garments.extend(chest_bow(body, armature, pink))
    return garments


def robust_clean_meshes(objects: list[bpy.types.Object]) -> None:
    for obj in objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        for _ in range(3):
            bm = bmesh.new()
            bm.from_mesh(mesh)
            bmesh.ops.dissolve_degenerate(bm, dist=1e-8, edges=list(bm.edges))
            zero_faces = [face for face in bm.faces if face.calc_area() <= 1e-12]
            if zero_faces:
                bmesh.ops.delete(bm, geom=zero_faces, context="FACES")
            if bm.faces:
                bmesh.ops.triangulate(bm, faces=list(bm.faces))
            loose = [vertex for vertex in bm.verts if not vertex.link_faces]
            if loose:
                bmesh.ops.delete(bm, geom=loose, context="VERTS")
            bm.to_mesh(mesh)
            bm.free()
            mesh.update(calc_edges=True)

            mesh.calc_loop_triangles()
            degenerate_polygons = {
                triangle.polygon_index
                for triangle in mesh.loop_triangles
                if (
                    (mesh.vertices[triangle.vertices[1]].co - mesh.vertices[triangle.vertices[0]].co)
                    .cross(mesh.vertices[triangle.vertices[2]].co - mesh.vertices[triangle.vertices[0]].co)
                    .length_squared
                    <= 1e-20
                )
            }
            if not degenerate_polygons:
                break
            cleanup = bmesh.new()
            cleanup.from_mesh(mesh)
            cleanup.faces.ensure_lookup_table()
            doomed = [
                cleanup.faces[index]
                for index in sorted(degenerate_polygons)
                if index < len(cleanup.faces)
            ]
            if doomed:
                bmesh.ops.delete(cleanup, geom=doomed, context="FACES")
            loose = [vertex for vertex in cleanup.verts if not vertex.link_faces]
            if loose:
                bmesh.ops.delete(cleanup, geom=loose, context="VERTS")
            cleanup.to_mesh(mesh)
            cleanup.free()
            mesh.update(calc_edges=True)


def strict_improve_clearance(body, garments, *, targets, movable):
    return ORIGINAL_IMPROVE_CLEARANCE(
        body,
        garments,
        targets=(0.0028, 0.0042, 0.0052),
        movable=movable,
    )


def refresh_hashes(product_root: Path) -> None:
    files = sorted(
        path
        for path in product_root.rglob("*")
        if path.is_file() and path.name != "SOURCE_HASHES.txt"
    )
    (product_root / "SOURCE_HASHES.txt").write_text(
        "\n".join(
            f"{base.sha256(path)}  {path.relative_to(product_root).as_posix()}"
            for path in files
        )
        + "\n",
        encoding="utf-8",
    )


def rewrite_handoff(job: dict, return_code: int) -> None:
    product_root = repo_path(job["productRoot"])
    artifact_dir = repo_path(job["artifactDir"])
    report_path = artifact_dir / "product-build-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    passed = bool(report.get("passed")) and return_code == 0
    report["targetProfile"] = {
        "profile": "Siroino standard PC body",
        "appliedShapeKeys": {},
        "vertices": report.get("targetProfile", {}).get("vertices"),
    }
    report["visualRevision"] = "v3-standard-body-stable-shell"
    report["notes"] = [
        "The tracked official neutral SiroinoSotai PC FBX is the target source.",
        "No _Large shape keys are required or applied.",
        "The skirt is a closed non-degenerate shell weighted to Hips; sleeves and stockings inherit official body weights.",
        "The product delivery contains only original garment assets and renders.",
        "Five-view and pose images are actual Blender renders of this generated scene.",
    ]
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schemaVersion": 1,
        "productId": job["id"],
        "productName": job["productName"],
        "status": "WORKING" if passed else "REJECTED",
        "targetAdapterId": job["adapterId"],
        "target": "Siroino standard PC body",
        "productRoot": job["productRoot"],
        "outfitPrefabPath": job["prefabAssetPath"],
        "integratedPrefabPath": job["integratedPrefabAssetPath"],
        "previewPath": job["previewPaths"]["front"],
        "documentationPath": f"{job['productRoot']}/README.md",
        "sourceJobPath": f"config/products/{job['id']}/job.json",
        "productBuildScript": job["productBuildScript"],
        "designRevision": "v3-standard-body-stable-shell",
        "handoff": {
            "resumable": True,
            "canonicalWorkspace": job["productRoot"],
            "doNotRebuildFromZero": True,
            "resumeFrom": job["productBuildScript"],
            "lastAttempt": {
                "result": "HOSTED_MODELED" if passed else "REJECTED",
                "visualRevision": "v3-standard-body-stable-shell",
            },
            "blockers": [
                "Import and save both Prefabs in pinned Unity",
                "Pass Prefab reload and Modular Avatar/NDMF checks",
                "Complete human multiview, pose-penetration, and VRChat runtime reviews",
            ],
        },
        "technicalGates": {
            "standardTargetResolved": "PASS",
            "blender": "PASS" if passed else "FAIL",
            "fbx": "PASS" if passed else "FAIL",
            "bodyClearance": "PASS" if passed else "FAIL",
            "fiveViewRender": "PASS" if passed else "FAIL",
            "poseRender": "PASS" if passed else "FAIL",
            "unityImport": "PENDING",
            "prefabSerialized": "PENDING",
            "prefabReload": "PENDING",
            "modularAvatar": "PENDING",
            "vrchatBuildAndTest": "PENDING",
            "humanVisualReview": "PENDING",
            "humanPoseReview": "PENDING",
            "humanRuntimeReview": "PENDING",
        },
        "outputs": {
            "blend": job["blendPath"],
            "fbx": job["fbxAssetPath"],
            "prefab": job["prefabAssetPath"],
            "integratedPrefab": job["integratedPrefabAssetPath"],
            "multiview": f"{job['productRoot']}/Previews/{job['id']}-multiview.webp",
            "poseReview": f"{job['productRoot']}/Previews/{job['id']}-pose-review.webp",
        },
    }
    repo_path(job["productManifestPath"]).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (product_root / "README.md").write_text(
        f"""# {job['productName']}

Target: **Siroino standard PC body**. No `_Large` shape keys are required or applied. The historical workspace slug is retained to preserve existing links and handoff continuity.

## Visual revision v3

- closed, non-degenerate plaid skirt shell weighted to the pelvis
- body-weighted shoulder and forearm sleeves for pose stability
- ankle-safe thigh-high stockings that do not cover the feet
- fitted black waistband and pink underskirt hem
- compact chest bow without free-floating waist/thigh ornaments

## Outputs

- Blender source: `{job['blendPath']}`
- FBX: `{job['fbxAssetPath']}`
- outfit Prefab: `{job['prefabAssetPath']}`
- integrated Prefab: `{job['integratedPrefabAssetPath']}`
- five-view render: `{manifest['outputs']['multiview']}`
- pose review: `{manifest['outputs']['poseReview']}`

Unity import, Prefab reload, Modular Avatar/NDMF, and runtime review remain explicit gates.
""",
        encoding="utf-8",
    )
    refresh_hashes(product_root)


def main() -> int:
    _, job = base.load_job()
    legacy.create_outfit = create_outfit
    legacy.clean_meshes = robust_clean_meshes
    legacy.g.apply_large_profile = apply_standard_profile
    legacy.g.improve_clearance = strict_improve_clearance
    return_code = legacy.main()
    rewrite_handoff(job, return_code)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
