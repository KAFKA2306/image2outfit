from __future__ import annotations

bl_info = {
    "name": "Image2Outfit OpenAI Assistant",
    "author": "KAFKA2306/image2outfit",
    "version": (0, 1, 0),
    "blender": (4, 4, 0),
    "location": "View3D > Sidebar > Image2Outfit",
    "description": "Thin Blender UI for running the image2outfit Codex agent workflow",
    "category": "Interface",
}

import queue
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Panel


_RESULT_QUEUE: queue.Queue[tuple[str, str]] = queue.Queue()
_RUNNING = False
_TIMER_REGISTERED = False
_TEXT_BLOCK_NAME = "Image2Outfit Assistant"


def _repo_root() -> Path | None:
    candidates: list[Path] = []
    blend_path = bpy.data.filepath
    if blend_path:
        candidates.append(Path(blend_path).resolve().parent)
    candidates.append(Path.cwd().resolve())

    for start in candidates:
        for candidate in (start, *start.parents):
            if (candidate / "AGENTS.md").is_file() and (
                candidate / "config" / "genworks-handoff-policy.json"
            ).is_file():
                return candidate
    return None


def _blender_mcp_listening(host: str = "127.0.0.1", port: int = 9876) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.15):
            return True
    except OSError:
        return False


def _connection_status() -> tuple[bool, str]:
    if not shutil.which("codex"):
        return False, "Codex not found on PATH"
    if not _blender_mcp_listening():
        return False, "Blender MCP localhost:9876 is not listening"
    if _repo_root() is None:
        return False, "image2outfit repository root not found"
    return True, "Connected"


def _write_result(status: str, content: str) -> None:
    scene = bpy.context.scene
    scene.image2outfit_assistant_status = status
    scene.image2outfit_assistant_preview = content[:500]

    text = bpy.data.texts.get(_TEXT_BLOCK_NAME)
    if text is None:
        text = bpy.data.texts.new(_TEXT_BLOCK_NAME)
    else:
        text.clear()
    text.write(content)


def _poll_results() -> float | None:
    global _RUNNING, _TIMER_REGISTERED

    try:
        status, content = _RESULT_QUEUE.get_nowait()
    except queue.Empty:
        if _RUNNING:
            return 0.25
        _TIMER_REGISTERED = False
        return None

    _RUNNING = False
    _write_result(status, content)
    _TIMER_REGISTERED = False
    return None


def _run_codex(repo_root: Path, blend_path: str, prompt: str) -> None:
    contract_prompt = f"""You are operating the KAFKA2306/image2outfit repository from Blender.
Before mutating anything, read AGENTS.md and the relevant product job, construction contract, ProductManifest.json, and last-good checkpoint.
Use configured MCP tools only when necessary. Preserve the canonical GenWorks layout and existing evidence contracts.
Do not treat MCP success, Unity import, NDMF, Modular Avatar, or VRChat runtime as a repository COMPLETE gate unless the canonical policy explicitly says so.
Do not bypass approvals or claim a tool ran when it did not.
Current Blender file: {blend_path or '(unsaved)'}

User request:
{prompt}
"""

    try:
        completed = subprocess.run(
            ["codex", "exec", contract_prompt],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
            check=False,
        )
        output = (completed.stdout or "").strip()
        error = (completed.stderr or "").strip()
        if completed.returncode == 0:
            content = output or "Codex completed without textual output."
            _RESULT_QUEUE.put(("Completed", content))
        else:
            content = "\n".join(
                part
                for part in (
                    f"Codex exited with code {completed.returncode}.",
                    output,
                    error,
                )
                if part
            )
            _RESULT_QUEUE.put(("Failed", content))
    except subprocess.TimeoutExpired:
        _RESULT_QUEUE.put(("Failed", "Codex execution exceeded the 1800 second local safety timeout."))
    except Exception as exc:  # noqa: BLE001 - surface local operator failures to Blender UI.
        _RESULT_QUEUE.put(("Failed", f"Failed to launch Codex: {exc}"))


class IMAGE2OUTFIT_OT_ask_codex(Operator):
    bl_idname = "image2outfit.ask_codex"
    bl_label = "Ask OpenAI / Codex"
    bl_description = "Run Codex from the image2outfit repository root with local MCP tools"

    def execute(self, context):
        global _RUNNING, _TIMER_REGISTERED

        if _RUNNING:
            self.report({"WARNING"}, "An Image2Outfit Codex request is already running.")
            return {"CANCELLED"}

        prompt = context.scene.image2outfit_assistant_prompt.strip()
        if not prompt:
            self.report({"ERROR"}, "Enter a prompt first.")
            return {"CANCELLED"}

        connected, reason = _connection_status()
        if not connected:
            self.report({"ERROR"}, reason)
            context.scene.image2outfit_assistant_status = reason
            return {"CANCELLED"}

        repo_root = _repo_root()
        if repo_root is None:
            self.report({"ERROR"}, "image2outfit repository root not found.")
            return {"CANCELLED"}

        blend_path = bpy.data.filepath
        _RUNNING = True
        context.scene.image2outfit_assistant_status = "Running"
        context.scene.image2outfit_assistant_preview = ""

        worker = threading.Thread(
            target=_run_codex,
            args=(repo_root, blend_path, prompt),
            daemon=True,
            name="image2outfit-codex",
        )
        worker.start()

        if not _TIMER_REGISTERED:
            _TIMER_REGISTERED = True
            bpy.app.timers.register(_poll_results, first_interval=0.25)

        return {"FINISHED"}


class IMAGE2OUTFIT_PT_assistant(Panel):
    bl_label = "OpenAI Assistant"
    bl_idname = "IMAGE2OUTFIT_PT_assistant"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Image2Outfit"

    def draw(self, context):
        layout = self.layout
        connected, reason = _connection_status()

        layout.label(text=f"Status: {'Connected' if connected else reason}")
        layout.prop(context.scene, "image2outfit_assistant_prompt", text="Prompt")

        run_row = layout.row()
        run_row.enabled = connected and not _RUNNING
        run_row.operator("image2outfit.ask_codex", text="Ask OpenAI / Codex")

        last_status = context.scene.image2outfit_assistant_status
        if last_status:
            layout.separator()
            layout.label(text=f"Last run: {last_status}")

        preview = context.scene.image2outfit_assistant_preview
        if preview:
            box = layout.box()
            for line in preview.splitlines()[:6]:
                box.label(text=line[:100])
            box.label(text=f"Full result: Text Editor > {_TEXT_BLOCK_NAME}")


_CLASSES = (
    IMAGE2OUTFIT_OT_ask_codex,
    IMAGE2OUTFIT_PT_assistant,
)


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.image2outfit_assistant_prompt = StringProperty(
        name="Prompt",
        description="Instruction sent to Codex from the image2outfit repository root",
        default="",
    )
    bpy.types.Scene.image2outfit_assistant_status = StringProperty(default="")
    bpy.types.Scene.image2outfit_assistant_preview = StringProperty(default="")


def unregister() -> None:
    for attribute in (
        "image2outfit_assistant_prompt",
        "image2outfit_assistant_status",
        "image2outfit_assistant_preview",
    ):
        if hasattr(bpy.types.Scene, attribute):
            delattr(bpy.types.Scene, attribute)

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
