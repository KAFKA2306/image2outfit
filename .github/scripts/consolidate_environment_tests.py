from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old[:120]!r}")
    file.write_text(text.replace(old, new), encoding="utf-8")


replace("tools/audit_toolchain.py", "import tempfile\n", "import tempfile\nimport tomllib\n")
replace(
    "tools/audit_toolchain.py",
    '''def exact_requirements(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return result
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            result[line] = ""
            continue
        name, version = line.split("==", 1)
        result[name.strip()] = version.strip()
    return result
''',
    '''def exact_project_dependencies(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        with path.open("rb") as stream:
            dependencies = tomllib.load(stream).get("project", {}).get("dependencies", [])
    except (OSError, tomllib.TOMLDecodeError):
        return result
    if not isinstance(dependencies, list):
        return result
    for value in dependencies:
        if not isinstance(value, str):
            continue
        if "==" not in value:
            result[value.strip()] = ""
            continue
        name, version = value.split("==", 1)
        result[name.strip()] = version.strip()
    return result
''',
)
replace(
    "tools/audit_toolchain.py",
    '''    requirements_value = str(blender_python.get("requirements", ""))
    requirements_path = (root / requirements_value).resolve()
    if not requirements_value.startswith("config/") or not requirements_path.is_file():
        errors.append(
            "Blender Python requirements must be a tracked file under config/"
        )
    actual_python_packages = exact_requirements(requirements_path)
''',
    '''    dependency_group = str(blender_python.get("dependencyGroup", ""))
    pyproject_path = root / "pyproject.toml"
    if dependency_group != "project" or not pyproject_path.is_file():
        errors.append(
            "Blender Python dependencies must use the project dependency set in pyproject.toml"
        )
    actual_python_packages = exact_project_dependencies(pyproject_path)
''',
)
replace(
    "tools/audit_toolchain.py",
    '''            "requirements": requirements_value,
            "packages": actual_python_packages,
''',
    '''            "dependencySource": "pyproject.toml",
            "dependencyGroup": dependency_group,
            "packages": actual_python_packages,
''',
)
replace(
    "tools/audit_toolchain.py",
    '            "Blender Python requirements mismatch: "\n',
    '            "Blender Python dependency mismatch: "\n',
)

replace(
    "tests/test_toolchain.py",
    '''        (self.root / "config" / "blender-python-requirements.txt").write_text(
            (PROJECT / "config" / "blender-python-requirements.txt").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
''',
    '''        (self.root / "pyproject.toml").write_text(
            (PROJECT / "pyproject.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
''',
)
replace(
    "tests/test_toolchain.py",
    '''    def test_blender_python_requirement_drift_is_rejected(self) -> None:
        (self.root / "config" / "blender-python-requirements.txt").write_text(
            "Pillow==12.2.0\\n", encoding="utf-8"
        )
        result = audit_toolchain.audit(self.root)
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("Blender Python requirements mismatch" in error for error in result["errors"])
        )
''',
    '''    def test_blender_python_dependency_drift_is_rejected(self) -> None:
        pyproject = (self.root / "pyproject.toml").read_text(encoding="utf-8")
        (self.root / "pyproject.toml").write_text(
            pyproject.replace("Pillow==12.3.0", "Pillow==12.2.0"),
            encoding="utf-8",
        )
        result = audit_toolchain.audit(self.root)
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("Blender Python dependency mismatch" in error for error in result["errors"])
        )
''',
)

replace(
    "tests/test_release_gate.py",
    '        (self.root / "config" / "blender-python-requirements.txt").write_text("Pillow==12.3.0\\n", encoding="utf-8")\n',
    '''        (self.root / "pyproject.toml").write_text(
            '[project]\\nname = "test"\\nversion = "0.0.0"\\ndependencies = ["Pillow==12.3.0"]\\n',
            encoding="utf-8",
        )
''',
)
