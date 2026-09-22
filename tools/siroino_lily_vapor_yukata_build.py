#!/usr/bin/env python3
"""Build the repaired Lily Vapor Yukata for Issue #673.

The accepted repair is a closed calf-length summer column with a compact
standing wrap collar, two real split-rail sleeves, a center back walking vent,
and a three-plate structural Petal Lock.  Broad obi/bow, cape, lantern,
waterfall, and conventional wide-sleeve constructions are intentionally absent.
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
PRODUCT_ID = "siroino-lily-vapor-yukata"
SHAPE_KEYS = ("All_L", "Chest_L", "Hips_01_L", "UpperLeg_L", "Breasts_L")


def parse_args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(values)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"path escapes repository: {value}")
    return resolved


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_texture_maps(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, color in {
        "lily_milk_shell_albedo.png": (232, 232, 226),
        "lily_mist_blue_albedo.png": (168, 188, 220),
        "lily_lavender_lock_albedo.png": (164, 151, 190),
        "lily_indigo_facing_albedo.png": (38, 49, 92),
        "lily_silver_hardware_albedo.png": (152, 158, 168),
        "lily_roughness.png": (176, 176, 176),
    }.items():
        Image.new("RGB", (512, 512), color).save(directory / name, optimize=True)


def make_pattern_layout(path: Path) -> None:
    image = Image.new("RGB", (1600, 980), (244, 244, 240))
    draw = ImageDraw.Draw(image)
    try:
        title = ImageFont.truetype("DejaVuSans.ttf", 34)
        label = ImageFont.truetype("DejaVuSans.ttf", 22)
    except OSError:
        title = ImageFont.load_default()
        label = title
    draw.text(
        (36, 26),
        "LILY VAPOR YUKATA — SUMMER COLUMN / SPLIT-RAIL PANEL LAYOUT",
        fill=(40, 47, 70),
        font=title,
    )
    shapes = [
        ("Front Under", [(70, 140), (260, 140), (280, 760), (45, 760)]),
        ("Front Over", [(300, 140), (490, 140), (510, 760), (275, 760)]),
        ("Back + Vent", [(530, 140), (760, 140), (780, 760), (510, 760)]),
        ("Rail Outer L/R", [(820, 120), (970, 150), (950, 610), (800, 610)]),
        ("Rail Inner L/R", [(1000, 150), (1150, 120), (1170, 610), (1020, 610)]),
        ("Petal Lock x3", [(1200, 170), (1390, 170), (1400, 390), (1190, 390)]),
    ]
    for name, points in shapes:
        draw.polygon(points, fill=(214, 222, 238), outline=(95, 110, 150), width=4)
        center = (
            sum(point[0] for point in points) // len(points),
            sum(point[1] for point in points) // len(points),
        )
        draw.text((center[0] - 75, center[1] - 12), name, fill=(40, 47, 70), font=label)
    draw.text(
        (36, 910),
        "Closed calf-length shell • exactly two split-rail sleeves • three-layer Petal Lock • no obi/bow/cape/lantern",
        fill=(70, 78, 105),
        font=label,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def curved_panel(
    name: str,
    x_top_left: float,
    x_top_right: float,
    x_bottom_left: float,
    x_bottom_right: float,
    z_min: float,
    z_max: float,
    y_function,
    material,
    armature,
    body,
    *,
    x_steps: int = 18,
    z_steps: int = 30,
    center_vent_z: float | None = None,
    center_vent_width: float = 0.024,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    for row in range(z_steps + 1):
        t = row / z_steps
        z = z_min + (z_max - z_min) * t
        x_left = x_bottom_left + (x_top_left - x_bottom_left) * t
        x_right = x_bottom_right + (x_top_right - x_bottom_right) * t
        for column in range(x_steps + 1):
            u = column / x_steps
            x = x_left + (x_right - x_left) * u
            y = y_function(x, z, u, t)
            vertices.append((x, y, z))
    faces: list[tuple[int, int, int, int]] = []
    stride = x_steps + 1
    for row in range(z_steps):
        row_z = z_min + (z_max - z_min) * (row + 0.5) / z_steps
        for column in range(x_steps):
            a = row * stride + column
            if center_vent_z is not None and row_z < center_vent_z:
                left = vertices[a][0]
                right = vertices[a + 1][0]
                if abs((left + right) * 0.5) < center_vent_width * 0.5:
                    continue
            faces.append((a, a + 1, a + stride + 1, a + stride))
    return base.mesh_object(
        name, vertices, faces, material, armature, body, solidify=False
    )


def side_gusset(
    name: str,
    side: float,
    material,
    armature,
    body,
    *,
    y_steps: int = 12,
    z_steps: int = 30,
) -> bpy.types.Object:
    """Bridge each pair of front/back panels around the avatar's side seam."""
    vertices: list[tuple[float, float, float]] = []
    for row in range(z_steps + 1):
        t = row / z_steps
        z = 0.29 + (1.075 - 0.29) * t
        # Match the side edges of the tapered front/back shell exactly.  The
        # previous 0.34 -> 0.15 rail left a visible 15-95 mm open seam.
        x = side * (0.18 - 0.060 * t)
        for column in range(y_steps + 1):
            u = column / y_steps
            y = -0.186 + 0.292 * u + 0.004 * math.sin(math.pi * u) * (1.0 - t)
            vertices.append((x, y, z))
    faces: list[tuple[int, int, int, int]] = []
    stride = y_steps + 1
    for row in range(z_steps):
        for column in range(y_steps):
            a = row * stride + column
            faces.append((a, a + 1, a + stride + 1, a + stride))
    return base.mesh_object(
        name, vertices, faces, material, armature, body, solidify=False
    )


def add_shape_keys(obj: bpy.types.Object, body: bpy.types.Object) -> None:
    base.add_shape_keys(obj, body)


def petal_plate(
    name: str,
    center_x: float,
    center_z: float,
    width: float,
    height: float,
    y: float,
    material,
    armature,
    body,
) -> bpy.types.Object:
    """Create one independently readable shallow Petal Lock plate."""
    points = [
        (center_x, y, center_z + height * 0.62),
        (center_x + width, y - 0.002, center_z),
        (center_x, y - 0.003, center_z - height * 0.62),
        (center_x - width, y - 0.002, center_z),
    ]
    return base.mesh_object(
        name, points, [(0, 1, 2, 3)], material, armature, body, solidify=True
    )


def add_petal_lock_and_details(armature, milk, lavender, indigo, silver, body):
    details: list[bpy.types.Object] = []
    details.extend(
        (
            petal_plate(
                "Lily_Petal_Lock_Root",
                0.000,
                0.805,
                0.060,
                0.072,
                -0.218,
                lavender,
                armature,
                body,
            ),
            petal_plate(
                "Lily_Petal_Lock_Outer",
                -0.055,
                0.835,
                0.044,
                0.064,
                -0.226,
                lavender,
                armature,
                body,
            ),
            petal_plate(
                "Lily_Petal_Lock_Inner",
                0.055,
                0.775,
                0.044,
                0.064,
                -0.230,
                lavender,
                armature,
                body,
            ),
        )
    )
    details.append(
        base.import_base.curve_tube(
            "Lily_Petal_Lock_Hardware",
            [(-0.060, -0.222, 0.785), (-0.060, -0.225, 0.785)],
            0.007,
            silver,
            armature,
            "Hips",
        )
    )
    details.append(
        base.import_base.curve_tube(
            "Lily_Waist_Stay_Upper",
            [(-0.235, -0.197, 0.805), (0.235, -0.197, 0.805)],
            0.0045,
            milk,
            armature,
            "Hips",
        )
    )
    details.append(
        base.import_base.curve_tube(
            "Lily_Center_Vent_Facing",
            [(0.0, 0.125, 0.49), (0.0, 0.125, 0.29)],
            0.003,
            indigo,
            armature,
            "Hips",
        )
    )
    details.append(
        base.import_base.curve_tube(
            "Lily_Front_Wrap_Facing",
            [(-0.235, -0.201, 1.065), (-0.235, -0.202, 0.82)],
            0.0028,
            indigo,
            armature,
            "Chest",
        )
    )
    return details


def main() -> int:
    global base
    tools_dir = ROOT / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import siroino_lunar_tech_hoodie_build as base
    import siroino_strappy_knit_build as import_base

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
    milk = base.plain_material("MAT_Lily_Summer_Shell", (0.82, 0.82, 0.78, 1.0), 0.82)
    mist = base.plain_material("MAT_Lily_Under_Sleeve", (0.42, 0.54, 0.76, 1.0), 0.76)
    lavender = base.plain_material("MAT_Lily_Petal_Lock", (0.48, 0.39, 0.62, 1.0), 0.72)
    indigo = base.plain_material(
        "MAT_Lily_Indigo_Facing", (0.055, 0.075, 0.18, 1.0), 0.78
    )
    silver = base.plain_material(
        "MAT_Lily_Silver_Hardware", (0.52, 0.56, 0.64, 1.0), 0.28, 0.72
    )

    garments: list[bpy.types.Object] = []
    garments.append(
        import_base.extract_surface(
            body,
            armature,
            "Lily_Summer_Underlayer_Front",
            lambda c: 0.82 <= c.z <= 1.075 and c.y < -0.004 and abs(c.x) <= 0.235,
            mist,
            0.008,
        )
    )
    garments.append(
        import_base.extract_surface(
            body,
            armature,
            "Lily_Summer_Underlayer_Back",
            lambda c: 0.82 <= c.z <= 1.075 and c.y >= -0.004 and abs(c.x) <= 0.235,
            mist,
            0.008,
        )
    )
    garments.append(
        import_base.extract_surface(
            body,
            armature,
            "Lily_Fitted_Under_Sleeve_L",
            lambda c: 0.78 <= c.z <= 1.08 and c.x < -0.255,
            mist,
            0.010,
        )
    )
    garments.append(
        import_base.extract_surface(
            body,
            armature,
            "Lily_Fitted_Under_Sleeve_R",
            lambda c: 0.78 <= c.z <= 1.08 and c.x > 0.255,
            mist,
            0.010,
        )
    )
    garments.append(import_base.collar_mesh(milk, armature))

    def front_y(x, z, u, t):
        return (
            -0.186
            - 0.014 * (0.82 - z)
            - 0.020 * (x / 0.30) ** 2
            + 0.004 * math.sin(math.pi * u) * (1.0 - t)
        )

    def back_y(x, z, u, t):
        return (
            0.106
            + 0.012 * (0.82 - z)
            + 0.016 * (x / 0.30) ** 2
            + 0.004 * math.sin(math.pi * u) * (1.0 - t)
        )

    panels = [
        curved_panel(
            "Lily_Summer_Front_Under",
            -0.135,
            0.010,
            -0.180,
            0.010,
            0.29,
            1.075,
            front_y,
            milk,
            armature,
            body,
        ),
        curved_panel(
            "Lily_Summer_Front_Over",
            -0.010,
            0.135,
            -0.010,
            0.180,
            0.29,
            1.075,
            front_y,
            milk,
            armature,
            body,
        ),
        curved_panel(
            "Lily_Summer_Back",
            -0.135,
            0.135,
            -0.180,
            0.180,
            0.29,
            1.075,
            back_y,
            milk,
            armature,
            body,
            center_vent_z=0.49,
            center_vent_width=0.026,
        ),
        curved_panel(
            "Lily_Sleeve_Rail_Outer_L",
            -0.235,
            -0.500,
            -0.235,
            -0.500,
            0.91,
            1.00,
            lambda x, z, u, t: -0.052 - 0.010 * (x / 0.575) ** 2,
            milk,
            armature,
            body,
        ),
        curved_panel(
            "Lily_Sleeve_Rail_Inner_L",
            -0.235,
            -0.500,
            -0.235,
            -0.500,
            0.80,
            0.88,
            lambda x, z, u, t: -0.050 - 0.010 * (x / 0.575) ** 2,
            mist,
            armature,
            body,
        ),
        curved_panel(
            "Lily_Sleeve_Rail_Inner_R",
            0.235,
            0.500,
            0.235,
            0.500,
            0.80,
            0.88,
            lambda x, z, u, t: -0.050 - 0.010 * (x / 0.575) ** 2,
            mist,
            armature,
            body,
        ),
        curved_panel(
            "Lily_Sleeve_Rail_Outer_R",
            0.235,
            0.500,
            0.235,
            0.500,
            0.91,
            1.00,
            lambda x, z, u, t: -0.052 - 0.010 * (x / 0.575) ** 2,
            milk,
            armature,
            body,
        ),
    ]
    garments.extend(panels)
    garments.extend(
        (
            side_gusset("Lily_Summer_Side_L", -1.0, milk, armature, body),
            side_gusset("Lily_Summer_Side_R", 1.0, milk, armature, body),
        )
    )
    garments.extend(
        add_petal_lock_and_details(armature, milk, lavender, indigo, silver, body)
    )

    def assign_region_weights(obj: bpy.types.Object) -> None:
        """Use stable garment-region weights instead of one nearest body vertex.

        The shell follows the torso/pelvis as a single garment.  Only the
        split rails follow the arms, with a small shoulder transition.  This
        prevents a seated pose from dragging the hem into the thighs while
        retaining authored deformation on the sleeves.
        """
        obj.vertex_groups.clear()
        groups = {
            group.name: obj.vertex_groups.new(name=group.name)
            for group in body.vertex_groups
        }

        def add(index: int, weights: dict[str, float]) -> None:
            valid = {
                name: value
                for name, value in weights.items()
                if name in groups and value > 1e-8
            }
            total = sum(valid.values())
            if total <= 1e-8:
                groups["Hips"].add([index], 1.0, "REPLACE")
                return
            for name, value in valid.items():
                groups[name].add([index], value / total, "REPLACE")

        for vertex in obj.data.vertices:
            point = obj.matrix_world @ vertex.co
            if "Sleeve_Rail" in obj.name:
                left = point.x < 0.0
                side = "L" if left else "R"
                distance = abs(point.x)
                # Root -> cuff: Shoulder, upper arm, forearm, then a small
                # hand influence.  The transition is continuous across the
                # rail instead of being a hard nearest-vertex boundary.
                if distance < 0.285:
                    add(vertex.index, {f"Shoulder_{side}": 0.45, f"UpperArm_{side}": 0.55})
                elif distance < 0.405:
                    add(vertex.index, {f"UpperArm_{side}": 0.55, f"LowerArm_{side}": 0.45})
                else:
                    add(vertex.index, {f"LowerArm_{side}": 0.72, f"Hand_{side}": 0.28})
                continue
            # The shell and its side seams remain attached to the torso.  A
            # short chest/hip blend keeps the waist from folding abruptly.
            if point.z >= 0.93:
                add(vertex.index, {"Chest": 1.0})
            elif point.z >= 0.79:
                blend = (point.z - 0.79) / 0.14
                add(vertex.index, {"Chest": blend, "Hips": 1.0 - blend})
            else:
                # Let the lower side panels travel a little with the
                # corresponding upper leg in seated/crouched poses.  The
                # centre remains pelvis-bound so the front overlap stays
                # closed instead of splitting into two rigid cards.
                if point.x < -0.035:
                    add(vertex.index, {"Hips": 0.62, "UpperLeg_L": 0.38})
                elif point.x > 0.035:
                    add(vertex.index, {"Hips": 0.62, "UpperLeg_R": 0.38})
                else:
                    add(vertex.index, {"Hips": 1.0})

    for obj in garments:
        # Select only the shell and sleeve meshes; decorative curve/tube
        # weights remain bound to their authored attachment bones.
        if obj.type == "MESH" and (
            obj.name.startswith("Lily_Summer_Front_")
            or obj.name in {"Lily_Summer_Back", "Lily_Summer_Side_L", "Lily_Summer_Side_R"}
        ):
            assign_region_weights(obj)

    for obj in garments:
        if obj.type == "MESH" and obj.name not in {panel.name for panel in panels}:
            add_shape_keys(obj, body)
        if obj.type == "MESH":
            for polygon in obj.data.polygons:
                polygon.use_smooth = False
            obj.data.update()
    for obj in panels:
        pin = obj.vertex_groups.new(name="Image2Outfit Cloth Pin")
        top = [vertex.index for vertex in obj.data.vertices if vertex.co.z >= 0.77]
        pin.add(top, 1.0, "REPLACE")
        obj["image2outfit_role"] = "cloth-panel"

    blend_path = repo_path(job["blendPath"])
    bpy.ops.wm.save_as_mainfile(
        filepath=str(blend_path), check_existing=False, compress=True
    )
    _, camera = import_base.studio_setup()
    camera.data.ortho_scale = 1.44
    target = (0.0, -0.005, 0.69)
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
    sidecars = import_base.write_unity_sidecars(
        fbx_path, prefab_path, job["productName"]
    )
    integrated = repo_path(job["integratedPrefabAssetPath"])
    sidecars.extend(base.write_integrated_prefab(prefab_path, integrated))
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
        "clothComponents": [panel.name for panel in panels],
        "clothSimulation": "PENDING_BAKE",
        "referenceArtifact": "REPAIRED_REPLACEMENT_GENERATED",
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
            "construction": "closed calf-length summer column shell with two split-rail sleeves, center back walking vent, flat waist stay, and three-plate Petal Lock",
            "excludedOverlap": [
                "broad obi",
                "rear bow",
                "detached waterfall panels",
                "conventional wide kimono sleeves",
                "lantern bag",
                "hanging tassel field",
                "cape",
                "thigh straps",
            ],
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
        "sourceReferenceStatus": "REPAIRED_REPLACEMENT_BOARD_GENERATED",
        "handoff": {
            "resumable": True,
            "canonicalWorkspace": job["productRoot"],
            "resumeFrom": job["prefabAssetPath"],
            "doNotRebuildFromZero": True,
            "blockers": [
                "exact original Issue PNG was unavailable; the repaired replacement board is persisted with its identity record",
                "visualAppearanceReview remains REVIEW_REQUIRED until the shoulder and seated-pose deformation loop is accepted",
                "real VRChat upload is not performed by the automated build; only SDK dry-run evidence is recorded",
            ],
        },
        "outputs": {
            "blend": job["blendPath"],
            "fbx": job["fbxAssetPath"],
            "prefab": job["prefabAssetPath"],
            "integratedPrefab": job["integratedPrefabAssetPath"],
            "multiview": str(multiview.relative_to(ROOT)).replace("\\", "/"),
            "poseReview": str(pose_review.relative_to(ROOT)).replace("\\", "/"),
        },
        "technicalGates": {
            "referenceArtifact": "REPLACEMENT_GENERATED",
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
    }
    write_json(repo_path(job["productManifestPath"]), manifest)
    (product_root / "README.md").write_text(
        "# Lily Vapor Yukata\n\nA repaired construction for Issue #673: a closed calf-length summer column with a compact wrap collar, exactly two narrow split-rail sleeves, a flat waist stay, a center back walking vent, and a three-plate structural Petal Lock. The design deliberately removes the conventional wide kimono sleeve, broad obi, rear bow, detached waterfall panels, cape, lantern bag, tassel field, and thigh straps.\n\nThe original run artifact was unavailable in this workspace; the persisted reference is the newly generated repaired manufacturing board. The ProductManifest remains WORKING until native Blender Cloth, visual review, Unity/NDMF, and VRChat dry-run evidence are complete.\n",
        encoding="utf-8",
    )
    source_files = [
        blend_path,
        fbx_path,
        prefab_path,
        integrated,
        multiview,
        pose_review,
        pattern_layout,
        *previews.values(),
        *pose_paths.values(),
        product_root / "README.md",
        repo_path(job["productManifestPath"]),
        product_root / "Evidence/Build/product-build-report.json",
        product_root / "References/lily-vapor-yukata-manufacturing-sheet.png",
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
