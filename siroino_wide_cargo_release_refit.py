"""Blender entry-point compatibility shim for Siroino Wide Cargo generators.

Blender executes scripts without automatically adding the script directory to
``sys.path``. Keep the implementation under ``tools`` while exposing the module
from the repository root, which is the hosted build working directory.
"""
from tools.siroino_wide_cargo_release_refit import *  # noqa: F401,F403
