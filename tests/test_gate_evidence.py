from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import audit_genworks_layout  # noqa: E402
import gate_evidence  # noqa: E402

VIEWS = ["front", "back", "left", "right", "three-quarter"]
POSES = ["neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"]
HANDOFF = {"requiredCompletionGates": ["blender", "fiveViewEvidence", "poseEvidence"]}
RELEASE = {
    "minimumPreview": {"requiredViews": VIEWS},
    "requiredPoses": POSES,
}
PRODUCT_ROOT = "Assets/GenWorks/demo"


def _manifest(**sections: object) -> dict:
    manifest: dict = {
        "schemaVersion": 1,
        "productId": "demo",
        "productRoot": PRODUCT_ROOT,
    }
    manifest.update(sections)
    return manifest


class GateEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write(self, relative: str, text: str = "evidence") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _write_views_and_poses(self) -> None:
        for view in VIEWS:
            self._write(f"{PRODUCT_ROOT}/Previews/{view}.png")
        for pose in POSES:
            self._write(f"{PRODUCT_ROOT}/Previews/Poses/{pose}.png")

    def test_pass_five_view_without_evidence_fails(self) -> None:
        manifest = _manifest(technicalGates={"fiveViewEvidence": "PASS"})
        rows = gate_evidence.violations(manifest, HANDOFF, RELEASE, self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["gate"], "fiveViewEvidence")
        self.assertIn(f"{PRODUCT_ROOT}/Previews/front.png", rows[0]["missing"])

    def test_pass_five_view_with_all_evidence_passes(self) -> None:
        self._write_views_and_poses()
        manifest = _manifest(
            technicalGates={"fiveViewEvidence": "PASS", "poseEvidence": "PASS"}
        )
        self.assertEqual(
            gate_evidence.violations(manifest, HANDOFF, RELEASE, self.root), []
        )

    def test_pass_pose_with_one_missing_pose_fails(self) -> None:
        self._write_views_and_poses()
        (self.root / f"{PRODUCT_ROOT}/Previews/Poses/prone.png").unlink()
        manifest = _manifest(technicalGates={"poseRender": "PASS"})
        rows = gate_evidence.violations(manifest, HANDOFF, RELEASE, self.root)
        self.assertEqual(
            rows[0]["missing"], [f"{PRODUCT_ROOT}/Previews/Poses/prone.png"]
        )

    def test_required_completion_pass_without_claimed_evidence_fails(self) -> None:
        manifest = _manifest(completionGates={"blender": "PASS"})
        rows = gate_evidence.violations(manifest, HANDOFF, RELEASE, self.root)
        self.assertEqual(rows[0]["section"], "completionGates")
        self.assertIn("claims no evidence", rows[0]["reasons"][0])

    def test_output_claim_must_exist(self) -> None:
        manifest = _manifest(
            completionGates={"blender": "PASS"},
            outputs={"blend": f"{PRODUCT_ROOT}/Source/demo.blend"},
        )
        rows = gate_evidence.violations(manifest, HANDOFF, RELEASE, self.root)
        self.assertEqual(rows[0]["missing"], [f"{PRODUCT_ROOT}/Source/demo.blend"])
        self._write(f"{PRODUCT_ROOT}/Source/demo.blend")
        self.assertEqual(
            gate_evidence.violations(manifest, HANDOFF, RELEASE, self.root), []
        )

    def test_unrecorded_or_non_passing_gates_are_not_checked(self) -> None:
        manifest = _manifest(
            technicalGates={"fiveViewEvidence": "UNVERIFIED", "poseRender": "FAIL"}
        )
        self.assertEqual(
            gate_evidence.violations(manifest, HANDOFF, RELEASE, self.root), []
        )

    def test_verified_hashed_evidence_must_match_digest(self) -> None:
        path = self._write(f"{PRODUCT_ROOT}/Evidence/unity-ready.json", "{}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        ready = {
            "status": "VERIFIED",
            "evidencePath": f"{PRODUCT_ROOT}/Evidence/unity-ready.json",
            "evidenceSha256": digest,
        }
        manifest = _manifest(releaseReadiness={"unityReady": ready})
        self.assertEqual(
            gate_evidence.violations(manifest, HANDOFF, RELEASE, self.root), []
        )
        ready["evidenceSha256"] = "0" * 64
        rows = gate_evidence.violations(manifest, HANDOFF, RELEASE, self.root)
        self.assertIn("evidenceSha256 mismatch", rows[0]["reasons"][0])

    def test_audit_fails_for_pass_without_evidence(self) -> None:
        config = self.root / "config"
        config.mkdir()
        (config / "genworks-handoff-policy.json").write_text(
            json.dumps(HANDOFF), encoding="utf-8"
        )
        (config / "release-policy.json").write_text(
            json.dumps(RELEASE), encoding="utf-8"
        )
        (self.root / "Assets/GenWorks/demo").mkdir(parents=True)
        manifest = _manifest(technicalGates={"fiveViewEvidence": "PASS"})
        manifest["productRoot"] = PRODUCT_ROOT
        (self.root / PRODUCT_ROOT / "ProductManifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        layout_config = json.loads(
            (ROOT / "config" / "genworks-layout.json").read_text(encoding="utf-8")
        )
        layout_path = self.root / "layout.json"
        layout_path.write_text(json.dumps(layout_config), encoding="utf-8")
        result = audit_genworks_layout.audit(self.root, layout_path)
        codes = [finding["code"] for finding in result["findings"]]
        self.assertIn("unbacked-pass-gate", codes)
        self.assertFalse(result["passed"])

    def test_build_scripts_do_not_write_literal_pass_for_view_or_pose(self) -> None:
        pattern = re.compile(
            r'"(fiveViewEvidence|poseEvidence|fiveViewRender|poseRender)"\s*:\s*"PASS"'
        )
        offenders = [
            path.name
            for path in sorted(TOOLS.glob("*.py"))
            if pattern.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [])

    def test_build_status_is_pass_only_with_all_files(self) -> None:
        self.assertEqual(
            gate_evidence._status(self.root, [f"{PRODUCT_ROOT}/a.png"]), "UNVERIFIED"
        )
        self._write(f"{PRODUCT_ROOT}/a.png")
        self.assertEqual(
            gate_evidence._status(self.root, [f"{PRODUCT_ROOT}/a.png"]), "PASS"
        )

    def test_committed_manifests_have_no_unbacked_pass(self) -> None:
        handoff, release = gate_evidence.load_policies(ROOT)
        for path in sorted((ROOT / "Assets/GenWorks").glob("*/ProductManifest.json")):
            manifest = json.loads(path.read_text(encoding="utf-8-sig"))
            self.assertEqual(
                gate_evidence.violations(manifest, handoff, release, ROOT),
                [],
                msg=path.parent.name,
            )


if __name__ == "__main__":
    unittest.main()
