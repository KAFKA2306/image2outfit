"""Project actual garment edges and UV loops for the existing public gallery."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def svg(lines, title):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
        '<rect width="1024" height="1024" fill="#101827"/>'
        f'<text x="32" y="40" fill="white" font-size="24">{title}</text>'
        '<g fill="none" stroke="#9be3c0" stroke-width="0.65">'
        + "".join(
            f'<path d="M{x:.3f},{y:.3f}L{u:.3f},{v:.3f}"/>' for x, y, u, v in lines
        )
        + "</g></svg>"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    root = Path(__file__).resolve().parents[1]
    job = json.loads((root / args.job).read_text(encoding="utf-8"))
    source = root / job["blendPath"]
    skin_report = (
        root / ".image2outfit/products" / job["id"] / "skin/skin-export-report.json"
    )
    if skin_report.is_file():
        skin = json.loads(skin_report.read_text(encoding="utf-8"))
        source = root / skin["weightedBlendPath"]
        if digest(source) != skin["weightedBlendSha256"]:
            raise ValueError("Mesh showcase source is stale")
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
    meshes = [
        o
        for o in bpy.context.scene.objects
        if o.type == "MESH"
        and o.get("prototypeRole")
        in {"weighted-unfit-sewn-prototype", "unfitted-unweighted-sewn-pattern"}
    ]
    out = root / job["productRoot"] / "Previews/Mesh"
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "schemaVersion": 1,
        "productId": job["id"],
        "sourcePath": source.relative_to(root).as_posix(),
        "sourceSha256": digest(source),
        "blenderVersion": bpy.app.version_string,
        "objects": [],
        "records": [],
        "grantsQualityAcceptance": False,
        "boundary": "Base garment edges in neutral coordinates, not evaluated deformation or a topology/UV quality pass. Avatar meshes excluded by explicit garment role.",
    }
    if not meshes:
        report["status"] = "UNAVAILABLE_GARMENT_SELECTION"
    else:
        vertices = [o.matrix_world @ v.co for o in meshes for v in o.data.vertices]
        xmin, xmax = min(v.x for v in vertices), max(v.x for v in vertices)
        zmin, zmax = min(v.z for v in vertices), max(v.z for v in vertices)
        scale = 900 / max(xmax - xmin, zmax - zmin)
        topology = []
        uvlines = []
        for obj in meshes:
            uv = obj.data.uv_layers.active
            report["objects"].append(
                {
                    "name": obj.name,
                    "vertices": len(obj.data.vertices),
                    "edges": len(obj.data.edges),
                    "faces": len(obj.data.polygons),
                    "uvLayer": uv.name if uv else None,
                }
            )
            for edge in obj.data.edges:
                a, b = [
                    obj.matrix_world @ obj.data.vertices[i].co for i in edge.vertices
                ]
                topology.append(
                    (
                        62 + (a.x - xmin) * scale,
                        962 - (a.z - zmin) * scale,
                        62 + (b.x - xmin) * scale,
                        962 - (b.z - zmin) * scale,
                    )
                )
            if uv:
                for face in obj.data.polygons:
                    loops = list(face.loop_indices)
                    for i, j in zip(loops, loops[1:] + loops[:1]):
                        a, b = uv.data[i].uv, uv.data[j].uv
                        uvlines.append(
                            (
                                62 + a.x * 900,
                                962 - a.y * 900,
                                62 + b.x * 900,
                                962 - b.y * 900,
                            )
                        )
        diagrams = [("topology", topology, "Garment topology - front projection")]
        if uvlines:
            diagrams.append(("uv", uvlines, "Active UV layout - unit tile"))
        report["uvStatus"] = "PRESENT_UNVERIFIED" if uvlines else "MISSING"
        for name, lines, title in diagrams:
            path = out / f"{name}.svg"
            path.write_text(svg(lines, title), encoding="utf-8")
            report["records"].append(
                {
                    "name": name,
                    "path": path.relative_to(root).as_posix(),
                    "sha256": digest(path),
                }
            )
        report["status"] = "GENERATED_UNVERIFIED"
    (out / "mesh-showcase.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "objects"}))


if __name__ == "__main__":
    main()
