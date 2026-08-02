#!/usr/bin/env python3
"""Audit deterministic product-to-method selection for every tracked product."""
from __future__ import annotations

import json

import method_selection


def main() -> int:
    report = method_selection.audit_all()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
