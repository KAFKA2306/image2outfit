from __future__ import annotations

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

    def test_contract_is_valid_and_ordered(self) -> None:
        data = contract.load_contract(self.path)
        self.assertEqual(
            tuple(item.object_name for item in contract.layer_specs(data)),
            contract.REQUIRED_LAYER_IDS,
        )

    def test_right_view_ease_is_lower_than_side_ease(self) -> None:
        data = contract.load_contract(self.path)
        for layer in contract.layer_specs(data):
            for ring in layer.rings:
                self.assertLessEqual(ring.ease_y, ring.ease_x)

    def test_resolved_rings_clear_body(self) -> None:
        data = contract.load_contract(self.path)
        sections = {"waist": (0.142, 0.104), "hip": (0.158, 0.119)}
        for layer in contract.layer_specs(data):
            rings = contract.resolve_rings(layer, sections)
            for ring, source in zip(rings, layer.rings):
                body_x, body_y = sections[source.anchor]
                self.assertGreater(ring[1], body_x)
                self.assertGreater(ring[2], body_y)

    def test_material_commands_use_official_cli_shape(self) -> None:
        data = contract.load_contract(self.path)
        commands = contract.material_maker_commands(data, ROOT)
        self.assertTrue(commands)
        for command in commands:
            self.assertEqual(
                command[1:4],
                ["--export-material", "--target", "Blender"],
            )
            self.assertIn("-o", command)

    def test_rejects_front_back_ease_larger_than_side_ease(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["layers"][1]["rings"][0]["easeY"] = 0.02
        with self.assertRaisesRegex(ValueError, "front/back ease"):
            contract.validate_contract(data)


if __name__ == "__main__":
    unittest.main()
