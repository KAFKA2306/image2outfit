#!/usr/bin/env python3
"""Model-corrected build for Malymoon CS-25-10300.

This revision keeps the v3 fitted garment checkpoint and adds the components
explicitly listed by the official Malymoon product page for CS-25-10300.
The source product image itself is not redistributed.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import bpy

import siroino_black_cat_bondage_v3_product as v3

v2 = v3.v2
geometry = v3.geometry
_V3_SHAPE = v3.corrected_shape
_ORIGINAL_BONE_FOR = v2.bone_for
PRODUCT_ID = "siroino-black-cat-bondage"
MODEL_CODE = "CS-25-10300"
OFFICIAL_URL = "https://www.malymoon-costume.com/view/item/000000004757"
ROOT = Path.cwd().resolve()


def remove_prefixes(objects: list[bpy.types.Object], prefixes: tuple[str, ...]) -> None:
    """Remove generated objects whose names begin with one of the prefixes."""
    v3.remove_objects(objects, lambda obj: obj.name.startswith(prefixes))


def z_tube(
    name: str,
    center_x: float,
    z0: float,
    z1: float,
    rx0: float,
    ry0: float,
    rx1: float,
    ry1: float,
    material: bpy.types.Material,
    *,
    segments: int = 18,
    rings: int = 8,
) -> bpy.types.Object:
    """Create a closed tapered tube aligned to the avatar's vertical leg axis."""
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for ring in range(rings):
        t = ring / (rings - 1)
        z = z0 + (z1 - z0) * t
        rx = rx0 + (rx1 - rx0) * t
        ry = ry0 + (ry1 - ry0) * t
        for segment in range(segments):
            angle = math.tau * segment / segments
            vertices.append(
                (
                    center_x + math.cos(angle) * rx,
                    math.sin(angle) * ry,
                    z,
                )
            )
    for ring in range(rings - 1):
        current = ring * segments
        following = (ring + 1) * segments
        for segment in range(segments):
            nxt = (segment + 1) % segments
            faces.append(
                (
                    current + segment,
                    current + nxt,
                    following + nxt,
                    following + segment,
                )
            )
    faces.append(tuple(reversed(tuple(range(segments)))))
    faces.append(tuple(range((rings - 1) * segments, rings * segments)))
    return v3.raw_mesh(name, vertices, faces, material, bevel=0.0015)


def pants_shell(material: bpy.types.Material) -> bpy.types.Object:
    """Create the fitted shorts/pants layer listed in the official set."""
    rows = 7
    segments = 24
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for row in range(rows):
        t = row / (rows - 1)
        z = 0.515 + 0.185 * t
        rx = 0.150 + 0.012 * t
        ry = 0.075 + 0.016 * t
        for segment in range(segments):
            angle = math.tau * segment / segments
            vertices.append((rx * math.cos(angle), ry * math.sin(angle), z))
    for row in range(rows - 1):
        current = row * segments
        following = (row + 1) * segments
        for segment in range(segments):
            nxt = (segment + 1) % segments
            faces.append(
                (
                    current + segment,
                    current + nxt,
                    following + nxt,
                    following + segment,
                )
            )
    obj = geometry.mesh("Pants_Body", vertices, faces, material, thickness=0.002)
    obj["referenceComponent"] = "pants"
    return obj


def rebuild_arm_belts(
    objects: list[bpy.types.Object],
    leather: bpy.types.Material,
    metal: bpy.types.Material,
) -> None:
    """Correct the official arm-belt count to six total: three per arm."""
    remove_prefixes(objects, ("Gauntlet_Strap_", "ArmBelt_"))
    for sign, side in ((-1.0, "L"), (1.0, "R")):
        for index, absolute_x in enumerate((0.395, 0.465, 0.535)):
            belt = geometry.torus(
                f"ArmBelt_{side}_{index}",
                (sign * absolute_x, -0.004, 0.995),
                0.037 - 0.0015 * index,
                0.0038,
                leather,
                (0.0, math.pi / 2.0, 0.0),
            )
            buckle = geometry.torus(
                f"ArmBelt_Buckle_{side}_{index}",
                (sign * absolute_x, -0.040, 0.995),
                0.0065,
                0.0018,
                metal,
                (0.0, math.pi / 2.0, 0.0),
            )
            objects.extend([belt, buckle])


def add_pants(objects: list[bpy.types.Object], leather: bpy.types.Material) -> None:
    """Add the pants/shorts layer beneath the pleated skirt."""
    remove_prefixes(objects, ("Pants_",))
    objects.append(pants_shell(leather))
    for sign, side in ((-1.0, "L"), (1.0, "R")):
        cuff = geometry.torus(
            f"Pants_Cuff_{side}",
            (sign * 0.073, 0.0, 0.520),
            0.052,
            0.004,
            leather,
            (0.0, 0.0, 0.0),
        )
        cuff.scale.y = 0.74
        objects.append(cuff)


def add_knee_high_socks(
    objects: list[bpy.types.Object],
    fabric: bpy.types.Material,
    leather: bpy.types.Material,
) -> None:
    """Add the knee-high socks and the separate ankle ornaments."""
    remove_prefixes(objects, ("KneeHighSock_", "Ankle_Ornament_"))
    for sign, side in ((-1.0, "L"), (1.0, "R")):
        sock = z_tube(
            f"KneeHighSock_{side}",
            sign * 0.070,
            0.115,
            0.405,
            0.035,
            0.034,
            0.047,
            0.044,
            fabric,
        )
        sock["referenceComponent"] = "knee-high-socks"
        ornament = geometry.torus(
            f"Ankle_Ornament_{side}",
            (sign * 0.070, 0.0, 0.135),
            0.037,
            0.0045,
            leather,
            (0.0, 0.0, 0.0),
        )
        ornament.scale.y = 0.88
        objects.extend([sock, ornament])


def add_tail(objects: list[bpy.types.Object], leather: bpy.types.Material) -> None:
    """Add the set's tail as a hip-bound mesh curve."""
    remove_prefixes(objects, ("CatTail",))
    curve = geometry.line(
        "CatTail",
        [
            (0.000, 0.095, 0.665),
            (0.015, 0.170, 0.720),
            (0.070, 0.245, 0.790),
            (0.105, 0.280, 0.700),
            (0.080, 0.260, 0.595),
        ],
        0.011,
        leather,
    )
    tail = v2.convert_curves([curve])[0]
    tail["referenceComponent"] = "tail"
    objects.append(tail)


def add_waist_studs(
    objects: list[bpy.types.Object],
    metal: bpy.types.Material,
) -> None:
    """Add the visible studded-metal rhythm of the CS-25-10300 waist belt."""
    remove_prefixes(objects, ("Waist_Stud_",))
    for index, angle in enumerate(
        (-2.55, -2.05, -1.55, -1.05, -0.55, 0.55, 1.05, 1.55, 2.05, 2.55)
    ):
        x = 0.172 * math.cos(angle)
        y = 0.112 * math.sin(angle)
        stud = geometry.cube(
            f"Waist_Stud_{index:02d}",
            (x, y, 0.720),
            (0.0042, 0.0030, 0.0042),
            metal,
            bevel=0.0015,
        )
        objects.append(stud)


def ensure_material_variants() -> None:
    """Store the two official colorways in the Blender source without geometry duplication."""
    black = bpy.data.materials.get("BCB_FauxLeather")
    fabric_black = bpy.data.materials.get("BCB_MatteFabric")
    if black is None or fabric_black is None:
        raise RuntimeError("base black-cat materials are unavailable")
    black["modelCode"] = MODEL_CODE
    black["colorway"] = "black"
    fabric_black["modelCode"] = MODEL_CODE
    fabric_black["colorway"] = "black"

    gray = bpy.data.materials.get("BCB_FauxLeather_Gray")
    if gray is None:
        gray = geometry.mat("BCB_FauxLeather_Gray", (0.23, 0.24, 0.25, 1.0), 0.05, 0.26)
    gray["modelCode"] = MODEL_CODE
    gray["colorway"] = "gray"

    gray_fabric = bpy.data.materials.get("BCB_MatteFabric_Gray")
    if gray_fabric is None:
        gray_fabric = geometry.mat("BCB_MatteFabric_Gray", (0.18, 0.19, 0.20, 1.0), 0.0, 0.50)
    gray_fabric["modelCode"] = MODEL_CODE
    gray_fabric["colorway"] = "gray"


def model_corrected_shape(objects: list[bpy.types.Object]) -> None:
    """Apply v3 fit corrections, then close the gap to the verified product model."""
    _V3_SHAPE(objects)
    leather = bpy.data.materials.get("BCB_FauxLeather")
    fabric = bpy.data.materials.get("BCB_MatteFabric")
    metal = bpy.data.materials.get("BCB_DarkMetal")
    if leather is None or fabric is None or metal is None:
        raise RuntimeError("black-cat materials are unavailable")

    rebuild_arm_belts(objects, leather, metal)
    add_pants(objects, leather)
    add_knee_high_socks(objects, fabric, leather)
    add_tail(objects, leather)
    add_waist_studs(objects, metal)
    ensure_material_variants()
    bpy.context.view_layer.update()


def model_bone_for(name: str) -> str:
    """Bind model-specific added components to the nearest existing Siroino bone."""
    if name.startswith("ArmBelt_"):
        return "LowerArm_L" if "_L_" in name else "LowerArm_R"
    if name.startswith("KneeHighSock_L") or name.startswith("Ankle_Ornament_L"):
        return "LowerLeg_L"
    if name.startswith("KneeHighSock_R") or name.startswith("Ankle_Ornament_R"):
        return "LowerLeg_R"
    if name.startswith("Pants_") or name.startswith("CatTail") or name.startswith("Waist_Stud_"):
        return "Hips"
    return _ORIGINAL_BONE_FOR(name)


def load_job() -> dict[str, Any]:
    """Load the canonical product job used by this product entrypoint."""
    path = ROOT / "config/products/siroino-black-cat-bondage/job.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))


def postprocess_reports(base_result: int) -> int:
    """Extend the technical audit with exact-model component checks."""
    job = load_job()
    product_root = ROOT / job["productRoot"]
    quality_path = product_root / "Evidence" / "Build" / "quality-audit.json"
    report_path = product_root / "Evidence" / "Build" / "product-build-report.json"

    names = {obj.name for obj in bpy.context.scene.objects}
    exact_belts = {
        f"ArmBelt_{side}_{index}"
        for side in ("L", "R")
        for index in range(3)
    }
    checks = {
        "modelCodeCS2510300": True,
        "armBelts6": exact_belts.issubset(names),
        "pantsLayer": "Pants_Body" in names,
        "kneeHighSocks2": {"KneeHighSock_L", "KneeHighSock_R"}.issubset(names),
        "ankleOrnaments2": {"Ankle_Ornament_L", "Ankle_Ornament_R"}.issubset(names),
        "tail": "CatTail" in names,
        "officialColorways": {
            "BCB_FauxLeather",
            "BCB_FauxLeather_Gray",
            "BCB_MatteFabric",
            "BCB_MatteFabric_Gray",
        }.issubset(set(bpy.data.materials.keys())),
    }

    quality: dict[str, Any] = {}
    if quality_path.is_file():
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
    component_checks = dict(quality.get("componentChecks", {}))
    component_checks.update(checks)
    quality.update(
        {
            "componentChecks": component_checks,
            "modelCode": MODEL_CODE,
            "officialSourceUrl": OFFICIAL_URL,
            "passed": bool(quality.get("passed", base_result == 0)) and all(checks.values()),
            "technicalOnly": True,
            "visualReviewRequired": True,
            "posePenetrationReviewRequired": True,
        }
    )
    v2.write_json(quality_path, quality)

    report: dict[str, Any] = {}
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    report.update(
        {
            "revision": "v4-cs-25-10300-reference-corrected",
            "referenceProduct": {
                "brand": "Malymoon",
                "modelCode": MODEL_CODE,
                "officialUrl": OFFICIAL_URL,
                "redistributed": False,
            },
            "pending": [
                "six-pose penetration review",
                "direct visual review of current five views and all required poses",
            ],
            "outOfScope": [
                "Unity import/save/reload",
                "NDMF/Modular Avatar execution",
                "VRChat Build & Test/runtime verification",
            ],
        }
    )
    v2.write_json(report_path, report)
    return 0 if quality["passed"] else 2


v3.v2.apply_shape_corrections = model_corrected_shape
v3.v2.bone_for = model_bone_for


def main() -> int:
    """Run the CS-25-10300-corrected production build."""
    return postprocess_reports(v3.main())


if __name__ == "__main__":
    raise SystemExit(main())
