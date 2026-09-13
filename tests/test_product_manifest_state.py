from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import product_manifest_state as state  # noqa: E402
import production_contract  # noqa: E402


class ProductManifestStateTest(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, dict, dict]:
        job = {
            "id": "demo",
            "buildRevision": "r7",
            "productRoot": "Assets/GenWorks/demo",
            "productManifestPath": "Assets/GenWorks/demo/ProductManifest.json",
        }
        job_path = root / "config" / "products" / "demo" / "job.json"
        job_path.parent.mkdir(parents=True)
        job_path.write_text(json.dumps(job), encoding="utf-8")
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
        manifest_path = root / job["productManifestPath"]
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        evidence = manifest_path.parent / "Evidence" / "Unity" / "unity-ready.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text('{"passed": true}\n', encoding="utf-8")
        payload = {
            "status": "VERIFIED",
            "multiMaterialSetup": "VERIFIED",
            "modularAvatarSetup": "VERIFIED",
            "ndmfBake": "VERIFIED",
            "reimport": "VERIFIED",
            "targetAvatarAssetPath": "Assets/Avatar.prefab",
            "materialRoles": {"body": "Body"},
            "evidencePath": "Assets/GenWorks/demo/Evidence/Unity/unity-ready.json",
            "evidenceSha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        }
        return manifest_path, job, payload

    @staticmethod
    def _proposed(manifest_path: Path, payload: dict) -> dict:
        proposed = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name in state.UNITY_GATE_NAMES:
            proposed["technicalGates"][name] = "PASS"
        proposed.setdefault("releaseReadiness", {})["unityReady"] = copy.deepcopy(
            payload
        )
        return proposed

    def test_valid_update_uses_canonical_completion_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, job, payload = self._fixture(root)
            state.replace_legacy_snapshot(
                manifest_path, self._proposed(manifest_path, payload), root=root
            )
            stored = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["releaseReadiness"]["unityReady"], payload)
            self.assertTrue(
                all(
                    stored["technicalGates"][name] == "PASS"
                    for name in state.UNITY_GATE_NAMES
                )
            )
            self.assertEqual(production_contract.product_state_errors(job, root), [])

    def test_stale_identity_and_unknown_kind_leave_manifest_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, job, payload = self._fixture(root)
            before = manifest_path.read_bytes()
            common = {
                "manifest_path": manifest_path,
                "job": job,
                "root": root,
            }
            with self.assertRaisesRegex(ValueError, "product identity mismatch"):
                state.apply_update(
                    **common,
                    intent={
                        "kind": "unity-ready",
                        "productId": "wrong",
                        "buildRevision": "r7",
                        "expectedManifestSha256": hashlib.sha256(before).hexdigest(),
                        "payload": payload,
                    },
                )
            self.assertEqual(manifest_path.read_bytes(), before)
            with self.assertRaisesRegex(
                ValueError, "unknown ProductManifest update kind"
            ):
                state.apply_update(
                    **common,
                    intent={
                        "kind": "complete",
                        "productId": "demo",
                        "buildRevision": "r7",
                        "expectedManifestSha256": hashlib.sha256(before).hexdigest(),
                        "payload": payload,
                    },
                )
            self.assertEqual(manifest_path.read_bytes(), before)

    def test_stale_revision_or_hash_leave_manifest_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, job, payload = self._fixture(root)
            before = manifest_path.read_bytes()
            base = {
                "kind": "unity-ready",
                "productId": "demo",
                "expectedManifestSha256": hashlib.sha256(before).hexdigest(),
                "payload": payload,
            }
            with self.assertRaisesRegex(ValueError, "revision mismatch"):
                state.apply_update(
                    manifest_path=manifest_path,
                    job=job,
                    intent={**base, "buildRevision": "stale"},
                    root=root,
                )
            self.assertEqual(manifest_path.read_bytes(), before)
            with self.assertRaisesRegex(ValueError, "manifest SHA-256 mismatch"):
                state.apply_update(
                    manifest_path=manifest_path,
                    job=job,
                    intent={
                        **base,
                        "buildRevision": "r7",
                        "expectedManifestSha256": "0" * 64,
                    },
                    root=root,
                )
            self.assertEqual(manifest_path.read_bytes(), before)

    def test_derived_completion_override_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, _, payload = self._fixture(root)
            before = manifest_path.read_bytes()
            proposed = self._proposed(manifest_path, payload)
            proposed["state"] = "COMPLETE"
            with self.assertRaisesRegex(
                ValueError, "direct ProductManifest field mutation"
            ):
                state.replace_legacy_snapshot(manifest_path, proposed, root=root)
            self.assertEqual(manifest_path.read_bytes(), before)

    def test_fault_before_atomic_replace_preserves_valid_previous_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, _, payload = self._fixture(root)
            before = manifest_path.read_bytes()

            def fail(_staged: Path, _target: Path) -> None:
                raise OSError("injected before os.replace")

            with self.assertRaisesRegex(OSError, "injected"):
                state.replace_legacy_snapshot(
                    manifest_path,
                    self._proposed(manifest_path, payload),
                    root=root,
                    before_replace=fail,
                )
            self.assertEqual(manifest_path.read_bytes(), before)
            json.loads(manifest_path.read_text(encoding="utf-8"))

    def test_allowed_update_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path, _, payload = self._fixture(root)
            state.replace_legacy_snapshot(
                manifest_path, self._proposed(manifest_path, payload), root=root
            )
            first = manifest_path.read_bytes()
            state.replace_legacy_snapshot(
                manifest_path, self._proposed(manifest_path, payload), root=root
            )
            self.assertEqual(manifest_path.read_bytes(), first)

    def test_generic_json_writer_routes_product_manifest_to_single_owner(self) -> None:
        contract_source = (TOOLS / "contract_io.py").read_text(encoding="utf-8")
        candidate_source = (TOOLS / "technical_candidate.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('path.name == "ProductManifest.json"', contract_source)
        self.assertIn("product_manifest_state.replace_legacy_snapshot", contract_source)
        self.assertNotIn(".replace(manifest_path)", candidate_source)
        self.assertNotIn("manifest_path.write_text", candidate_source)


if __name__ == "__main__":
    unittest.main()
