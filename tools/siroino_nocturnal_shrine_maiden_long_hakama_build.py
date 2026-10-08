#!/usr/bin/env python3
"""Build the replacement Nocturnal Shrine Maiden long hakama candidate.

Issue #647 rejected the first shrine-maiden construction as too close to the
existing shrine/obi references.  This build therefore uses a fitted,
non-crossed tunic and four independent architectural hakama panels.  The
panels remain separate cloth components so the native Blender bake is
observable and reproducible.
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
PRODUCT_ID = "siroino-nocturnal-shrine-maiden-long-hakama-set"
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
        "nocturnal_indigo_albedo.png": (28, 33, 52),
        "nocturnal_charcoal_albedo.png": (43, 45, 54),
        "nocturnal_violet_albedo.png": (98, 91, 132),
        "nocturnal_roughness.png": (170, 170, 170),
    }.items():
        Image.new("RGB", (512, 512), color).save(directory / name, optimize=True)


def make_pattern_layout(path: Path) -> None:
    image = Image.new("RGB", (1600, 980), (30, 34, 47))
    draw = ImageDraw.Draw(image)
    try:
        title = ImageFont.truetype("DejaVuSans.ttf", 34)
        label = ImageFont.truetype("DejaVuSans.ttf", 22)
    except OSError:
        title = ImageFont.load_default()
        label = title
    draw.text(
        (36, 26),
        "NOCTURNAL SHRINE MAIDEN — MOON-GATE PANEL LAYOUT",
        fill=(242, 244, 250),
        font=title,
    )
    shapes = [
        ("Tunic front", [(80, 140), (300, 140), (325, 390), (55, 390)]),
        ("Tunic back", [(355, 140), (575, 140), (600, 390), (330, 390)]),
        ("Hakama front L", [(690, 120), (805, 150), (770, 800), (620, 800)]),
        ("Hakama front R", [(820, 150), (935, 120), (1005, 800), (850, 800)]),
        ("Hakama back L", [(1080, 150), (1195, 150), (1165, 800), (1015, 800)]),
        ("Hakama back R", [(1210, 150), (1325, 150), (1390, 800), (1240, 800)]),
    ]
    for name, points in shapes:
        draw.polygon(points, fill=(52, 61, 87), outline=(155, 166, 198), width=4)
        center = (
            sum(point[0] for point in points) // len(points),
            sum(point[1] for point in points) // len(points),
        )
        draw.text(
            (center[0] - 75, center[1] - 12), name, fill=(242, 244, 250), font=label
        )
    draw.text(
        (36, 910),
        "Four pinned long panels • fitted attached sleeves • integrated crescent clasp • no obi/bow/tassel/cape",
        fill=(190, 200, 222),
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
        for column in range(x_steps):
            a = row * stride + column
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
        z = 0.28 + (0.83 - 0.28) * t
        x = side * (0.34 - 0.19 * t)
        for column in range(y_steps + 1):
            u = column / y_steps
            y = -0.170 + 0.305 * u + 0.006 * math.sin(math.pi * u) * (1.0 - t)
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


def add_moon_gate_trim(armature, silver, violet) -> list[bpy.types.Object]:
    trims: list[bpy.types.Object] = []
    for side in (-1.0, 1.0):
        trims.append(
            base.import_base.curve_tube(
                f"Nocturnal_MoonGate_Front_{'L' if side < 0 else 'R'}",
                [
                    (side * 0.15, -0.184, 0.82),
                    (side * 0.23, -0.183, 0.61),
                    (side * 0.32, -0.175, 0.30),
                ],
                0.0025,
                silver,
                armature,
                "Hips",
            )
        )
        trims.append(
            base.import_base.curve_tube(
                f"Nocturnal_MoonGate_Back_{'L' if side < 0 else 'R'}",
                [
                    (side * 0.15, 0.145, 0.82),
                    (side * 0.23, 0.143, 0.61),
                    (side * 0.32, 0.135, 0.30),
                ],
                0.0022,
                violet,
                armature,
                "Hips",
            )
        )
    trims.append(
        base.import_base.curve_tube(
            "Nocturnal_Front_Closure",
            [(0.0, -0.188, 1.075), (0.0, -0.190, 0.93), (0.0, -0.186, 0.84)],
            0.0020,
            silver,
            armature,
            "Chest",
        )
    )
    arc = []
    for index in range(15):
        angle = math.radians(72.0 + 216.0 * index / 14.0)
        arc.append(
            (0.055 + 0.045 * math.cos(angle), -0.193, 0.86 + 0.045 * math.sin(angle))
        )
    trims.append(
        base.import_base.curve_tube(
            "Nocturnal_Integrated_Crescent_Clasp", arc, 0.0045, silver, armature, "Hips"
        )
    )
    return trims


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
    indigo = base.plain_material(
        "MAT_Nocturnal_Indigo_Woven", (0.028, 0.039, 0.075, 1.0), 0.70
    )
    charcoal = base.plain_material(
        "MAT_Nocturnal_Charcoal_Facing", (0.065, 0.070, 0.092, 1.0), 0.78
    )
    violet = base.plain_material(
        "MAT_Nocturnal_Violet_Accent", (0.25, 0.22, 0.38, 1.0), 0.66
    )
    silver = base.plain_material(
        "MAT_Nocturnal_Silver_Trim", (0.48, 0.52, 0.65, 1.0), 0.24, 0.82
    )

    garments: list[bpy.types.Object] = []
    garments.append(
        import_base.extract_surface(
            body,
            armature,
            "Nocturnal_Inner_Tunic_Front",
            lambda c: 0.82 <= c.z <= 1.075 and c.y < -0.004 and abs(c.x) <= 0.235,
            indigo,
            0.008,
        )
    )
    garments.append(
        import_base.extract_surface(
            body,
            armature,
            "Nocturnal_Inner_Tunic_Back",
            lambda c: 0.82 <= c.z <= 1.075 and c.y >= -0.004 and abs(c.x) <= 0.235,
            indigo,
            0.008,
        )
    )
    garments.append(
        import_base.extract_surface(
            body,
            armature,
            "Nocturnal_Attached_Sleeve_L",
            lambda c: 0.78 <= c.z <= 1.08 and c.x < -0.255,
            indigo,
            0.010,
        )
    )
    garments.append(
        import_base.extract_surface(
            body,
            armature,
            "Nocturnal_Attached_Sleeve_R",
            lambda c: 0.78 <= c.z <= 1.08 and c.x > 0.255,
            indigo,
            0.010,
        )
    )
    garments.append(import_base.collar_mesh(indigo, armature))

    def front_y(x, z, u, t):
        return (
            -0.160
            - 0.017 * (0.82 - z)
            - 0.016 * (x / 0.34) ** 2
            + 0.006 * math.sin(math.pi * u) * (1.0 - t)
        )

    def back_y(x, z, u, t):
        return (
            0.118
            + 0.016 * (0.82 - z)
            + 0.012 * (x / 0.34) ** 2
            + 0.005 * math.sin(math.pi * u) * (1.0 - t)
        )

    panels = [
        curved_panel(
            "Nocturnal_Hakama_Front_L",
            -0.15,
            0.0,
            -0.34,
            -0.012,
            0.28,
            0.83,
            front_y,
            indigo,
            armature,
            body,
        ),
        curved_panel(
            "Nocturnal_Hakama_Front_R",
            0.0,
            0.15,
            0.012,
            0.34,
            0.28,
            0.83,
            front_y,
            indigo,
            armature,
            body,
        ),
        curved_panel(
            "Nocturnal_Hakama_Back_L",
            -0.15,
            0.0,
            -0.34,
            -0.012,
            0.28,
            0.83,
            back_y,
            charcoal,
            armature,
            body,
        ),
        curved_panel(
            "Nocturnal_Hakama_Back_R",
            0.0,
            0.15,
            0.012,
            0.34,
            0.28,
            0.83,
            back_y,
            charcoal,
            armature,
            body,
        ),
    ]
    panels.extend(
        (
            side_gusset("Nocturnal_Hakama_Side_L", -1.0, indigo, armature, body),
            side_gusset("Nocturnal_Hakama_Side_R", 1.0, charcoal, armature, body),
        )
    )
    garments.extend(panels)
    garments.extend(add_moon_gate_trim(armature, silver, violet))
    for obj in garments:
        if obj.type == "MESH" and obj.name not in {panel.name for panel in panels}:
            add_shape_keys(obj, body)
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
        "referenceArtifact": "REPLACEMENT_NOT_EXACT",
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
            "construction": "fitted high-neck tunic with four-panel architectural long hakama and integrated crescent clasp",
            "excludedOverlap": [
                "crossed shrine upper",
                "detached wide sleeves",
                "conventional obi",
                "rear bow",
                "cords",
                "tassels",
                "floral decoration",
                "cape",
                "harness",
                "utility-wrap panels",
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
        "sourceReferenceStatus": job["sourceReferenceStatus"],
        "outputs": {
            "blend": job["blendPath"],
            "fbx": job["fbxAssetPath"],
            "prefab": job["prefabAssetPath"],
            "integratedPrefab": job["integratedPrefabAssetPath"],
            "multiview": str(multiview.relative_to(ROOT)).replace("\\", "/"),
            "poseReview": str(pose_review.relative_to(ROOT)).replace("\\", "/"),
        },
        "technicalGates": {
            "referenceArtifact": "FAIL_EXACT_ORIGINAL_MISSING",
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
        "# Nocturnal Shrine Maiden Long Hakama Set\n\nA replacement construction for Issue #647: a fitted, non-crossed high-neck tunic over four independent architectural long hakama panels. The design deliberately removes the rejected shrine/obi/bow/tassel/detached-sleeve coordinate.\n\nThe original Issue manufacturing board is not present in the current workspace. The persisted reference is explicitly a replacement and the ProductManifest remains WORKING until that exact artifact is recovered or the Issue gate is revised. Native Blender 4.4.3 Cloth is required for all four long panels.\n",
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
        product_root
        / "References/nocturnal-shrine-maiden-manufacturing-sheet-replacement.png",
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
