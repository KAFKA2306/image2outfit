#!/usr/bin/env python3
"""Build the Siroino heart-cutout rib-knit long dress and review renders."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector
from PIL import Image

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_strappy_knit_build as common

ROOT = Path(__file__).resolve().parents[1]
DESIGN_REVISION = "v1-parametric-heart-cutout-rib-panel"
REFERENCE_SHA256 = "e7b267d6aa9b9143fb645f85266cb81beb02f09eb4443c1f9c81bfee4daf88d3"


def width_at(z: float) -> float:
    if z >= 1.005:
        return 0.046
    if z >= 0.935:
        return 0.046 + 0.060 * ((1.005 - z) / 0.070)
    if z >= 0.775:
        return 0.108
    if z >= 0.600:
        return 0.108 + 0.020 * ((0.775 - z) / 0.175)
    if z >= 0.360:
        return 0.128 + 0.020 * ((0.600 - z) / 0.240)
    return 0.148 + 0.030 * min(1.0, max(0.0, (0.360 - z) / 0.180))


def heart_inside(x: float, z: float) -> bool:
    xn = x / 0.061
    zn = (z - 0.925) / 0.078
    return (xn * xn + zn * zn - 1.0) ** 3 - xn * xn * zn**3 <= 0.0


def surface_y(body: bpy.types.Object, x: float, z: float, *, front: bool) -> float:
    sample_z = max(0.54, z)
    if front:
        return common.body_front_y(body, x, sample_z) - 0.0065
    return common.body_back_y(body, x, sample_z) + 0.0065


def finish_panel(obj: bpy.types.Object) -> None:
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    loose = [vertex for vertex in bm.verts if not vertex.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.dissolve_degenerate(bm, dist=1e-8, edges=list(bm.edges))
    bm.to_mesh(mesh)
    bm.free()
    mesh.update(calc_edges=True)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    solidify = obj.modifiers.new("Knit thickness", "SOLIDIFY")
    solidify.thickness = 0.0016
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    bevel = obj.modifiers.new("Finished panel edges", "BEVEL")
    bevel.width = 0.00055
    bevel.segments = 2
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    obj.select_set(False)


def build_panel(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    name: str,
    material: bpy.types.Material,
    *,
    front: bool,
) -> bpy.types.Object:
    rows, columns = 48, 34
    z_top, z_bottom = 1.036, 0.180
    vertices = []
    uvs = []
    for row in range(rows + 1):
        z = z_top + (z_bottom - z_top) * row / rows
        width = width_at(z)
        for column in range(columns + 1):
            u = column / columns
            x = -width + 2.0 * width * u
            y = surface_y(body, x, z, front=front)
            if z < 0.54:
                anchor = surface_y(body, x * 0.65, 0.54, front=front)
                y = anchor + ((-0.006 if front else 0.006) * ((0.54 - z) / 0.36))
            vertices.append((x, y, z))
            uvs.append((u, (z - z_bottom) / (z_top - z_bottom)))

    faces = []
    for row in range(rows):
        z0 = z_top + (z_bottom - z_top) * row / rows
        z1 = z_top + (z_bottom - z_top) * (row + 1) / rows
        zc = (z0 + z1) * 0.5
        w0, w1 = width_at(z0), width_at(z1)
        for column in range(columns):
            uc = (column + 0.5) / columns
            xc = ((-w0 + 2.0 * w0 * uc) + (-w1 + 2.0 * w1 * uc)) * 0.5
            if front and heart_inside(xc, zc):
                continue
            if front and zc < 0.405 and abs(xc) < 0.0085:
                continue
            a = row * (columns + 1) + column
            b = a + 1
            d = (row + 1) * (columns + 1) + column
            e = d + 1
            faces.append((a, d, e, b) if front else (a, b, e, d))

    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = uvs[vertex_index]
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    finish_panel(obj)
    common.transfer_nearest_body_weights(obj, body)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    common.add_nearest_shape_keys(obj, body)
    return obj


def arm_warmer(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
) -> bpy.types.Object:
    """Author a detached lower-arm knit tube from the target rig, not body-region guessing."""
    bone = armature.data.bones.get(f"LowerArm_{side}")
    if bone is None:
        raise RuntimeError(f"target armature is missing LowerArm_{side}")
    head = armature.matrix_world @ bone.head_local
    tail = armature.matrix_world @ bone.tail_local
    direction = (tail - head).normalized()
    reference = Vector((0.0, 0.0, 1.0))
    if abs(direction.dot(reference)) > 0.92:
        reference = Vector((0.0, 1.0, 0.0))
    axis_a = direction.cross(reference).normalized()
    axis_b = direction.cross(axis_a).normalized()

    rings = 15
    segments = 28
    vertices = []
    uvs = []
    for ring in range(rings):
        t = ring / (rings - 1)
        along = 0.06 + 0.96 * t
        center = head.lerp(tail, along)
        radius = 0.031 - 0.008 * t + 0.004 * max(0.0, (t - 0.78) / 0.22)
        for segment in range(segments):
            angle = math.tau * segment / segments
            point = center + axis_a * (radius * math.cos(angle)) + axis_b * (
                radius * math.sin(angle)
            )
            vertices.append(tuple(point))
            uvs.append((segment / segments, t))

    faces = []
    for ring in range(rings - 1):
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            a = ring * segments + segment
            b = ring * segments + next_segment
            d = (ring + 1) * segments + segment
            e = (ring + 1) * segments + next_segment
            faces.append((a, d, e, b))

    mesh = bpy.data.meshes.new(f"Rib_Arm_Warmer_{side}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = uvs[vertex_index]
    mesh.materials.append(material)
    obj = bpy.data.objects.new(f"Rib_Arm_Warmer_{side}", mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    finish_panel(obj)
    common.transfer_nearest_body_weights(obj, body)
    common.add_nearest_shape_keys(obj, body)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def side_ties(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    cords = []
    for side, sign in (("L", 1.0), ("R", -1.0)):
        for index, z in enumerate((0.735, 0.670, 0.605)):
            x = sign * width_at(z)
            front = Vector((x, surface_y(body, x, z, front=True) - 0.0015, z))
            back = Vector((x, surface_y(body, x, z, front=False) + 0.0015, z))
            midpoint = (front + back) * 0.5
            midpoint.x += sign * 0.010
            midpoint.z -= 0.006 * index
            cords.append(
                common.curve_tube(
                    f"Side_Tie_{side}_{index + 1}",
                    [front, midpoint, back],
                    0.00155,
                    material,
                    armature,
                    "Hips",
                    resolution=3,
                )
            )
        z = 0.670
        x = sign * width_at(z)
        y = surface_y(body, x, z, front=True)
        cords.append(
            common.curve_tube(
                f"Side_Tail_{side}_A",
                [(x, y - 0.003, z), (x + sign * 0.015, y - 0.010, 0.635), (x + sign * 0.012, y - 0.008, 0.585)],
                0.00135,
                material,
                armature,
                "Hips",
            )
        )
        cords.append(
            common.curve_tube(
                f"Side_Tail_{side}_B",
                [(x, y - 0.003, z), (x + sign * 0.026, y - 0.006, 0.640), (x + sign * 0.030, y - 0.004, 0.600)],
                0.00135,
                material,
                armature,
                "Hips",
            )
        )
    joined = common.join_objects("Rib_Side_Ties", cords)
    common.transfer_nearest_body_weights(joined, body)
    common.add_nearest_shape_keys(joined, body)
    return joined


def heart_binding(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    y = common.body_front_y(body, 0.0, 0.925) - 0.010
    obj = common.heart_curve(
        "Heart_Cutout_Binding",
        (0.0, y, 0.925),
        0.0040,
        material,
        armature,
        "Chest",
    )
    common.transfer_nearest_body_weights(obj, body)
    common.add_nearest_shape_keys(obj, body)
    return obj


def copy_integrated_prefab(prefab: Path, integrated: Path) -> list[Path]:
    integrated.parent.mkdir(parents=True, exist_ok=True)
    integrated.write_text(prefab.read_text(encoding="utf-8"), encoding="utf-8")
    meta = integrated.with_suffix(integrated.suffix + ".meta")
    meta.write_text(
        "fileFormatVersion: 2\n"
        "guid: 3a70fc7bb3884ff09ed9746298231b3e\n"
        "PrefabImporter:\n"
        "  externalObjects: {}\n"
        "  userData: declaration-only; runtime integration is OUT_OF_SCOPE\n"
        "  assetBundleName:\n"
        "  assetBundleVariant:\n",
        encoding="utf-8",
    )
    return [integrated, meta]


def write_manifest(
    job: dict,
    measured: dict,
    previews: dict[str, Path],
    multiview: Path,
) -> Path:
    path = common.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["designRevision"] = DESIGN_REVISION
    manifest["status"] = "WORKING"
    manifest["materialVariants"] = {
        "primary": "black",
        "black": "MAT_Black_Ribbed_Knit",
        "ivory": "MAT_Ivory_Ribbed_Knit",
    }
    manifest["technicalGates"].update(
        {
            "blender": "PASS",
            "editableSource": "PASS",
            "fbx": "PASS",
            "prefabDeclared": "PASS",
            "fiveViewEvidence": "PASS",
            "poseEvidence": "PENDING",
            "visualAppearanceReview": "PENDING",
        }
    )
    manifest["outputs"] = {
        "blend": job["blendPath"],
        "fbx": job["fbxAssetPath"],
        "prefab": job["prefabAssetPath"],
        "integratedPrefab": job["integratedPrefabAssetPath"],
        "multiview": str(multiview.relative_to(ROOT)).replace("\\", "/"),
        "poseReview": f'{job["productRoot"]}/Previews/{job["id"]}-pose-review.webp',
    }
    manifest["metrics"] = measured
    manifest["fiveViewEvidence"] = {
        name: {"path": job["previewPaths"][name], "sha256": common.sha256(image)}
        for name, image in previews.items()
    }
    manifest["handoff"]["lastAttempt"] = {
        "result": "HOSTED_TECHNICAL_CANDIDATE",
        "visualRevision": DESIGN_REVISION,
    }
    manifest["handoff"]["blockers"] = [
        "Render and inspect all six required poses.",
        "Pass direct visualAppearanceReview against the supplied reference before COMPLETE.",
    ]
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_product_readme(job: dict, measured: dict) -> Path:
    path = common.repo_path(job["productRoot"]) / "README.md"
    path.write_text(
        f"""# {job["productName"]}

Target: SiroinoSotai_PC neutral PC body.

WORKING candidate reconstructed from one user-supplied reference image. The image itself is not redistributed.

Authored structure:
- rib-knit high neck and sleeveless long front/back panels
- real heart-shaped chest opening with modeled knit binding
- large open sides with three tie cords per side and hanging tails
- centre-front lower hem slit
- detached left/right long rib-knit arm warmers
- black primary material plus an authored ivory material variant

Rear construction and exact rear tie attachment are not visible in the supplied reference, so those details remain UNVERIFIED independent design choices.

Static metrics:
- mesh objects: {measured["meshObjects"]}
- vertices: {measured["vertices"]}
- triangles: {measured["triangles"]}
- material slots: {measured["materialSlots"]}
- maximum bone influences: {measured["maxBoneInfluences"]}

Five current Blender views are generated by the build. COMPLETE still requires required pose evidence and direct visualAppearanceReview PASS.
""",
        encoding="utf-8",
    )
    return path


def main() -> int:
    _, job = common.load_job()
    common.clean_scene()
    source = common.repo_path(job["targetSourcePath"])
    blend_path = common.repo_path(job["blendPath"])
    fbx_path = common.repo_path(job["fbxAssetPath"])
    prefab_path = common.repo_path(job["prefabAssetPath"])
    integrated_prefab = common.repo_path(job["integratedPrefabAssetPath"])
    product_root = common.repo_path(job["productRoot"])
    texture_dir = product_root / "Textures"
    product_root.mkdir(parents=True, exist_ok=True)

    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body = next(
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC")
    )
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    armature.name = "SiroinoSotai_Armature"
    common.set_skin_material(body)

    textures = common.make_texture_maps(texture_dir)
    black = common.textured_material(
        "MAT_Black_Ribbed_Knit",
        textures["black_satin_albedo.png"],
        textures["ivory_knit_normal.png"],
        textures["ivory_knit_roughness.png"],
        normal_strength=0.78,
        sheen=0.20,
    )
    ivory = common.textured_material(
        "MAT_Ivory_Ribbed_Knit",
        textures["ivory_knit_albedo.png"],
        textures["ivory_knit_normal.png"],
        textures["ivory_knit_roughness.png"],
        normal_strength=0.78,
        sheen=0.20,
    )

    front = build_panel(body, armature, "Heart_Rib_Front_Panel", black, front=True)
    back = build_panel(body, armature, "Heart_Rib_Back_Panel", black, front=False)
    collar = common.collar_mesh(black, armature)
    common.add_nearest_shape_keys(collar, body)
    left_warmer = arm_warmer(body, armature, black, "L")
    right_warmer = arm_warmer(body, armature, black, "R")
    binding = heart_binding(body, armature, black)
    ties = side_ties(body, armature, black)
    garments = [front, back, collar, left_warmer, right_warmer, binding, ties]
    front.data.materials.append(ivory)
    back.data.materials.append(ivory)

    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)

    _, camera = common.studio_setup()
    camera.data.ortho_scale = 1.16
    common.preview_pose(armature)
    previews = {
        name: common.repo_path(value)
        for name, value in job["previewPaths"].items()
    }
    common.render_views(camera, previews)
    multiview = product_root / "Previews" / f'{job["id"]}-multiview.webp'
    common.contact_sheet(previews, multiview)

    common.reset_pose(armature)
    body.hide_render = True
    common.export_fbx(fbx_path, armature, garments)
    sidecars = common.write_unity_sidecars(fbx_path, prefab_path, job["productName"])
    integrated_files = copy_integrated_prefab(prefab_path, integrated_prefab)

    measured = common.metrics(garments)
    passed = (
        measured["meshObjects"] >= 7
        and measured["vertices"] > 1200
        and measured["triangles"] > 1800
        and measured["unweightedVertices"] == 0
        and measured["weightSumErrors"] == 0
        and measured["degenerateTriangles"] == 0
        and measured["maxBoneInfluences"] <= 4
    )
    manifest_path = write_manifest(job, measured, previews, multiview)
    readme_path = write_product_readme(job, measured)
    report_path = product_root / "Tests" / "build-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "passed": passed,
        "checkedAt": common.utc_now(),
        "blenderVersion": bpy.app.version_string,
        "designRevision": DESIGN_REVISION,
        "sourceReference": f"private-reference://sha256/{REFERENCE_SHA256}",
        "metrics": measured,
        "views": {
            name: {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": common.sha256(path),
                "width": Image.open(path).width,
                "height": Image.open(path).height,
            }
            for name, path in previews.items()
        },
        "notes": [
            "The supplied reference image is not committed or redistributed.",
            "The chest heart opening and lower front slit are real mesh openings, not transparency tricks.",
            "The rear panel and rear tie attachment remain UNVERIFIED because the single reference does not show them.",
            "visualAppearanceReview remains blocking and is not auto-passed by this build.",
        ],
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    hash_targets = [
        blend_path,
        fbx_path,
        prefab_path,
        manifest_path,
        readme_path,
        report_path,
        multiview,
        *sidecars,
        *integrated_files,
        *previews.values(),
        *textures.values(),
    ]
    (product_root / "SOURCE_HASHES.txt").write_text(
        "\n".join(
            f"{common.sha256(path)}  {path.relative_to(product_root).as_posix()}"
            for path in hash_targets
            if path.is_file()
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
