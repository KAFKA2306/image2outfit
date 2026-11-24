from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import blender_cloth_simulation as bcs  # noqa: E402

PRODUCT_ID = "demo-fencing-set"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


class RebindFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.config_dir = root / "config" / "products" / PRODUCT_ID
        self.evidence_dir = root / ".image2outfit" / "products" / PRODUCT_ID / "evidence"
        self.target_path = root / "Assets" / "Target" / "Avatar.fbx"
        self.job_path = self.config_dir / "job.json"
        self.construction_path = self.config_dir / "construction.json"
        self.assembly_pose_path = self.config_dir / "assembly-pose.json"
        self.pattern_path = self.config_dir / "pattern-draft.json"
        self.stitch_path = self.config_dir / "stitch-graph.json"

        _git(root, "init")
        _git(root, "config", "user.email", "test@example.com")
        _git(root, "config", "user.name", "Test")

        self.target_path.parent.mkdir(parents=True, exist_ok=True)
        target_bytes = b"synthetic-target-avatar-fbx-v1"
        self.target_path.write_bytes(target_bytes)
        self.target_sha = _sha256_bytes(target_bytes)

        self.pattern_doc: dict[str, Any] = {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "units": "m",
            "coordinateSystem": "garmentcode-2d",
            "sourceReference": "private-reference://sha256/" + ("a" * 64),
            "measurementBasis": "neutral",
            "pieces": [
                {"pieceId": "overskirt-front", "boundary": [[0.0, 0.0], [0.2, -0.14]]},
                {"pieceId": "overskirt-back", "boundary": [[0.0, 0.0], [0.2, -0.14]]},
                {"pieceId": "waistband-front", "boundary": [[0.0, 0.0], [0.2, 0.03]]},
                {"pieceId": "waistband-back", "boundary": [[0.0, 0.0], [0.2, 0.03]]},
                {"pieceId": "shorts-front-left", "boundary": [[0.0, -0.12], [0.22, -0.12]]},
            ],
        }
        self.pose_doc: dict[str, Any] = {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "status": "PROTOTYPE",
            "coordinateSystem": "blender-z-up",
            "targetSourceSha256": self.target_sha,
            "measurementEvidencePath": "config/products/demo-fencing-set/meas.json",
            "measurementEvidenceSha256": "b" * 64,
            "poses": {
                "overskirt-front": {"skirtWrap": {"widthQuadraticControlM": [0.2, 0.25, 0.3]}},
                "overskirt-back": {"skirtWrap": {"widthQuadraticControlM": [0.2, 0.25, 0.3]}},
                "waistband-front": {"zM": 0.74},
                "waistband-back": {"zM": 0.74},
                "shorts-front-left": {"widthBoundsProfileM": [[-0.12, 0.0, 0.22]]},
            },
            "shortsOrientationEvidence": {
                "frontAxis": "GarmentCode +Z = Blender -Y",
                "leftAxis": "GarmentCode +X = Blender +X",
                "method": "Initial shorts placement method.",
                "evidenceBoundary": "Initial shorts boundary.",
            },
            "skirtPleatPlacement": {
                "method": "crease-aligned",
                "pieceIds": ["overskirt-front", "overskirt-back"],
                "waistZM": 0.74,
                "hemZM": 0.60,
                "seamContinuationPieceIds": ["waistband-front", "waistband-back"],
            },
        }
        self.stitch_doc: dict[str, Any] = {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "stitches": [
                {
                    "stitchId": "front-waistband-skirt",
                    "first": {"pieceId": "overskirt-front", "edgeId": "waist"},
                    "second": {"pieceId": "waistband-front", "edgeId": "skirt"},
                },
                {
                    "stitchId": "back-waistband-skirt",
                    "first": {"pieceId": "overskirt-back", "edgeId": "waist"},
                    "second": {"pieceId": "waistband-back", "edgeId": "skirt"},
                },
                {
                    "stitchId": "overskirt-side",
                    "first": {"pieceId": "overskirt-front", "edgeId": "side"},
                    "second": {"pieceId": "overskirt-back", "edgeId": "side"},
                },
            ],
        }
        self.job_doc: dict[str, Any] = {
            "schemaVersion": 2,
            "id": PRODUCT_ID,
            "targetSourcePath": "Assets/Target/Avatar.fbx",
            "garmentPipeline": {
                "constructionPath": f"config/products/{PRODUCT_ID}/construction.json",
                "assemblyPosePath": f"config/products/{PRODUCT_ID}/assembly-pose.json",
                "patternContractPath": f"config/products/{PRODUCT_ID}/pattern-draft.json",
                "stitchGraphPath": f"config/products/{PRODUCT_ID}/stitch-graph.json",
            },
        }

        pattern_bytes = _write_json(self.pattern_path, self.pattern_doc)
        pose_bytes = _write_json(self.assembly_pose_path, self.pose_doc)
        _write_json(self.stitch_path, self.stitch_doc)
        _write_json(self.job_path, self.job_doc)

        baseline_evidence: dict[str, Any] = {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "blenderVersion": "4.4.3",
            "assemblyPoseSha256": _sha256_bytes(pose_bytes),
            "patternSha256": _sha256_bytes(pattern_bytes),
            "targetSourceSha256": self.target_sha,
            "sourceSkirtMeshSha256": "c" * 64,
            "bendingStiffness": 20.0,
            "bendingStiffnessMax": 20.0,
            "bendingModel": "ANGULAR",
            "frameEnd": 16,
            "cacheBaked": True,
            "settledMeshSha256": "d" * 64,
            "grantsFitAcceptance": False,
            "grantsVisualAcceptance": False,
        }
        evidence_bytes = (
            json.dumps(baseline_evidence, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        self.baseline_evidence_sha = _sha256_bytes(evidence_bytes)
        self.baseline_evidence_rel = (
            f".image2outfit/products/{PRODUCT_ID}/evidence/"
            f"skirt-bending-{self.baseline_evidence_sha[:16]}.json"
        )
        self.baseline_evidence_path = root / self.baseline_evidence_rel
        self.baseline_evidence_path.parent.mkdir(parents=True, exist_ok=True)
        self.baseline_evidence_path.write_bytes(evidence_bytes)

        self.construction_doc: dict[str, Any] = {
            "clothSimulation": {
                "applicability": "REQUIRED",
                "components": ["jacket-sleeves", "pleated-overskirt"],
                "prototypePanelGroups": {
                    "jacket-sleeves": ["shorts-front-left"],
                    "pleated-overskirt": ["overskirt-front", "overskirt-back"],
                },
                "prototypeFrameEnd": 16,
                "prototypeComponentBending": {
                    "pleated-overskirt": {
                        "stiffness": 20,
                        "evidencePath": self.baseline_evidence_rel,
                        "evidenceSha256": self.baseline_evidence_sha,
                        "evidenceBoundary": "Baseline isolated overskirt comparison.",
                    }
                },
            }
        }
        _write_json(self.construction_path, self.construction_doc)

        _git(root, "add", "config", "Assets")
        _git(root, "commit", "-m", "baseline")
        self.baseline_commit = _git(root, "rev-parse", "HEAD")

    def apply_unrelated_shorts_hem_extension(self, *, commit: bool = True) -> str | None:
        self.pattern_doc["pieces"][-1]["boundary"] = [[0.0, -0.17], [0.22, -0.17]]
        self.pose_doc["poses"]["shorts-front-left"]["widthBoundsProfileM"] = [
            [-0.17, 0.0, 0.22]
        ]
        self.pose_doc["shortsOrientationEvidence"]["method"] = (
            "Extended shorts hem 50 mm toward knee landmark."
        )
        self.pose_doc["shortsOrientationEvidence"]["evidenceBoundary"] = (
            "Coverage hypothesis only; cloth evidence stale."
        )
        _write_json(self.pattern_path, self.pattern_doc)
        _write_json(self.assembly_pose_path, self.pose_doc)
        if commit:
            _git(self.root, "add", "config")
            _git(self.root, "commit", "-m", "Extend shorts hem")
            return _git(self.root, "rev-parse", "HEAD")
        return None


class BlenderClothSimulationRebindTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.fixture = RebindFixture(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _validate_current(self) -> tuple[float, dict[str, Any]]:
        construction = bcs.read_json(self.fixture.construction_path)
        declared = construction["clothSimulation"]["prototypeComponentBending"][
            "pleated-overskirt"
        ]
        return bcs.validate_component_bending_evidence(
            self.fixture.job_doc,
            declared,
            frame_end=16,
            blender_version="4.4.3",
            bending_model="ANGULAR",
            stiffness_min=0.0,
            stiffness_max=10000.0,
            root=self.fixture.root,
        )

    def test_rebind_succeeds_for_unrelated_piece_change_and_keeps_stale_gate_active(
        self,
    ) -> None:
        self.fixture.apply_unrelated_shorts_hem_extension()

        # Regression: normal validation MUST fail closed before rebinding.
        with self.assertRaisesRegex(
            ValueError, r"Bending comparison inputs are stale: assemblyPoseSha256"
        ):
            self._validate_current()

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code = bcs.main(
                [
                    "--job",
                    f"config/products/{PRODUCT_ID}/job.json",
                    "--rebind-bending-component",
                    "pleated-overskirt",
                    "--baseline-revision",
                    self.fixture.baseline_commit[:7],
                ],
                root=self.fixture.root,
            )
        self.assertEqual(exit_code, 0)
        cli_output = json.loads(buf.getvalue())
        self.assertEqual(cli_output["status"], "REBOUND")
        self.assertEqual(cli_output["baselineRevision"], self.fixture.baseline_commit)

        # Old evidence file must remain untouched.
        self.assertTrue(self.fixture.baseline_evidence_path.is_file())
        self.assertEqual(
            _sha256_bytes(self.fixture.baseline_evidence_path.read_bytes()),
            self.fixture.baseline_evidence_sha,
        )

        # Updated construction.json must match construction.schema.v1.json contract.
        updated_construction = bcs.read_json(self.fixture.construction_path)
        declared = updated_construction["clothSimulation"]["prototypeComponentBending"][
            "pleated-overskirt"
        ]
        self.assertEqual(
            set(declared.keys()),
            {"stiffness", "evidencePath", "evidenceSha256", "evidenceBoundary"},
        )
        self.assertEqual(declared["stiffness"], 20)
        self.assertNotEqual(declared["evidenceSha256"], self.fixture.baseline_evidence_sha)
        self.assertTrue(
            declared["evidencePath"].startswith(
                f".image2outfit/products/{PRODUCT_ID}/evidence/skirt-bending-"
            )
        )
        new_evidence_path = self.fixture.root / declared["evidencePath"]
        self.assertTrue(new_evidence_path.is_file())
        self.assertEqual(
            _sha256_bytes(new_evidence_path.read_bytes()), declared["evidenceSha256"]
        )

        # Rebound evidence must record truthful provenance and updated input hashes.
        rebound = bcs.read_json(new_evidence_path)
        self.assertEqual(
            rebound["assemblyPoseSha256"],
            _sha256_bytes(self.fixture.assembly_pose_path.read_bytes()),
        )
        self.assertEqual(
            rebound["patternSha256"],
            _sha256_bytes(self.fixture.pattern_path.read_bytes()),
        )
        self.assertEqual(rebound["targetSourceSha256"], self.fixture.target_sha)
        self.assertFalse(rebound["grantsFitAcceptance"])
        self.assertFalse(rebound["grantsVisualAcceptance"])
        prov = rebound["rebindProvenance"]
        self.assertEqual(prov["method"], "baseline-component-invariance-rebind")
        self.assertEqual(prov["baselineRevision"], self.fixture.baseline_commit)
        self.assertEqual(
            prov["baselineEvidenceSha256"], self.fixture.baseline_evidence_sha
        )
        self.assertEqual(
            prov["protectedPieceIds"],
            ["overskirt-back", "overskirt-front", "waistband-back", "waistband-front"],
        )
        self.assertEqual(
            prov["changedNonComponentPatternPieces"], ["shorts-front-left"]
        )
        self.assertEqual(prov["changedNonComponentPosePieces"], ["shorts-front-left"])
        self.assertEqual(
            prov["changedNonComponentPoseBlocks"], ["shortsOrientationEvidence"]
        )
        self.assertFalse(prov["meshHashVerifiedInBlender"])

        # After rebind, normal validation passes with exact stiffness.
        stiffness, validated = self._validate_current()
        self.assertEqual(stiffness, 20.0)
        self.assertEqual(validated["productId"], PRODUCT_ID)

        # Regression: subsequent edit MUST trigger stale failure again.
        self.fixture.pattern_doc["pieces"][-1]["boundary"] = [[0.0, -0.19], [0.22, -0.19]]
        _write_json(self.fixture.pattern_path, self.fixture.pattern_doc)
        with self.assertRaisesRegex(
            ValueError, r"Bending comparison inputs are stale: patternSha256"
        ):
            self._validate_current()

    def test_rebind_is_unchanged_when_inputs_already_match_baseline(self) -> None:
        before_construction = self.fixture.construction_path.read_bytes()
        result = bcs.rebind_component_bending(
            self.fixture.job_doc,
            "pleated-overskirt",
            self.fixture.baseline_commit,
            root=self.fixture.root,
        )
        self.assertEqual(result["status"], "UNCHANGED")
        self.assertEqual(
            self.fixture.construction_path.read_bytes(), before_construction
        )

    def test_cli_argument_validation_fails_fast_without_modifying_files(self) -> None:
        self.fixture.apply_unrelated_shorts_hem_extension()
        before_construction = self.fixture.construction_path.read_bytes()
        job_arg = f"config/products/{PRODUCT_ID}/job.json"

        invalid_invocations = [
            ["--job", job_arg, "--rebind-bending-component", "pleated-overskirt"],
            ["--job", job_arg, "--baseline-revision", self.fixture.baseline_commit],
            [
                "--job",
                job_arg,
                "--rebind-bending-component",
                "   ",
                "--baseline-revision",
                self.fixture.baseline_commit,
            ],
            [
                "--job",
                job_arg,
                "--rebind-bending-component",
                "pleated-overskirt",
                "--baseline-revision",
                "",
            ],
            [
                "--job",
                job_arg,
                "--prototype",
                "--rebind-bending-component",
                "pleated-overskirt",
                "--baseline-revision",
                self.fixture.baseline_commit,
            ],
            [
                "--job",
                job_arg,
                "--force",
                "--rebind-bending-component",
                "pleated-overskirt",
                "--baseline-revision",
                self.fixture.baseline_commit,
            ],
        ]
        for argv in invalid_invocations:
            with self.subTest(argv=argv):
                with self.assertRaises(ValueError):
                    bcs.main(argv, root=self.fixture.root)
                self.assertEqual(
                    self.fixture.construction_path.read_bytes(), before_construction
                )

    def test_invalid_revision_component_missing_or_corrupt_inputs_fail_fast(self) -> None:
        self.fixture.apply_unrelated_shorts_hem_extension()
        before_construction = self.fixture.construction_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "Invalid baseline git revision"):
            bcs.rebind_component_bending(
                self.fixture.job_doc,
                "pleated-overskirt",
                "deadbeef00000000",
                root=self.fixture.root,
            )

        with self.assertRaisesRegex(ValueError, "Invalid baseline git revision"):
            bcs.rebind_component_bending(
                self.fixture.job_doc,
                "pleated-overskirt",
                "--help",
                root=self.fixture.root,
            )

        with self.assertRaisesRegex(ValueError, "Unknown or undeclared bending component"):
            bcs.rebind_component_bending(
                self.fixture.job_doc,
                "nonexistent-component",
                self.fixture.baseline_commit,
                root=self.fixture.root,
            )

        # Component exists in prototypePanelGroups but has no prototypeComponentBending entry
        with self.assertRaisesRegex(ValueError, "Unknown or undeclared bending component"):
            bcs.rebind_component_bending(
                self.fixture.job_doc,
                "jacket-sleeves",
                self.fixture.baseline_commit,
                root=self.fixture.root,
            )

        # Wrong baseline revision (HEAD instead of baseline_commit)
        with self.assertRaisesRegex(
            ValueError,
            "Baseline revision does not match existing bending comparison evidence",
        ):
            bcs.rebind_component_bending(
                self.fixture.job_doc,
                "pleated-overskirt",
                "HEAD",
                root=self.fixture.root,
            )

        self.assertEqual(
            self.fixture.construction_path.read_bytes(), before_construction
        )

    def test_corrupt_json_and_missing_files_fail_fast(self) -> None:
        self.fixture.apply_unrelated_shorts_hem_extension()
        before_construction = self.fixture.construction_path.read_bytes()

        # Corrupt assembly-pose.json
        original_pose = self.fixture.assembly_pose_path.read_bytes()
        self.fixture.assembly_pose_path.write_text("{corrupt-json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            bcs.rebind_component_bending(
                self.fixture.job_doc,
                "pleated-overskirt",
                self.fixture.baseline_commit,
                root=self.fixture.root,
            )
        self.fixture.assembly_pose_path.write_bytes(original_pose)

        # Tampered evidence file
        original_evidence = self.fixture.baseline_evidence_path.read_bytes()
        self.fixture.baseline_evidence_path.write_bytes(original_evidence + b" ")
        with self.assertRaisesRegex(ValueError, "evidence hash mismatch"):
            bcs.rebind_component_bending(
                self.fixture.job_doc,
                "pleated-overskirt",
                self.fixture.baseline_commit,
                root=self.fixture.root,
            )
        self.fixture.baseline_evidence_path.write_bytes(original_evidence)

        # Missing evidence file
        self.fixture.baseline_evidence_path.unlink()
        with self.assertRaisesRegex(ValueError, "evidence file is missing"):
            bcs.rebind_component_bending(
                self.fixture.job_doc,
                "pleated-overskirt",
                self.fixture.baseline_commit,
                root=self.fixture.root,
            )
        self.fixture.baseline_evidence_path.write_bytes(original_evidence)

        # Missing target FBX
        original_target = self.fixture.target_path.read_bytes()
        self.fixture.target_path.unlink()
        with self.assertRaisesRegex(ValueError, "Required input file is missing"):
            bcs.rebind_component_bending(
                self.fixture.job_doc,
                "pleated-overskirt",
                self.fixture.baseline_commit,
                root=self.fixture.root,
            )
        self.fixture.target_path.write_bytes(original_target)

        self.assertEqual(
            self.fixture.construction_path.read_bytes(), before_construction
        )

    def test_disprove_component_or_stitched_neighbor_or_global_changes_are_rejected(
        self,
    ) -> None:
        self.fixture.apply_unrelated_shorts_hem_extension(commit=False)

        def assert_rejected(pattern: str, mutate: Any) -> None:
            saved = {
                p: p.read_bytes()
                for p in (
                    self.fixture.pattern_path,
                    self.fixture.assembly_pose_path,
                    self.fixture.stitch_path,
                    self.fixture.construction_path,
                    self.fixture.target_path,
                )
            }
            try:
                mutate()
                with self.assertRaisesRegex(ValueError, pattern):
                    bcs.rebind_component_bending(
                        self.fixture.job_doc,
                        "pleated-overskirt",
                        self.fixture.baseline_commit,
                        root=self.fixture.root,
                    )
            finally:
                for p, data in saved.items():
                    p.write_bytes(data)

        # 1. Component's own piece modified in pattern-draft.json
        def mutate_skirt_pattern() -> None:
            doc = bcs.read_json(self.fixture.pattern_path)
            doc["pieces"][0]["boundary"][1][1] = -0.18
            _write_json(self.fixture.pattern_path, doc)

        assert_rejected("Pattern changed for component-relevant piece 'overskirt-front'", mutate_skirt_pattern)

        # 2. Directly stitched neighbor piece (waistband-front) modified in assembly-pose.json
        def mutate_waistband_pose() -> None:
            doc = bcs.read_json(self.fixture.assembly_pose_path)
            doc["poses"]["waistband-front"]["zM"] = 0.76
            _write_json(self.fixture.assembly_pose_path, doc)

        assert_rejected("Assembly pose changed for component-relevant piece 'waistband-front'", mutate_waistband_pose)

        # 3. Component placement block modified
        def mutate_pleat_block() -> None:
            doc = bcs.read_json(self.fixture.assembly_pose_path)
            doc["skirtPleatPlacement"]["hemZM"] = 0.58
            _write_json(self.fixture.assembly_pose_path, doc)

        assert_rejected("Assembly pose block 'skirtPleatPlacement' affects component-relevant pieces", mutate_pleat_block)

        # 4. Non-prose axis field modified in shortsOrientationEvidence
        def mutate_shorts_axis() -> None:
            doc = bcs.read_json(self.fixture.assembly_pose_path)
            doc["shortsOrientationEvidence"]["frontAxis"] = "flipped"
            _write_json(self.fixture.assembly_pose_path, doc)

        assert_rejected("changed non-prose or component-relevant data", mutate_shorts_axis)

        # 5. Core global field modified in assembly-pose.json
        def mutate_global_coord() -> None:
            doc = bcs.read_json(self.fixture.assembly_pose_path)
            doc["coordinateSystem"] = "changed"
            _write_json(self.fixture.assembly_pose_path, doc)

        assert_rejected("Assembly pose global key 'coordinateSystem' changed", mutate_global_coord)

        # 6. Stitch touching overskirt modified
        def mutate_stitch() -> None:
            doc = bcs.read_json(self.fixture.stitch_path)
            doc["stitches"][0]["second"]["edgeId"] = "other-edge"
            _write_json(self.fixture.stitch_path, doc)

        assert_rejected("Stitch graph changed for 'pleated-overskirt'", mutate_stitch)

        # 7. Target avatar FBX changed
        def mutate_target() -> None:
            self.fixture.target_path.write_bytes(b"modified-target-avatar-fbx")

        assert_rejected("Target source changed", mutate_target)

        # 8. Cloth simulation policy changed since baseline
        def mutate_cloth_policy() -> None:
            doc = bcs.read_json(self.fixture.construction_path)
            doc["clothSimulation"]["prototypeFrameEnd"] = 20
            _write_json(self.fixture.construction_path, doc)

        assert_rejected("incompatible with this solve|prototypeFrameEnd changed", mutate_cloth_policy)

    def test_cli_subprocess_exits_nonzero_on_invalid_rebind_args(self) -> None:
        script = ROOT / "tools" / "blender_cloth_simulation.py"
        job = ROOT / "config/products/siroino-lilac-lame-fencing-practice-set/job.json"
        for extra in (
            ["--rebind-bending-component", "pleated-overskirt"],
            [
                "--rebind-bending-component",
                "pleated-overskirt",
                "--baseline-revision",
                "nonexistent-revision-deadbeef",
            ],
        ):
            with self.subTest(extra=extra):
                proc = subprocess.run(
                    [sys.executable, str(script), "--job", str(job), *extra],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("ValueError", proc.stderr)

    def test_real_lilac_4b75c18_to_head_preconditions_read_only(self) -> None:
        job_path = ROOT / "config/products/siroino-lilac-lame-fencing-practice-set/job.json"
        if not job_path.is_file():
            self.skipTest("Lilac product job not present")
        job = bcs.read_json(job_path)
        construction = bcs.read_json(ROOT / job["garmentPipeline"]["constructionPath"])
        declared = construction["clothSimulation"]["prototypeComponentBending"][
            "pleated-overskirt"
        ]
        if not (ROOT / declared["evidencePath"]).is_file():
            self.skipTest("Local gitignored baseline bending evidence not present")
        # Read-only verification only: proves 17ec15b vs 4b75c18 satisfies every precondition
        # without mutating any repository file.
        checked = bcs.verify_component_bending_rebind_preconditions(
            job,
            "pleated-overskirt",
            "4b75c18",
            root=ROOT,
        )
        self.assertEqual(checked["component"], "pleated-overskirt")
        self.assertEqual(
            checked["protectedPieceIds"],
            ["overskirt-back", "overskirt-front", "waistband-back", "waistband-front"],
        )
        self.assertEqual(
            checked["changedPatternPieces"],
            [
                "shorts-back-left",
                "shorts-back-right",
                "shorts-front-left",
                "shorts-front-right",
            ],
        )
        self.assertEqual(
            checked["changedPoseBlocks"],
            ["shortsOrientationEvidence"],
        )


if __name__ == "__main__":
    unittest.main()
