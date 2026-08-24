#!/usr/bin/env python3
"""Shared Blender render-quality floor for canonical image2outfit flows."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "config" / "pipeline" / "visual-quality-defaults.v1.json"
_GUARD_MARKER = "_image2outfit_visual_quality_guard"
_OPT_OUT_KEY = "image2outfit_visual_quality_opt_out"


def _number(value: object, label: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    number = float(value)
    if number < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return number


def load_profile(path: Path = DEFAULT_PROFILE) -> dict[str, Any]:
    """Load and validate the versioned shared visual-quality profile."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ValueError("visual-quality profile schemaVersion must be 1")
    if not isinstance(value.get("profileId"), str) or not value["profileId"]:
        raise ValueError("visual-quality profileId is required")
    render = value.get("render")
    if not isinstance(render, dict) or render.get("engine") not in {
        "CYCLES",
        "BLENDER_EEVEE_NEXT",
    }:
        raise ValueError("visual-quality render settings are invalid")
    _number(render.get("minimumLongEdge"), "render.minimumLongEdge", 1)
    _number(render.get("samples"), "render.samples", 1)
    _number(render.get("adaptiveThreshold"), "render.adaptiveThreshold", 0.000001)
    for key in ("denoising", "adaptiveSampling", "filmTransparent"):
        if not isinstance(render.get(key), bool):
            raise ValueError(f"render.{key} must be boolean")
    color = value.get("colorManagement")
    if not isinstance(color, dict) or not all(
        isinstance(color.get(key), str) and color[key]
        for key in ("viewTransform", "look")
    ):
        raise ValueError("visual-quality colorManagement settings are invalid")
    studio = value.get("fallbackStudio")
    if not isinstance(studio, dict) or not isinstance(studio.get("lights"), list):
        raise ValueError("visual-quality fallbackStudio settings are required")
    return value


def _opted_out(scene: object) -> bool:
    getter = getattr(scene, "get", None)
    return bool(getter(_OPT_OUT_KEY, False)) if callable(getter) else False


def _raise_resolution(render: object, minimum: int) -> None:
    width = max(1, int(render.resolution_x))
    height = max(1, int(render.resolution_y))
    longest = max(width, height)
    if longest < minimum:
        scale = minimum / longest
        render.resolution_x = max(1, round(width * scale))
        render.resolution_y = max(1, round(height * scale))
    render.resolution_percentage = 100


def apply_scene_defaults(
    scene: object,
    profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Upgrade weak settings without lowering deliberate higher-quality settings."""
    if _opted_out(scene):
        return {"applied": False, "reason": "scene-opt-out"}
    settings = dict(profile or load_profile())
    quality = settings["render"]
    render = scene.render
    render.engine = str(quality["engine"])
    _raise_resolution(render, int(quality["minimumLongEdge"]))
    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGBA"
    render.image_settings.color_depth = "8"
    render.film_transparent = bool(quality["filmTransparent"])

    cycles = getattr(scene, "cycles", None)
    if cycles is not None and render.engine == "CYCLES":
        cycles.samples = max(int(cycles.samples), int(quality["samples"]))
        cycles.use_denoising = bool(quality["denoising"])
        cycles.use_adaptive_sampling = bool(quality["adaptiveSampling"])
        current = float(cycles.adaptive_threshold or 0.0)
        target = float(quality["adaptiveThreshold"])
        cycles.adaptive_threshold = min(current, target) if current > 0 else target

    scene.view_settings.view_transform = str(settings["colorManagement"]["viewTransform"])
    scene.view_settings.look = str(settings["colorManagement"]["look"])
    return {
        "applied": True,
        "profileId": settings["profileId"],
        "engine": render.engine,
        "resolution": [int(render.resolution_x), int(render.resolution_y)],
    }


def ensure_fallback_studio(
    scene: object,
    profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Add neutral world/lights only when the delegated scene provides none."""
    if _opted_out(scene):
        return {"applied": False, "reason": "scene-opt-out"}
    import bpy
    from mathutils import Vector

    studio = dict(profile or load_profile())["fallbackStudio"]
    world_created = False
    if scene.world is None:
        world = bpy.data.worlds.new("Image2Outfit_Quality_World")
        world.use_nodes = True
        background = world.node_tree.nodes.get("Background")
        if background is not None:
            background.inputs["Color"].default_value = (*studio["world"]["color"], 1.0)
            background.inputs["Strength"].default_value = float(studio["world"]["strength"])
        scene.world = world
        world_created = True

    lights_created = 0
    if not any(getattr(obj, "type", None) == "LIGHT" for obj in scene.objects):
        target = Vector(studio["target"])
        for spec in studio["lights"]:
            name = f"Image2Outfit_Quality_{spec['name']}"
            data = bpy.data.lights.new(name, type="AREA")
            data.energy = float(spec["energy"])
            data.color = tuple(spec["color"])
            data.shape = "DISK"
            data.size = float(spec["size"])
            obj = bpy.data.objects.new(name, data)
            scene.collection.objects.link(obj)
            obj.location = spec["location"]
            obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()
            lights_created += 1
    return {
        "applied": world_created or lights_created > 0,
        "worldCreated": world_created,
        "lightsCreated": lights_created,
    }


def install_render_quality_guard(profile_path: Path = DEFAULT_PROFILE) -> dict[str, Any]:
    """Install an idempotent persistent pre-render guard when running in Blender."""
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
