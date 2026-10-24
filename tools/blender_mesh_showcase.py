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
        "boundary": "Base garment edges in neutral coordinates, not evaluated deformation or a topology/UV quality pass. Only the explicitly named AuthoredPatternPanels layer is counted as source-authored; other active layers are listed as unverified and omitted from its chart. Avatar meshes excluded by explicit garment role.",
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
        authored_uv_layers = {
            obj.name: obj.data.uv_layers.get("AuthoredPatternPanels") for obj in meshes
        }
        uv_mapped_objects = [
            obj for obj in meshes if authored_uv_layers[obj.name] is not None
        ]
        uv_unverified_objects = [
            obj.name
            for obj in meshes
            if obj.data.uv_layers.active and authored_uv_layers[obj.name] is None
        ]
        uv_unmapped_objects = [
            obj.name for obj in meshes if not obj.data.uv_layers.active
        ]
        complete_uv_coverage = len(uv_mapped_objects) == len(meshes)
        for obj in meshes:
            uv = obj.data.uv_layers.active
            authored_uv = authored_uv_layers[obj.name]
            report["objects"].append(
                {
                    "name": obj.name,
                    "vertices": len(obj.data.vertices),
                    "edges": len(obj.data.edges),
                    "faces": len(obj.data.polygons),
                    "uvLayer": uv.name if uv else None,
                    "sourceAuthoredUvLayer": (
                        authored_uv.name if authored_uv is not None else None
                    ),
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
            # Draw only authored UVs. The report and diagram label disclose any
            # omitted garment objects; no unwrap or substitute coordinates are made.
            if authored_uv is not None:
                for face in obj.data.polygons:
                    loops = list(face.loop_indices)
                    for i, j in zip(loops, loops[1:] + loops[:1]):
                        a, b = authored_uv.data[i].uv, authored_uv.data[j].uv
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
            uv_title = (
                "Source-authored pattern UV - unit tile"
                if complete_uv_coverage
                else (
                    f"PARTIAL source-authored pattern UV ({len(uv_mapped_objects)}/"
                    f"{len(meshes)} objects; {len(uv_unverified_objects)} unverified maps, "
                    f"{len(uv_unmapped_objects)} missing; omitted)"
                )
            )
            diagrams.append(("uv", uvlines, uv_title))
        report["uvMappedObjects"] = [obj.name for obj in uv_mapped_objects]
        report["uvUnverifiedObjects"] = uv_unverified_objects
        report["uvUnmappedObjects"] = uv_unmapped_objects
        report["uvCoverage"] = {
            "sourceAuthoredObjectCount": len(uv_mapped_objects),
            "unverifiedActiveLayerObjectCount": len(uv_unverified_objects),
            "missingActiveLayerObjectCount": len(uv_unmapped_objects),
            "totalObjectCount": len(meshes),
        }
        report["uvStatus"] = (
            "MISSING"
            if not uvlines and not uv_unverified_objects and not uv_unmapped_objects
            else "PRESENT_UNVERIFIED"
            if complete_uv_coverage
            else "UNVERIFIED_PROVENANCE"
            if not uvlines and uv_unverified_objects
            else "PARTIAL_UNVERIFIED"
        )
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
        if report["uvStatus"] == "MISSING":
            stale_uv = out / "uv.svg"
            if stale_uv.exists():
                stale_uv.unlink()
        report["status"] = "GENERATED_UNVERIFIED"
    (out / "mesh-showcase.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "objects"}))


if __name__ == "__main__":
    main()
