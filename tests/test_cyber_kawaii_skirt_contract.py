from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import cyber_kawaii_skirt_contract as contract


class CyberKawaiiSkirtContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = (
            ROOT
            / "Assets/GenWorks/siroino-cyber-kawaii-large/Source/Patterns/"
            "cyber-kawaii-skirt.pattern.json"
        )
        self.data = contract.load_contract(self.path)

    def test_contract_stages_and_layers_are_complete(self) -> None:
        self.assertEqual(tuple(self.data["stages"]), contract.REQUIRED_STAGES)
        self.assertEqual(
            tuple(self.data["silhouetteProfiles"]),
            contract.REQUIRED_LAYERS,
        )

    def test_contract_preserves_reviewed_v6_silhouette(self) -> None:
        self.assertEqual(
            contract.silhouette_profiles(self.data),
            {
                "Black_Pink_Plaid_Pleated_Skirt": {
                    "topScale": 0.985,
                    "bottomScale": 0.835,
                    "pleatScale": 0.56,
                    "zOffset": -0.006,
                },
                "White_Ruffle_Underskirt": {
                    "topScale": 0.9,
                    "bottomScale": 0.86,
                    "pleatScale": 0.62,
                    "zOffset": -0.004,
                },
                "Black_Skirt_Waistband": {
                    "topScale": 0.975,
                    "bottomScale": 0.965,
                    "pleatScale": 0.5,
                    "zOffset": -0.008,
                },
                "Pink_Underskirt_Hem": {
                    "topScale": 0.885,
                    "bottomScale": 0.855,
                    "pleatScale": 0.58,
                    "zOffset": -0.004,
                },
            },
        )

    def test_missing_external_evidence_stays_pending(self) -> None:
        evidence = contract.evidence_state(ROOT, self.path, self.data)
        self.assertEqual(evidence.pattern_contract, "PASS")
        self.assertEqual(evidence.garment_code, "PENDING")
        self.assertEqual(evidence.zozo_contact_solver, "PENDING")
        self.assertEqual(evidence.material_maker_source, "PENDING")

    def test_material_maker_commands_match_official_cli_shape(self) -> None:
        commands = contract.material_maker_commands(self.data, ROOT)
        self.assertEqual(len(commands), 4)
        for command in commands:
            self.assertEqual(
                command[1:4],
                ["--export-material", "--target", "Blender"],
            )
            self.assertIn("-o", command)
            self.assertTrue(command[-1].endswith(".ptex"))

    def test_rejects_seam_reference_to_unknown_panel(self) -> None:
        invalid = copy.deepcopy(self.data)
        invalid["construction"]["seams"][0]["pair"][0] = "missing.side"
        with self.assertRaisesRegex(ValueError, "missing panel"):
            contract.validate_contract(invalid)

    def test_tracked_manifest_keeps_reviewed_visual_revision(self) -> None:
        manifest_path = (
            ROOT
            / "Assets/GenWorks/siroino-cyber-kawaii-large/ProductManifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["designRevision"],
            "v6-large-fitted-skirt-silhouette",
        )


if __name__ == "__main__":
    unittest.main()
