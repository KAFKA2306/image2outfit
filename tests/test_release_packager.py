from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import release_packager  # noqa: E402


class ReleasePackagerTest(unittest.TestCase):
    def test_raw_human_and_runtime_evidence_are_packaged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / ".image2outfit/products/demo/candidate"
            release = root / ".image2outfit/products/demo/release"
            candidate.mkdir(parents=True)
            payload = candidate / "UnityAssets/demo.prefab"
            payload.parent.mkdir(parents=True)
            payload.write_text("prefab", encoding="utf-8")
            manifest = {
                "schemaVersion": 2,
                "kind": "image2outfit-candidate",
                "sourceCommit": "abc",
            }
            manifest_path = candidate / "candidate-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            candidate_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

            screenshot = root / "Assets/_Local/Evidence/demo/runtime.png"
            screenshot.parent.mkdir(parents=True)
            screenshot.write_bytes(b"runtime")
            evidence_path = (
                root / "Assets/_Local/Evidence/demo/vrchat-runtime-review.json"
            )
            evidence_path.write_text(
                json.dumps(
                    {"runtimeScreenshot": ("Assets/_Local/Evidence/demo/runtime.png")}
                ),
                encoding="utf-8",
            )
            commercial = root / "Assets/GenWorks/demo/Evidence/Commercial"
            commercial.mkdir(parents=True)
            (commercial / "topology-audit.json").write_text("{}\n", encoding="utf-8")
            job_path = root / "config/products/demo/job.json"
            job_path.parent.mkdir(parents=True)
            job_path.write_text("{}\n", encoding="utf-8")
            job = {
                "id": "demo",
                "productName": "Demo",
                "adapterId": "demo-v1",
                "productRoot": "Assets/GenWorks/demo",
                "humanEvidence": {
                    "vrchat-runtime-review": (
                        "Assets/_Local/Evidence/demo/vrchat-runtime-review.json"
                    )
                },
            }
            result = release_packager.package_release(
                root=root,
                job_path=job_path,
                job=job,
                policy={"blockedReleaseAdapterIds": []},
                candidate=candidate,
                release=release,
                candidate_manifest=manifest,
                candidate_hash=candidate_hash,
                human_evidence={"vrchat-runtime-review": {"passed": True}},
                verify_candidate=lambda *_: [],
                now=lambda: datetime.now(timezone.utc).isoformat(),
            )
            self.assertTrue(
                (
                    release / "Package/Evidence/Human/vrchat-runtime-review.json"
                ).is_file()
            )
            self.assertTrue(
                (release / "Package/Evidence/Human/runtime/runtime.png").is_file()
            )
            self.assertTrue(
                (release / "Package/Evidence/Commercial/topology-audit.json").is_file()
            )
            archive = root / result["zip"]["path"]
            self.assertTrue(archive.is_file())
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
            self.assertIn("Package/Evidence/Human/vrchat-runtime-review.json", names)
            self.assertIn("Package/Evidence/Human/runtime/runtime.png", names)


if __name__ == "__main__":
    unittest.main()
