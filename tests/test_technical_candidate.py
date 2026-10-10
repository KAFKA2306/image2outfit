from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
import sys

sys.path.insert(0, str(TOOLS))

import blender_python_env  # noqa: E402
import technical_candidate  # noqa: E402


import hashlib
import json


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UnityReadyPublishTests(unittest.TestCase):
    """Unity-ready publish happens only after the candidate manifest exists."""

    def _fixture(self, root: Path) -> dict:
        product = root / "Assets" / "GenWorks" / "demo"
        manifest_path = product / "ProductManifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest = {
            "schemaVersion": 1,
            "productId": "demo",
            "productRoot": "Assets/GenWorks/demo",
            "sourceJobPath": "config/products/demo/job.json",
            "state": "WORKING",
            "technicalGates": {
                "blender": "PASS",
                "unityImport": "OUT_OF_SCOPE",
                "prefabSerialized": "OUT_OF_SCOPE",
                "prefabReload": "OUT_OF_SCOPE",
                "modularAvatar": "OUT_OF_SCOPE",
                "ndmf": "OUT_OF_SCOPE",
            },
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        evidence = product / "Evidence" / "Unity" / "unity-ready.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text('{"tracked": "before"}\n', encoding="utf-8")

        artifact = root / "reports" / "artifact"
        artifact.mkdir(parents=True)
        (artifact / "unity-ready.json").write_text(
            '{"unityReadyStatus": "VERIFIED"}\n', encoding="utf-8"
        )
        candidate_dir = root / "candidate"
        candidate_dir.mkdir(parents=True)
        candidate_manifest = candidate_dir / "candidate-manifest.json"
        candidate_manifest.write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "kind": "image2outfit-candidate",
                    "jobId": "demo",
                    "runId": "run-1",
                    "unityReady": {
                        "status": "VERIFIED",
                        "evidencePath": "Assets/GenWorks/demo/Evidence/Unity/unity-ready.json",
                    },
                }
            ),
            encoding="utf-8",
        )
        job = {
            "id": "demo",
            "buildRevision": "r7",
            "productRoot": "Assets/GenWorks/demo",
            "productManifestPath": "Assets/GenWorks/demo/ProductManifest.json",
            "targetAvatarAssetPath": "Assets/Avatar.prefab",
            "unityReady": {"materialRoles": {"body": "Body"}},
        }
        return {
            "job": job,
            "manifest": manifest_path,
            "evidence": evidence,
            "artifact": artifact,
            "candidate_manifest": candidate_manifest,
        }

    def _publish(self, root: Path, fx: dict, run_id: str = "run-1") -> Path:
        with patch.object(technical_candidate.candidate_contract, "ROOT", root):
            return technical_candidate.publish_unity_ready_product_state(
                fx["job"],
                {"unityReadyStatus": "VERIFIED"},
                fx["artifact"],
                fx["candidate_manifest"],
                run_id,
            )

    def test_publish_updates_manifest_and_evidence_bound_to_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fx = self._fixture(root)
            self._publish(root, fx)

            stored = json.loads(fx["manifest"].read_text(encoding="utf-8"))
            for gate in (
                "unityImport",
                "prefabSerialized",
                "prefabReload",
                "modularAvatar",
                "ndmf",
            ):
                self.assertEqual(stored["technicalGates"][gate], "PASS")
            unity = stored["releaseReadiness"]["unityReady"]
            self.assertEqual(unity["status"], "VERIFIED")
            self.assertEqual(unity["materialRoles"], {"body": "Body"})
            self.assertEqual(
                unity["evidenceSha256"], _sha(fx["artifact"] / "unity-ready.json")
            )
            self.assertEqual(
                fx["evidence"].read_bytes(),
                (fx["artifact"] / "unity-ready.json").read_bytes(),
            )

    def test_refused_candidate_identity_keeps_manifest_and_evidence_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fx = self._fixture(root)
            manifest_before = _sha(fx["manifest"])
            evidence_before = fx["evidence"].read_bytes()

            with self.assertRaises(ValueError):
                self._publish(root, fx, run_id="run-2")

            self.assertEqual(_sha(fx["manifest"]), manifest_before)
            self.assertEqual(fx["evidence"].read_bytes(), evidence_before)

    def test_refused_publish_without_prior_evidence_removes_staged_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fx = self._fixture(root)
            fx["evidence"].unlink()
            manifest_before = _sha(fx["manifest"])

            with self.assertRaises(ValueError):
                self._publish(root, fx, run_id="run-2")

            self.assertFalse(fx["evidence"].exists())
            self.assertEqual(_sha(fx["manifest"]), manifest_before)

    def test_stale_candidate_manifest_hash_is_rejected_by_canonical_writer(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fx = self._fixture(root)
            manifest_before = _sha(fx["manifest"])
            evidence_before = fx["evidence"].read_bytes()

            real_digest = technical_candidate.candidate_contract.digest

            def tampered(path: Path) -> str:
                # Candidate identity is hashed before the writer re-reads it; a
                # change in between must be refused, not published.
                if path == fx["candidate_manifest"]:
                    return "0" * 64
                return real_digest(path)

            with patch.object(
                technical_candidate.candidate_contract, "digest", tampered
            ):
                with self.assertRaises(ValueError):
                    self._publish(root, fx)

            self.assertEqual(_sha(fx["manifest"]), manifest_before)
            self.assertEqual(fx["evidence"].read_bytes(), evidence_before)


class HostedPoseRenderTests(unittest.TestCase):
    def test_hosted_pose_script_is_run_and_required_outputs_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "tools" / "poses.py"
            blend = root / "Assets" / "Product" / "outfit.blend"
            pose_root = root / "Assets" / "Product" / "Previews" / "Poses"
            script.parent.mkdir(parents=True)
            blend.parent.mkdir(parents=True)
            script.write_text("# test\n", encoding="utf-8")
            blend.write_bytes(b"blend")
            required = ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone")
            for pose in required:
                pose_path = pose_root / f"{pose}.png"
                pose_path.parent.mkdir(parents=True, exist_ok=True)
                pose_path.write_bytes(b"png")

            job = {
                "hostedPoseScript": "tools/poses.py",
                "blendPath": "Assets/Product/outfit.blend",
                "productRoot": "Assets/Product",
            }
            policy = {"requiredPoses": list(required)}
            prepared = blender_python_env.PreparedEnvironment(
                command_prefix=["blender", "--python-use-system-env"],
                environment={},
                report={},
            )

            with (
                patch.object(technical_candidate.candidate_contract, "ROOT", root),
                patch.object(technical_candidate, "run_command", return_value=0) as run,
            ):
                result = technical_candidate.run_hosted_pose_render(
                    root / "job.json", job, policy, prepared, root / "reports"
                )

            self.assertTrue(result["passed"])
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["missingPoses"], [])
            command = run.call_args.args[0]
            self.assertIn(str(script), command)
            self.assertIn(str(blend), command)
            self.assertIn("--job", command)

    def test_unconfigured_hosted_pose_is_explicitly_not_requested(self) -> None:
        prepared = blender_python_env.PreparedEnvironment([], {}, {})
        result = technical_candidate.run_hosted_pose_render(
            Path("job.json"),
            {},
            {"requiredPoses": ["neutral"]},
            prepared,
            Path("reports"),
        )
        self.assertEqual(result, {"passed": True, "status": "NOT_REQUESTED"})


class SkinBindingSummaryTests(unittest.TestCase):
    def test_mesh_without_vertex_groups_is_unrigged_mesh_only_output(self) -> None:
        summary = technical_candidate.skin_binding_summary(
            [{"name": "TripoSG_Raw", "hasVertexGroups": False, "armatureTargets": []}]
        )
        self.assertEqual(summary["riggingState"], "UNRIGGED")
        self.assertEqual(summary["unriggedMeshObjects"], ["TripoSG_Raw"])

    def test_vertex_groups_without_armature_modifier_are_not_bound(self) -> None:
        summary = technical_candidate.skin_binding_summary(
            [{"name": "Garment", "hasVertexGroups": True, "armatureTargets": []}]
        )
        self.assertEqual(summary["riggingState"], "UNRIGGED")
        self.assertEqual(summary["unriggedMeshObjects"], ["Garment"])

    def test_one_unbound_mesh_makes_the_whole_scene_unrigged(self) -> None:
        summary = technical_candidate.skin_binding_summary(
            [
                {
                    "name": "Body",
                    "hasVertexGroups": True,
                    "armatureTargets": ["Armature"],
                },
                {"name": "Raw", "hasVertexGroups": False, "armatureTargets": []},
            ]
        )
        self.assertEqual(summary["riggingState"], "UNRIGGED")
        self.assertEqual(summary["unriggedMeshObjects"], ["Raw"])

    def test_fully_bound_meshes_are_rigged(self) -> None:
        summary = technical_candidate.skin_binding_summary(
            [
                {
                    "name": "Body",
                    "hasVertexGroups": True,
                    "armatureTargets": ["Armature"],
                },
                {
                    "name": "Garment",
                    "hasVertexGroups": True,
                    "armatureTargets": ["Armature"],
                },
            ]
        )
        self.assertEqual(summary["riggingState"], "RIGGED")
        self.assertEqual(summary["unriggedMeshObjects"], [])

    def test_empty_scene_is_not_reported_as_rigged(self) -> None:
        summary = technical_candidate.skin_binding_summary([])
        self.assertEqual(summary["riggingState"], "UNRIGGED")


if __name__ == "__main__":
    unittest.main()
