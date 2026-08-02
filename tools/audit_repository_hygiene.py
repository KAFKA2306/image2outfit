#!/usr/bin/env python3
"""Repository hygiene entry point with a narrow branch-ref cleanup exception."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    from .audit_repository_hygiene_core import ROOT, audit as _audit
except ImportError:  # Direct execution from the tools directory.
    from audit_repository_hygiene_core import ROOT, audit as _audit

_BRANCH_WORKFLOW = ".github/workflows/branch-hygiene.yml"


def _is_ref_only_branch_cleanup(root: Path) -> bool:
    path = root / _BRANCH_WORKFLOW
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8").lower()
    forbidden_mutations = (
        r"\bgit\s+push\b",
        r"github\.rest\.repos\.(createorupdatefilecontents|deletefile)",
        r"github\.rest\.git\.(createblob|createtree|createcommit|updateref)",
    )
    return (
        "github.rest.git.deleteref" in text
        and not any(re.search(pattern, text) for pattern in forbidden_mutations)
    )


def audit(root: Path = ROOT) -> dict[str, Any]:
    result = _audit(root)
    if _is_ref_only_branch_cleanup(root):
        result["findings"] = [
            finding
            for finding in result["findings"]
            if not (
                finding.get("code") == "self-mutating-workflow"
                and finding.get("path") == _BRANCH_WORKFLOW
            )
        ]
        result["findingCount"] = len(result["findings"])
        result["passed"] = not result["findings"]
    return result


def main() -> int:
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
