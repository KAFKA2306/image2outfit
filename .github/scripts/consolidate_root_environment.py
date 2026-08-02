from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old[:120]!r}")
    file.write_text(text.replace(old, new), encoding="utf-8")


(ROOT / "pyproject.toml").write_text(
    """[project]
name = "image2outfit"
version = "0.1.0"
requires-python = "==3.11.*"
dependencies = [
  "Pillow==12.3.0",
]

[dependency-groups]
dev = [
  "ruff",
]
snapshot = [
  "matplotlib",
  "numpy",
  "scipy",
  "trimesh",
]
""",
    encoding="utf-8",
)

toolchain_path = ROOT / "config" / "toolchain-lock.json"
toolchain = json.loads(toolchain_path.read_text(encoding="utf-8"))
python_lock = toolchain["blender"]["python"]
python_lock.pop("requirements", None)
python_lock["dependencyGroup"] = "project"
toolchain_path.write_text(
    json.dumps(toolchain, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

release_path = ROOT / "config" / "release-policy.json"
release = json.loads(release_path.read_text(encoding="utf-8"))
release["humanEvidenceContracts"] = {
    "visual-review": {
        "requiredFields": [
            "schemaVersion",
            "jobId",
            "adapterId",
            "candidateManifestSha256",
            "reviewer",
            "checkedAt",
            "decision",
            "visualScores",
            "reviewedAssets",
            "visualNotes",
        ],
        "decisionValues": ["APPROVE", "REJECT"],
        "scoreFields": ["silhouette", "fit", "material", "presentation"],
        "minimumScore": release["minimumVisualScore"],
    },
    "pose-penetration-review": {
        "requiredFields": [
            "schemaVersion",
            "jobId",
            "adapterId",
            "candidateManifestSha256",
            "reviewer",
            "checkedAt",
            "decision",
            "poses",
            "reviewedAssets",
            "poseNotes",
        ],
        "decisionValues": ["APPROVE", "REJECT"],
        "requiredPoses": release["requiredPoses"],
        "passValue": "PASS",
    },
    "vrchat-runtime-review": {
        "requiredFields": [
            "schemaVersion",
            "jobId",
            "adapterId",
            "candidateManifestSha256",
            "reviewer",
            "checkedAt",
            "decision",
            "vrchatBuildAndTest",
            "testedInVRChat",
            "reviewedAssets",
            "runtimeScreenshot",
            "runtimeNotes",
        ],
        "decisionValues": ["APPROVE", "REJECT"],
        "passValue": "PASS",
        "testedInVRChat": True,
    },
}
release_path.write_text(
    json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

replace(
    "tools/release_gate.py",
    '        "blenderPythonRequirements": ROOT / "config" / "blender-python-requirements.txt",\n',
    '        "pythonProject": ROOT / "pyproject.toml",\n',
)

replace("tools/blender_python_env.py", "import subprocess\n", "import subprocess\nimport tomllib\n")
replace(
    "tools/blender_python_env.py",
    "\ndef _expected_packages(lock: dict[str, Any]) -> dict[str, dict[str, str]]:\n",
    """
def _project_dependencies(root: Path, group: str) -> list[str]:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise FileNotFoundError(f"Python project configuration missing: {pyproject}")
    with pyproject.open("rb") as stream:
        configuration = tomllib.load(stream)
    project = configuration.get("project", {})
    if group == "project":
        requirements = project.get("dependencies", [])
    else:
        requirements = project.get("optional-dependencies", {}).get(group)
    if not isinstance(requirements, list) or not requirements:
        raise ValueError(f"pyproject dependency group is empty or missing: {group}")
    if not all(isinstance(value, str) and value for value in requirements):
        raise ValueError(f"pyproject dependency group contains invalid entries: {group}")
    return requirements


def _expected_packages(lock: dict[str, Any]) -> dict[str, dict[str, str]]:
""",
)
replace(
    "tools/blender_python_env.py",
    '    requirements = root / str(python_lock.get("requirements", ""))\n',
    '    dependency_group = str(python_lock.get("dependencyGroup", ""))\n    requirements = _project_dependencies(root, dependency_group)\n',
)
replace(
    "tools/blender_python_env.py",
    '    if not requirements.is_file():\n        raise FileNotFoundError(f"Blender Python requirements missing: {requirements}")\n\n',
    "",
)
replace(
    "tools/blender_python_env.py",
    "    requirements_sha = sha256(requirements)\n",
    """    requirements_sha = hashlib.sha256(
        json.dumps(requirements, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
""",
)
replace(
    "tools/blender_python_env.py",
    '                "--requirements",\n                str(requirements),\n                "--only-binary",\n                ":all:",\n                "--no-deps",\n',
    '                "--only-binary",\n                ":all:",\n                "--no-deps",\n                *requirements,\n',
)
replace(
    "tools/blender_python_env.py",
    '        "requirements": str(requirements.relative_to(root)).replace("\\\\", "/"),\n        "requirementsSha256": requirements_sha,\n',
    '        "dependencySource": "pyproject.toml",\n        "dependencyGroup": dependency_group,\n        "dependencySetSha256": requirements_sha,\n',
)

replace(
    "tools/siroino_wide_cargo_release_refit_v23.py",
    "import json\nimport math\nfrom pathlib import Path\n\nimport bpy\n\nimport siroino_wide_cargo_release_refit as legacy\n",
    """import json
import math
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit as legacy
""",
)

taskfile = ROOT / "Taskfile.yml"
task = taskfile.read_text(encoding="utf-8")
task = task.replace(
    "uv run --no-cache --no-project\n        --with numpy --with pillow --with trimesh --with scipy --with matplotlib\n        python tools/audit_snapshot.py",
    "uv run --no-cache --group snapshot\n        python tools/audit_snapshot.py",
)
task = task.replace(
    "uv run --no-cache --no-project --with ruff\n        ruff ",
    "uv run --no-cache --group dev\n        ruff ",
)
if "--with ruff" in task or "--with numpy" in task:
    raise SystemExit("Taskfile still declares ad-hoc Python dependencies")
taskfile.write_text(task, encoding="utf-8")

audit_path = ROOT / "tools" / "audit_repository_hygiene.py"
audit = audit_path.read_text(encoding="utf-8")
audit = audit.replace('    "blender-python-requirements.txt",\n', "")
marker = '    allowed_statuses = set(handoff_policy.get("statuses", []))\n'
insertion = """    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        add(
            findings,
            "missing-python-project",
            pyproject,
            root,
            "Python dependencies and environment groups must be declared in pyproject.toml",
        )
    if config_root.is_dir():
        for requirements_file in sorted(config_root.glob("*requirements*.txt")):
            add(
                findings,
                "environment-config-residue",
                requirements_file,
                root,
                "Python environment declarations belong in pyproject.toml",
            )

"""
if marker not in audit:
    raise SystemExit("audit policy insertion marker missing")
audit = audit.replace(marker, insertion + marker)
marker = '    workflow_root = root / ".github" / "workflows"\n'
insertion = """    product_tokens = {
        product_id.replace("-", "_").replace(".", "_") for product_id in product_ids
    }
    for root_script in sorted(root.glob("*.py")):
        if any(token and token in root_script.stem.lower() for token in product_tokens):
            add(
                findings,
                "product-script-at-repository-root",
                root_script,
                root,
                "product-specific Python scripts must live under tools/ or the product workspace",
            )

"""
if marker not in audit:
    raise SystemExit("root script insertion marker missing")
audit_path.write_text(audit.replace(marker, insertion + marker), encoding="utf-8")

agents_path = ROOT / "AGENTS.md"
agents = agents_path.read_text(encoding="utf-8")
marker = "- Common automation must remain product-neutral. Product-specific implementation needed to reproduce or continue a checkpoint is valid repository state when it is referenced by the job or manifest; do not delete it merely because it is product-specific.\n"
addition = marker + "- The repository root is reserved for repository-wide entry points and contracts. Product-specific Python modules must live under `tools/` or the canonical `Assets/GenWorks/<slug>/` workspace; never add product shims to the root.\n- `pyproject.toml` is the sole Python dependency and environment-group declaration. Do not add requirements files or ad-hoc `uv --with` dependency lists elsewhere.\n"
if marker not in agents:
    raise SystemExit("AGENTS authority marker missing")
agents_path.write_text(agents.replace(marker, addition), encoding="utf-8")

for obsolete in (
    ROOT / "examples" / "review-approval.json",
    ROOT / "config" / "blender-python-requirements.txt",
    ROOT / "siroino_wide_cargo_release_refit.py",
):
    obsolete.unlink(missing_ok=True)
