"""Compatibility entry point for the pinned Blender Python environment.

The implementation is retained in ``blender_python_env_core``.  This module
patches only the runtime probe expression, whose previous string contained an
extra closing brace and failed before any Blender product generation started.
"""
from __future__ import annotations

try:
    from . import blender_python_env_core as _core
except ImportError:  # Direct execution/import from the tools directory.
    import blender_python_env_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)


def probe_runtime(blender: str) -> dict[str, str]:
    expression = (
        "import bpy,json,platform,sys;"
        f"print('{_core.PROBE_MARKER}'+json.dumps({{"
        "'blenderVersion':bpy.app.version_string.split()[0],"
        "'pythonVersion':platform.python_version(),"
        "'pythonPrefix':sys.prefix}))"
    )
    output = _core._run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python-expr",
            expression,
        ]
    )
    return _core._marked_json(output, _core.PROBE_MARKER)


_core.probe_runtime = probe_runtime
prepare = _core.prepare
