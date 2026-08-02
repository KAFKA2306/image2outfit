#!/usr/bin/env python3
"""Boundary-welded, fitted Siroino Wide Cargo v34."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bmesh
import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit_v32 as v32


WAIST_Z = 0.785


def fit_profile(obj: bpy.types.Object) -> None:
    """Fit waist and upper thigh while preserving a relaxed straight leg."""
    v32.previous.apply_product_profile(obj)
    for vertex in obj.data.vertices:
        x, y, z = vertex.co
        waist = v32.smoothstep(0.665, 0.805, z)
        upper = v32.smoothstep(0.405, 0.505, z) * (
            1.0 - v32.smoothstep(0.680, 0.745, z)
        )
        lower = 1.0 - v32.smoothstep(v32.HEM_Z, 0.455, z)

        vertex.co.x *= 1.0 - 0.145 * waist
        vertex.co.y *= 1.0 - 0.100 * waist
        vertex.co.x *= 1.0 - 0.095 * upper
        vertex.co.y *= 1.0 - 0.050 * upper
        vertex.co.x *= 1.0 - 0.020 * lower
        vertex.co.y *= 1.0 - 0.018 * lower

        side = v32.smoothstep(0.100, 0.150, abs(vertex.co.x))
        drape = math.sin((z - v32.HEM_Z) * math.pi * 4.6) * 0.0018 * side
        if abs(vertex.co.x) > 1e-6:
            vertex.co.x += math.copysign(drape, vertex.co.x)
        vertex.co.z = max(float(vertex.co.z), v32.HEM_Z)
    obj.data.update(calc_edges=True)


def level_open_boundaries(obj: bpy.types.Object) -> dict[str, int]:
    """Level the waist and both hems before welding duplicate seam vertices."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    waist_components = 0
    hem_components = 0
    for edges in v32.boundary_components(bm):
        vertices = {vertex for edge in edges for vertex in edge.verts}
        if not vertices:
            continue
        mean_z = sum(float(vertex.co.z) for vertex in vertices) / len(vertices)
        if mean_z >= 0.690:
            for vertex in vertices:
                vertex.co.z = WAIST_Z
            waist_components += 1
        elif mean_z <= 0.225:
            for vertex in vertices:
                vertex.co.z = v32.HEM_Z
            hem_components += 1
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update(calc_edges=True)
    return {"waist": waist_components, "hem": hem_components}


def weld_and_remove_degenerates(obj: bpy.types.Object) -> dict[str, int]:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    before_vertices = len(bm.verts)
    before_faces = len(bm.faces)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=0.00035)
    bmesh.ops.dissolve_degenerate(
        bm,
        dist=0.00001,
        edges=list(bm.edges),
    )
    zero_faces = [face for face in bm.faces if face.calc_area() <= 1e-12]
    if zero_faces:
        bmesh.ops.delete(bm, geom=zero_faces, context="FACES")
    loose = [vertex for vertex in bm.verts if not vertex.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    after_vertices = len(bm.verts)
    after_faces = len(bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update(calc_edges=True)
    return {
        "mergedVertices": before_vertices - after_vertices,
        "removedFaces": before_faces - after_faces,
    }


def reset_material_nodes(material: bpy.types.Material) -> tuple[object, object]:
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return nodes, shader


def configure_fabric(material: bpy.types.Material) -> None:
    nodes, shader = reset_material_nodes(material)
    shader.inputs["Roughness"].default_value = 0.92
    shader.inputs["Metallic"].default_value = 0.0
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 145.0
    noise.inputs["Detail"].default_value = 2.2
    noise.inputs["Roughness"].default_value = 0.62
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.20
    ramp.color_ramp.elements[0].color = (0.045, 0.052, 0.065, 1.0)
    ramp.color_ramp.elements[1].position = 0.80
    ramp.color_ramp.elements[1].color = (0.130, 0.145, 0.175, 1.0)
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.10
    bump.inputs["Distance"].default_value = 0.020
    material.node_tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    material.node_tree.links.new(ramp.outputs["Color"], shader.inputs["Base Color"])
    material.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    material.node_tree.links.new(bump.outputs["Normal"], shader.inputs["Normal"])
    material.diffuse_color = (0.09, 0.105, 0.13, 1.0)


def configure_panel(material: bpy.types.Material) -> None:
    nodes, shader = reset_material_nodes(material)
    shader.inputs["Base Color"].default_value = (0.004, 0.006, 0.011, 1.0)
    shader.inputs["Roughness"].default_value = 0.23
    shader.inputs["Metallic"].default_value = 0.04
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 28.0
    noise.inputs["Detail"].default_value = 1.4
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.035
    bump.inputs["Distance"].default_value = 0.010
    material.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    material.node_tree.links.new(bump.outputs["Normal"], shader.inputs["Normal"])
    material.diffuse_color = (0.004, 0.006, 0.011, 1.0)


def assign_materials(pants: bpy.types.Object, fabric, panel) -> None:
    configure_fabric(fabric)
    configure_panel(panel)
    pants.data.materials.clear()
    pants.data.materials.append(fabric)
    pants.data.materials.append(panel)
    for polygon in pants.data.polygons:
        points = [pants.data.vertices[index].co for index in polygon.vertices]
        mean_x = sum(float(point.x) for point in points) / len(points)
        mean_y = sum(float(point.y) for point in points) / len(points)
        mean_z = sum(float(point.z) for point in points) / len(points)
        waistband = mean_z >= 0.742
        knee_panel = 0.350 <= mean_z <= 0.440
        side_panel = abs(mean_x) >= 0.112 and 0.235 <= mean_z <= 0.710
        cargo_patch = (
            abs(mean_x) >= 0.095
            and abs(mean_y) >= 0.050
            and 0.485 <= mean_z <= 0.650
        )
        polygon.material_index = (
            1 if waistband or knee_panel or side_panel or cargo_patch else 0
        )
    pants.data.update()


def create_outfit(body, armature, fabric, strap, metal):
    del metal
    pants = v32.build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        v32.previous.pants_surface,
        fabric,
        0.011,
    )
    fit_profile(pants)
    v32.build.clean_topology(pants)
    boundaries = level_open_boundaries(pants)
    repair = weld_and_remove_degenerates(pants)
    # Level once more after welding, then remove any collapse created by the
    # horizontal open boundaries.
    boundaries_after = level_open_boundaries(pants)
    repair_after = weld_and_remove_degenerates(pants)
    subdivided = v32.subdivide_long_interior_edges(pants)
    weld_and_remove_degenerates(pants)
    v32.unwrap_uv(pants)
    assign_materials(pants, fabric, strap)
    pants["flattened_hem_boundaries"] = max(
        boundaries["hem"], boundaries_after["hem"]
    )
    pants["levelled_waist_boundaries"] = max(
        boundaries["waist"], boundaries_after["waist"]
    )
    pants["merged_boundary_vertices"] = (
        repair["mergedVertices"] + repair_after["mergedVertices"]
    )
    pants["removed_degenerate_faces"] = (
        repair["removedFaces"] + repair_after["removedFaces"]
    )
    pants["subdivided_long_interior_edges"] = subdivided
    pants["removed_stretched_faces"] = 0
    return [pants]


def audit() -> dict[str, object]:
    report = v32.audit()
    pants = bpy.data.objects.get("Cargo_Continuous_Pants")
    if pants is None:
        return report
    checks = report["checks"]
    metrics = checks["metrics"]
    metrics.update(
        {
            "levelledWaistBoundaries": int(
                pants.get("levelled_waist_boundaries", 0)
            ),
            "mergedBoundaryVertices": int(
                pants.get("merged_boundary_vertices", 0)
            ),
            "removedDegenerateFaces": int(
                pants.get("removed_degenerate_faces", 0)
            ),
        }
    )
    checks["levelWaistPassed"] = (
        int(pants.get("levelled_waist_boundaries", 0)) >= 1
    )
    checks["boundaryWeldPassed"] = metrics["degenerateTriangles"] == 0
    required = [
        "singleShellOnly",
        "finiteCoordinatesPassed",
        "sourceStretchResolved",
        "spikeGuardPassed",
        "topologyPassed",
        "uvPassed",
        "materialSeparationPassed",
        "shapeKeyIsolationPassed",
        "footAndFloorClearancePassed",
        "controlledVolumePassed",
        "profileContinuityPassed",
        "kneeContinuityPassed",
        "rearSeatClearancePassed",
        "levelOpenHemsPassed",
        "levelWaistPassed",
        "boundaryWeldPassed",
        "waistVolumePassed",
        "upperThighVolumePassed",
        "straightWideProfilePassed",
    ]
    report["passed"] = all(bool(checks.get(name)) for name in required)
    return report


def record(report: dict[str, object]) -> None:
    v32.record(report)
    _, job = v32.build.c.load_job()
    path = v32.build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["designRevision"] = "v34-boundary-welded-fitted-panels"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


v32.build.create_outfit = create_outfit


if __name__ == "__main__":
    v32.clear_stale_render_evidence()
    v32.build.main()
    result = audit()
    record(result)
    v32.base.save_distribution_blend()
    if not result["passed"]:
        raise RuntimeError(f"v34 boundary and volume audit failed: {result}")
    raise SystemExit(0)
