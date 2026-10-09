"""Import a hash-bound GarmentCode sewn surface into an editable Blender prototype.

This stage deliberately reports unweighted/untested geometry as rejected. It does
not substitute a body shell for the submitted pattern or claim product fit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(value):
    path = (ROOT / value).resolve()
    if ROOT not in path.parents:
        raise ValueError(f"Path escapes repository: {value}")
    return path


def add_prototype_edge_trim(mesh, job, pieces, recipe):
    """Build explicit bevelled trim on declared open panel edges only.

    This is a visual prototype aid. It does not add seam allowance or establish
    collision, fit, construction, or runtime acceptance.
    """
    spec = recipe.get("prototypeEdgeTrim")
    if spec is None:
        return {"applied": False, "reason": "not-declared"}
    if not isinstance(spec, dict):
        raise ValueError("prototypeEdgeTrim must be an object")
    if spec.get("enabled") is False:
        return {"applied": False, "reason": "disabled-unmapped-panel-boundaries"}
    piece_ids = spec.get("pieceIds")
    if not isinstance(piece_ids, list) or not piece_ids or not set(piece_ids) <= set(pieces):
        raise ValueError("prototypeEdgeTrim pieceIds must name existing canonical pieces")
    radius = float(spec.get("bevelRadiusM", 0.0))
    color = spec.get("baseColorLinearRgb")
    if not (0.0001 <= radius <= 0.005):
        raise ValueError("prototypeEdgeTrim bevelRadiusM must be between 0.1 and 5 mm")
    if (not isinstance(color, list) or len(color) != 3
            or any(not isinstance(channel, (int, float)) or not 0 <= channel <= 1 for channel in color)):
        raise ValueError("prototypeEdgeTrim baseColorLinearRgb must be three channels in [0, 1]")

    edge_faces = {}
    for face_index, face in enumerate(mesh["faces"]):
        owner = mesh["facePieceIds"][face_index]
        for offset, first in enumerate(face):
            second = face[(offset + 1) % len(face)]
            edge = tuple(sorted((int(first), int(second))))
            edge_faces.setdefault(edge, []).append(owner)
    boundaries = {piece_id: set() for piece_id in piece_ids}
    for edge, adjacent_owners in edge_faces.items():
        if len(adjacent_owners) == 1 and adjacent_owners[0] in boundaries:
            boundaries[adjacent_owners[0]].add(edge)

    material = bpy.data.materials.new(str(spec.get("name", "lilac-edge-trim-prototype")))
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Roughness"].default_value = float(spec.get("roughness", 0.5))
    shader.inputs["Metallic"].default_value = float(spec.get("metallic", 0.0))
    material["evidenceBoundary"] = spec.get("evidenceBoundary", "Prototype visual hypothesis; not approved trim or fit.")

    audits = {}
    for piece_id, edges in boundaries.items():
        if not edges:
            audits[piece_id] = {"boundaryEdgeCount": 0, "polylineCount": 0}
            continue
        adjacency = {}
        remaining = set(edges)
        for first, second in edges:
            adjacency.setdefault(first, set()).add(second)
            adjacency.setdefault(second, set()).add(first)
        chains = []
        while remaining:
            degrees = {vertex: sum(tuple(sorted((vertex, other))) in remaining for other in neighbors)
                       for vertex, neighbors in adjacency.items()}
            endpoints = sorted(vertex for vertex, degree in degrees.items() if degree == 1)
            start = endpoints[0] if endpoints else min(min(edge) for edge in remaining)
            chain = [start]
            current = start
            while True:
                choices = sorted(other for other in adjacency.get(current, ())
                                 if tuple(sorted((current, other))) in remaining)
                if not choices:
                    break
                following = choices[0]
                remaining.remove(tuple(sorted((current, following))))
                chain.append(following)
                current = following
                if current == start:
                    break
            if len(chain) >= 2:
                chains.append(chain)

        curve = bpy.data.curves.new(f"{job['id']}-{piece_id}-prototype-piping", "CURVE")
        curve.dimensions = "3D"
        curve.resolution_u = 1
        curve.bevel_depth = radius
        curve.bevel_resolution = 2
        curve.use_fill_caps = True
        for chain in chains:
            spline = curve.splines.new("POLY")
            spline.points.add(len(chain) - 1)
            for point, vertex_index in zip(spline.points, chain):
                point.co = (*mesh["vertices"][vertex_index], 1)
        trim = bpy.data.objects.new(f"{job['id']}-prototype-piping-{piece_id}", curve)
        bpy.context.collection.objects.link(trim)
        trim.data.materials.append(material)
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = trim
        trim.select_set(True)
        bpy.ops.object.convert(target="MESH")
        trim = bpy.context.view_layer.objects.active
        trim["prototypeRole"] = "unfitted-prototype-edge-trim"
        trim["canonicalPieceIds"] = json.dumps(pieces)
        ownership = trim.data.attributes.new("canonical_piece_index", "INT", "FACE")
        owner_index = pieces.index(piece_id)
        for item in ownership.data:
            item.value = owner_index
        # Preserve attachment to the sewn edge across cloth component splitting.
        # Independent nearest-body weights can detach trim from its cloth surface.
        from mathutils import Vector
        bindings = []
        segments = [(a, b, Vector(mesh["vertices"][a]), Vector(mesh["vertices"][b]))
                    for a, b in sorted(edges)]
        for vertex in trim.data.vertices:
            best = None
            for a, b, first, second in segments:
                direction = second - first
                if direction.length_squared <= 1e-16:
                    raise ValueError("Prototype piping contains a zero-length source edge")
                fraction = max(0.0, min(1.0, (vertex.co-first).dot(direction)/direction.length_squared))
                offset = vertex.co - first.lerp(second, fraction)
                record = (offset.length_squared, a, b, fraction, list(offset), list(direction))
                if best is None or record[0] < best[0]:
                    best = record
            bindings.append({"first": best[1], "second": best[2], "fraction": best[3],
                             "restOffset": best[4], "restDirection": best[5]})
        trim["prototypeTrimBindings"] = json.dumps(bindings)
        trim["prototypeTrimPieceId"] = piece_id
        trim.select_set(False)
        audits[piece_id] = {
            "boundaryEdgeCount": len(edges),
            "polylineCount": len(chains),
            "meshVertexCount": len(trim.data.vertices),
            "bindingMethod": "canonical-sewn-edge-interpolation",
            "grantsFitAcceptance": False,
        }
    return {
        "applied": True,
        "materialName": material.name,
        "bevelRadiusM": radius,
        "pieceAudits": audits,
        "grantsFitAcceptance": False,
        "evidenceBoundary": spec.get("evidenceBoundary", "Prototype visual hypothesis; not approved trim or fit."),
    }


def add_prototype_surface_motifs(mesh, job, recipe):
    """Place provisional plastron and elbow quilting on the sewn garment surface."""
    spec = recipe.get("prototypeSurfaceMotifs")
    if spec is None:
        return {"applied": False, "reason": "not-declared"}
    if not isinstance(spec, dict):
        raise ValueError("prototypeSurfaceMotifs must be an object")

    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    points = [Vector(value) for value in mesh["vertices"]]
    owners = mesh["facePieceIds"]

    def locator(piece_ids):
        faces = []
        selected = set(piece_ids)
        for face, owner in zip(mesh["faces"], owners):
            if owner not in selected or len(face) != 3:
                continue
            center_y = sum(points[index].y for index in face) / 3
            if center_y < -0.004:
                faces.append(face)
        if not faces:
            raise ValueError(f"No front-facing garment triangles for {sorted(selected)}")
        face_owners = []
        selected = set(piece_ids)
        for face, owner in zip(mesh["faces"], owners):
            if owner not in selected or len(face) != 3:
                continue
            center_y = sum(points[index].y for index in face) / 3
            if center_y < -0.004:
                face_owners.append(owner)
        return BVHTree.FromPolygons(points, faces, all_triangles=True), face_owners

    def surface_point(locator_value, x, z, query_y, offset):
        tree, face_owners = locator_value
        result = tree.find_nearest(Vector((x, query_y, z)))
        if result is None or result[0] is None or result[0].y >= -0.002:
            raise ValueError("Prototype motif could not bind to the garment front surface")
        return result[0] + Vector((0.0, -offset, 0.0)), face_owners[result[2]]

    def bind_piece_ownership(obj, piece_ids, face_piece_ids):
        obj["canonicalPieceIds"] = json.dumps(piece_ids)
        ownership = obj.data.attributes.new("canonical_piece_index", "INT", "FACE")
        piece_indices = {piece_id: index for index, piece_id in enumerate(piece_ids)}
        for face, piece_id in zip(ownership.data, face_piece_ids):
            face.value = piece_indices[piece_id]
        obj["prototypeRole"] = "unfitted-unweighted-sewn-pattern"

    color = spec.get("baseColorLinearRgb")
    if (not isinstance(color, list) or len(color) != 3
            or any(not isinstance(channel, (int, float)) or not 0 <= channel <= 1 for channel in color)):
        raise ValueError("prototypeSurfaceMotifs baseColorLinearRgb must be three channels in [0, 1]")
    material = bpy.data.materials.new(str(spec.get("materialName", "lilac-surface-motif-hypothesis")))
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Roughness"].default_value = float(spec.get("roughness", 0.55))
    shader.inputs["Metallic"].default_value = float(spec.get("metallic", 0.0))
    material["evidenceBoundary"] = spec.get(
        "evidenceBoundary", "Unfitted surface-placement hypothesis; appearance acceptance remains pending."
    )

    plastron = spec.get("plastron")
    if not isinstance(plastron, dict):
        raise ValueError("prototypeSurfaceMotifs plastron must be an object")
    start = plastron.get("pathStartXZ")
    end = plastron.get("pathEndXZ")
    sample_count = int(plastron.get("sampleCount", 32))
    half_width = float(plastron.get("halfWidthM", 0.018))
    surface_offset = float(plastron.get("surfaceOffsetM", 0.0015))
    if (not isinstance(start, list) or len(start) != 2
            or not isinstance(end, list) or len(end) != 2
            or sample_count < 4 or not 0.005 <= half_width <= 0.04
            or not 0.0002 <= surface_offset <= 0.005):
        raise ValueError("Invalid prototype plastron path, width, or surface offset")
    front_tree = locator(plastron.get("hostPieceIds", []))
    dx, dz = float(end[0]) - float(start[0]), float(end[1]) - float(start[1])
    length = (dx * dx + dz * dz) ** 0.5
    if length <= 0.02:
        raise ValueError("Prototype plastron path is too short")
    normal_x, normal_z = -dz / length, dx / length
    band_vertices = []
    band_sample_owners = []
    for index in range(sample_count + 1):
        fraction = index / sample_count
        center_x = float(start[0]) + dx * fraction
        center_z = float(start[1]) + dz * fraction
        for side in (-1.0, 1.0):
            x = center_x + normal_x * half_width * side
            z = center_z + normal_z * half_width * side
            point, owner = surface_point(
                front_tree, x, z, float(plastron.get("frontQueryYM", -0.16)), surface_offset
            )
            band_vertices.append(list(point))
            band_sample_owners.append(owner)
    band_faces = []
    band_face_owners = []
    for index in range(sample_count):
        first = index * 2
        band_faces.append((first, first + 1, first + 3, first + 2))
        band_face_owners.append(band_sample_owners[index])
    band_data = bpy.data.meshes.new(f"{job['id']}-prototype-plastron-surface")
    band_data.from_pydata(band_vertices, [], band_faces)
    band_data.update()
    band = bpy.data.objects.new(f"{job['id']}-prototype-plastron-hypothesis", band_data)
    bpy.context.collection.objects.link(band)
    band.data.materials.append(material)
    band_pieces = sorted(set(band_face_owners))
    bind_piece_ownership(band, band_pieces, band_face_owners)
    band["prototypeRole"] = "unfitted-unweighted-sewn-pattern"
    band["canonicalHostPieceIds"] = json.dumps(plastron["hostPieceIds"])
    band["uvStatus"] = "NOT_CREATED"

    quilt = spec.get("elbowQuilting")
    if not isinstance(quilt, dict):
        raise ValueError("prototypeSurfaceMotifs elbowQuilting must be an object")
    sleeve_ids = quilt.get("hostPieceIds")
    if not isinstance(sleeve_ids, list) or len(sleeve_ids) != 2:
        raise ValueError("Elbow quilting requires two declared sleeve host pieces")
    sleeve_trees = {piece_id: locator([piece_id]) for piece_id in sleeve_ids}
    center_abs_x = float(quilt.get("centerAbsXM", 0.275))
    center_z = float(quilt.get("centerZM", 1.012))
    half_length = float(quilt.get("halfLengthM", 0.035))
    half_height = float(quilt.get("halfHeightM", 0.024))
    curve_depth = float(quilt.get("threadRadiusM", 0.001))
    query_y = float(quilt.get("frontQueryYM", -0.08))
    if not (0.01 <= half_length <= 0.08 and 0.01 <= half_height <= 0.06
            and 0.0002 <= curve_depth <= 0.003):
        raise ValueError("Invalid prototype elbow quilting dimensions")
    quilt_audits = {}
    for piece_id in sleeve_ids:
        curve_data = bpy.data.curves.new(f"{job['id']}-{piece_id}-prototype-elbow-quilting", "CURVE")
        curve_data.dimensions = "3D"
        curve_data.resolution_u = 1
        curve_data.bevel_depth = curve_depth
        curve_data.bevel_resolution = 2
        curve_data.use_fill_caps = True
        sign = 1.0 if "left" in piece_id else -1.0
        center_x = sign * center_abs_x
        raw_paths = [
            [(center_x, center_z + half_height),
             (center_x + sign * half_length, center_z),
             (center_x, center_z - half_height),
             (center_x - sign * half_length, center_z),
             (center_x, center_z + half_height)],
            [(center_x, center_z + half_height), (center_x, center_z - half_height)],
            [(center_x - sign * half_length, center_z), (center_x + sign * half_length, center_z)],
        ]
        tree = sleeve_trees[piece_id]
        projected_count = 0
        for raw_path in raw_paths:
            sampled = []
            for first, second in zip(raw_path, raw_path[1:]):
                for step in range(5):
                    fraction = step / 5
                    sampled.append((
                        first[0] + (second[0] - first[0]) * fraction,
                        first[1] + (second[1] - first[1]) * fraction,
                    ))
            sampled.append(raw_path[-1])
            spline = curve_data.splines.new("POLY")
            spline.points.add(len(sampled) - 1)
            for point, (x, z) in zip(spline.points, sampled):
                bound, _ = surface_point(tree, x, z, query_y, surface_offset)
                point.co = (*bound, 1)
                projected_count += 1
        quilting = bpy.data.objects.new(f"{job['id']}-{piece_id}-prototype-elbow-quilting-hypothesis", curve_data)
        bpy.context.collection.objects.link(quilting)
        quilting.data.materials.append(material)
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = quilting
        quilting.select_set(True)
        bpy.ops.object.convert(target="MESH")
        quilting = bpy.context.view_layer.objects.active
        bind_piece_ownership(quilting, [piece_id], [piece_id] * len(quilting.data.polygons))
        quilting["prototypeRole"] = "unfitted-unweighted-sewn-pattern"
        quilting["hostPieceIds"] = json.dumps([piece_id])
        quilting.select_set(False)
        quilt_audits[piece_id] = {
            "surfaceSampleCount": projected_count,
            "pathCount": len(raw_paths),
            "hostPieceId": piece_id,
            "grantsAppearanceAcceptance": False,
        }
    return {
        "applied": True,
        "plastron": {
            "vertexCount": len(band_vertices),
            "quadCount": len(band_faces),
            "pathStartXZ": start,
            "pathEndXZ": end,
            "halfWidthM": half_width,
            "hostPieceIds": plastron["hostPieceIds"],
            "surfaceBinding": "nearest-point-on-current-front-sewn-panels",
            "uvStatus": "NOT_CREATED",
            "grantsAppearanceAcceptance": False,
        },
        "elbowQuilting": quilt_audits,
        "grantsFitOrAppearanceAcceptance": False,
        "evidenceBoundary": spec.get(
            "evidenceBoundary", "Unfitted visual hypothesis; requires direct image review."
        ),
    }


def preserved_seam_factors(mesh, spec):
    """Fade placement displacement continuously away from preserved seams."""
    from collections import defaultdict
    from mathutils import Vector
    import math
    preserve = set(spec.get("preserveSharedPieceIds", []))
    if not preserve:
        return {}
    owners = defaultdict(set)
    for face, piece in zip(mesh["faces"], mesh["facePieceIds"]):
        for i in face:
            owners[i].add(piece)
    if not preserve.issubset(set(mesh["facePieceIds"])):
        raise ValueError("Preserved seam pieces missing")
    shared = [i for i, pieces in owners.items() if pieces.intersection(preserve) and pieces.intersection(spec["pieceIds"])]
    fade = spec.get("preservedSeamFadeDistanceM")
    if fade is None:
        return {i: 0.0 for i in shared}
    if not shared or not math.isfinite(fade) or fade <= 0:
        raise ValueError("Invalid preserved seam fade configuration")
    points = [Vector(mesh["vertices"][i]) for i in shared]
    result = {}
    for i, pieces in owners.items():
        if not pieces.intersection(spec["pieceIds"]):
            continue
        point = Vector(mesh["vertices"][i])
        fraction = min(1.0, min((point-q).length for q in points)/fade)
        result[i] = fraction*fraction*(3-2*fraction)
    return result


def place_on_measured_contours(mesh, body_objects, pose, target_path, *, angular_source_vertices=None):
    """Place original garment vertices against measured neutral cross-sections.

    Retain canonical faces, piece ownership and sewing vertices. The body only
    supplies coordinate measurements; no body faces are copied to the garment.
    """
    import math
    from collections import defaultdict
    from bisect import bisect_right
    from mathutils import Vector

    spec = pose.get("bodyContourPlacement")
    if spec is None:
        return {"applied": False}
    envelope = spec["method"] == "measured-horizontal-body-envelope-minimum-clearance"
    if spec["method"] not in {"measured-horizontal-body-contour-radial-placement", "measured-horizontal-body-envelope-minimum-clearance"} or spec["outsideSampleRange"] != "hold-nearest-contour":
        raise ValueError("Unknown body contour placement method")
    zs = spec["sampleZM"]
    clearance = spec["radialClearanceM"]
    if len(zs) < 2 or any(not math.isfinite(z) for z in zs) or any(a >= b for a,b in zip(zs,zs[1:])) or not math.isfinite(clearance) or clearance < 0:
        raise ValueError("Invalid measured contour configuration")
    height_blend = spec.get("heightBlendM")
    if height_blend is not None:
        if (len(height_blend) != 2 or not all(math.isfinite(v) for v in height_blend)
                or height_blend[0] >= height_blend[1] or envelope):
            raise ValueError("Invalid contour height blend")
        if digest(target_path) != pose["targetSourceSha256"]:
            raise ValueError("Contour transition target hash mismatch")
        if angular_source_vertices is None or len(angular_source_vertices) != len(mesh["vertices"]):
            raise ValueError("Contour transition requires common native angular coordinates")
    bodies = [o for o in body_objects if o.type == "MESH" and o.name.startswith(spec["bodyMeshNamePrefix"])]
    if len(bodies) != 1:
        raise ValueError("Measured contour placement requires one explicit body mesh")
    body = bodies[0]
    if height_blend is not None and body.data.shape_keys and any(abs(k.value) > 1e-8 for k in body.data.shape_keys.key_blocks):
        raise ValueError("Contour transition requires explicit Neutral Shape Keys")
    if envelope:
        if digest(target_path) != pose["targetSourceSha256"]:
            raise ValueError("Body envelope target hash mismatch")
        if body.data.shape_keys and any(abs(k.value) > 1e-8 for k in body.data.shape_keys.key_blocks):
            raise ValueError("Body envelope requires explicit neutral Shape Keys")
    evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    data = evaluated.to_mesh()
    try:
        data.calc_loop_triangles()
        coords = [evaluated.matrix_world @ v.co for v in data.vertices]
        triangles = [tuple(t.vertices) for t in data.loop_triangles]
    finally:
        evaluated.to_mesh_clear()
    sections = []
    for z in zs:
        segments = []
        for tri in triangles:
            points = [coords[i] for i in tri]
            crossings = []
            for a,b in zip(points, points[1:]+points[:1]):
                if (a.z < z <= b.z) or (b.z < z <= a.z):
                    f = (z-a.z)/(b.z-a.z)
                    q = a + f*(b-a)
                    crossings.append((float(q.x),float(q.y)))
            if len(crossings)==2 and math.dist(*crossings)>1e-9:
                segments.append(crossings)
        graph = defaultdict(list)
        for i,(a,b) in enumerate(segments):
            for point in (a,b):graph[tuple(round(c,6) for c in point)].append(i)
        unseen = set(range(len(segments))); loops=[]
        while unseen:
            stack=[unseen.pop()]; ids=set(stack)
            while stack:
                i=stack.pop()
                for point in segments[i]:
                    for neighbor in graph[tuple(round(c,6) for c in point)]:
                        if neighbor in unseen:
                            unseen.remove(neighbor);ids.add(neighbor);stack.append(neighbor)
            selected=[segments[i] for i in ids]
            nodes={tuple(round(c,6) for c in point) for seg in selected for point in seg}
            closed=all(len(graph[n])==2 for n in nodes)
            xs=[point[0] for seg in selected for point in seg];ys=[point[1] for seg in selected for point in seg]
            if closed and (envelope or min(xs)<0<max(xs)):
                loops.append((sum(math.dist(a,b) for a,b in selected),selected,[(min(xs)+max(xs))/2,(min(ys)+max(ys))/2]))
        if not loops:
            raise ValueError(f"No closed central body contour at Z={z}")
        if envelope:
            # The skirt surrounds both thighs. Measure the convex envelope of
            # all closed section loops rather than selecting a single leg.
            points = sorted(set(tuple(p) for loop in loops for segment in loop[1] for p in segment))
            def cross(o, a, b):
                return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
            lower, upper = [], []
            for point in points:
                while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
                    lower.pop()
                lower.append(point)
            for point in reversed(points):
                while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
                    upper.pop()
                upper.append(point)
            hull = lower[:-1]+upper[:-1]
            if len(hull) < 3:
                raise ValueError("Body envelope section collapsed")
            selected = list(zip(hull, hull[1:]+hull[:1]))
            center = [(min(p[i] for p in hull)+max(p[i] for p in hull))/2 for i in range(2)]
            perimeter = sum(math.dist(a,b) for a,b in selected)
        else:
            perimeter,selected,center=max(loops,key=lambda x:x[0])
        maximum_perimeter = spec.get("maximumSectionCircumferenceM")
        if maximum_perimeter is not None:
            if not math.isfinite(maximum_perimeter) or maximum_perimeter <= 0 or perimeter > maximum_perimeter:
                raise ValueError(f"Body contour exceeds declared circumference bound at Z={z}: {perimeter}")
        sections.append({"zM":z,"centerM":center,"circumferenceM":perimeter,"segmentsM":selected,"closed":True})

    def radial_point(section, direction, layer_offset):
        c=section["centerM"];dx,dy=direction; distances=[]
        for a,b in section["segmentsM"]:
            ex,ey=b[0]-a[0],b[1]-a[1];qx,qy=a[0]-c[0],a[1]-c[1]
            den=dx*ey-dy*ex
            if abs(den)<1e-12:continue
            distance=(qx*ey-qy*ex)/den
            u=(qx*dy-qy*dx)/den
            if distance>0 and -1e-8<=u<=1+1e-8:distances.append(distance)
        if not distances:raise ValueError("Contour radial intersection missing")
        distance=max(distances)+clearance+layer_offset
        return Vector((c[0]+dx*distance,c[1]+dy*distance))

    ids=set(spec["pieceIds"])
    if not ids.issubset(set(mesh["facePieceIds"])):raise ValueError("Contour placement pieces missing")
    layer_offsets = spec.get("exclusivePieceLayerOffsetM", {})
    if not set(layer_offsets).issubset(ids) or any(not math.isfinite(v) or v < 0 for v in layer_offsets.values()):
        raise ValueError("Invalid exclusive panel layer offsets")
    vertex_owners = defaultdict(set)
    for face, piece in zip(mesh["faces"], mesh["facePieceIds"]):
        for vertex in face:
            vertex_owners[vertex].add(piece)
    vertex_ids={v for face,piece in zip(mesh["faces"],mesh["facePieceIds"]) if piece in ids for v in face}
    seam_factors = preserved_seam_factors(mesh, spec)
    before=json.dumps(mesh["vertices"],separators=(",",":"))
    extrapolated=0
    layered=0
    height_blend_skipped = 0
    for i in sorted(vertex_ids):
        if seam_factors.get(i, 1.0) == 0:
            continue
        x,y,z=mesh["vertices"][i];length=math.hypot(x,y)
        height_weight = 1.0
        if height_blend is not None:
            fraction = min(1.0, max(0.0, (z-height_blend[0])/(height_blend[1]-height_blend[0])))
            height_weight = fraction*fraction*(3-2*fraction)
            if height_weight == 0:
                height_blend_skipped += 1
                continue
        if length<1e-9:raise ValueError("Torso angular coordinate collapsed")
        direction=(x/length,y/length)
        origin = spec.get("angularOriginBlenderXYM")
        if origin is not None:
            if len(origin) != 2 or any(not math.isfinite(v) for v in origin):
                raise ValueError("Invalid contour angular origin")
            angular_x, angular_y = (angular_source_vertices[i][:2] if angular_source_vertices is not None else (x,y))
            angular_length = math.hypot(angular_x-origin[0], angular_y-origin[1])
            if angular_length < 1e-9:
                raise ValueError("Contour angular origin collapsed")
            direction = ((angular_x-origin[0])/angular_length, (angular_y-origin[1])/angular_length)
        j=max(0,min(len(zs)-2,bisect_right(zs,z)-1))
        f=min(1,max(0,(z-zs[j])/(zs[j+1]-zs[j])))
        if envelope:
            center = [sections[j]["centerM"][k]*(1-f)+sections[j+1]["centerM"][k]*f for k in range(2)]
            length = math.hypot(x-center[0],y-center[1])
            if length < 1e-9:
                raise ValueError("Skirt envelope angular coordinate collapsed")
            direction = ((x-center[0])/length,(y-center[1])/length)
        if z<zs[0] or z>zs[-1]:extrapolated+=1
        # Keep shared sewing vertices on their common surface. Only the
        # exclusive vertices of an explicitly declared outer panel move out.
        owners = vertex_owners[i]
        offset = layer_offsets.get(next(iter(owners)), 0) if len(owners) == 1 else 0
        if offset:
            layered += 1
        q=radial_point(sections[j],direction,offset).lerp(radial_point(sections[j+1],direction,offset),f)
        if envelope and length >= math.hypot(q.x-center[0],q.y-center[1]):
            continue
        weight = seam_factors.get(i, 1.0)*height_weight
        mesh["vertices"][i]=[x+(float(q.x)-x)*weight,y+(float(q.y)-y)*weight,z]
    # Reject newly collapsed geometry instead of deleting or repairing faces.
    for face in mesh["faces"]:
        a,b,c=[Vector(mesh["vertices"][v]) for v in face]
        if (b-a).cross(c-a).length/2<=1e-12:raise ValueError("Body contour placement collapsed a triangle")
    return {"applied":True,"targetSourceSha256":digest(target_path),"bodyObject":body.name,"configuration":spec,"sections":sections,"placedVertexCount":len(vertex_ids),"heightBlendSkippedVertexCount":height_blend_skipped,"angularSourceVerticesSha256":hashlib.sha256(json.dumps(angular_source_vertices,separators=(",",":")).encode()).hexdigest() if angular_source_vertices is not None else None,"layerOffsetVertexCount":layered,"sharedSeamVerticesLayerOffsetM":0,"heightExtrapolatedVertexCount":extrapolated,"beforeVerticesSha256":hashlib.sha256(before.encode()).hexdigest(),"afterVerticesSha256":hashlib.sha256(json.dumps(mesh["vertices"],separators=(",",":")).encode()).hexdigest(),"bodyFacesCopied":False,"grantsFitAcceptance":False}


def place_on_measured_upper_surface(mesh, body_objects, pose, target_path):
    """Fit original upper garment vertices to the evaluated target surface.

    Shared sewn vertices move once. No body topology is copied and no garment
    faces are removed when a projection fails or collapses a triangle.
    """
    import math
    from collections import defaultdict
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    spec = pose.get("upperSurfacePlacement")
    if spec is None:
        return {"applied": False}
    if spec["method"] != "evaluated-body-nearest-surface-blended-placement":
        raise ValueError("Unknown upper surface placement method")
    if digest(target_path) != pose["targetSourceSha256"]:
        raise ValueError("Upper surface target source is stale")
    z0, z1, zmax = spec["fadeStartZM"], spec["fullWeightStartZM"], spec["maximumZM"]
    x1, x0 = spec["fullWeightAbsXM"], spec["fadeEndAbsXM"]
    clearance, limit = spec["normalClearanceM"], spec["maximumProjectionDistanceM"]
    maximum_weight = spec["maximumBlendWeight"]
    if (not all(math.isfinite(v) for v in (z0, z1, zmax, x1, x0, clearance, limit))
            or not z0 < z1 < zmax or not 0 < x1 < x0 or clearance <= 0 or limit <= 0
            or not math.isfinite(maximum_weight) or not 0 < maximum_weight < 1):
        raise ValueError("Invalid upper surface placement bounds")
    bodies = [o for o in body_objects if o.type == "MESH" and o.name.startswith(spec["bodyMeshNamePrefix"])]
    if len(bodies) != 1:
        raise ValueError("Upper surface placement requires one explicit target body")
    body = bodies[0]
    shape_values = {k.name: float(k.value) for k in body.data.shape_keys.key_blocks} if body.data.shape_keys else {}
    if any(abs(v) > 1e-8 for v in shape_values.values()):
        raise ValueError("Upper surface placement requires zero-valued target Shape Keys")
    evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    data = evaluated.to_mesh()
    try:
        data.calc_loop_triangles()
        coordinates = [evaluated.matrix_world @ v.co for v in data.vertices]
        triangles = [tuple(t.vertices) for t in data.loop_triangles]
    finally:
        evaluated.to_mesh_clear()
    tree = BVHTree.FromPolygons(coordinates, triangles, all_triangles=True)
    owners = defaultdict(set)
    for face, piece in zip(mesh["faces"], mesh["facePieceIds"]):
        for i in face:
            owners[i].add(piece)
    selected = set(spec["pieceIds"])
    if not selected.issubset(set(mesh["facePieceIds"])):
        raise ValueError("Upper surface placement pieces are missing")
    preserve = set(spec.get("preserveSharedPieceIds", []))
    if not preserve.issubset(set(mesh["facePieceIds"])):
        raise ValueError("Preserved seam pieces missing")
    seam_factors = preserved_seam_factors(mesh, spec)
    records = []
    for i, pieces in sorted(owners.items()):
        if pieces.intersection(preserve):
            continue
        point = Vector(mesh["vertices"][i])
        if not pieces.intersection(selected) or not z0 < point.z <= zmax or abs(point.x) >= x0:
            continue
        # Bounded relaxation retains a declared fraction of the original
        # garment coordinates; full projection can merge vertices at body
        # triangle edges. Degenerate triangles are still rejected below.
        weight = maximum_weight * min(1, (point.z-z0)/(z1-z0)) * min(1, (x0-abs(point.x))/(x0-x1))
        weight *= seam_factors.get(i, 1.0)
        location, normal, _, distance = tree.find_nearest(point)
        if location is None or distance > limit or normal.length < .99:
            raise ValueError(f"Upper surface projection unavailable/out of bounds at vertex {i}")
        offset = clearance + (spec["outerLayerOffsetM"] if pieces == {spec["outerPieceId"]} else 0)
        result = point.lerp(location + normal*offset, weight)
        mesh["vertices"][i] = list(result)
        records.append({"vertexIndex": i, "pieceIds": sorted(pieces), "beforeM": list(point),
                        "nearestBodyPointM": list(location), "normal": list(normal),
                        "distanceM": distance, "blendWeight": weight, "afterM": list(result)})
    if not records:
        raise ValueError("Upper surface placement selected no vertices")
    for face in mesh["faces"]:
        a, b, c = [Vector(mesh["vertices"][v]) for v in face]
        if (b-a).cross(c-a).length/2 <= 1e-12:
            raise ValueError("Upper surface projection collapsed a triangle")
    return {"applied": True, "configuration": spec, "targetSourceSha256": digest(target_path),
            "targetShapeKeyValues": shape_values, "bodyObject": body.name,
            "placedVertexCount": len(records), "records": records,
            "bodyFacesCopied": False, "garmentFacesRemoved": 0, "grantsFitAcceptance": False}


def split_declared_skirt_creases(mesh, pose):
    """Cut canonical skirt/band faces at fold extrema before body placement."""
    import bmesh
    import math
    from mathutils import Vector

    spec = pose.get("skirtPleatPlacement")
    if spec is None or spec["method"] != "crease-aligned-triangular-radial-fold":
        return {"applied": False}
    count = spec["foldCount"]
    origin = spec["axisOriginBlenderXYM"]
    phase = spec["phaseRadians"]
    selected = set(spec["pieceIds"]) | set(spec["seamContinuationPieceIds"])
    if (not isinstance(count, int) or isinstance(count, bool) or not 2 <= count <= 64
            or len(origin) != 2 or not all(math.isfinite(v) for v in [*origin, phase])
            or not selected.issubset(set(mesh["facePieceIds"]))):
        raise ValueError("Invalid explicit crease topology declaration")
    pieces = sorted(set(mesh["facePieceIds"]))
    bm = bmesh.new()
    owner = bm.faces.layers.int.new("canonical_owner")
    original_id = bm.verts.layers.int.new("original_vertex_id")
    initial_count = len(mesh["vertices"])
    initial_face_count = len(mesh["faces"])
    vertices = []
    for index, point in enumerate(mesh["vertices"]):
        vertex = bm.verts.new(point)
        vertex[original_id] = index + 1
        vertices.append(vertex)
    for indices, piece in zip(mesh["faces"], mesh["facePieceIds"]):
        face = bm.faces.new([vertices[i] for i in indices])
        face[owner] = pieces.index(piece) + 1
    cuts = []
    try:
        for i in range(count):
            angle = phase + i * math.pi / count
            faces = [f for f in bm.faces if pieces[f[owner]-1] in selected]
            edges = {e for f in faces for e in f.edges}
            verts = {v for f in faces for v in f.verts}
            old_vertices = set(bm.verts)
            result = bmesh.ops.bisect_plane(
                bm, geom=[*verts, *edges, *faces], dist=1e-6,
                plane_co=Vector((origin[0], origin[1], 0)),
                plane_no=Vector((math.cos(angle), math.sin(angle), 0)),
                clear_inner=False, clear_outer=False)
            added = [v for v in bm.verts if v not in old_vertices]
            for vertex in added:
                vertex[original_id] = 0
            cuts.append({"planeAngleRadians": angle, "newVertexCount": len(added),
                         "cutEdgeCount": sum(isinstance(g, bmesh.types.BMEdge) for g in result["geom_cut"])})
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        original = {v[original_id]-1: v for v in bm.verts if v[original_id] > 0}
        if set(original) != set(range(initial_count)):
            raise ValueError("Crease cuts lost original sewn vertex identity")
        ordered = [original[i] for i in range(initial_count)] + [v for v in bm.verts if v[original_id] == 0]
        remap = {v: i for i, v in enumerate(ordered)}
        result_vertices = [list(v.co) for v in ordered]
        result_faces, result_owners = [], []
        for face in bm.faces:
            if not 1 <= face[owner] <= len(pieces):
                raise ValueError("Crease cut lost canonical face ownership")
            if len(face.verts) != 3 or face.calc_area() <= 1e-12:
                raise ValueError("Crease cut produced a degenerate triangle")
            result_faces.append([remap[v] for v in face.verts])
            result_owners.append(pieces[face[owner]-1])
        edges_by_piece = {}
        for piece in spec["pieceIds"]:
            group_faces = [f for f in bm.faces if pieces[f[owner]-1] == piece]
            edges_by_piece[piece] = {e for f in group_faces for e in f.edges}
        band_edges = {e for f in bm.faces if pieces[f[owner]-1] in set(spec["seamContinuationPieceIds"]) for e in f.edges}
        skirt_edges = set().union(*edges_by_piece.values())
        seam_edges = skirt_edges & band_edges
        if not seam_edges or any(len(e.link_faces) != 2 for e in seam_edges):
            raise ValueError("Crease cuts broke sewn skirt/waistband adjacency")
        non_manifold = sum(len(e.link_faces) > 2 for e in bm.edges)
        if non_manifold:
            raise ValueError("Crease cuts created non-manifold edges")
        mesh.update(vertices=result_vertices, faces=result_faces, facePieceIds=result_owners)
        return {"applied": True, "method": spec["method"], "cuts": cuts,
                "beforeVertexCount": initial_count, "afterVertexCount": len(ordered),
                "beforeTriangleCount": initial_face_count, "afterTriangleCount": len(result_faces),
                "sharedSkirtWaistbandEdgeCount": len(seam_edges),
                "degenerateTriangleCount": 0, "nonManifoldEdgeCount": non_manifold,
                "originalVertexIdentityPreserved": True,
                "grantsFitAcceptance": False, "grantsVisualAcceptance": False,
                "evidenceBoundary": "Native radial cuts align fold extrema to actual mesh edges; canonical ownership and sewn waist adjacency survive. Fold count/depth remain design hypotheses; no exact fabric isometry or fit acceptance."}
    finally:
        bm.free()


def place_declared_skirt_folds(mesh, pose, native_vertices):
    """Seed explicit garment folds while retaining the sewn face topology."""
    import math
    from mathutils import Vector

    spec = pose.get("skirtPleatPlacement")
    if spec is None:
        return {"applied": False}
    if spec["method"] not in {"outward-triangular-radial-fold-seed", "crease-aligned-triangular-radial-fold"}:
        raise ValueError("Unknown skirt fold placement")
    origin = spec["axisOriginBlenderXYM"]
    waist, hem = spec["waistZM"], spec["hemZM"]
    count, depth, phase = spec["foldCount"], spec["hemFoldDepthM"], spec["phaseRadians"]
    if (len(origin) != 2 or not all(math.isfinite(v) for v in [*origin, waist, hem, depth, phase])
            or not hem < waist or not isinstance(count, int) or isinstance(count, bool)
            or count < 2 or depth <= 0 or len(native_vertices) != len(mesh["vertices"])):
        raise ValueError("Invalid skirt fold specification")
    ids = set(spec["pieceIds"])
    if not ids or not ids.issubset(set(mesh["facePieceIds"])):
        raise ValueError("Skirt fold pieces missing")
    vertices = {i for face, owner in zip(mesh["faces"], mesh["facePieceIds"]) if owner in ids for i in face}
    before = json.dumps(mesh["vertices"], separators=(",", ":"))
    moved = 0
    displacement_max = 0.0
    for i in sorted(vertices):
        x, y, z = mesh["vertices"][i]
        if z > waist+1e-6 or z < hem-1e-6:
            raise ValueError("Skirt fold vertex outside declared height range")
        blend = min(1.0, max(0.0, (waist-z)/(waist-hem)))
        if blend == 0:
            continue
        native = native_vertices[i]
        angle = math.atan2(native[0]-origin[0], -(native[1]-origin[1]))
        position = ((angle-phase)*count/(2*math.pi)) % 1
        displacement = depth*blend*(1-abs(2*position-1))
        radius = math.hypot(x-origin[0], y-origin[1])
        if radius <= 1e-9:
            raise ValueError("Skirt fold radial coordinate collapsed")
        mesh["vertices"][i] = [x+(x-origin[0])*displacement/radius,
                                y+(y-origin[1])*displacement/radius, z]
        moved += 1
        displacement_max = max(displacement_max, displacement)
    minimum_area = math.inf
    for face in mesh["faces"]:
        a, b, c = [Vector(mesh["vertices"][i]) for i in face]
        area = (b-a).cross(c-a).length/2
        if area <= 1e-12:
            raise ValueError("Skirt fold placement collapsed a triangle")
        minimum_area = min(minimum_area, area)
    return {"applied": True, "configuration": spec, "selectedVertexCount": len(vertices),
            "movedVertexCount": moved, "maximumRadialDisplacementM": displacement_max,
            "minimumTriangleAreaM2": minimum_area,
            "beforeVerticesSha256": hashlib.sha256(before.encode()).hexdigest(),
            "afterVerticesSha256": hashlib.sha256(json.dumps(mesh["vertices"], separators=(",", ":")).encode()).hexdigest(),
            "canonicalFacesChanged": False, "sewnWaistDisplacementM": 0,
            "grantsFitAcceptance": False, "grantsVisualAcceptance": False}


def main():
    raw = sys.argv[sys.argv.index("--") + 1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    job = read(Path(parser.parse_args(raw).job))
    mesh_path = resolve(os.environ["IMAGE2OUTFIT_SEWN_MESH_PATH"])
    mesh = read(mesh_path)
    pipeline = job["garmentPipeline"]
    expected = {
        "patternSha256": digest(resolve(pipeline["patternContractPath"])),
        "stitchGraphSha256": digest(resolve(pipeline["stitchGraphPath"])),
    }
    for name, value in expected.items():
        if mesh["canonicalInputs"][name] != value:
            raise ValueError(f"Sewn mesh input is stale: {name}")
    if mesh["topology"]["degenerateFaceCount"] or mesh["topology"]["nonManifoldEdgeCount"]:
        raise ValueError("Rejected sewn topology cannot be imported as a product prototype")
    if mesh["productId"] != job["id"] or mesh.get("coordinateSystem") != "blender-z-up":
        raise ValueError("Sewn mesh product or coordinate frame mismatch")
    if mesh["units"] != "meter" or not mesh["vertices"] or not mesh["faces"]:
        raise ValueError("Sewn mesh must contain nonempty geometry in meters")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.fbx(filepath=str(resolve(job["targetSourcePath"])))
    body_objects = list(bpy.context.scene.objects)
    for obj in body_objects:
        obj["prototypeRole"] = "target-avatar-reference-only"
    pose = read(resolve(pipeline["assemblyPosePath"]))
    crease_evidence = split_declared_skirt_creases(mesh, pose)
    # Preserve bounded, stable vertex trajectories in the existing build report.
    from collections import defaultdict
    trace_owners = defaultdict(set)
    for face, owner in zip(mesh["faces"], mesh["facePieceIds"]):
        for vertex in face:
            trace_owners[vertex].add(owner)
    trace_ids = [i for i, point in enumerate(mesh["vertices"]) if point[2] >= .98 and abs(point[0]) <= .12 and any(p.startswith("jacket-") or p == "stand-collar" for p in trace_owners[i])]
    neck_trace = {i: {"vertexIndex": i, "pieceIds": sorted(trace_owners[i]), "coordinatesByStageM": {"native-sewn": list(mesh["vertices"][i])}} for i in trace_ids}
    def trace_stage(name):
        for i in trace_ids:
            neck_trace[i]["coordinatesByStageM"][name] = list(mesh["vertices"][i])
    collar_evidence = {"applied": False}
    if "collarContourPlacement" in pose:
        collar_pose = dict(pose, bodyContourPlacement=pose["collarContourPlacement"])
        collar_evidence = place_on_measured_contours(mesh, body_objects, collar_pose, resolve(job["targetSourcePath"]))
    trace_stage("collar-contour")
    contour_evidence = place_on_measured_contours(mesh, body_objects, pose, resolve(job["targetSourcePath"]))
    trace_stage("torso-contour")
    upper_surface_evidence = place_on_measured_upper_surface(mesh, body_objects, pose, resolve(job["targetSourcePath"]))
    trace_stage("upper-surface")
    skirt_envelope_evidence = {"applied": False}
    native_angular_vertices = [list(point) for point in mesh["vertices"]]
    if "skirtEnvelopePlacement" in pose:
        skirt_pose = dict(pose, bodyContourPlacement=pose["skirtEnvelopePlacement"])
        skirt_envelope_evidence = place_on_measured_contours(mesh, body_objects, skirt_pose, resolve(job["targetSourcePath"]))
    waistband_evidence = {"applied": False}
    if "waistbandContourPlacement" in pose:
        waistband_pose = dict(pose, bodyContourPlacement=pose["waistbandContourPlacement"])
        waistband_evidence = place_on_measured_contours(mesh, body_objects, waistband_pose, resolve(job["targetSourcePath"]), angular_source_vertices=native_angular_vertices)
    fold_evidence = place_declared_skirt_folds(mesh, pose, native_angular_vertices)
    data = bpy.data.meshes.new(job["id"] + "-sewn-surface")
    data.from_pydata(mesh["vertices"], [], mesh["faces"])
    data.update()
    owners = mesh["facePieceIds"]
    pieces = sorted(set(owners))
    if len(owners) != len(data.polygons):
        raise ValueError("Sewn face ownership is incomplete")
    ownership = data.attributes.new("canonical_piece_index", "INT", "FACE")
    for face, owner in zip(ownership.data, owners):
        face.value = pieces.index(owner)
    garment = bpy.data.objects.new(job["id"], data)
    bpy.context.collection.objects.link(garment)
    garment["prototypeRole"] = "unfitted-unweighted-sewn-pattern"
    garment["sewnMeshSha256"] = digest(mesh_path)
    garment["sourcePatternSha256"] = expected["patternSha256"]
    garment["canonicalPieceIds"] = json.dumps(pieces)
    bpy.ops.object.select_all(action="DESELECT")
    garment.select_set(True)
    bpy.context.view_layer.objects.active = garment
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    recipe = read(resolve(pipeline["materialRecipePath"]))
    spec = recipe["prototypeMaterial"]
    material = bpy.data.materials.new(spec["name"])
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*spec["baseColorLinearRgb"], 1)
    shader.inputs["Roughness"].default_value = spec["roughness"]
    material["evidenceBoundary"] = recipe["evidenceBoundary"]
    garment.data.materials.append(material)
    prototype_edge_trim = add_prototype_edge_trim(mesh, job, pieces, recipe)
    prototype_surface_motifs = add_prototype_surface_motifs(mesh, job, recipe)
    source = resolve(job["blendPath"])
    source.parent.mkdir(parents=True, exist_ok=True)
    # The workflow transaction owns rollback; avoid undeclared .blend1 writes.
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(source))
    report = {
        "schemaVersion": 1, "productId": job["id"], "passed": False,
        "measuredWaistbandPlacement": waistband_evidence,
        "declaredSkirtFoldPlacement": fold_evidence,
        "declaredSkirtCreaseTopology": crease_evidence,
        "buildDisposition": "EDITABLE_SEWN_PROTOTYPE_ONLY",
        "prototypeEdgeTrim": prototype_edge_trim,
        "prototypeSurfaceMotifs": prototype_surface_motifs,
        "sourceBlendSha256": digest(source), "sewnMeshSha256": digest(mesh_path),
        "canonicalInputs": expected,
        "measuredContourPlacement": contour_evidence,
        "measuredUpperSurfacePlacement": upper_surface_evidence,
        "measuredSkirtEnvelopePlacement": skirt_envelope_evidence,
        "measuredCollarPlacement": collar_evidence,
        "necklinePlacementTrace": {"coordinateSystem": "blender-z-up", "selection": {"nativeMinimumZM": .98, "nativeMaximumAbsXM": .12}, "records": list(neck_trace.values()), "evidenceBoundary": "Original sewn vertex IDs/face ownership and per-stage coordinates; diagnostic only, not fit or appearance acceptance."},
        "metrics": {"vertices": len(data.vertices), "triangles": len(data.polygons),
                    "unweightedVertices": len(data.vertices),
                    "degenerateTriangles": mesh["topology"]["degenerateFaceCount"]},
        "geometryGate": {"checks": {"sewnTopologyValid": True,
            "avatarFitVerified": False, "deformWeightsVerified": False}},
        "pending": ["panel placement and physical cloth settling", "avatar fit",
            "deform weights and Shape Keys", "FBX export", "rendered appearance",
            "Unity and VRChat runtime"],
    }
    report_path = resolve(job["productRoot"] + "/Evidence/Build/product-build-report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
