#!/usr/bin/env python3
"""Hosted-only Cyber Kawaii entry point using the already opened seed scene.

``build_product_from_seed_blend.py`` opens the tracked Siroino seed before
executing this module. Re-importing an FBX copy changed the effective coordinate
space and caused torso surface predicates to select no faces. This wrapper keeps
the verified body and armature from the seed scene, removes every other seed
object, and delegates the complete product build while suppressing only the
redundant clean/import operations.
"""
from __future__ import annotations

from types import SimpleNamespace

import bpy

import siroino_cyber_kawaii_large_build as product


body, armature = product.g.select_body_and_armature()
for obj in list(bpy.data.objects):
    if obj not in {body, armature}:
        bpy.data.objects.remove(obj, do_unlink=True)


class _ImportSceneProxy:
    def fbx(self, **_kwargs):
        return {"FINISHED"}

    def __getattr__(self, name):
        return getattr(bpy.ops.import_scene, name)


class _OpsProxy:
    import_scene = _ImportSceneProxy()

    def __getattr__(self, name):
        return getattr(bpy.ops, name)


class _BpyProxy:
    ops = _OpsProxy()

    def __getattr__(self, name):
        return getattr(bpy, name)


product.base.clean_scene = lambda: None
product.bpy = _BpyProxy()


if __name__ == "__main__":
    raise SystemExit(product.main())
