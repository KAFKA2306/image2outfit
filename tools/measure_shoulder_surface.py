"""Measure neutral shoulder support on the evaluated avatar inside Blender."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--armhole", action="store_true")
    parser.add_argument("--sleeve-tube", action="store_true")
    parser.add_argument("--cuff-section", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.cuff_section and not args.sleeve_tube:
        parser.error("--cuff-section requires --sleeve-tube")
    root = Path.cwd()
    job = json.loads((root / args.job).read_text(encoding="utf-8-sig"))
    source = root / job["targetSourcePath"]
    blend = root / job["blendPath"]
    pose = json.loads((root / job["garmentPipeline"]["assemblyPosePath"]).read_text(encoding="utf-8-sig"))
    if digest(source) != pose["targetSourceSha256"]:
        raise ValueError("Avatar source does not match placement")
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    prefix = pose["upperSurfacePlacement"]["bodyMeshNamePrefix"]
    bodies = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.name.startswith(prefix) and not o.get("canonicalPieceIds")]
    if len(bodies) != 1:
        raise ValueError("Expected one explicit target body")
    body = bodies[0]
    values = {k.name: float(k.value) for k in body.data.shape_keys.key_blocks} if body.data.shape_keys else {}
    if any(abs(v) > 1e-8 for v in values.values()):
        raise ValueError("Expected neutral target Shape Keys")
    evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    data = evaluated.to_mesh()
    try:
        data.calc_loop_triangles()
        vertices = [evaluated.matrix_world @ v.co for v in data.vertices]
        triangles = [tuple(t.vertices) for t in data.loop_triangles]
    finally:
        evaluated.to_mesh_clear()
    tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
    records = []
    for side, bone_name in [("left", "UpperArm_L"), ("right", "UpperArm_R")]:
        rigs = [o for o in bpy.context.scene.objects if o.type == "ARMATURE" and bone_name in o.data.bones]
        if len(rigs) != 1:
            raise ValueError("Expected one avatar shoulder bone")
        rig = rigs[0]
        anchor = rig.matrix_world @ rig.data.bones[bone_name].head_local
        # A bone locates the sampling column only. Its height is not the surface.
        origin = Vector((anchor.x, anchor.y, max(v.z for v in vertices) + 0.01))
        hit, normal, triangle, distance = tree.ray_cast(origin, Vector((0, 0, -1)))
        if hit is None or normal.z <= 0 or not anchor.z <= hit.z <= anchor.z + 0.15:
            raise ValueError("Shoulder support ray missed the local upward body surface")
        clearance = pose["upperSurfacePlacement"]["normalClearanceM"]
        support = hit + normal * clearance
        record = {"side": side, "bone": bone_name, "samplingAnchorBlenderM": list(anchor), "rayOriginBlenderM": list(origin), "bodyTriangle": triangle, "surfaceBlenderM": list(hit), "surfaceNormalBlender": list(normal), "normalClearanceM": clearance, "supportGarmentCodeM": [support.x, support.z, -support.y]}
        if args.sleeve_tube:
            sections = []
            landmarks = {}
            sleeve_spec = pose["poses"][f"jacket-sleeve-{side}"]["cylindricalWrap"]
            for segment in (("UpperArm", "LowerArm", "Hand") if args.cuff_section else ("UpperArm", "LowerArm")):
                segment_name = f"{segment}_{'L' if side == 'left' else 'R'}"
                bone = rig.data.bones.get(segment_name)
                if bone is None:
                    raise ValueError(f"Missing sleeve measurement bone: {segment_name}")
                head = rig.matrix_world @ bone.head_local
                tail = rig.matrix_world @ bone.tail_local
                next_name = f"{'LowerArm' if segment == 'UpperArm' else 'Hand'}_{'L' if side == 'left' else 'R'}"
                next_bone = rig.data.bones.get(next_name)
                if next_bone is None:
                    raise ValueError(f"Missing sleeve segment endpoint: {next_name}")
                joint_end = tail if segment == "Hand" else rig.matrix_world @ next_bone.head_local
                landmarks[segment_name] = {"headBlenderM": list(head), "tailBlenderM": list(tail), "lengthM": (tail-head).length,
                    "measurementEndBone": next_name, "measurementEndBlenderM": list(joint_end), "measuredJointSpanM": (joint_end-head).length}
                # Imported bone tails may stop halfway to the next joint.
                # Sample the full joint-to-joint span, without bridging by guesswork.
                axis = (joint_end - head).normalized()
                up = Vector((0, 0, 1))
                up = (up - axis * up.dot(axis)).normalized()
                front = up.cross(axis).normalized()
                if front.y > 0:
                    front.negate()
                fractions = (0.15, 0.35, 0.60, 0.85, 0.95)
                if segment == "Hand":
                    target_x = anchor.x + sleeve_spec["axisDirection"]*sleeve_spec["cuffAxisDistanceM"]
                    fraction = (target_x-head.x)/(joint_end.x-head.x)
                    if not 0 <= fraction <= 1:
                        raise ValueError("Declared cuff lies outside measurable Hand bone span")
                    fractions = (0.0, fraction) if fraction > 1e-8 else (0.0,)
                for fraction in fractions:
                    center = head.lerp(joint_end, fraction)
                    axial_distance = abs(center.x-anchor.x)
                    tube_fraction = min(1.0, max(0.0, (axial_distance-sleeve_spec["capAxisDepthM"])/(sleeve_spec["cuffAxisDistanceM"]-sleeve_spec["capAxisDepthM"])))
                    base_width = sleeve_spec["tubeBaseBoundsXM"][1]-sleeve_spec["tubeBaseBoundsXM"][0]
                    cuff_width = sleeve_spec["cuffBoundsXM"][1]-sleeve_spec["cuffBoundsXM"][0]
                    samples = []
                    for i in range(64):
                        angle = i * 2 * math.pi / 64
                        direction = up * math.cos(angle) + front * math.sin(angle)
                        point, outward, face, radius = tree.ray_cast(center, direction, 0.08)
                        if point is None or radius < 0.002 or outward.dot(direction) <= 0.2:
                            raise ValueError(f"Invalid sleeve radial section: {segment_name}, {fraction}, sample {i}")
                        target = point + outward * clearance
                        samples.append({"surfaceBlenderM": list(point), "supportBlenderM": list(target), "normalBlender": list(outward), "bodyTriangle": face})
                    def perimeter(key):
                        return sum((Vector(samples[i][key]) - Vector(samples[(i+1) % 64][key])).length for i in range(64))
                    sections.append({"bone": segment_name, "boneFraction": fraction,
                        "centerBlenderM": list(center), "axisBlender": list(axis),
                        "upperArmHeadAxialDistanceM": axial_distance,
                        "bodyCircumferenceM": perimeter("surfaceBlenderM"),
                        "supportCircumferenceM": perimeter("supportBlenderM"),
                        "existingTubeCircumferenceM": base_width*(1-tube_fraction)+cuff_width*tube_fraction,
                        "samples": samples})
            record["sleeveTubeSections"] = sections
            hand_name = f"Hand_{'L' if side == 'left' else 'R'}"
            hand = rig.data.bones.get(hand_name)
            if hand is None:
                raise ValueError(f"Missing wrist landmark bone: {hand_name}")
            hand_head = rig.matrix_world @ hand.head_local
            landmarks[hand_name] = {"headBlenderM": list(hand_head), "upperArmHeadAxialDistanceM": abs(hand_head.x-anchor.x)}
            record["sleeveBoneLandmarks"] = landmarks
            record["existingSleevePlacement"] = {"cuffAxisDistanceM": sleeve_spec["cuffAxisDistanceM"],
                "capAxisDepthM": sleeve_spec["capAxisDepthM"],
                "tubePatternLengthM": sleeve_spec["tubeBaseLocalYM"]-sleeve_spec["cuffLocalYM"],
                "tubePlacedAxialLengthM": sleeve_spec["cuffAxisDistanceM"]-sleeve_spec["capAxisDepthM"],
                "cuffMinusHandHeadAxialDistanceM": sleeve_spec["cuffAxisDistanceM"]-abs(hand_head.x-anchor.x)}
            record["sleeveTubeMeasurementPolicy"] = {"radialSamples": 64,
                "maximumRayDistanceM": 0.08, "minimumRadiusM": 0.002,
                "minimumOutwardAlignment": 0.2, "normalClearanceM": clearance,
                "evidenceBoundary": "Neutral evaluated body radial sections. Clearance is provisional; no Large, continuous penetration, strain or motion acceptance."}
        if args.armhole:
            tail = rig.matrix_world @ rig.data.bones[bone_name].tail_local
            axis = (tail - anchor).normalized()
            up = Vector((0, 0, 1))
            up = (up - axis * up.dot(axis)).normalized()
            front = Vector((0, -1, 0))
            front = (front - axis * front.dot(axis) - up * front.dot(up)).normalized()
            attempts = []
            selected = None
            # Select the first closed local radial section along the actual arm.
            # These bounds are explicit prototype selection rules, not fit approval.
            for step in range(13):
                fraction = step * 0.05
                center = anchor.lerp(tail, fraction)
                samples = []
                for i in range(32):
                    angle = i * 2 * math.pi / 32
                    direction = up * math.cos(angle) + front * math.sin(angle)
                    point, outward, face, radius = tree.ray_cast(center, direction, 0.08)
                    if point is None or radius < 0.004 or outward.dot(direction) <= 0.2:
                        break
                    target = point + outward * clearance
                    samples.append({"angleRadians": angle, "surfaceBlenderM": list(point), "normalBlender": list(outward), "bodyTriangle": face, "radiusM": radius, "supportGarmentCodeM": [target.x, target.z, -target.y]})
                attempts.append({"boneFraction": fraction, "validRadialSamples": len(samples)})
                if len(samples) == 32:
                    selected = {"boneFraction": fraction, "axisBlender": list(axis), "centerBlenderM": list(center), "samples": samples}
                    break
            if selected is None:
                raise ValueError(f"No closed local arm cross-section: {side}; {attempts}")
            record["armholeSection"] = selected
            record["sectionSelection"] = {"attempts": attempts, "radialSamples": 32, "maximumRayDistanceM": 0.08, "minimumRadiusM": 0.004, "minimumOutwardAlignment": 0.2, "boneFractions": [0, 0.6, 0.05]}
        records.append(record)
    report = {"schemaVersion": 1, "productId": job["id"], "sourceAvatarSha256": digest(source), "sourceBlendPath": job["blendPath"], "sourceBlendSha256": digest(blend), "measurementScriptSha256": digest(Path(__file__)), "bodyObject": body.name, "bodyVertexCount": len(vertices), "bodyTriangleCount": len(triangles), "shapeKeyValues": values, "method": "evaluated-neutral-body-shoulder-support-and-requested-bone-radial-sections", "records": records, "evidenceBoundary": "Only the requested neutral body sections are measured. Clearance is an explicit prototype hypothesis. No Large, continuous penetration, seam strain or motion acceptance.", "grantsFitAcceptance": False}
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(report, indent=2) + "\n").encode()
    if output.exists() and output.read_bytes() != raw:
        raise ValueError("Preserve earlier measurement; use a new output path")
    output.write_bytes(raw)
    print(json.dumps({"output": str(output), "sha256": digest(output), "records": records}))


if __name__ == "__main__":
    main()
