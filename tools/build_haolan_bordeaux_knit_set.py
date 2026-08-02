#!/usr/bin/env python3
"""Run the retained HAOLAN Bordeaux generator from any schema-v2 job location.

The original generator predates tracked jobs and resolves the repository root
from an Assets/_Local/Jobs/<id>/job.json path. This adapter preserves that
validated implementation while making config/products/<id>/job.json the
canonical, reproducible entry point.
"""
from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_BUILDER = ROOT / "tools" / "haolan_knit_build.py"
LOCAL_JOB = ROOT / "Assets" / "_Local" / "Jobs" / "haolan-bordeaux-knit-set" / "job.json"


def parse_job_path() -> Path:
    if "--" not in sys.argv:
        raise SystemExit("Blender arguments must contain -- --job <path>")
    args = sys.argv[sys.argv.index("--") + 1 :]
    if "--job" not in args:
        raise SystemExit("--job is required")
    value = Path(args[args.index("--job") + 1])
    return value if value.is_absolute() else (ROOT / value).resolve()


def main() -> int:
    source_job = parse_job_path()
    job = json.loads(source_job.read_text(encoding="utf-8-sig"))
    if job.get("schemaVersion") != 2:
        raise ValueError("HAOLAN Bordeaux build requires schemaVersion 2")
    if job.get("id") != "haolan-bordeaux-knit-set":
        raise ValueError("Unexpected job id for HAOLAN Bordeaux builder")

    LOCAL_JOB.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_JOB.write_text(
        json.dumps(job, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    sys.argv = [str(LEGACY_BUILDER), "--", "--job", str(LOCAL_JOB)]
    runpy.run_path(str(LEGACY_BUILDER), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
