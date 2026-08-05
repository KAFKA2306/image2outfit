from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TaskfileContractTest(unittest.TestCase):
    def test_python_tasks_cover_every_reusable_source_root(self) -> None:
        taskfile = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")
        for command in (
            "python -m compileall -q src tools tests",
            "ruff check --ignore S102 src tools tests",
            "ruff format src tools tests",
            "python tools/manage.py audit all",
            "python -m unittest discover -s tests -v",
        ):
            with self.subTest(command=command):
                self.assertIn(command, taskfile)


if __name__ == "__main__":
    unittest.main()
