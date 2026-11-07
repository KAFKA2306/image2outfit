"""Measure the declared skirt waist and proposed band on evaluated avatar bodies."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--band-height-m", type=float, required=True)
    parser.add_argument("--radial-clearance-m", type=float, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    if not 0 < args.band_height_m < .1 or not 0 < args.radial_clearance_m < .05:
        raise ValueError("Explicit prototype band dimensions are out of range")
    root = Path.cwd()
    read = lambda p: json.loads(p.read_text(encoding="utf-8-sig"))
    job = read(root/args.job)
    construction_path = root/job["garmentPipeline"]["constructionPath"]
    construction = read(construction_path)
    profile_path = root/construction["bodyProfileEvidence"]["path"]
    if sha(profile_path) != construction["bodyProfileEvidence"]["sha256"]:
        raise ValueError("Body profile evidence hash mismatch")
    profile = read(profile_path)
    target = root/job["targetSourcePath"]
    if sha(target) != profile["targetAvatarSha256"]:
        raise ValueError("Body profile avatar mismatch")
    source = root/job["blendPath"]
    bpy.ops.wm.open_mainfile(filepath=str(source))
    pose = read(root/job["garmentPipeline"]["assemblyPosePath"])
    prefix = pose["upperSurfacePlacement"]["bodyMeshNamePrefix"]
    bodies = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.name.startswith(prefix) and not o.get("canonicalPieceIds")]
    if len(bodies) != 1:
        raise ValueError("Expected one explicit avatar body")
    body = bodies[0]
    keys = body.data.shape_keys.key_blocks
    profiles = {name: profile["profiles"][name]["appliedShapeKeys"] for name in ("Neutral", "Large")}
    base = pose["poses"]["overskirt-front"]["skirtWrap"]["axisAnchorGarmentCodeM"]
    records = []
    for name, values in profiles.items():
        for key in keys:
            key.value = 0
        for key, value in values.items():
            if key not in keys:
                raise ValueError(f"Missing declared Shape Key: {key}")
            keys[key].value = value
        bpy.context.view_layer.update()
        evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
        data = evaluated.to_mesh()
        try:
            data.calc_loop_triangles()
            vertices = [evaluated.matrix_world @ v.co for v in data.vertices]
            triangles = [tuple(t.vertices) for t in data.loop_triangles]
        finally:
            evaluated.to_mesh_clear()
        tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
        sections = []
        for z in [base[1]+args.band_height_m*t for t in (0, .5, 1)]:
            center = Vector((base[0], -base[2], z))
            points, supports = [], []
            for i in range(128):
                angle = 2*math.pi*i/128
                direction = Vector((math.sin(angle), -math.cos(angle), 0))
                point, normal, face, distance = tree.ray_cast(center, direction, .3)
                if point is None or distance < .01 or normal.dot(direction) <= .2:
                    raise ValueError(f"Invalid waist section: {name}, {z}, {i}")
                support = point+direction*args.radial_clearance_m
                points.append(list(point)); supports.append(list(support))
            perimeter = lambda points: sum((Vector(points[i])-Vector(points[(i+1)%len(points)])).length for i in range(len(points)))
            sections.append({"zM":z, "bodyCircumferenceM":perimeter(points), "supportCircumferenceM":perimeter(supports), "bodyBlenderM":points, "supportBlenderM":supports})
        records.append({"profile":name, "appliedShapeKeys":values, "sections":sections})
    report = {"schemaVersion":1, "productId":job["id"], "sourceAvatarSha256":sha(target), "sourceBlendSha256":sha(source), "assemblyPoseSha256":sha(root/job["garmentPipeline"]["assemblyPosePath"]), "measurementScriptSha256":sha(Path(__file__)), "blenderVersion":bpy.app.version_string, "bandHeightM":args.band_height_m, "radialClearanceM":args.radial_clearance_m, "records":records, "evidenceBoundary":"Evaluated Neutral and declared Large body sections only. Proposed 25 mm band height and radial clearance are prototype drafting hypotheses. No garment Shape Key, fit, motion, continuous penetration or release acceptance.", "grantsFitAcceptance":False}
    output = root/args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(report,indent=2)+"\n").encode()
    if output.exists() and output.read_bytes() != raw:
        raise ValueError("Preserve previous measurement; use another path")
    output.write_bytes(raw)
    print(json.dumps({"output":str(output),"sha256":sha(output)}))


if __name__ == "__main__":
    main()
