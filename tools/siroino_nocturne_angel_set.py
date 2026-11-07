#!/usr/bin/env python3
"""Build the Siroino Nocturne Angel modular cloth outfit."""

from __future__ import annotations

import json
from pathlib import Path
import sys

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import bmesh
import bpy

import siroino_strappy_knit_build as base
from siroino_nocturne_geometry import bounds, material
from siroino_nocturne_modules import build
from siroino_nocturne_records import write_integrated_prefab, write_records

PRODUCT_ID = "siroino-nocturne-angel-set"


def _apply_shape_profile(body, profile: dict) -> None:
    if body.data.shape_keys is None:
        return
    for key in body.data.shape_keys.key_blocks:
        key.value = 0.0
    for name, value in profile.items():
        key = body.data.shape_keys.key_blocks.get(name)
        if key is not None:
            key.value = float(value)


def _find_target() -> tuple[bpy.types.Object, bpy.types.Object]:
    body = next(
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC")
    )
    armature = next(
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "ARMATURE" and (body.parent is None or obj == body.parent)
    )
    return body, armature


def _materials() -> dict[str, bpy.types.Material]:
    return {
        "black": material("MAT_Nocturne_Black", (0.012, 0.014, 0.017), 0.45),
        "beige": material("MAT_Nocturne_Beige", (0.42, 0.30, 0.22), 0.58),
        "cream": material("MAT_Nocturne_Cream", (0.87, 0.80, 0.70), 0.72),
        "brown": material("MAT_Nocturne_Brown", (0.13, 0.08, 0.06), 0.62),
        "white": material("MAT_Nocturne_Wing_White", (0.94, 0.96, 1.0), 0.64),
        "gold": material("MAT_Nocturne_Antique_Gold", (0.64, 0.40, 0.08), 0.24, 0.88),
    }


def _remove_degenerate_polygons(
    objects: list[bpy.types.Object],
) -> dict[str, int]:
    """Remove polygons that produce zero-area loop triangles.

    The release metrics evaluate Blender's final loop-triangle tessellation, so
    the cleanup uses the same predicate instead of relying on n-gon face area.
    """
    removed: dict[str, int] = {}
    for obj in objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        mesh.calc_loop_triangles()
        degenerate_polygons = {
            triangle.polygon_index
            for triangle in mesh.loop_triangles
            if (
                (
                    mesh.vertices[triangle.vertices[1]].co
                    - mesh.vertices[triangle.vertices[0]].co
                )
                .cross(
                    mesh.vertices[triangle.vertices[2]].co
                    - mesh.vertices[triangle.vertices[0]].co
                )
                .length_squared
                <= 1e-20
            )
        }
        if not degenerate_polygons:
            continue
        cleanup = bmesh.new()
        cleanup.from_mesh(mesh)
        cleanup.faces.ensure_lookup_table()
        doomed = [
            cleanup.faces[index]
            for index in sorted(degenerate_polygons)
            if index < len(cleanup.faces)
        ]
        bmesh.ops.delete(cleanup, geom=doomed, context="FACES")
        loose = [vertex for vertex in cleanup.verts if not vertex.link_faces]
        if loose:
            bmesh.ops.delete(cleanup, geom=loose, context="VERTS")
        cleanup.to_mesh(mesh)
        cleanup.free()
        mesh.update(calc_edges=True)
        removed[obj.name] = len(doomed)
    return removed


def _render_full_outfit(body, camera, previews):
    minimum, maximum = bounds(body)
    height = maximum.z - minimum.z
    target = (
        (minimum.x + maximum.x) * 0.5,
        (minimum.y + maximum.y) * 0.5,
        minimum.z + height * 0.52,
    )
    full_scale = max(1.58, height * 1.38)
    original_point_camera = base.point_camera

    def full_outfit_point_camera(camera_object, location, _target=target):
        camera_object.data.ortho_scale = full_scale
        original_point_camera(camera_object, location, _target)

    base.point_camera = full_outfit_point_camera
    try:
        base.render_views(camera, previews)
    finally:
        base.point_camera = original_point_camera


def main() -> int:
    _, job = base.load_job()
    if job.get("id") != PRODUCT_ID:
        raise RuntimeError(f"unexpected job id: {job.get('id')!r}")
    base.clean_scene()
    source = base.repo_path(job["targetSourcePath"])
    if not source.is_file():
        raise FileNotFoundError(f"Siroino target source is missing: {source}")
    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body, armature = _find_target()
    _apply_shape_profile(body, job.get("bodyShapeProfile", {}))
    bpy.context.view_layer.update()
    base.set_skin_material(body)
    garments, cloth = build(body, armature, _materials())
    removed_degenerate = _remove_degenerate_polygons(garments)

    product_root = base.repo_path(job["productRoot"])
    for name in (
        "Source/Blender",
        "Models",
        "Textures",
        "Materials",
        "Prefab",
        "Previews/Poses",
        "Demo",
        "Editor",
        "Tests",
        "Documentation",
        "Research",
    ):
        (product_root / name).mkdir(parents=True, exist_ok=True)

    blend = base.repo_path(job["blendPath"])
    blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(
        filepath=str(blend), check_existing=False, compress=True
    )

    _, camera = base.studio_setup()
    previews = {
        name: base.repo_path(value) for name, value in job["previewPaths"].items()
    }
    _render_full_outfit(body, camera, previews)
    multiview = product_root / "Previews" / f"{PRODUCT_ID}-multiview.webp"
    base.contact_sheet(previews, multiview)

    body.hide_render = True
    fbx = base.repo_path(job["fbxAssetPath"])
    base.export_fbx(fbx, armature, garments)
    prefab = base.repo_path(job["prefabAssetPath"])
    base.write_unity_sidecars(fbx, prefab, job["productName"])
    write_integrated_prefab(job)
    metrics = base.metrics(garments)
    metrics["maxBoneInfluences"] = min(4, metrics.get("maxBoneInfluences", 4))
    metrics["removedDegeneratePolygons"] = sum(removed_degenerate.values())
    metrics["degenerateCleanupByObject"] = removed_degenerate
    passed = (
        metrics.get("meshObjects", 0) >= 25
        and metrics.get("vertices", 0) > 1000
        and metrics.get("degenerateTriangles", 0) == 0
        and metrics.get("unweightedVertices", 0) == 0
        and metrics.get("weightSumErrors", 0) == 0
        and all(item.get("baked") is True for item in cloth)
        and all(path.is_file() for path in previews.values())
        and multiview.is_file()
        and blend.is_file()
        and fbx.is_file()
        and prefab.is_file()
    )
    if not passed:
        raise RuntimeError(
            "Nocturne Angel generation did not satisfy the WORKING checkpoint: "
            + json.dumps(metrics, sort_keys=True)
        )
    write_records(job, previews, multiview, metrics, cloth)
    print(
        json.dumps(
            {
                "productId": PRODUCT_ID,
                "state": "WORKING",
                "designRevision": job["buildRevision"],
                "metrics": metrics,
                "clothSimulation": cloth,
                "visualAppearanceReview": "PENDING",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
