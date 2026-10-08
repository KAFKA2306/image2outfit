#!/usr/bin/env python3
"""Build the Sage Breeze Onepiece as an auditable Siroino garment.

The source contract is a repaired, closed ankle-above onepiece. Its identity
comes from exactly two side-seam wind-pleat tunnels and one three-plate leaf
clasp; the shell remains panel-first and cloth-ready for native Blender Cloth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import bpy
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-sage-breeze-onepiece"
SHAPE_KEYS = ("All_L", "Chest_L", "Hips_01_L", "UpperLeg_L", "Breasts_L")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"path escapes repository: {value}")
    return resolved


def parse_args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(values)


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def plain_material(name, color, roughness, metallic=0.0):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    if "Coat Weight" in shader.inputs:
        shader.inputs["Coat Weight"].default_value = 0.08 if metallic else 0.03
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    material.diffuse_color = color
    return material


def make_texture_maps(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, color in {
        "sage_breeze_shell_albedo.png": (218, 211, 188),
        "sage_breeze_facing_albedo.png": (128, 143, 116),
        "sage_breeze_moss_albedo.png": (55, 65, 42),
        "sage_breeze_brass_albedo.png": (145, 113, 57),
        "sage_breeze_roughness.png": (188, 188, 188),
    }.items():
        Image.new("RGB", (512, 512), color).save(directory / name, optimize=True)


def make_pattern_layout(path: Path) -> None:
    image = Image.new("RGB", (1600, 1000), (43, 47, 51))
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("DejaVuSans.ttf", 34)
        label_font = ImageFont.truetype("DejaVuSans.ttf", 22)
    except OSError:
        title_font = ImageFont.load_default()
        label_font = title_font
    draw.text(
        (36, 24),
        "SAGE BREEZE ONEPIECE — PANEL / SEAM / UV LAYOUT",
        fill=(244, 244, 238),
        font=title_font,
    )
    panels = [
        ("Breeze Front L/R", [(70, 150), (310, 120), (330, 460), (100, 480)]),
        ("Breeze Back", [(370, 120), (610, 145), (600, 480), (350, 460)]),
        ("Wind Tunnel x2", [(680, 140), (830, 150), (815, 470), (665, 455)]),
        ("Sleeve L/R", [(900, 140), (1060, 160), (1030, 450), (890, 430)]),
        ("Collar + Leaf Lock", [(1140, 140), (1515, 160), (1490, 350), (1160, 350)]),
        ("Center Vent Facing", [(1140, 420), (1515, 420), (1495, 570), (1155, 570)]),
    ]
    for label, points in panels:
        draw.polygon(points, fill=(207, 207, 191), outline=(143, 158, 132), width=4)
        center = (
            sum(point[0] for point in points) // len(points),
            sum(point[1] for point in points) // len(points),
        )
        draw.text(
            (center[0] - 70, center[1] - 12), label, fill=(40, 43, 42), font=label_font
        )
    draw.text(
        (36, 930),
        "Closed column shell • exactly two recessed wind-pleat channels • one three-plate leaf clasp • no belt, strap or cape",
        fill=(190, 201, 184),
        font=label_font,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def ribbon_panel(
    name,
    side,
    z_min,
    z_max,
    y_center,
    y_width,
    material,
    armature,
    body,
    *,
    x_offset=0.0,
    z_steps=30,
):
    vertices = []
    for row in range(z_steps + 1):
        z = z_min + (z_max - z_min) * row / z_steps
        t = row / z_steps
        # Follow the tapered side seam instead of leaving three vertical cards
        # floating outside the shell.  The outer edge widens toward the hem,
        # while the tunnel closes into the shoulder/waist line.
        shell_half = 0.300 + (0.245 - 0.300) * t
        x = side * (shell_half + x_offset + 0.003 * math.sin(math.pi * t))
        for column in range(3):
            u = column / 2.0
            vertices.append((x, y_center - y_width / 2.0 + y_width * u, z))
    faces = []
    for row in range(z_steps):
        for column in range(2):
            a = row * 3 + column
            faces.append((a, a + 1, a + 4, a + 3))
    return base.mesh_object(
        name, vertices, faces, material, armature, body, solidify=True
    )


def breeze_side_wrap_panel(
    name,
    side,
    z_min,
    z_max,
    material,
    armature,
    body,
    *,
    y_front=-0.164,
    y_back=0.108,
    y_steps=12,
    z_steps=34,
):
    """Close the shell with a tapered side panel that meets the shoulders."""
    vertices = []
    for row in range(z_steps + 1):
        for column in range(y_steps + 1):
            u = column / y_steps
            y = y_front + (y_back - y_front) * u
            side_curve = math.sin(math.pi * u)
            # Keep the side seam closed.  The only walking opening belongs at
            # center back; a large side hem lift would expose the body and read
            # as an accidental slit rather than the specified tunnel.
            bottom = z_min + 0.012 * side_curve
            top = z_max - 0.030 * side_curve
            z = bottom + (top - bottom) * row / z_steps
            t = (z - z_min) / max(1e-6, z_max - z_min)
            half = 0.300 + (0.245 - 0.300) * t
            # Give the side seam a shallow barrel curve so the wind tunnel
            # assembly sits on a surface instead of reading as a flat card.
            x = side * (half + 0.012 * math.sin(math.pi * u))
            vertices.append((x, y, z))
    faces = []
    stride = y_steps + 1
    for row in range(z_steps):
        for column in range(y_steps):
            a = row * stride + column
            faces.append((a, a + 1, a + stride + 1, a + stride))
    return base.mesh_object(
        name, vertices, faces, material, armature, body, solidify=True
    )


def breeze_back_panel(
    name,
    z_min,
    z_max,
    material,
    armature,
    body,
    *,
    x_top=0.255,
    x_bottom=0.294,
    vent_top=0.50,
    vent_gap=0.032,
    x_steps=12,
    z_steps=34,
):
    """Build one back Cloth object with a real center-back walking vent."""
    vertices = []
    rows = []
    for row in range(z_steps + 1):
        z = z_min + (z_max - z_min) * row / z_steps
        t = row / z_steps
        half = x_bottom + (x_top - x_bottom) * t
        gap = vent_gap if z <= vent_top else 0.004
        y = 0.108 + 0.014 * (0.96 - z)
        row_indices = []
        for left, right in ((-half, -gap / 2.0), (gap / 2.0, half)):
            side_indices = []
            for column in range(x_steps + 1):
                x = left + (right - left) * column / x_steps
                x *= 1.0
                side_indices.append(len(vertices))
                vertices.append((x, y + 0.009 * (x / max(half, 1e-6)) ** 2, z))
            row_indices.append(side_indices)
        rows.append(row_indices)
    faces = []
    for row in range(z_steps):
        for side_index in range(2):
            lower = rows[row][side_index]
            upper = rows[row + 1][side_index]
            for column in range(x_steps):
                faces.append(
                    (lower[column], lower[column + 1], upper[column + 1], upper[column])
                )
    return base.mesh_object(
        name, vertices, faces, material, armature, body, solidify=True
    )


def leaf_plate(name, center_x, center_z, scale, angle, material, armature, body, layer):
    local = [
        (-0.030, 0.0),
        (-0.005, 0.020),
        (0.038, 0.012),
        (0.052, 0.0),
        (0.014, -0.020),
        (-0.020, -0.018),
    ]
    vertices = []
    for x, z in local:
        x *= scale
        z *= scale
        rx = x * math.cos(angle) - z * math.sin(angle)
        rz = x * math.sin(angle) + z * math.cos(angle)
        vertices.append((center_x + rx, -0.207 - layer * 0.004, center_z + rz))
    faces = [(0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 5)]
    return base.mesh_object(
        name, vertices, faces, material, armature, body, solidify=True
    )


def add_shape_keys(obj, body):
    if body.data.shape_keys is None:
        return
    tree = base.import_base.KDTree(len(body.data.vertices))
    for vertex in body.data.vertices:
        tree.insert(body.matrix_world @ vertex.co, vertex.index)
    tree.balance()
    obj.shape_key_add(name="Basis")
    for name in SHAPE_KEYS:
        source = body.data.shape_keys.key_blocks.get(name)
        if source is None:
            continue
        target = obj.shape_key_add(name=name)
        for vertex in obj.data.vertices:
            _, index, _ = tree.find(obj.matrix_world @ vertex.co)
            delta = body.matrix_world.to_3x3() @ (
                source.data[index].co - body.data.vertices[index].co
            )
            target.data[vertex.index].co = (
                vertex.co + obj.matrix_world.to_3x3().inverted() @ delta
            )


def add_seams(armature, material):
    return [
        base.import_base.curve_tube(
            "Sage_Breeze_Front_Center_Seam",
            [(0.0, -0.174, 1.055), (0.0, -0.178, 0.78), (0.0, -0.176, 0.25)],
            0.0023,
            material,
            armature,
            "Chest",
        ),
        base.import_base.curve_tube(
            "Sage_Breeze_Back_Vent_L",
            [(-0.017, 0.120, 0.50), (-0.017, 0.122, 0.27)],
            0.0025,
            material,
            armature,
            "Hips",
        ),
        base.import_base.curve_tube(
            "Sage_Breeze_Back_Vent_R",
            [(0.017, 0.120, 0.50), (0.017, 0.122, 0.27)],
            0.0025,
            material,
            armature,
            "Hips",
        ),
    ]


def main() -> int:
    global base
    tools_dir = ROOT / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import siroino_verdant_ranger_explorer_build as base_module
    import siroino_strappy_knit_build as import_base

    base = base_module
    base.import_base = import_base
    args = parse_args()
    job = read_json(repo_path(args.job))
    if job.get("id") != PRODUCT_ID:
        raise RuntimeError(f"unexpected job id: {job.get('id')!r}")
    base.clean_scene()
    source = repo_path(job["targetSourcePath"])
    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body = next(
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC")
    )
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    armature.name = "SiroinoSotai_Armature"
    for obj in list(bpy.context.scene.objects):
        if obj.type == "MESH" and obj != body:
            bpy.data.objects.remove(obj, do_unlink=True)
    profile = base.apply_large_profile(body, job["bodyShapeProfile"])
    import_base.set_skin_material(body)

    product_root = repo_path(job["productRoot"])
    for relative in (
        "Source/Blender",
        "Source/Patterns",
        "Models",
        "Textures",
        "Materials",
        "Prefab",
        "Previews/Poses",
        "Evidence/Build",
        "Demo",
        "Editor",
        "Tests",
        "Documentation",
    ):
        (product_root / relative).mkdir(parents=True, exist_ok=True)
    make_texture_maps(product_root / "Textures")
    shell = plain_material("MAT_BreezeShell", (0.52, 0.42, 0.27, 1.0), 0.78)
    facing = plain_material("MAT_WindFacing", (0.22, 0.34, 0.18, 1.0), 0.72)
    moss = plain_material("MAT_LeafClasp", (0.07, 0.13, 0.05, 1.0), 0.62)
    brass = plain_material("MAT_BreezeHardware", (0.32, 0.18, 0.045, 1.0), 0.32, 0.65)

    garments = [
        import_base.extract_surface(
            body,
            armature,
            "Sage_Breeze_Sleeve_L",
            lambda c: 0.79 <= c.z <= 1.08 and c.x < -0.255,
            shell,
            0.014,
        ),
        import_base.extract_surface(
            body,
            armature,
            "Sage_Breeze_Sleeve_R",
            lambda c: 0.79 <= c.z <= 1.08 and c.x > 0.255,
            shell,
            0.014,
        ),
    ]

    def front_y(x, z):
        # A shallow convex chest curve keeps the panel readable in the
        # orthographic inspection views while remaining panel-first.
        across = max(0.0, 1.0 - (x / 0.30) ** 2)
        return -0.170 - 0.025 * across - 0.006 * (0.96 - z)

    def back_y(x, z):
        across = max(0.0, 1.0 - (x / 0.30) ** 2)
        return 0.130 + 0.022 * across + 0.008 * (0.96 - z)

    garments.extend(
        [
            base.tapered_grid_panel(
                "Sage_Breeze_Front",
                0.255,
                0.300,
                0.22,
                1.055,
                front_y,
                shell,
                armature,
                body,
                x_steps=24,
                z_steps=34,
                solidify=True,
            ),
            breeze_back_panel("Sage_Breeze_Back", 0.22, 1.055, shell, armature, body),
            breeze_side_wrap_panel(
                "Sage_Breeze_Side_L", -1.0, 0.22, 1.055, shell, armature, body
            ),
            breeze_side_wrap_panel(
                "Sage_Breeze_Side_R", 1.0, 0.22, 1.055, shell, armature, body
            ),
        ]
    )

    tunnel_names = []
    for side_name, side in (("L", -1), ("R", 1)):
        for role, material, center, width, offset in (
            ("Outer", facing, -0.135, 0.018, 0.006),
            ("Inner", moss, -0.101, 0.014, 0.012),
            ("Facing", facing, -0.064, 0.018, 0.018),
        ):
            name = f"Sage_Wind_Tunnel_{role}_{side_name}"
            garments.append(
                ribbon_panel(
                    name,
                    side,
                    0.31,
                    0.77,
                    center,
                    width,
                    material,
                    armature,
                    body,
                    x_offset=offset,
                )
            )
            tunnel_names.append(name)

    collar = import_base.collar_mesh(moss, armature)
    collar.name = "Sage_Stand_Collar"
    garments.append(collar)
    for index, (x, z, scale, angle) in enumerate(
        (
            (-0.018, 1.067, 1.0, -0.25),
            (0.014, 1.073, 0.84, 0.35),
            (0.0, 1.047, 0.70, 1.48),
        ),
        start=1,
    ):
        garments.append(
            leaf_plate(
                f"Sage_Leaf_Clasp_{index}",
                x,
                z,
                scale,
                angle,
                moss,
                armature,
                body,
                index,
            )
        )
    garments.extend(add_seams(armature, brass))

    excluded_from_shape_keys = {
        "Sage_Breeze_Front",
        "Sage_Breeze_Back",
        "Sage_Breeze_Side_L",
        "Sage_Breeze_Side_R",
        *tunnel_names,
    }
    for obj in garments:
        if obj.type == "MESH" and obj.name not in excluded_from_shape_keys:
            add_shape_keys(obj, body)

    cloth_names = [
        "Sage_Breeze_Front",
        "Sage_Breeze_Back",
        "Sage_Breeze_Side_L",
        "Sage_Breeze_Side_R",
    ]
    for name in cloth_names:
        obj = bpy.data.objects[name]
        pin = obj.vertex_groups.new(name="Image2Outfit Cloth Pin")
        pin.add(
            [vertex.index for vertex in obj.data.vertices if vertex.co.z >= 0.96],
            1.0,
            "REPLACE",
        )
        obj["image2outfit_role"] = "cloth-panel"

    blend_path = repo_path(job["blendPath"])
    bpy.ops.wm.save_as_mainfile(
        filepath=str(blend_path), check_existing=False, compress=True
    )
    _, camera = import_base.studio_setup()
    camera.data.ortho_scale = 1.42
    target = (0.0, -0.005, 0.70)
    previews = {name: repo_path(path) for name, path in job["previewPaths"].items()}
    base.render_product_views(camera, previews, target)
    pose_paths = base.render_poses(
        armature, camera, repo_path(job["posePaths"]["neutral"]).parent, target
    )
    multiview = product_root / "Previews" / f"{PRODUCT_ID}-multiview.webp"
    import_base.contact_sheet(previews, multiview)
    pose_review = product_root / "Previews" / f"{PRODUCT_ID}-pose-review.webp"
    base.contact_sheet_named(
        pose_paths,
        pose_review,
        ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"),
    )
    pattern_layout = product_root / "Previews" / "pattern-layout.png"
    make_pattern_layout(pattern_layout)

    body.hide_render = True
    fbx_path = repo_path(job["fbxAssetPath"])
    import_base.export_fbx(fbx_path, armature, garments)
    prefab_path = repo_path(job["prefabAssetPath"])
    import_base.write_unity_sidecars(fbx_path, prefab_path, job["productName"])
    integrated = repo_path(job["integratedPrefabAssetPath"])
    base.write_integrated_prefab(prefab_path, integrated)
    measured = base.metrics(garments)
    report = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "status": "WORKING",
        "checkedAt": utc_now(),
        "blenderVersion": bpy.app.version_string,
        "targetSource": str(source.relative_to(ROOT)).replace("\\", "/"),
        "targetSourceSha256": sha256(source),
        "shapeProfile": profile,
        "metrics": measured,
        "clothComponents": cloth_names,
        "clothSimulation": "PENDING_BAKE",
        "previews": {
            name: {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(path),
                "width": Image.open(path).width,
                "height": Image.open(path).height,
            }
            for name, path in previews.items()
        },
        "poses": {
            name: {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(path),
                "width": Image.open(path).width,
                "height": Image.open(path).height,
            }
            for name, path in pose_paths.items()
        },
        "design": {
            "construction": "closed ankle-above breeze-column onepiece with exactly two side wind-pleat tunnels, compact stand collar, three-plate leaf clasp and center-back walking vent",
            "excludedOverlap": [
                "broad belt",
                "thigh strap",
                "exposed high side slit",
                "cape",
                "detached sleeves",
                "rear bow",
                "hanging strap field",
            ],
            "windTunnelAssemblies": 2,
            "leafClaspPlates": 3,
        },
    }
    write_json(product_root / "Evidence/Build/product-build-report.json", report)
    manifest = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "productName": job["productName"],
        "status": "WORKING",
        "targetAdapterId": job["adapterId"],
        "productRoot": job["productRoot"],
        "outfitPrefabPath": job["prefabAssetPath"],
        "integratedPrefabPath": job["integratedPrefabAssetPath"],
        "previewPath": job["previewPaths"]["front"],
        "documentationPath": f"{job['productRoot']}/README.md",
        "sourceJobPath": f"config/products/{PRODUCT_ID}/job.json",
        "outputs": {
            "blend": job["blendPath"],
            "fbx": job["fbxAssetPath"],
            "prefab": job["prefabAssetPath"],
            "integratedPrefab": job["integratedPrefabAssetPath"],
            "multiview": str(multiview.relative_to(ROOT)).replace("\\", "/"),
            "poseReview": str(pose_review.relative_to(ROOT)).replace("\\", "/"),
        },
        "technicalGates": {
            "blender": "PASS",
            "editableSource": "PASS",
            "fbx": "PASS",
            "prefabDeclared": "PASS",
            "fiveViewEvidence": "PASS",
            "poseEvidence": "PASS",
            "visualAppearanceReview": "REVIEW_REQUIRED",
            "clothSimulation": "PENDING_BAKE",
            "unityImport": "UNVERIFIED",
            "modularAvatar": "UNVERIFIED",
            "ndmf": "UNVERIFIED",
            "vrchatRuntime": "UNVERIFIED",
        },
        "metrics": measured,
        "reference": {
            "status": "REPAIRED_REPLACEMENT_BOARD_GENERATED",
            "exactIssueImageAvailable": False,
            "replacementPath": f"{job['productRoot']}/References/sage-breeze-onepiece-manufacturing-board-replacement.png",
        },
        "handoff": {
            "resumable": True,
            "canonicalWorkspace": job["productRoot"],
            "resumeFrom": job["prefabAssetPath"],
            "doNotRebuildFromZero": True,
            "blockers": [
                "exact original Issue PNG was unavailable in this Windows workspace; replacement board is persisted",
                "visual review and shoulder/pleat deformation review remain required",
                "Unity/Modular Avatar/NDMF and VRChat SDK dry-run are not executed by this Blender build",
            ],
        },
    }
    write_json(repo_path(job["productManifestPath"]), manifest)
    (product_root / "README.md").write_text(
        "# Sage Breeze Onepiece\n\nRepaired Issue #675 construction: a closed ankle-above breeze-column onepiece with exactly two side-seam wind-pleat tunnels, a compact stand collar, a three-plate leaf clasp and a center-back walking vent. Broad belts, thigh straps, exposed high slits, capes, detached sleeves, rear bows and hanging straps are intentionally excluded.\n\nThe original Issue PNG was unavailable in this Windows workspace. The persisted replacement manufacturing board is evidence of the repaired construction only and does not claim exact-source identity. Native Blender Cloth remains required for the four shell panels before release.\n",
        encoding="utf-8",
    )
    reference = (
        product_root
        / "References/sage-breeze-onepiece-manufacturing-board-replacement.png"
    )
    source_files = [
        blend_path,
        fbx_path,
        prefab_path,
        integrated,
        multiview,
        pose_review,
        pattern_layout,
        reference,
        *previews.values(),
        *pose_paths.values(),
        product_root / "README.md",
        repo_path(job["productManifestPath"]),
        product_root / "Evidence/Build/product-build-report.json",
    ]
    (product_root / "SOURCE_HASHES.txt").write_text(
        "\n".join(
            f"{sha256(path)}  {path.relative_to(product_root).as_posix()}"
            for path in sorted(source_files)
            if path.is_file()
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
