#!/usr/bin/env python3
"""Run the continuous-knee candidate with fresh-evidence enforcement."""
from __future__ import annotations

import shutil

import siroino_wide_cargo_release_refit_v29 as v29


def clear_stale_render_evidence() -> None:
    """Prevent old previews from being uploaded as evidence for a failed run."""
    _, job = v29.build.c.load_job()
    preview_root = v29.build.c.repo_path(job["productRoot"]) / "Previews"
    if not preview_root.exists():
        return
    for pattern in ("*.png", "*.webp"):
        for path in preview_root.glob(pattern):
            path.unlink(missing_ok=True)
    shutil.rmtree(preview_root / "Poses", ignore_errors=True)
    for metadata in preview_root.glob("*.png.meta"):
        metadata.unlink(missing_ok=True)
    for metadata in preview_root.glob("*.webp.meta"):
        metadata.unlink(missing_ok=True)
    (preview_root / "Poses.meta").unlink(missing_ok=True)


if __name__ == "__main__":
    clear_stale_render_evidence()
    v29.build.main()
    result = v29.audit()
    v29.record(result)
    v29.base.save_distribution_blend()
    if not result["passed"]:
        raise RuntimeError(f"v30 fresh-evidence wearability audit failed: {result}")
    raise SystemExit(0)
