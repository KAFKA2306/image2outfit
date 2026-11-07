#!/usr/bin/env python3
"""Reject environment-specific imports from the reusable src package."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.architecture import audit_src_boundaries


def main() -> int:
    violations = audit_src_boundaries(ROOT)
    result = {
        "schemaVersion": 1,
        "passed": not violations,
        "violations": [
            {
                "path": item.path,
                "importedModule": item.imported_module,
                "line": item.line,
            }
            for item in violations
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
