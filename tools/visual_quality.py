#!/usr/bin/env python3
"""Canonical Blender render-quality floor for image2outfit product tooling.

The module is importable without Blender so its profile and pure scene-setting
logic remain unit-testable. Blender-specific fallback studio setup is imported
lazily when the canonical launchers install the render guard.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "config" / "visual-quality-defaults.v1.json"
_GUARD_MARKER = "_image2outfit_visual_quality_guard"
_OPT_OUT_KEY = "image2outfit_visual_quality_opt_out"


def _require_number(value: object, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    number = float(value)
    if number < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return number


def load_profile(path: Path = DEFAULT_PROFILE) -> dict[str, Any]:
    """Load and validate the canonical visual-quality profile."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("visual-quality profile must contain a JSON object")
    if value.get("schemaVersion") != 1:
        raise ValueError("visual-quality profile schemaVersion must be 1")
    if not isinstance(value.get("profileId"), str) or not value["profileId"]:
        raise ValueError("visual-quality profileId is required")

    render = value.get("render")
    if not isinstance(render, dict):
        raise ValueError("visual-quality render settings are required")
    if render.get("engine") not in {"CYCLES", "BLENDER_EEVEE_NEXT"}:
        raise ValueError("visual-quality render.engine is unsupported")
    _require_number(render.get("minimumLongEdge"), "render.minimumLongEdge", minimum=1)
    _require_number(render.get("samples"), "render.samples", minimum=1)
    _require_number(
        render.get("adaptiveThreshold"),
        "render.adaptiveThreshold",
        minimum=0.000001,
    )
    if not isinstance(render.get("denoising"), bool):
        raise ValueError("render.denoising must be boolean")
    if not isinstance(render.get("adaptiveSampling"), bool):
        raise ValueError("render.adaptiveSampling must be boolean")
    if not isinstance(render.get("filmTransparent"), bool):
        raise ValueError("render.filmTransparent must be boolean")

    color = value.get("colorManagement")
    if not isinstance(color, dict):
        raise ValueError("visual-quality colorManagement settings are required")
    for key in ("viewTransform", "look"):
        if not isinstance(color.get(key), str) or not color[key]:
            raise ValueError(f"colorManagement.{key} is required")

    studio = value.get("fallbackStudio")
    if not isinstance(studio, dict):
        raise ValueError("visual-quality fallbackStudio settings are required")
    world = studio.get("world")
    if not isinstance(world, dict):
        raise ValueError("fallbackStudio.world is required")
    color_value = world.get("color")
    if (
        not isinstance(color_value, list)
        or len(color_value) != 3
        or any(
            isinstance(channel, bool) or not isinstance(channel, (int, float))
            for channel in color_value
        )
    ):
        raise ValueError("fallbackStudio.world.color must contain three numbers")
    _require_number(world.get("strength"), "fallbackStudio.world.strength")

    lights = studio.get("lights")
    if not isinstance(lights, list) or not lights:
        raise ValueError("fallbackStudio.lights must be a non-empty list")
    for index, light in enumerate(lights):
        if not isinstance(light, dict):
            raise ValueError(f"fallbackStudio.lights[{index}] must be an object")
        if not isinstance(light.get("name"), str) or not light["name"]:
            raise ValueError(f"fallbackStudio.lights[{index}].name is required")
        for key in ("location", "color"):
            vector = light.get(key)
            if (
                not isinstance(vector, list)
                or len(vector) != 3
                or any(
                    isinstance(component, bool)
                    or not isinstance(component, (int, float))
                    for component in vector
                )
            ):
                raise ValueError(
                    f"fallbackStudio.lights[{index}].{key} must contain three numbers"
                )
        _require_number(light.get("energy"), f"fallbackStudio.lights[{index}].energy")
        _require_number(light.get("size"), f"fallbackStudio.lights[{index}].size")
    return value


def _scene_opted_out(scene: object) -> bool:
    getter = getattr(scene, "get", None)
    return bool(getter(_OPT_OUT_KEY, False)) if callable(getter) else False


def _scale_resolution_to_long_edge(render_settings: object, minimum: int) -> None:
    width = max(1, int(getattr(render_settings, "resolution_x")))
    height = max(1, int(getattr(render_settings, "resolution_y")))
    longest = max(width, height)
    if longest < minimum:
        scale = minimum / longest
        width = max(1, round(width * scale))
        height = max(1, round(height * scale))
        render_settings.resolution_x = width
        render_settings.resolution_y = height
    render_settings.resolution_percentage = 100


def apply_scene_defaults(
    scene: object,
    profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a quality floor without lowering deliberate higher-quality settings."""
    settings = dict(profile or load_profile())
    if _scene_opted_out(scene):
        return {"applied": False, "reason": "scene-opt-out"}

    render_profile = settings["render"]
    render_settings = scene.render
    render_settings.engine = str(render_profile["engine"])
    _scale_resolution_to_long_edge(
        render_settings,
        int(render_profile["minimumLongEdge"]),
    )
    render_settings.image_settings.file_format = "PNG"
    render_settings.image_settings.color_mode = "RGBA"
    render_settings.image_settings.color_depth = "8"
    render_settings.film_transparent = bool(render_profile["filmTransparent"])

    cycles = getattr(scene, "cycles", None)
    if cycles is not None and render_settings.engine == "CYCLES":
        cycles.samples = max(int(getattr(cycles, "samples", 0)), int(render_profile["samples"]))
        cycles.use_denoising = bool(render_profile["denoising"])
        cycles.use_adaptive_sampling = bool(render_profile["adaptiveSampling"])
        current_threshold = float(getattr(cycles, "adaptive_threshold", 0.0) or 0.0)
        target_threshold = float(render_profile["adaptiveThreshold"])
        cycles.adaptive_threshold = (
            min(current_threshold, target_threshold)
            if current_threshold > 0.0
            else target_threshold
        )

    view_settings = scene.view_settings
    view_settings.view_transform = str(settings["colorManagement"]["viewTransform"])
    view_settings.look = str(settings["colorManagement"]["look"])
    return {
        "applied": True,
        "profileId": settings["profileId"],
        "engine": render_settings.engine,
        "resolution": [
            int(render_settings.resolution_x),
            int(render_settings.resolution_y),
        ],
    }


def ensure_fallback_studio(
    scene: object,
    profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create neutral world/lights only when the delegated tool provides none."""
    if _scene_opted_out(scene):
        return {"applied": False, "reason": "scene-opt-out"}

    import bpy
    from mathutils import Vector

    settings = dict(profile or load_profile())
    studio = settings["fallbackStudio"]
    world_created = False
    if scene.world is None:
        world = bpy.data.worlds.new("Image2Outfit_Quality_World")
        scene.world = world
        world.use_nodes = True
        background = world.node_tree.nodes.get("Background")
        if background is not None:
            color = studio["world"]["color"]
            background.inputs["Color"].default_value = (*color, 1.0)
            background.inputs["Strength"].default_value = float(
                studio["world"]["strength"]
            )
        world_created = True

    existing_lights = [obj for obj in scene.objects if getattr(obj, "type", None) == "LIGHT"]
    lights_created = 0
    if not existing_lights:
        target = Vector(tuple(float(value) for value in studio["target"]))
        for light_spec in studio["lights"]:
            name = f"Image2Outfit_Quality_{light_spec['name']}"
            data = bpy.data.lights.new(name, type="AREA")
            data.energy = float(light_spec["energy"])
            data.color = tuple(float(value) for value in light_spec["color"])
            data.shape = "DISK"
            data.size = float(light_spec["size"])
            obj = bpy.data.objects.new(name, data)
            bpy.context.collection.objects.link(obj)
            obj.location = tuple(float(value) for value in light_spec["location"])
            obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()
            lights_created += 1

    return {
        "applied": world_created or lights_created > 0,
        "worldCreated": world_created,
        "lightsCreated": lights_created,
    }


def install_render_quality_guard(
    profile_path: Path = DEFAULT_PROFILE,
) -> dict[str, Any]:
    """Install an idempotent persistent pre-render quality guard in Blender."""
    try:
        import bpy
        from bpy.app.handlers import persistent
    except ImportError:
        return {"installed": False, "reason": "blender-unavailable"}

    profile = load_profile(profile_path)

    @persistent
    def render_quality_guard(scene, _depsgraph=None) -> None:
        apply_scene_defaults(scene, profile)
        ensure_fallback_studio(scene, profile)

    setattr(render_quality_guard, _GUARD_MARKER, True)
    handlers = bpy.app.handlers.render_pre
    if not any(getattr(handler, _GUARD_MARKER, False) for handler in handlers):
        handlers.append(render_quality_guard)

    apply_scene_defaults(bpy.context.scene, profile)
    return {
        "profileId": profile["profileId"],
        "installed": True,
        "handlerCount": sum(
            1 for handler in handlers if getattr(handler, _GUARD_MARKER, False)
        ),
    }
