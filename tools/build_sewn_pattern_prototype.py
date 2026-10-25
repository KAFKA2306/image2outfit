"""Import a hash-bound GarmentCode sewn surface into an editable Blender prototype.

This stage deliberately reports unweighted/untested geometry as rejected. It does
not substitute a body shell for the submitted pattern or claim product fit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pack_panel_uv_bounds(panel_bounds, padding):
    """Pack pattern-space panel bounds without rotating or reshaping panels."""
    extents = {
        key: (bounds[2] - bounds[0], bounds[3] - bounds[1])
        for key, bounds in panel_bounds.items()
    }
    if any(width <= 0 or height <= 0 for width, height in extents.values()):
        raise ValueError("Pattern panel has zero UV extent")

    def attempt(scale):
        rectangles = sorted(
            (
                (width * scale + padding * 2),
                (height * scale + padding * 2),
                key,
            )
            for key, (width, height) in extents.items()
        )
        rectangles.sort(key=lambda item: (-item[0] * item[1], -item[1], -item[0], item[2]))
        free = [(0.0, 0.0, 1.0, 1.0)]
        placed = {}
        epsilon = 1e-12

        for width, height, key in rectangles:
            candidates = []
            for free_index, (free_x, free_y, free_w, free_h) in enumerate(free):
                if width <= free_w + epsilon and height <= free_h + epsilon:
                    remaining_w, remaining_h = free_w - width, free_h - height
                    candidates.append((
                        min(remaining_w, remaining_h),
                        max(remaining_w, remaining_h),
                        free_y,
                        free_x,
                        free_index,
                    ))
            if not candidates:
                return None
            _, _, y, x, _ = min(candidates)
            placed[key] = (x + padding, y + padding)
            right, top = x + width, y + height
            split = []
            for free_x, free_y, free_w, free_h in free:
                free_right, free_top = free_x + free_w, free_y + free_h
                if right <= free_x + epsilon or x >= free_right - epsilon \
                        or top <= free_y + epsilon or y >= free_top - epsilon:
                    split.append((free_x, free_y, free_w, free_h))
                    continue
                if x > free_x + epsilon:
                    split.append((free_x, free_y, x - free_x, free_h))
                if right < free_right - epsilon:
                    split.append((right, free_y, free_right - right, free_h))
                if y > free_y + epsilon:
                    split.append((free_x, free_y, free_w, y - free_y))
                if top < free_top - epsilon:
                    split.append((free_x, top, free_w, free_top - top))

            pruned = []
            for index, rect in enumerate(split):
                rx, ry, rw, rh = rect
                contained = False
                for other_index, other in enumerate(split):
                    if index == other_index:
                        continue
                    ox, oy, ow, oh = other
                    if rx >= ox - epsilon and ry >= oy - epsilon \
                            and rx + rw <= ox + ow + epsilon \
                            and ry + rh <= oy + oh + epsilon:
                        if (rw * rh < ow * oh - epsilon) or other_index < index:
                            contained = True
                            break
                if not contained and rw > epsilon and rh > epsilon:
                    pruned.append(rect)
            free = pruned
        return placed

    maximum_extent = max(max(extents.values(), key=max))
    low = 0.0
    high = (1.0 - padding * 2) / maximum_extent
    best = attempt(high)
    if best is not None:
        return high, best
    for _ in range(40):
        middle = (low + high) * 0.5
        packed = attempt(middle)
        if packed is None:
            high = middle
        else:
            low, best = middle, packed
    if best is None:
        raise ValueError("Authored UV panel bounds cannot be packed in the unit tile")
    return low, best


def assign_authored_panel_uvs(mesh_data, sewn_mesh):
    """Map sewn faces from explicit pattern or accessory source coordinates."""
    face_coordinates = sewn_mesh.get("facePatternCoordinates")
    panel_keys = sewn_mesh.get("facePatternPanelKeys")
    source_kinds = sewn_mesh.get("faceUvSourceKinds")
    faces = sewn_mesh.get("faces")
    if (sewn_mesh.get("schemaVersion") != 2
            or not isinstance(face_coordinates, list)
            or not isinstance(panel_keys, list)
            or not isinstance(source_kinds, list)
            or not isinstance(faces, list) or len(face_coordinates) != len(faces)
            or len(panel_keys) != len(faces) or len(source_kinds) != len(faces)
            or len(mesh_data.polygons) != len(faces)):
        raise ValueError("Sewn mesh lacks complete face-local pattern UV provenance")
    supported_sources = {
        "garmentcode-pattern-panel",
        "declared-parametric-accessory",
    }
    if any(kind not in supported_sources for kind in source_kinds):
        raise ValueError("Sewn mesh UV provenance includes an unsupported source kind")

    panels = sorted(set(panel_keys))
    if not panels or any(not isinstance(key, str) or not key for key in panels):
        raise ValueError("Sewn mesh UV provenance has invalid panel keys")
    padding = 0.006
    panel_bounds = {}
    for panel_key in panels:
        points = [
            point
            for face_points, face_panel in zip(face_coordinates, panel_keys)
            if face_panel == panel_key
            for point in face_points
        ]
        if not points or any(len(point) != 2 for point in points):
            raise ValueError(f"Pattern panel {panel_key} has invalid 2D UV coordinates")
        panel_bounds[panel_key] = (
            min(float(point[0]) for point in points),
            min(float(point[1]) for point in points),
            max(float(point[0]) for point in points),
            max(float(point[1]) for point in points),
        )

    scale, placements = pack_panel_uv_bounds(panel_bounds, padding)
    uv_layer = mesh_data.uv_layers.new(name="AuthoredPatternPanels")
    for polygon, face_points, panel_key in zip(mesh_data.polygons, face_coordinates, panel_keys):
        min_x, min_y, max_x, max_y = panel_bounds[panel_key]
        offset_x, offset_y = placements[panel_key]
        if len(face_points) != len(polygon.loop_indices):
            raise ValueError("Pattern UV loop count does not match sewn polygon")
        for loop_index, point in zip(polygon.loop_indices, face_points):
            uv_layer.data[loop_index].uv = (
                offset_x + (float(point[0]) - min_x) * scale,
                offset_y + (float(point[1]) - min_y) * scale,
            )
    return {
        "status": "AUTHORED_FROM_DECLARED_2D_SOURCE_COORDINATES",
        "method": "face-local-source-coordinates-with-uniform-scale-unrotated-maxrects-packing",
        "panelCount": len(panels),
        "mappedFaceCount": len(faces),
        "uniformPatternToUvScale": scale,
        "panelUvBounds": {
            key: {
                "sourceBounds": list(panel_bounds[key]),
                "uvOrigin": list(placements[key]),
                "rotationDegrees": 0,
            }
            for key in panels
        },
        "sourceKindFaceCounts": {
            kind: source_kinds.count(kind) for kind in sorted(supported_sources)
        },
        "grantsQualityAcceptance": False,
    }


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
        face_owners = []
        for face, owner in zip(mesh["faces"], owners):
            if owner not in selected or len(face) != 3:
                continue
            center_y = sum(points[index].y for index in face) / 3
            if center_y >= -0.004:
                continue
            first, second, third = (points[index] for index in face)
            if (second - first).cross(third - first).normalized().y >= -0.05:
                continue
            faces.append(face)
            face_owners.append(owner)
        if not faces:
            raise ValueError(f"No front-facing garment triangles for {sorted(selected)}")
        return BVHTree.FromPolygons(points, faces, all_triangles=True), face_owners

    def surface_point(locator_value, x, z, query_y, offset, offset_mode="surface-normal"):
        tree, face_owners = locator_value
        origin = Vector((x, query_y, z))
        result = tree.ray_cast(origin, Vector((0.0, 1.0, 0.0)), 0.5)
        if result is None or result[0] is None:
            raise ValueError(f"Prototype motif ray missed front panel at x={x:.4f}, z={z:.4f}")
        location, normal, face_index, _distance = result
        if location.y >= -0.002 or normal.y > -0.05:
            raise ValueError("Prototype motif ray did not hit an outward-facing front surface")
        if offset_mode == "front-depth":
            # Front orthographic renders look along +Y. A local face-normal
            # offset can move the strip sideways/upward on sharply changing
            # triangles, allowing the garment to occlude patches of the motif.
            # Keep its sampled X/Z and move only toward the camera instead.
            displacement = Vector((0.0, -offset, 0.0))
        elif offset_mode == "surface-normal":
            displacement = normal.normalized() * offset
        else:
            raise ValueError(f"Unsupported prototype motif surface offset mode: {offset_mode}")
        return location + displacement, face_owners[face_index]

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
    half_width_start = float(plastron.get("halfWidthStartM", half_width))
    half_width_end = float(plastron.get("halfWidthEndM", half_width))
    across_sample_count = int(plastron.get("acrossSampleCount", 8))
    surface_offset = float(plastron.get("surfaceOffsetM", 0.0015))
    surface_offset_mode = str(plastron.get("surfaceOffsetMode", "surface-normal"))
    if (not isinstance(start, list) or len(start) != 2
            or not isinstance(end, list) or len(end) != 2
            or sample_count < 4
            or not 2 <= across_sample_count <= 32
            or not 0.001 <= half_width_start <= 0.08
            or not 0.001 <= half_width_end <= 0.08
            or not 0.0002 <= surface_offset <= 0.005):
        raise ValueError("Invalid prototype plastron path, width, or surface offset")
    front_piece_ids = plastron.get("hostPieceIds", [])
    front_tree = locator(front_piece_ids)
    front_piece_trees = {piece_id: locator([piece_id]) for piece_id in front_piece_ids}
    dx, dz = float(end[0]) - float(start[0]), float(end[1]) - float(start[1])
    length = (dx * dx + dz * dz) ** 0.5
    if length <= 0.02:
        raise ValueError("Prototype plastron path is too short")
    normal_x, normal_z = -dz / length, dx / length
    band_vertices = []
    band_sample_owners = []
    corner_owner_fallback_count = 0
    cross_owner_section_count = 0
    for index in range(sample_count + 1):
        fraction = index / sample_count
        local_half_width = half_width_start + (half_width_end - half_width_start) * fraction
        center_x = float(start[0]) + dx * fraction
        center_z = float(start[1]) + dz * fraction
        # Prefer the centerline panel for each side of this section so the
        # motif follows a sewn panel where it covers the full width. At a
        # panel boundary, however, a corner can legitimately fall outside
        # that panel's triangles. In that case resolve against the combined
        # declared front surface and record the ownership transition instead
        # of aborting the entire build or silently crossing an undeclared part.
        _center, sample_owner = surface_point(
            front_tree, center_x, center_z,
            float(plastron.get("frontQueryYM", -0.16)), surface_offset,
            surface_offset_mode,
        )
        sample_tree = front_piece_trees[sample_owner]
        section_owners = set()
        for across_index in range(across_sample_count + 1):
            across_fraction = (2.0 * across_index / across_sample_count) - 1.0
            x = center_x + normal_x * local_half_width * across_fraction
            z = center_z + normal_z * local_half_width * across_fraction
            try:
                point, owner = surface_point(
                    sample_tree, x, z,
                    float(plastron.get("frontQueryYM", -0.16)), surface_offset,
                    surface_offset_mode,
                )
            except ValueError as error:
                if not str(error).startswith("Prototype motif ray"):
                    raise
                point, owner = surface_point(
                    front_tree, x, z,
                    float(plastron.get("frontQueryYM", -0.16)), surface_offset,
                    surface_offset_mode,
                )
                corner_owner_fallback_count += 1
            band_vertices.append(list(point))
            band_sample_owners.append(owner)
            section_owners.add(owner)
        if len(section_owners) > 1:
            cross_owner_section_count += 1
    band_faces = []
    band_face_owners = []
    preferred_owner = "jacket-overlap-front"
    cross_owner_transition_quads = []
    triangulation_choices = {"diagonal-ac": 0, "diagonal-bd": 0}
    weakest_triangle_front_normal = 1.0
    row_width = across_sample_count + 1
    for index in range(sample_count):
        for across_index in range(across_sample_count):
            first = index * row_width + across_index
            next_row = first + row_width
            # Raycasting every transverse sample makes each narrow patch cell
            # follow the sewn cloth curvature instead of bridging across a
            # concave chest section, which let the host fabric occlude the old
            # two-edge ribbon and show through as white cutouts.
            quad = (first, next_row, next_row + 1, first + 1)
            quad_owners = {band_sample_owners[item] for item in quad}
            if len(quad_owners) > 1:
                cross_owner_transition_quads.append(index * across_sample_count + across_index)
            owner = preferred_owner if preferred_owner in quad_owners else next(iter(quad_owners))

            # Choose the outward-facing diagonal for each conforming cell.
            candidates = {
                "diagonal-ac": ((quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])),
                "diagonal-bd": ((quad[0], quad[1], quad[3]), (quad[1], quad[2], quad[3])),
            }

            def triangle_frontness(face):
                a, b, c = (Vector(band_vertices[vertex]) for vertex in face)
                cross = (b - a).cross(c - a)
                if cross.length_squared <= 1e-14:
                    return None
                return -cross.normalized().y

            scored = []
            for diagonal, triangles in candidates.items():
                frontness = [triangle_frontness(face) for face in triangles]
                if any(value is None or value <= 0.05 for value in frontness):
                    continue
                scored.append((min(frontness), sum(frontness), diagonal, triangles, frontness))
            if not scored:
                raise ValueError(
                    f"Prototype plastron cell {index}:{across_index} has no outward, "
                    f"non-degenerate triangulation; panel owners={sorted(quad_owners)}"
                )
            _minimum, _total, diagonal, triangles, frontness = max(scored)
            triangulation_choices[diagonal] += 1
            weakest_triangle_front_normal = min(weakest_triangle_front_normal, *frontness)
            band_faces.extend(triangles)
            band_face_owners.extend([owner, owner])
    band_data = bpy.data.meshes.new(f"{job['id']}-prototype-plastron-surface")
    band_data.from_pydata(band_vertices, [], band_faces)
    band_data.update()
    inward_faces = [polygon.index for polygon in band_data.polygons if polygon.normal.y >= -0.05]
    if inward_faces:
        raise ValueError(
            f"Prototype plastron has {len(inward_faces)} faces not oriented toward -Y"
        )
    band = bpy.data.objects.new(f"{job['id']}-prototype-plastron-hypothesis", band_data)
    bpy.context.collection.objects.link(band)
    band.data.materials.append(material)
    band_pieces = sorted(set(band_face_owners))
    bind_piece_ownership(band, band_pieces, band_face_owners)
    band["prototypeRole"] = "unfitted-unweighted-sewn-pattern"
    band["canonicalHostPieceIds"] = json.dumps(plastron["hostPieceIds"])
    band["uvStatus"] = "NOT_CREATED"

    fastener_spec = spec.get("frontFastenerHypothesis")
    fastener_audit = {"applied": False, "reason": "not-declared", "grantsClosureAcceptance": False}
    if fastener_spec is not None:
        if not isinstance(fastener_spec, dict):
            raise ValueError("frontFastenerHypothesis must be an object")
        fractions = fastener_spec.get("pathFractions")
        radius = fastener_spec.get("radiusM")
        relief = fastener_spec.get("reliefM")
        segment_count = fastener_spec.get("segments")
        if (not isinstance(fractions, list) or not fractions
                or any(not isinstance(value, (int, float)) or not 0.1 <= value <= 0.9 for value in fractions)
                or any(a >= b for a, b in zip(fractions, fractions[1:]))
                or not isinstance(radius, (int, float)) or not 0.003 <= radius <= 0.012
                or not isinstance(relief, (int, float)) or not 0.0005 <= relief <= 0.004
                or not isinstance(segment_count, int) or isinstance(segment_count, bool) or not 8 <= segment_count <= 32):
            raise ValueError("Invalid surface-bound front fastener hypothesis")
        fastener_color = fastener_spec.get("baseColorLinearRgb")
        if (not isinstance(fastener_color, list) or len(fastener_color) != 3
                or any(not isinstance(channel, (int, float)) or not 0 <= channel <= 1 for channel in fastener_color)):
            raise ValueError("Front fastener color must contain three channels in [0, 1]")
        fastener_material = bpy.data.materials.new(str(fastener_spec.get("materialName", "front-fastener-hypothesis")))
        fastener_material.use_nodes = True
        fastener_shader = fastener_material.node_tree.nodes.get("Principled BSDF")
        fastener_shader.inputs["Base Color"].default_value = (*fastener_color, 1)
        fastener_shader.inputs["Roughness"].default_value = float(fastener_spec.get("roughness", 0.3))
        fastener_shader.inputs["Metallic"].default_value = float(fastener_spec.get("metallic", 0.55))
        fastener_material["evidenceBoundary"] = fastener_spec["evidenceBoundary"]
        dx, dz = float(end[0]) - float(start[0]), float(end[1]) - float(start[1])
        centers = []
        for index, fraction in enumerate(fractions):
            center_x = float(start[0]) + dx * float(fraction)
            center_z = float(start[1]) + dz * float(fraction)
            vertices = [list(surface_point(front_tree, center_x, center_z, float(plastron.get("frontQueryYM", -0.16)), surface_offset + float(relief), surface_offset_mode)[0])]
            for segment in range(segment_count):
                angle = (2.0 * math.pi * segment) / segment_count
                x = center_x + float(radius) * math.cos(angle)
                z = center_z + float(radius) * math.sin(angle)
                bound, _owner = surface_point(front_tree, x, z, float(plastron.get("frontQueryYM", -0.16)), surface_offset + float(relief), surface_offset_mode)
                vertices.append(list(bound))
            faces = [(0, 1 + (segment + 1) % segment_count, 1 + segment) for segment in range(segment_count)]
            data = bpy.data.meshes.new(f"{job['id']}-front-fastener-{index + 1}-mesh")
            data.from_pydata(vertices, [], faces)
            data.update()
            button = bpy.data.objects.new(f"{job['id']}-front-fastener-{index + 1}-hypothesis", data)
            bpy.context.collection.objects.link(button)
            button.data.materials.append(fastener_material)
            bind_piece_ownership(button, ["jacket-overlap-front"], ["jacket-overlap-front"] * len(button.data.polygons))
            button["hostPieceIds"] = json.dumps(["jacket-overlap-front"])
            button["uvStatus"] = "NOT_CREATED"
            centers.append({"pathFraction": float(fraction), "centerXZ": [center_x, center_z], "vertexCount": len(vertices), "triangleCount": len(faces)})
        fastener_audit = {
            "applied": True,
            "method": "front-depth-raycast-bound-low-profile-metal-discs-on-declared-plastron-path",
            "hostPieceIds": ["jacket-overlap-front"],
            "radiusM": float(radius),
            "reliefM": float(relief),
            "segmentCount": segment_count,
            "materialName": fastener_material.name,
            "placements": centers,
            "evidenceBoundary": fastener_spec["evidenceBoundary"],
            "grantsClosureAcceptance": False,
            "grantsFitAcceptance": False,
        }

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
    path_layout = quilt.get("pathLayout", "diamond-cross-v1")
    if path_layout not in {"diamond-cross-v1", "integrated-panel-seams-v1"}:
        raise ValueError(f"Unsupported elbow quilting pathLayout: {path_layout}")
    quilt_material = material
    if path_layout == "integrated-panel-seams-v1":
        stitch_color = quilt.get("stitchColorLinearRgb")
        if (not isinstance(stitch_color, list) or len(stitch_color) != 3
                or any(not isinstance(channel, (int, float)) or not 0 <= channel <= 1 for channel in stitch_color)):
            raise ValueError("Integrated elbow seam layout requires stitchColorLinearRgb in [0, 1]")
        quilt_material = bpy.data.materials.new(str(quilt.get("stitchMaterialName", "elbow-seam-prototype")))
        quilt_material.use_nodes = True
        stitch_shader = quilt_material.node_tree.nodes.get("Principled BSDF")
        stitch_shader.inputs["Base Color"].default_value = (*stitch_color, 1)
        stitch_shader.inputs["Roughness"].default_value = float(quilt.get("stitchRoughness", 0.55))
        stitch_shader.inputs["Metallic"].default_value = float(quilt.get("stitchMetallic", 0.0))
        quilt_material["evidenceBoundary"] = quilt.get(
            "evidenceBoundary", "Surface-bound prototype seam hypothesis; appearance unapproved."
        )
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
        if path_layout == "integrated-panel-seams-v1":
            # Replace the floating-looking diamond/cross motif with a small,
            # surface-bound elbow panel perimeter and parallel seam channels.
            # These remain prototype thread paths, not sewn garment topology.
            raw_paths = [[
                (center_x + sign * half_length * math.cos(2.0 * math.pi * i / 32),
                 center_z + half_height * math.sin(2.0 * math.pi * i / 32))
                for i in range(33)
            ]]
            inset_height = half_height * 0.38
            inset_half_length = half_length * 0.72
            for lane in (-1.0, 1.0):
                lane_z = center_z + lane * inset_height
                edge_fraction = math.sqrt(max(0.0, 1.0 - (inset_height / half_height) ** 2))
                lane_half_length = inset_half_length * edge_fraction
                raw_paths.append([
                    (center_x - sign * lane_half_length + 2 * sign * lane_half_length * i / 12, lane_z)
                    for i in range(13)
                ])
        else:
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
        quilting.data.materials.append(quilt_material)
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = quilting
        quilting.select_set(True)
        bpy.ops.object.convert(target="MESH")
        quilting = bpy.context.view_layer.objects.active
        bind_piece_ownership(quilting, [piece_id], [piece_id] * len(quilting.data.polygons))
        quilting["prototypeRole"] = "unfitted-unweighted-sewn-pattern"
        quilting["hostPieceIds"] = json.dumps([piece_id])
        quilting.select_set(False)

        filled_patch_enabled = quilt.get("filledPatchEnabled", True)
        if not isinstance(filled_patch_enabled, bool):
            raise ValueError("filledPatchEnabled must be a boolean")
        patch_vertices = []
        patch_faces = []
        if filled_patch_enabled:
            # Optional surface-bound inset hypothesis. Direct review rejected
            # the filled geometric patch as a conspicuous applique rather than
            # integrated seam quilting, so disabling it leaves only the bound
            # stitch paths visible.
            patch_segments_per_side = int(quilt.get("patchSegmentsPerSide", 8))
            if not 4 <= patch_segments_per_side <= 24:
                raise ValueError("patchSegmentsPerSide must be between 4 and 24")
            corners = [
                (center_x, center_z + half_height),
                (center_x + sign * half_length, center_z),
                (center_x, center_z - half_height),
                (center_x - sign * half_length, center_z),
            ]
            patch_outline = []
            for corner_index, first in enumerate(corners):
                second = corners[(corner_index + 1) % len(corners)]
                for step in range(patch_segments_per_side):
                    fraction = step / patch_segments_per_side
                    patch_outline.append((
                        first[0] + (second[0] - first[0]) * fraction,
                        first[1] + (second[1] - first[1]) * fraction,
                    ))
            patch_vertices = [
                list(surface_point(tree, x, z, query_y, float(quilt.get("surfaceOffsetM", 0.0025)))[0])
                for x, z in patch_outline
            ]
            patch_vertices.append(list(surface_point(
                tree, center_x, center_z, query_y, float(quilt.get("surfaceOffsetM", 0.0025))
            )[0]))
            patch_center = len(patch_vertices) - 1
            patch_faces = [
                (patch_center, index, (index + 1) % len(patch_outline))
                for index in range(len(patch_outline))
            ]
            patch_data = bpy.data.meshes.new(f"{job['id']}-{piece_id}-prototype-elbow-quilt-inset")
            patch_data.from_pydata(patch_vertices, [], patch_faces)
            patch_data.update()
            patch = bpy.data.objects.new(
                f"{job['id']}-{piece_id}-prototype-elbow-quilt-inset-hypothesis", patch_data
            )
            bpy.context.collection.objects.link(patch)
            patch.data.materials.append(material)
            bind_piece_ownership(patch, [piece_id], [piece_id] * len(patch.data.polygons))
            patch["hostPieceIds"] = json.dumps([piece_id])
            patch["uvStatus"] = "NOT_CREATED"
        quilt_audits[piece_id] = {
            "surfaceSampleCount": projected_count,
            "pathCount": len(raw_paths),
            "pathLayout": path_layout,
            "filledPatchEnabled": filled_patch_enabled,
            "filledPatchVertexCount": len(patch_vertices),
            "filledPatchTriangleCount": len(patch_faces),
            "filledPatchStatus": "APPLIED" if filled_patch_enabled else "OMITTED_BY_REVIEWED_RECIPE",
            "filledPatchBinding": "positive-y-raycast-to-declared-sleeve-panel" if filled_patch_enabled else None,
            "hostPieceId": piece_id,
            "grantsAppearanceAcceptance": False,
        }
    return {
        "applied": True,
        "plastron": {
            "vertexCount": len(band_vertices),
            "quadCount": sample_count * across_sample_count,
            "acrossSampleCount": across_sample_count,
            "triangleCount": len(band_faces),
            "pathStartXZ": start,
            "pathEndXZ": end,
            "halfWidthStartM": half_width_start,
            "halfWidthEndM": half_width_end,
            "hostPieceIds": plastron["hostPieceIds"],
            "surfaceBinding": f"positive-y-raycast-conforming-grid-with-sewn-panel-transition-and-{surface_offset_mode}-offset",
            "cornerOwnerFallbackCount": corner_owner_fallback_count,
            "crossOwnerSectionCount": cross_owner_section_count,
            "crossOwnerTransitionQuadCount": len(cross_owner_transition_quads),
            "triangulation": {
                "method": "explicit-outward-diagonal-selection",
                "quadCount": sample_count * across_sample_count,
                "acrossSampleCount": across_sample_count,
                "triangleCount": len(band_faces),
                "diagonalCounts": triangulation_choices,
                "minimumOutwardNormalY": weakest_triangle_front_normal,
            },
            "uvStatus": "NOT_CREATED",
            "grantsAppearanceAcceptance": False,
        },
        "elbowQuilting": quilt_audits,
        "frontFastenerHypothesis": fastener_audit,
        "grantsFitOrAppearanceAcceptance": False,
        "evidenceBoundary": spec.get(
            "evidenceBoundary", "Unfitted visual hypothesis; requires direct image review."
        ),
    }


def append_declared_rear_waist_tab(mesh, body_objects, pose, recipe, target_path):
    """Add a small rear waist tab projected from the actual avatar surface.

    The tab remains part of the garment mesh so the existing cloth, weight,
    export, and render stages process it with the rest of the candidate.
    Projection and offsets are prototype hypotheses only.
    """
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    spec = pose.get("rearWaistAdjustmentTab")
    if spec is None:
        return {"applied": False, "reason": "not-declared", "grantsFitAcceptance": False}
    if not isinstance(spec, dict) or spec.get("method") != "avatar-back-surface-projected-tab-v1":
        raise ValueError("Invalid rear waist adjustment tab method")
    piece_id = spec.get("pieceId")
    center = spec.get("centerXZ")
    width = spec.get("widthM")
    height = spec.get("heightM")
    x_segments = spec.get("xSegments")
    z_segments = spec.get("zSegments")
    query_y = spec.get("backQueryYM")
    offset = spec.get("surfaceOffsetM")
    buckle_offset = spec.get("buckleReliefM")
    buckle_width = spec.get("buckleWidthM")
    buckle_height = spec.get("buckleHeightM")
    query_distance = spec.get("maximumProjectionDistanceM")
    if (not isinstance(piece_id, str) or not piece_id
            or not isinstance(center, list) or len(center) != 2
            or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in center)
            or not all(isinstance(value, (int, float)) and math.isfinite(value)
                       for value in (width, height, query_y, offset, buckle_offset,
                                     buckle_width, buckle_height, query_distance))
            or not 0.07 <= width <= 0.18 or not 0.018 <= height <= 0.05
            or not isinstance(x_segments, int) or isinstance(x_segments, bool) or not 4 <= x_segments <= 16
            or not isinstance(z_segments, int) or isinstance(z_segments, bool) or not 1 <= z_segments <= 4
            or query_y <= 0.05 or not 0.006 <= offset <= 0.02
            or not 0.0005 <= buckle_offset <= 0.004
            or not 0.018 <= buckle_width <= width * 0.6
            or not 0.008 <= buckle_height <= height * 0.8
            or not 0.05 <= query_distance <= 0.8):
        raise ValueError("Invalid rear waist adjustment tab dimensions or projection bounds")
    bodies = [obj for obj in body_objects
              if obj.type == "MESH" and obj.name.startswith(spec.get("bodyMeshNamePrefix", ""))]
    if len(bodies) != 1:
        raise ValueError("Rear waist tab requires exactly one declared target body mesh")
    body = bodies[0]
    shape_values = {key.name: float(key.value) for key in body.data.shape_keys.key_blocks} if body.data.shape_keys else {}
    if any(abs(value) > 1e-8 for value in shape_values.values()):
        raise ValueError("Rear waist tab projection requires zero-valued target Shape Keys")
    evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated_data = evaluated.to_mesh()
    try:
        evaluated_data.calc_loop_triangles()
        coordinates = [evaluated.matrix_world @ vertex.co for vertex in evaluated_data.vertices]
        triangles = [tuple(triangle.vertices) for triangle in evaluated_data.loop_triangles]
    finally:
        evaluated.to_mesh_clear()
    tree = BVHTree.FromPolygons(coordinates, triangles, all_triangles=True)

    def project(x, z, extra_offset=0.0):
        origin = Vector((x, query_y, z))
        result = tree.ray_cast(origin, Vector((0.0, -1.0, 0.0)), query_distance)
        if result is None or result[0] is None:
            raise ValueError(f"Rear waist tab projection missed target body at x={x:.4f}, z={z:.4f}")
        location, normal, face_index, distance = result
        if normal.y <= 0.05 or distance <= 0:
            raise ValueError("Rear waist tab projection did not hit an outward-facing posterior body surface")
        point = location + normal.normalized() * (offset + extra_offset)
        return point, normal.normalized(), face_index, float(distance)

    tab_vertices = []
    tab_normals = []
    tab_samples = []
    row_width = x_segments + 1
    for row in range(z_segments + 1):
        fraction_z = row / z_segments
        z = center[1] - height / 2 + height * fraction_z
        for column in range(x_segments + 1):
            fraction_x = column / x_segments
            x = center[0] - width / 2 + width * fraction_x
            point, normal, face_index, distance = project(x, z)
            tab_vertices.append(list(point))
            tab_normals.append(list(normal))
            tab_samples.append({"xM": x, "zM": z, "targetFaceIndex": face_index,
                                "distanceM": distance, "pointM": list(point),
                                "normal": list(normal)})
    tab_faces = []
    for row in range(z_segments):
        for column in range(x_segments):
            lower_left = row * row_width + column
            upper_left = lower_left + row_width
            quad = (lower_left, lower_left + 1, upper_left + 1, upper_left)
            candidates = [(quad[0], quad[3], quad[2]), (quad[0], quad[2], quad[1])]
            oriented = []
            for face in candidates:
                a, b, c = (Vector(tab_vertices[index]) for index in face)
                face_normal = (b - a).cross(c - a)
                if face_normal.length_squared <= 1e-14:
                    raise ValueError("Rear waist tab grid produced a degenerate triangle")
                expected_normal = sum((Vector(tab_normals[index]) for index in face), Vector())
                oriented.append(tuple(reversed(face)) if face_normal.dot(expected_normal) < 0 else face)
            tab_faces.extend(oriented)

    buckle_vertices = []
    buckle_normals = []
    buckle_faces = []
    buckle_row_width = 3
    for row in range(3):
        z = center[1] - buckle_height / 2 + buckle_height * row / 2
        for column in range(3):
            x = center[0] - buckle_width / 2 + buckle_width * column / 2
            point, normal, _face_index, _distance = project(x, z, buckle_offset)
            buckle_vertices.append(list(point))
            buckle_normals.append(list(normal))
    for row in range(2):
        for column in range(2):
            lower_left = row * buckle_row_width + column
            upper_left = lower_left + buckle_row_width
            quad = (lower_left, lower_left + 1, upper_left + 1, upper_left)
            candidates = [(quad[0], quad[3], quad[2]), (quad[0], quad[2], quad[1])]
            for face in candidates:
                a, b, c = (Vector(buckle_vertices[index]) for index in face)
                face_normal = (b - a).cross(c - a)
                expected_normal = sum((Vector(buckle_normals[index]) for index in face), Vector())
                if face_normal.length_squared <= 1e-14:
                    raise ValueError("Rear waist tab buckle produced a degenerate triangle")
                buckle_faces.append(tuple(reversed(face)) if face_normal.dot(expected_normal) < 0 else face)

    old_vertex_count = len(mesh["vertices"])
    old_face_count = len(mesh["faces"])
    face_uv = mesh.get("facePatternCoordinates")
    panel_uv_keys = mesh.get("facePatternPanelKeys")
    face_uv_kinds = mesh.get("faceUvSourceKinds")
    if (not isinstance(face_uv, list) or not isinstance(panel_uv_keys, list)
            or not isinstance(face_uv_kinds, list)
            or len(face_uv) != old_face_count
            or len(panel_uv_keys) != old_face_count
            or len(face_uv_kinds) != old_face_count):
        raise ValueError(
            "Pattern UV provenance must cover the sewn faces before accessory "
            f"placement (schema={mesh.get('schemaVersion')!r}, "
            f"faces={old_face_count}, coordinates="
            f"{len(face_uv) if isinstance(face_uv, list) else 'missing'}, "
            f"panelKeys={len(panel_uv_keys) if isinstance(panel_uv_keys, list) else 'missing'}, "
            f"sourceKinds={len(face_uv_kinds) if isinstance(face_uv_kinds, list) else 'missing'})"
        )
    tab_uv_vertices = [
        [((column / x_segments) - 0.5) * width,
         ((row / z_segments) - 0.5) * height]
        for row in range(z_segments + 1)
        for column in range(x_segments + 1)
    ]
    buckle_uv_vertices = [
        [((column / 2) - 0.5) * buckle_width,
         ((row / 2) - 0.5) * buckle_height]
        for row in range(3)
        for column in range(3)
    ]
    accessory_uv = [
        [tab_uv_vertices[index] for index in face] for face in tab_faces
    ] + [
        [buckle_uv_vertices[index] for index in face] for face in buckle_faces
    ]
    accessory_panel_keys = (
        [f"accessory:{piece_id}:tab" for _ in tab_faces]
        + [f"accessory:{piece_id}:buckle" for _ in buckle_faces]
    )
    if "faceMaterialIds" not in mesh:
        mesh["faceMaterialIds"] = ["prototypeMaterial"] * old_face_count
    elif len(mesh["faceMaterialIds"]) != old_face_count:
        raise ValueError("Face material ownership is not aligned to prototype topology")
    mesh["vertices"].extend(tab_vertices)
    mesh["vertices"].extend(buckle_vertices)
    mesh["faces"].extend([tuple(old_vertex_count + index for index in face) for face in tab_faces])
    mesh["facePieceIds"].extend([piece_id] * len(tab_faces))
    mesh["faceMaterialIds"].extend(["rearWaistTabMaterial"] * len(tab_faces))
    buckle_start = old_vertex_count + len(tab_vertices)
    mesh["faces"].extend([tuple(buckle_start + index for index in face) for face in buckle_faces])
    mesh["facePieceIds"].extend([piece_id] * len(buckle_faces))
    mesh["faceMaterialIds"].extend(["rearWaistBuckleMaterial"] * len(buckle_faces))
    mesh["facePatternCoordinates"].extend(accessory_uv)
    mesh["facePatternPanelKeys"].extend(accessory_panel_keys)
    mesh["faceUvSourceKinds"].extend(
        ["declared-parametric-accessory"] * len(accessory_uv)
    )
    if len(mesh["faces"]) != len(mesh["facePieceIds"]) or len(mesh["faces"]) != len(mesh["faceMaterialIds"]):
        raise ValueError("Rear waist tab broke face ownership alignment")
    if not (len(mesh["faces"]) == len(mesh["facePatternCoordinates"])
            == len(mesh["facePatternPanelKeys"]) == len(mesh["faceUvSourceKinds"])):
        raise ValueError("Rear waist tab broke authored UV provenance alignment")
    material_spec = recipe.get("prototypeRearWaistTabMaterials")
    if not isinstance(material_spec, dict):
        raise ValueError("Rear waist tab requires declared prototype materials")
    for key in ("tab", "buckle"):
        entry = material_spec.get(key)
        color = entry.get("baseColorLinearRgb") if isinstance(entry, dict) else None
        if (not isinstance(color, list) or len(color) != 3
                or any(not isinstance(channel, (int, float)) or not 0 <= channel <= 1 for channel in color)):
            raise ValueError(f"Rear waist tab {key} material needs an RGB color in [0, 1]")
    return {
        "applied": True,
        "method": spec["method"],
        "pieceId": piece_id,
        "targetBodyObject": body.name,
        "targetAvatarSha256": digest(target_path),
        "targetShapeKeyValues": shape_values,
        "centerXZ": center,
        "boundsM": {"width": width, "height": height},
        "surfaceOffsetM": offset,
        "buckleReliefM": buckle_offset,
        "rayBoundVertexCount": len(tab_samples) + len(buckle_vertices),
        "tabTriangleCount": len(tab_faces),
        "buckleTriangleCount": len(buckle_faces),
        "samples": tab_samples,
        "grantsFitAcceptance": False,
        "grantsVisualAcceptance": False,
        "evidenceBoundary": spec["evidenceBoundary"],
    }


def lengthen_declared_shorts(mesh, pose):
    """Extend only the lower edge zone of the sewn shorts before body projection."""
    from collections import defaultdict
    from mathutils import Vector

    spec = pose.get("shortsCoverageExtension")
    if spec is None:
        return {"applied": False, "grantsFitAcceptance": False}
    if not isinstance(spec, dict) or spec.get("method") != "shorts-lower-hem-skirt-coverage-v1":
        raise ValueError("Invalid shorts coverage extension method")
    pieces = set(spec.get("pieceIds", []))
    extension = spec.get("extensionM")
    fade_height = spec.get("fadeHeightM")
    if (not pieces or not pieces.issubset(set(mesh["facePieceIds"]))
            or not all(isinstance(value, (int, float)) and math.isfinite(value)
                       for value in (extension, fade_height))
            or not 0.015 <= extension <= 0.08 or not 0.025 <= fade_height <= 0.12):
        raise ValueError("Invalid shorts lower hem extension bounds or panel selection")
    vertex_owners = defaultdict(set)
    for face, owner in zip(mesh["faces"], mesh["facePieceIds"]):
        for vertex in face:
            vertex_owners[vertex].add(owner)
    selected = {vertex for vertex, owners in vertex_owners.items()
                if owners.intersection(pieces) and owners.issubset(pieces)}
    if not selected:
        raise ValueError("Shorts coverage extension selected no vertices")
    lower = min(mesh["vertices"][index][2] for index in selected)
    upper = max(mesh["vertices"][index][2] for index in selected)
    if upper - lower < fade_height:
        raise ValueError("Shorts coverage fade height exceeds panel length")
    moved = 0
    records = []
    for index in sorted(selected):
        point = mesh["vertices"][index]
        fraction = max(0.0, min(1.0, (point[2] - lower) / fade_height))
        smooth = fraction * fraction * (3.0 - 2.0 * fraction)
        displacement = extension * (1.0 - smooth)
        if displacement > 1e-7:
            before = list(point)
            point[2] -= displacement
            moved += 1
            records.append({"vertexIndex": index, "pieceIds": sorted(vertex_owners[index]),
                            "beforeM": before, "afterM": list(point), "displacementM": displacement})
    if not moved:
        raise ValueError("Shorts coverage extension moved no vertices")
    for face in mesh["faces"]:
        a, b, c = [Vector(mesh["vertices"][vertex]) for vertex in face]
        if (b - a).cross(c - a).length / 2 <= 1e-12:
            raise ValueError("Shorts coverage extension collapsed a triangle")
    return {
        "applied": True,
        "method": spec["method"],
        "pieceIds": sorted(pieces),
        "sourceLowerHemZM": lower,
        "sourceUpperZM": upper,
        "extensionM": extension,
        "fadeHeightM": fade_height,
        "movedVertexCount": moved,
        "minimumAfterZM": min(mesh["vertices"][index][2] for index in selected),
        "records": records,
        "grantsFitAcceptance": False,
        "grantsVisualAcceptance": False,
        "evidenceBoundary": spec["evidenceBoundary"],
    }


def preserved_seam_factors(mesh, spec):
    """Fade placement displacement continuously away from preserved seams."""
    from collections import defaultdict
    from mathutils import Vector
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
        for i, (a, b) in enumerate(segments):
            for point in (a, b):
                graph[tuple(round(c, 6) for c in point)].append(i)
        unseen = set(range(len(segments)))
        loops = []
        while unseen:
            stack = [unseen.pop()]
            ids = set(stack)
            while stack:
                i = stack.pop()
                for point in segments[i]:
                    for neighbor in graph[tuple(round(c, 6) for c in point)]:
                        if neighbor in unseen:
                            unseen.remove(neighbor)
                            ids.add(neighbor)
                            stack.append(neighbor)
            selected = [segments[i] for i in ids]
            nodes = {tuple(round(c, 6) for c in point) for seg in selected for point in seg}
            closed = all(len(graph[n]) == 2 for n in nodes)
            xs = [point[0] for seg in selected for point in seg]
            ys = [point[1] for seg in selected for point in seg]
            if closed and (envelope or min(xs)<0<max(xs)):
                loops.append((sum(math.dist(a, b) for a, b in selected), selected,
                              [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]))
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
        c = section["centerM"]
        dx, dy = direction
        distances = []
        for a, b in section["segmentsM"]:
            ex, ey = b[0] - a[0], b[1] - a[1]
            qx, qy = a[0] - c[0], a[1] - c[1]
            den = dx * ey - dy * ex
            if abs(den) < 1e-12:
                continue
            distance = (qx * ey - qy * ex) / den
            u = (qx * dy - qy * dx) / den
            if distance > 0 and -1e-8 <= u <= 1 + 1e-8:
                distances.append(distance)
        if not distances:
            raise ValueError("Contour radial intersection missing")
        distance = max(distances) + clearance + layer_offset
        return Vector((c[0] + dx * distance, c[1] + dy * distance))

    ids = set(spec["pieceIds"])
    if not ids.issubset(set(mesh["facePieceIds"])):
        raise ValueError("Contour placement pieces missing")
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
        x, y, z = mesh["vertices"][i]
        length = math.hypot(x, y)
        height_weight = 1.0
        if height_blend is not None:
            fraction = min(1.0, max(0.0, (z-height_blend[0])/(height_blend[1]-height_blend[0])))
            height_weight = fraction*fraction*(3-2*fraction)
            if height_weight == 0:
                height_blend_skipped += 1
                continue
        if length < 1e-9:
            raise ValueError("Torso angular coordinate collapsed")
        direction = (x / length, y / length)
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
        if z < zs[0] or z > zs[-1]:
            extrapolated += 1
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
        if (b - a).cross(c - a).length / 2 <= 1e-12:
            raise ValueError("Body contour placement collapsed a triangle")
    return {"applied":True,"targetSourceSha256":digest(target_path),"bodyObject":body.name,"configuration":spec,"sections":sections,"placedVertexCount":len(vertex_ids),"heightBlendSkippedVertexCount":height_blend_skipped,"angularSourceVerticesSha256":hashlib.sha256(json.dumps(angular_source_vertices,separators=(",",":")).encode()).hexdigest() if angular_source_vertices is not None else None,"layerOffsetVertexCount":layered,"sharedSeamVerticesLayerOffsetM":0,"heightExtrapolatedVertexCount":extrapolated,"beforeVerticesSha256":hashlib.sha256(before.encode()).hexdigest(),"afterVerticesSha256":hashlib.sha256(json.dumps(mesh["vertices"],separators=(",",":")).encode()).hexdigest(),"bodyFacesCopied":False,"grantsFitAcceptance":False}


def place_on_measured_upper_surface(mesh, body_objects, pose, target_path):
    """Fit original upper garment vertices to the evaluated target surface.

    Shared sewn vertices move once. No body topology is copied and no garment
    faces are removed when a projection fails or collapses a triangle.
    """
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
    outer_piece_ids = set(spec.get("outerPieceIds", []))
    if "outerPieceId" in spec:
        outer_piece_ids.add(spec["outerPieceId"])
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
        outer_offset = (
            spec["outerLayerOffsetM"]
            if pieces and pieces.issubset(outer_piece_ids)
            else 0
        )
        offset = clearance + outer_offset
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
    from mathutils import Vector

    spec = pose.get("skirtPleatPlacement")
    if spec is None:
        return {"applied": False}
    fold_method = spec.get("foldMethod", spec["method"])
    if fold_method not in {
            "crease-aligned-triangular-radial-fold",
            "crease-aligned-alternating-triangular-radial-pleat",
            "crease-aligned-smooth-radial-pleat",
            "crease-bound-soft-box-pleat-v1",
            "panel-local-soft-knife-pleat-v1"}:
        return {"applied": False}
    fold_count = spec["foldCount"]
    topology_subdivision_factor = spec.get("topologySubdivisionFactor", 1)
    if not isinstance(fold_count, int) or isinstance(fold_count, bool) or not 2 <= fold_count <= 64:
        raise ValueError("Invalid authored skirt fold count")
    if (not isinstance(topology_subdivision_factor, int)
            or isinstance(topology_subdivision_factor, bool)
            or not 1 <= topology_subdivision_factor <= 4):
        raise ValueError("Invalid radial skirt topology subdivision factor")
    radial_cut_count = fold_count * topology_subdivision_factor
    origin = spec["axisOriginBlenderXYM"]
    phase = spec["phaseRadians"]
    selected = set(spec["pieceIds"]) | set(spec["seamContinuationPieceIds"])
    if (radial_cut_count > 256
            or len(origin) != 2 or not all(math.isfinite(v) for v in [*origin, phase])
            or not selected.issubset(set(mesh["facePieceIds"]))):
        raise ValueError("Invalid explicit crease topology declaration")
    pieces = sorted(set(mesh["facePieceIds"]))
    bm = bmesh.new()
    owner = bm.faces.layers.int.new("canonical_owner")
    original_id = bm.verts.layers.int.new("original_vertex_id")
    initial_count = len(mesh["vertices"])
    initial_face_count = len(mesh["faces"])
    uv_coordinates = mesh.get("facePatternCoordinates")
    uv_panel_keys = mesh.get("facePatternPanelKeys")
    uv_source_kinds = mesh.get("faceUvSourceKinds")
    if (not isinstance(uv_coordinates, list)
            or not isinstance(uv_panel_keys, list)
            or not isinstance(uv_source_kinds, list)
            or len(uv_coordinates) != initial_face_count
            or len(uv_panel_keys) != initial_face_count
            or len(uv_source_kinds) != initial_face_count):
        raise ValueError("Crease subdivision requires complete source-face UV provenance")
    panel_keys = sorted(set(uv_panel_keys))
    source_kinds = sorted(set(uv_source_kinds))
    if (not panel_keys or not source_kinds
            or any(not isinstance(key, str) or not key for key in panel_keys)
            or any(not isinstance(kind, str) or not kind for kind in source_kinds)):
        raise ValueError("Crease subdivision found invalid UV panel/source provenance")
    vertices = []
    uv_layer = bm.loops.layers.uv.new("image2outfit_source_pattern_uv")
    for index, point in enumerate(mesh["vertices"]):
        vertex = bm.verts.new(point)
        vertex[original_id] = index + 1
        vertices.append(vertex)
    panel_layer = bm.faces.layers.int.new("image2outfit_uv_panel_index")
    source_layer = bm.faces.layers.int.new("image2outfit_uv_source_index")
    for face_index, (indices, piece) in enumerate(zip(mesh["faces"], mesh["facePieceIds"])):
        face = bm.faces.new([vertices[i] for i in indices])
        face[owner] = pieces.index(piece) + 1
        face[panel_layer] = panel_keys.index(uv_panel_keys[face_index]) + 1
        face[source_layer] = source_kinds.index(uv_source_kinds[face_index]) + 1
        source_coordinates = uv_coordinates[face_index]
        if len(source_coordinates) != len(face.loops):
            raise ValueError("Crease subdivision source UV loop count does not match face")
        for loop, coordinate in zip(face.loops, source_coordinates):
            if len(coordinate) != 2:
                raise ValueError("Crease subdivision source UV coordinate is malformed")
            loop[uv_layer].uv = (float(coordinate[0]), float(coordinate[1]))
    cuts = []
    longitudinal_cuts = []
    try:
        for i in range(radial_cut_count):
            angle = phase + i * math.pi / radial_cut_count
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
        row_count = spec.get("longitudinalSubdivisionCount", 0)
        waist = spec["waistZM"]
        hem = spec["sourceHemZM"]
        if (not isinstance(row_count, int) or isinstance(row_count, bool)
                or not 0 <= row_count <= 12 or not math.isfinite(waist + hem)
                or waist <= hem):
            raise ValueError("Invalid declared longitudinal skirt subdivision count")
        skirt_piece_ids = set(spec["pieceIds"])
        for i in range(1, row_count + 1):
            z = hem + (waist - hem) * i / (row_count + 1)
            faces = [f for f in bm.faces if pieces[f[owner]-1] in skirt_piece_ids]
            edges = {e for f in faces for e in f.edges}
            verts = {v for f in faces for v in f.verts}
            old_vertices = set(bm.verts)
            result = bmesh.ops.bisect_plane(
                bm, geom=[*verts, *edges, *faces], dist=1e-6,
                plane_co=Vector((0, 0, z)), plane_no=Vector((0, 0, 1)),
                clear_inner=False, clear_outer=False)
            added = [v for v in bm.verts if v not in old_vertices]
            for vertex in added:
                vertex[original_id] = 0
            longitudinal_cuts.append({
                "heightZM": z, "newVertexCount": len(added),
                "cutEdgeCount": sum(isinstance(g, bmesh.types.BMEdge)
                                    for g in result["geom_cut"])})
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        original = {v[original_id]-1: v for v in bm.verts if v[original_id] > 0}
        if set(original) != set(range(initial_count)):
            raise ValueError("Crease cuts lost original sewn vertex identity")
        ordered = [original[i] for i in range(initial_count)] + [v for v in bm.verts if v[original_id] == 0]
        remap = {v: i for i, v in enumerate(ordered)}
        result_vertices = [list(v.co) for v in ordered]
        result_faces, result_owners = [], []
        result_uv_coordinates, result_uv_panel_keys, result_uv_source_kinds = [], [], []
        for face in bm.faces:
            if not 1 <= face[owner] <= len(pieces):
                raise ValueError("Crease cut lost canonical face ownership")
            if len(face.verts) != 3 or face.calc_area() <= 1e-12:
                raise ValueError("Crease cut produced a degenerate triangle")
            result_faces.append([remap[v] for v in face.verts])
            result_owners.append(pieces[face[owner]-1])
            panel_index = face[panel_layer]
            source_index = face[source_layer]
            if not 1 <= panel_index <= len(panel_keys) or not 1 <= source_index <= len(source_kinds):
                raise ValueError("Crease subdivision lost UV panel/source provenance")
            result_uv_coordinates.append([
                [float(loop[uv_layer].uv.x), float(loop[uv_layer].uv.y)]
                for loop in face.loops
            ])
            result_uv_panel_keys.append(panel_keys[panel_index - 1])
            result_uv_source_kinds.append(source_kinds[source_index - 1])
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
        mesh.update(
            vertices=result_vertices,
            faces=result_faces,
            facePieceIds=result_owners,
            facePatternCoordinates=result_uv_coordinates,
            facePatternPanelKeys=result_uv_panel_keys,
            faceUvSourceKinds=result_uv_source_kinds,
        )
        if not (len(result_faces) == len(result_uv_coordinates)
                == len(result_uv_panel_keys) == len(result_uv_source_kinds)):
            raise ValueError("Crease subdivision broke source-face UV alignment")
        return {"applied": True, "method": spec["method"], "foldMethod": fold_method,
                "foldCount": fold_count,
                "topologySubdivisionFactor": topology_subdivision_factor,
                "radialTopologyCutCount": len(cuts),
                "cuts": cuts, "longitudinalSubdivisionCuts": longitudinal_cuts,
                "longitudinalSubdivisionCount": len(longitudinal_cuts),
                "beforeVertexCount": initial_count, "afterVertexCount": len(ordered),
                "beforeTriangleCount": initial_face_count, "afterTriangleCount": len(result_faces),
                "sharedSkirtWaistbandEdgeCount": len(seam_edges),
                "authoredUvFaceCount": len(result_uv_coordinates),
                "authoredUvPanelCount": len(set(result_uv_panel_keys)),
                "authoredUvSourceKinds": {kind: result_uv_source_kinds.count(kind)
                                           for kind in sorted(set(result_uv_source_kinds))},
                "degenerateTriangleCount": 0, "nonManifoldEdgeCount": non_manifold,
                "originalVertexIdentityPreserved": True,
                "grantsFitAcceptance": False, "grantsVisualAcceptance": False,
                "evidenceBoundary": "Native radial cuts align the declared fold profile to actual mesh edges; canonical ownership and sewn waist adjacency survive. Fold count/depth remain design hypotheses; no exact fabric isometry or fit acceptance."}
    finally:
        bm.free()


def lengthen_declared_skirt_panels(mesh, pose):
    """Extend the sewn overskirt downward while anchoring its waist seam."""

    spec = pose.get("skirtPleatPlacement")
    if spec is None:
        return {"applied": False}
    pieces = set(spec.get("pieceIds", []))
    owners = set(mesh.get("facePieceIds", []))
    waist = spec.get("waistZM")
    source_hem = spec.get("sourceHemZM")
    target_hem = spec.get("hemZM")
    placement_method = spec.get("method", "lower-to-declared-skirt-hem")
    retain_pattern_hem = placement_method == "retain-short-sewn-pattern-hem-v1"
    if (not pieces or not pieces.issubset(owners)
            or any(not isinstance(value, (int, float)) or not math.isfinite(value)
                   for value in (waist, source_hem, target_hem))
            or not source_hem < waist
            or (retain_pattern_hem and abs(target_hem-source_hem) > 1e-6)
            or (not retain_pattern_hem and not target_hem < source_hem)):
        raise ValueError("Invalid declared overskirt lengthening bounds")
    extension = source_hem - target_hem
    if ((retain_pattern_hem and extension != 0)
            or (not retain_pattern_hem and not 0.02 <= extension <= 0.24)):
        raise ValueError("Overskirt extension must remain within the bounded 20-240 mm trial")
    selected = {
        vertex
        for face, piece in zip(mesh["faces"], mesh["facePieceIds"])
        if piece in pieces
        for vertex in face
    }
    if not selected:
        raise ValueError("Declared overskirt pieces have no vertices")
    from collections import defaultdict
    vertex_owners = defaultdict(set)
    for face, owner in zip(mesh["faces"], mesh["facePieceIds"]):
        for vertex in face:
            vertex_owners[vertex].add(owner)
    before_min = min(mesh["vertices"][index][2] for index in selected)
    before_max = max(mesh["vertices"][index][2] for index in selected)
    apron = None if retain_pattern_hem else spec.get("forwardApron")
    if apron is not None:
        apron_piece_ids = apron.get("pieceIds", [apron.get("pieceId")])
        if (apron.get("method") != "front-panel-forward-scoop-v2"
                or not apron_piece_ids
                or not set(apron_piece_ids).issubset(pieces)
                or not isinstance(apron.get("axisOriginBlenderXYM"), list)
                or len(apron["axisOriginBlenderXYM"]) != 2
                or not all(math.isfinite(v) for v in apron["axisOriginBlenderXYM"])
                or not math.isfinite(apron.get("additionalExtensionM", math.nan))
                or not 0 <= apron["additionalExtensionM"] <= 0.10
                or not math.isfinite(apron.get("forwardProjectionM", math.nan))
                or not 0 <= apron["forwardProjectionM"] <= 0.04
                or not math.isfinite(apron.get("fullExtensionHalfAngleRadians", math.nan))
                or not math.isfinite(apron.get("zeroExtensionHalfAngleRadians", math.nan))
                or not 0 < apron["fullExtensionHalfAngleRadians"] < apron["zeroExtensionHalfAngleRadians"] <= math.pi):
            raise ValueError("Invalid forward apron extension profile")
        if extension + apron["additionalExtensionM"] > 0.24 + 1e-9:
            raise ValueError("Combined rear hem and forward apron extension exceeds the 240 mm trial bound")
    moved = 0
    max_displacement = 0.0
    max_apron_displacement = 0.0
    max_forward_projection = 0.0
    for index in selected:
        point = mesh["vertices"][index]
        z = float(point[2])
        if z < source_hem - 0.002 or z > waist + 0.002:
            raise ValueError("Overskirt vertex falls outside the declared source height span")
        fraction = min(1.0, max(0.0, (waist - z) / (waist - source_hem)))
        displacement = extension * fraction
        apron_displacement = 0.0
        forward_projection = 0.0
        if apron is not None:
            if vertex_owners[index].intersection(apron_piece_ids):
                origin = apron["axisOriginBlenderXYM"]
                native = point
                angle = math.atan2(native[0] - origin[0], -(native[1] - origin[1]))
                delta = abs(math.atan2(math.sin(angle), math.cos(angle)))
                start = apron["fullExtensionHalfAngleRadians"]
                end = apron["zeroExtensionHalfAngleRadians"]
                fade = min(1.0, max(0.0, (delta - start) / (end - start)))
                fade = fade * fade * (3.0 - 2.0 * fade)
                apron_displacement = apron["additionalExtensionM"] * fraction * (1.0 - fade)
                forward_projection = apron["forwardProjectionM"] * fraction * (1.0 - fade)
                displacement += apron_displacement
        if displacement:
            point[2] = z - displacement
            point[1] -= forward_projection
            moved += 1
            max_displacement = max(max_displacement, displacement)
            max_apron_displacement = max(max_apron_displacement, apron_displacement)
            max_forward_projection = max(max_forward_projection, forward_projection)
    after_min = min(mesh["vertices"][index][2] for index in selected)
    after_max = max(mesh["vertices"][index][2] for index in selected)
    apron_allowance = apron["additionalExtensionM"] if apron else 0.0
    if (after_min > target_hem + 0.003
            or after_min < target_hem - apron_allowance - 0.003
            or abs(after_max - before_max) > 0.003):
        raise ValueError("Overskirt lengthening did not preserve the waist and declared hem")
    return {
        "applied": True,
        "method": placement_method if retain_pattern_hem else "short-panelized-hem-with-forward-apron-and-faded-side-seams" if apron else "linear-downward-extension-from-fixed-sewn-waist-to-overskirt-hem",
        "pieceIds": sorted(pieces),
        "sourceHemZM": source_hem,
        "targetHemZM": target_hem,
        "waistZM": waist,
        "extensionM": extension,
        "selectedVertexCount": len(selected),
        "movedVertexCount": moved,
        "maximumVertexDisplacementM": max_displacement,
        "forwardApron": apron,
        "maximumAdditionalForwardApronDisplacementM": max_apron_displacement,
        "maximumForwardApronProjectionM": max_forward_projection,
        "beforeBoundsZM": [before_min, before_max],
        "afterBoundsZM": [after_min, after_max],
        "grantsFitAcceptance": False,
        "grantsVisualAcceptance": False,
        "evidenceBoundary": "Sewn overskirt geometry-only length hypothesis. It adds lower panel area while preserving the waist seam; no sitting coverage, collision, cloth, weight, fit or appearance acceptance is implied.",
    }


def place_declared_skirt_folds(mesh, pose, native_vertices):
    """Seed explicit garment folds while retaining the sewn face topology."""
    from mathutils import Vector

    spec = pose.get("skirtPleatPlacement")
    if spec is None:
        return {"applied": False}
    fold_method = spec.get("foldMethod", spec["method"])
    if fold_method not in {
            "outward-triangular-radial-fold-seed",
            "crease-aligned-triangular-radial-fold",
            "crease-aligned-alternating-triangular-radial-pleat",
            "crease-aligned-smooth-radial-pleat",
            "crease-bound-soft-box-pleat-v1",
            "panel-local-soft-knife-pleat-v1"}:
        raise ValueError("Unknown skirt fold placement")
    origin = spec["axisOriginBlenderXYM"]
    waist, declared_hem = spec["waistZM"], spec["hemZM"]
    count, depth, phase = spec["foldCount"], spec["hemFoldDepthM"], spec["phaseRadians"]
    if (len(origin) != 2 or not all(math.isfinite(v) for v in [*origin, waist, declared_hem, depth, phase])
            or not declared_hem < waist or not isinstance(count, int) or isinstance(count, bool)
            or count < 2 or depth <= 0 or len(native_vertices) != len(mesh["vertices"])):
        raise ValueError("Invalid skirt fold specification")
    ids = set(spec["pieceIds"])
    if not ids or not ids.issubset(set(mesh["facePieceIds"])):
        raise ValueError("Skirt fold pieces missing")
    panel_local = fold_method == "panel-local-soft-knife-pleat-v1"
    panel_ranges = {}
    if panel_local:
        from collections import defaultdict
        folds_per_panel = spec.get("foldsPerPanel")
        if isinstance(folds_per_panel, bool) or not isinstance(folds_per_panel, int) or not 1 <= folds_per_panel <= 6:
            raise ValueError("Panel-local pleats require 1-6 folds per sewn panel")
        by_piece = {piece: set() for piece in ids}
        vertex_piece_owners = defaultdict(set)
        for face, piece in zip(mesh["faces"], mesh["facePieceIds"]):
            if piece in by_piece:
                by_piece[piece].update(face)
                for vertex_id in face:
                    vertex_piece_owners[vertex_id].add(piece)
        for piece, indices in by_piece.items():
            angles = [math.atan2(native_vertices[i][0]-origin[0], -(native_vertices[i][1]-origin[1])) for i in indices]
            center = math.atan2(sum(math.sin(value) for value in angles), sum(math.cos(value) for value in angles))
            unwrapped = [center + math.atan2(math.sin(value-center), math.cos(value-center)) for value in angles]
            low, high = min(unwrapped), max(unwrapped)
            if high-low < 0.08:
                raise ValueError(f"Panel angular span is too small for local pleats: {piece}")
            panel_ranges[piece] = [low, high]
    vertices = {i for face, owner in zip(mesh["faces"], mesh["facePieceIds"]) if owner in ids for i in face}
    # A preceding, separately bounded skirt-lengthening step can lower the
    # panel hem below the original pleat-layout hem. Seed folds against the
    # actual post-placement geometry while retaining the authored hem in the
    # evidence. The lower limit remains bounded by the source hem and the
    # existing 240 mm maximum extension trial.
    effective_hem = min(mesh["vertices"][i][2] for i in vertices)
    source_hem = float(spec.get("sourceHemZM", declared_hem))
    if source_hem - effective_hem > 0.243:
        raise ValueError("Skirt fold geometry exceeds the bounded extension range")
    hem = effective_hem
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
        if panel_local:
            # Resolve phase inside each canonical sewn panel. The fold field
            # returns to the same recessed boundary value at both side seams,
            # so adjacent panels remain coincident while panel centers rise.
            owners = vertex_piece_owners.get(i, set())
            if not owners:
                raise ValueError(f"Panel-local pleat vertex has no sewn panel owner: {i}")
            waves = []
            for owner in owners:
                low, high = panel_ranges[owner]
                angle = math.atan2(native[0]-origin[0], -(native[1]-origin[1]))
                center = (low+high)/2
                unwrapped_angle = center + math.atan2(math.sin(angle-center), math.cos(angle-center))
                panel_fraction = min(1.0, max(0.0, (unwrapped_angle-low)/(high-low)))
                local_phase = (panel_fraction * spec["foldsPerPanel"]) % 1.0
                waves.append(-math.cos(2.0 * math.pi * local_phase))
            wave = sum(waves)/len(waves)
        elif fold_method == "crease-aligned-smooth-radial-pleat":
            # Crease cuts align with cosine extrema; the smooth field avoids
            # the sharp triangular facets rejected in the prior prototype.
            wave = math.cos(2.0 * math.pi * position)
        elif fold_method == "crease-bound-soft-box-pleat-v1":
            # Each actual bisect plane is a shallow recessed sewn valley;
            # each intervening panel eases into a broad raised center. This
            # replaces the rejected radial cosine field with a piecewise
            # sewn box-pleat hypothesis, not a render-only normal effect.
            half_cell = (position * 2.0) % 1.0
            distance_from_crease = min(half_cell, 1.0 - half_cell)
            valley_width = float(spec.get("foldValleyHalfWidthFraction", math.nan))
            valley_depth_ratio = float(spec.get("foldValleyDepthRatio", math.nan))
            if not (0.05 <= valley_width < 0.45 and 0.0 < valley_depth_ratio <= 1.0):
                raise ValueError("Invalid cut-bound soft box-pleat profile")
            eased = max(0.0, min(1.0,
                (distance_from_crease - valley_width) / (0.5 - valley_width)))
            eased = eased * eased * (3.0 - 2.0 * eased)
            wave = -valley_depth_ratio + (1.0 + valley_depth_ratio) * eased
        elif fold_method == "crease-aligned-alternating-triangular-radial-pleat":
            wave = 1.0 - 4.0*abs(position-0.5)
        else:
            wave = 1-abs(2*position-1)
        displacement = depth*blend*wave
        radius = math.hypot(x-origin[0], y-origin[1])
        if radius <= 1e-9 or radius + displacement <= 1e-9:
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
    return {"applied": True, "configuration": spec,
            "effectiveHeightRangeZM": [effective_hem, waist],
            "extensionBelowDeclaredPleatHemM": max(0.0, declared_hem - effective_hem),
            "selectedVertexCount": len(vertices),
            "movedVertexCount": moved, "maximumRadialDisplacementM": displacement_max,
            "minimumTriangleAreaM2": minimum_area,
            "beforeVerticesSha256": hashlib.sha256(before.encode()).hexdigest(),
            "afterVerticesSha256": hashlib.sha256(json.dumps(mesh["vertices"], separators=(",", ":")).encode()).hexdigest(),
            "canonicalFacesChanged": False, "sewnWaistDisplacementM": 0,
            "panelAngularRangesRadians": {key: value for key, value in sorted(panel_ranges.items())},
            "grantsFitAcceptance": False, "grantsVisualAcceptance": False}


def place_skirt_front_on_thigh_surfaces(mesh, body_objects, pose, target_path):
    """Transfer front apron panels onto measured deform-bone thigh surfaces.

    The neutral skirt envelope is useful for the waist and side silhouette but
    cannot follow thighs raised by the avatar rig. This bounded placement uses
    only target-body triangles carrying the declared thigh deform weights,
    leaving garment topology and panel ownership intact for the later skin
    transfer. It is an attachment hypothesis, not fit or pose acceptance.
    """
    from collections import defaultdict
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    spec = pose.get("poseAwareThighAttachment")
    if spec is None:
        return {"applied": False, "reason": "not-declared"}
    if spec.get("method") != "bilateral-deform-bone-surface-placement-v1":
        raise ValueError("Unknown pose-aware thigh attachment method")
    if digest(target_path) != pose["targetSourceSha256"]:
        raise ValueError("Thigh attachment target source is stale")
    selected = set(spec["pieceIds"])
    if not selected or not selected.issubset(set(mesh["facePieceIds"])):
        raise ValueError("Thigh attachment panel ownership is incomplete")
    fade_start, full_blend = spec["fadeStartZM"], spec["fullBlendZM"]
    clearance = spec["normalClearanceM"]
    projection_limit = spec["maximumProjectionDistanceM"]
    max_blend = spec["maximumBlendWeight"]
    min_bone_weight = spec["minimumTriangleBoneWeight"]
    if (not all(math.isfinite(v) for v in (fade_start, full_blend, clearance,
                                           projection_limit, max_blend, min_bone_weight))
            or full_blend >= fade_start or clearance <= 0 or projection_limit <= 0
            or not 0 < max_blend <= 1 or not 0 < min_bone_weight <= 1):
        raise ValueError("Invalid thigh attachment bounds")
    bodies = [obj for obj in body_objects if obj.type == "MESH"
              and obj.name.startswith(spec["bodyMeshNamePrefix"])]
    if len(bodies) != 1:
        raise ValueError("Thigh attachment requires one explicit target body mesh")
    body = bodies[0]
    shape_values = {key.name: float(key.value) for key in body.data.shape_keys.key_blocks} if body.data.shape_keys else {}
    if any(abs(value) > 1e-8 for value in shape_values.values()):
        raise ValueError("Thigh attachment requires zero-valued target Shape Keys")
    side_specs = {
        "left": spec["leftThighBone"],
        "right": spec["rightThighBone"],
    }
    group_indices = {}
    for side, bone in side_specs.items():
        group = body.vertex_groups.get(bone)
        if group is None:
            raise ValueError(f"Target body lacks declared deform group {bone}")
        group_indices[side] = group.index
    coords = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
    body.data.calc_loop_triangles()
    triangles = [tuple(tri.vertices) for tri in body.data.loop_triangles]
    side_trees = {}
    side_triangle_counts = {}
    for side, group_index in group_indices.items():
        group_weights = []
        for vertex in body.data.vertices:
            group_weights.append(next((item.weight for item in vertex.groups
                                       if item.group == group_index), 0.0))
        eligible = [tri for tri in triangles
                    if sum(group_weights[index] for index in tri) / 3.0 >= min_bone_weight]
        if not eligible:
            raise ValueError(f"No target surface triangles carry {side} thigh weights")
        side_trees[side] = BVHTree.FromPolygons(coords, eligible, all_triangles=True)
        side_triangle_counts[side] = len(eligible)
    bones = [obj for obj in body_objects if obj.type == "ARMATURE"]
    if len(bones) != 1:
        raise ValueError("Thigh attachment requires one target armature")
    left_x = (bones[0].matrix_world @ bones[0].data.bones[side_specs["left"]].head_local).x
    right_x = (bones[0].matrix_world @ bones[0].data.bones[side_specs["right"]].head_local).x
    if abs(left_x - right_x) <= 1e-6:
        raise ValueError("Target thigh frames do not define a bilateral axis")
    center_x = (left_x + right_x) * 0.5
    left_positive = left_x > right_x
    owners = defaultdict(set)
    for face, piece_id in zip(mesh["faces"], mesh["facePieceIds"]):
        for vertex_id in face:
            owners[vertex_id].add(piece_id)
    seam_factors = preserved_seam_factors(mesh, spec)
    before = json.dumps(mesh["vertices"], separators=(",", ":"))
    moved = {"left": 0, "right": 0}
    max_distance = 0.0
    max_displacement = 0.0
    for index, point_values in enumerate(mesh["vertices"]):
        if not owners[index].intersection(selected):
            continue
        point = Vector(point_values)
        if point.z >= fade_start or point.y >= spec["maximumFrontYM"]:
            continue
        factor = max(0.0, min(1.0, (fade_start - point.z) / (fade_start - full_blend)))
        factor = factor * factor * (3.0 - 2.0 * factor)
        factor *= max_blend * seam_factors.get(index, 1.0)
        if factor <= 1e-8:
            continue
        is_left = (point.x >= center_x) == left_positive
        side = "left" if is_left else "right"
        result = side_trees[side].find_nearest(point)
        if result is None or result[0] is None or result[1] is None:
            raise ValueError(f"Thigh surface lookup failed at sewn vertex {index}")
        location, normal, _triangle, distance = result
        if distance > projection_limit or normal.length < .99:
            raise ValueError(f"Thigh projection exceeds declared range at sewn vertex {index}")
        normal = normal.normalized()
        # Orient the offset toward the garment's original exterior, rather than
        # trusting arbitrary triangle winding in the imported avatar mesh.
        if (point - location).dot(normal) < 0:
            normal.negate()
        target = location + normal * clearance
        placed = point.lerp(target, factor)
        displacement = (placed - point).length
        mesh["vertices"][index] = list(placed)
        moved[side] += 1
        max_distance = max(max_distance, distance)
        max_displacement = max(max_displacement, displacement)
    if not sum(moved.values()):
        raise ValueError("Thigh attachment selected no front panel vertices")
    minimum_area = math.inf
    for face in mesh["faces"]:
        a, b, c = [Vector(mesh["vertices"][vertex_id]) for vertex_id in face]
        area = (b - a).cross(c - a).length / 2
        if area <= 1e-12:
            raise ValueError("Thigh attachment collapsed a sewn triangle")
        minimum_area = min(minimum_area, area)
    return {
        "applied": True,
        "method": spec["method"],
        "targetSourceSha256": digest(target_path),
        "targetBodyObject": body.name,
        "targetTriangleCountByThigh": side_triangle_counts,
        "panelIds": sorted(selected),
        "movedVertexCountByThigh": moved,
        "maximumNearestSurfaceDistanceM": max_distance,
        "maximumRestDisplacementM": max_displacement,
        "minimumTriangleAreaM2": minimum_area,
        "beforeVerticesSha256": hashlib.sha256(before.encode()).hexdigest(),
        "afterVerticesSha256": hashlib.sha256(json.dumps(mesh["vertices"], separators=(",", ":")).encode()).hexdigest(),
        "bodyFacesCopied": False,
        "grantsFitAcceptance": False,
        "grantsPoseAcceptance": False,
    }


def weld_subpixel_degenerate_triangles(mesh, *, max_weld_distance_m=1e-5):
    """Remove only sub-pixel, sub-10-micrometre triangular slivers.

    The downstream Blender structure gate rejects triangles whose cross
    product squared is <= 1e-20.  The sewn-pattern audit uses face area and
    previously allowed a smaller sliver through, so this targeted weld keeps
    the authoring and candidate checks aligned without weakening either gate.
    """
    import bmesh
    threshold_squared = 1e-20
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        boundary_before = sum(edge.is_boundary for edge in bm.edges)
        non_manifold_before = sum(not edge.is_manifold for edge in bm.edges)
        welds = []
        for _ in range(32):
            bad_face = next((
                face for face in bm.faces
                if len(face.verts) == 3
                and (face.verts[1].co - face.verts[0].co).cross(
                    face.verts[2].co - face.verts[0].co
                ).length_squared <= threshold_squared
            ), None)
            if bad_face is None:
                break
            pairs = [
                (left, right, (left.co - right.co).length)
                for index, left in enumerate(bad_face.verts)
                for right in list(bad_face.verts)[index + 1:]
            ]
            left, right, distance = min(pairs, key=lambda item: item[2])
            if distance > max_weld_distance_m:
                raise ValueError(
                    "Degenerate triangle needs a weld beyond the 10-micrometre "
                    f"prototype cleanup bound: {distance:.9g} m"
                )
            before_coordinates = [list(vertex.co) for vertex in bad_face.verts]
            bmesh.ops.weld_verts(bm, targetmap={right: left})
            welds.append({
                "maximumInputEdgeDistanceM": distance,
                "triangleCoordinatesM": before_coordinates,
            })
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
        else:
            raise ValueError("Subpixel triangle cleanup exceeded 32 bounded welds")

        boundary_after = sum(edge.is_boundary for edge in bm.edges)
        non_manifold_after = sum(not edge.is_manifold for edge in bm.edges)
        if non_manifold_after > non_manifold_before:
            raise ValueError("Subpixel triangle cleanup introduced non-manifold edges")
        bm.to_mesh(mesh)
        mesh.update(calc_edges=True)
        mesh.calc_loop_triangles()
        remaining = []
        for triangle in mesh.loop_triangles:
            a, b, c = (mesh.vertices[index].co for index in triangle.vertices)
            if (b - a).cross(c - a).length_squared <= threshold_squared:
                remaining.append(list(triangle.vertices))
        if remaining:
            raise ValueError(
                "Subpixel triangle cleanup left candidate-gate degenerates: "
                + json.dumps(remaining[:8])
            )
        return {
            "method": "weld-closest-vertex-pair-on-subpixel-triangle",
            "candidateDegenerateCrossProductSquaredThreshold": threshold_squared,
            "maximumWeldDistanceM": max_weld_distance_m,
            "weldCount": len(welds),
            "welds": welds,
            "boundaryEdgesBefore": boundary_before,
            "boundaryEdgesAfter": boundary_after,
            "nonManifoldEdgesBefore": non_manifold_before,
            "nonManifoldEdgesAfter": non_manifold_after,
            "remainingDegenerateTriangles": len(remaining),
            "grantsFitAcceptance": False,
            "grantsAppearanceAcceptance": False,
            "evidenceBoundary": (
                "Local topology cleanup bounded to edges no longer than 10 micrometres; "
                "does not establish fit, motion, UV, appearance, or release acceptance."
            ),
        }
    finally:
        bm.free()


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
    shorts_extension_evidence = lengthen_declared_shorts(mesh, pose)
    shorts_pose = dict(pose, upperSurfacePlacement=pose.get("shortsUpperSurfacePlacement"))
    shorts_surface_evidence = place_on_measured_upper_surface(mesh, body_objects, shorts_pose, resolve(job["targetSourcePath"]))
    trace_stage("shorts-surface")
    native_angular_vertices = [list(point) for point in mesh["vertices"]]
    skirt_lengthening_evidence = lengthen_declared_skirt_panels(mesh, pose)
    skirt_envelope_evidence = {"applied": False}
    if "skirtEnvelopePlacement" in pose:
        skirt_pose = dict(pose, bodyContourPlacement=pose["skirtEnvelopePlacement"])
        skirt_envelope_evidence = place_on_measured_contours(mesh, body_objects, skirt_pose, resolve(job["targetSourcePath"]))
    waistband_evidence = {"applied": False}
    if "waistbandContourPlacement" in pose:
        waistband_pose = dict(pose, bodyContourPlacement=pose["waistbandContourPlacement"])
        waistband_evidence = place_on_measured_contours(mesh, body_objects, waistband_pose, resolve(job["targetSourcePath"]), angular_source_vertices=native_angular_vertices)
    fold_evidence = place_declared_skirt_folds(mesh, pose, native_angular_vertices)
    thigh_attachment_evidence = place_skirt_front_on_thigh_surfaces(
        mesh, body_objects, pose, resolve(job["targetSourcePath"])
    )
    recipe = read(resolve(pipeline["materialRecipePath"]))
    rear_waist_tab_evidence = append_declared_rear_waist_tab(
        mesh, body_objects, pose, recipe, resolve(job["targetSourcePath"])
    )
    data = bpy.data.meshes.new(job["id"] + "-sewn-surface")
    data.from_pydata(mesh["vertices"], [], mesh["faces"])
    data.update()
    # Keep piping bindings stable if the bounded microdegenerate cleanup welds
    # vertices and Blender compacts the resulting point table. Bindings name
    # indices in the canonical sewn mesh, so the correspondence must travel
    # with each surviving point through cleanup and cloth component splitting.
    sewn_vertex_ids = data.attributes.new(
        "canonical_sewn_vertex_index", "INT", "POINT"
    )
    for item, source_id in zip(sewn_vertex_ids.data, range(len(mesh["vertices"]))):
        item.value = source_id
    uv_evidence = assign_authored_panel_uvs(data, mesh)
    owners = mesh["facePieceIds"]
    pieces = sorted(set(owners))
    if len(owners) != len(data.polygons):
        raise ValueError("Sewn face ownership is incomplete")
    ownership = data.attributes.new("canonical_piece_index", "INT", "FACE")
    for face, owner in zip(ownership.data, owners):
        face.value = pieces.index(owner)
    # The sleeves and the sewn overskirt are continuous cloth surfaces.
    # Smooth shading complements the explicit crease and longitudinal cuts;
    # those cuts remain real mesh topology, not a normal-map substitute.
    smooth_surface_pieces = {
        "jacket-sleeve-left", "jacket-sleeve-right",
        "overskirt-front-left", "overskirt-front-right",
        "overskirt-front-lap-left", "overskirt-front-lap-right",
        "overskirt-back-left", "overskirt-back-right",
    }
    for polygon, owner in zip(data.polygons, owners):
        polygon.use_smooth = owner in smooth_surface_pieces
    garment = bpy.data.objects.new(job["id"], data)
    bpy.context.collection.objects.link(garment)
    garment["prototypeRole"] = "unfitted-unweighted-sewn-pattern"
    garment["sewnMeshSha256"] = digest(mesh_path)
    garment["sourcePatternSha256"] = expected["patternSha256"]
    garment["canonicalPieceIds"] = json.dumps(pieces)
    bpy.ops.object.select_all(action="DESELECT")
    garment.select_set(True)
    bpy.context.view_layer.objects.active = garment
    garment["uvStatus"] = uv_evidence["status"]
    garment["uvProvenance"] = json.dumps(uv_evidence, sort_keys=True)
    spec = recipe["prototypeMaterial"]
    material = bpy.data.materials.new(spec["name"])
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*spec["baseColorLinearRgb"], 1)
    shader.inputs["Roughness"].default_value = spec["roughness"]
    material["evidenceBoundary"] = recipe["evidenceBoundary"]
    garment.data.materials.append(material)
    tab_material_indices = {"prototypeMaterial": 0}
    if rear_waist_tab_evidence.get("applied"):
        tab_material_spec = recipe["prototypeRearWaistTabMaterials"]
        for material_id, key in (("rearWaistTabMaterial", "tab"), ("rearWaistBuckleMaterial", "buckle")):
            entry = tab_material_spec[key]
            tab_material = bpy.data.materials.new(entry["name"])
            tab_material.use_nodes = True
            tab_shader = tab_material.node_tree.nodes.get("Principled BSDF")
            tab_shader.inputs["Base Color"].default_value = (*entry["baseColorLinearRgb"], 1)
            tab_shader.inputs["Roughness"].default_value = entry["roughness"]
            tab_shader.inputs["Metallic"].default_value = entry["metallic"]
            tab_material["evidenceBoundary"] = entry["evidenceBoundary"]
            garment.data.materials.append(tab_material)
            tab_material_indices[material_id] = len(garment.data.materials) - 1
        if len(mesh["faceMaterialIds"]) != len(garment.data.polygons):
            raise ValueError("Sewn face material ownership is incomplete")
        for polygon, material_id in zip(garment.data.polygons, mesh["faceMaterialIds"]):
            if material_id not in tab_material_indices:
                raise ValueError(f"Unknown prototype face material owner: {material_id}")
            polygon.material_index = tab_material_indices[material_id]
    microdegenerate_cleanup = weld_subpixel_degenerate_triangles(garment.data)
    sewn_vertex_ids = garment.data.attributes.get("canonical_sewn_vertex_index")
    if sewn_vertex_ids is None or len(sewn_vertex_ids.data) != len(garment.data.vertices):
        raise ValueError("Microdegenerate cleanup lost canonical sewn vertex provenance")
    if any(not 0 <= item.value < len(mesh["vertices"]) for item in sewn_vertex_ids.data):
        raise ValueError("Microdegenerate cleanup produced an invalid sewn vertex source id")
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
        "poseAwareThighAttachment": thigh_attachment_evidence,
        "declaredSkirtLengthening": skirt_lengthening_evidence,
        "declaredSkirtCreaseTopology": crease_evidence,
        "buildDisposition": "EDITABLE_SEWN_PROTOTYPE_ONLY",
        "authoredPatternUvEvidence": uv_evidence,
        "prototypeEdgeTrim": prototype_edge_trim,
        "prototypeSurfaceMotifs": prototype_surface_motifs,
        "shortsCoverageExtension": shorts_extension_evidence,
        "rearWaistAdjustmentTab": rear_waist_tab_evidence,
        "sourceBlendSha256": digest(source), "sewnMeshSha256": digest(mesh_path),
        "microdegenerateTriangleCleanup": microdegenerate_cleanup,
        "canonicalInputs": expected,
        "measuredContourPlacement": contour_evidence,
        "measuredUpperSurfacePlacement": upper_surface_evidence,
        "measuredShortsUpperSurfacePlacement": shorts_surface_evidence,
        "measuredSkirtEnvelopePlacement": skirt_envelope_evidence,
        "measuredCollarPlacement": collar_evidence,
        "necklinePlacementTrace": {"coordinateSystem": "blender-z-up", "selection": {"nativeMinimumZM": .98, "nativeMaximumAbsXM": .12}, "records": list(neck_trace.values()), "evidenceBoundary": "Original sewn vertex IDs/face ownership and per-stage coordinates; diagnostic only, not fit or appearance acceptance."},
        "metrics": {"vertices": len(data.vertices), "triangles": len(data.polygons),
                    "unweightedVertices": len(data.vertices),
                    "degenerateTriangles": microdegenerate_cleanup["remainingDegenerateTriangles"]},
        "surfaceShadingHypothesis": {
            "components": sorted(smooth_surface_pieces),
            "method": "smooth-per-polygon normals on canonical sleeve faces",
            "reason": "Direct inspection showed strong triangle faceting on the coarse sleeve prototype.",
            "grantsAppearanceAcceptance": False,
            "grantsFitAcceptance": False,
        },
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
