from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "tools" / "siroino_heather_hooded_fused_pose_probe.py"


class HeatherHoodedSitPoseContractTest(unittest.TestCase):
    def test_sit_direction_is_corrected_at_pose_generation_not_pages(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertIn('if name != "sit"', source)
        self.assertIn('"UpperLeg_L", (-78.0, 0.0, 4.0)', source)
        self.assertIn('"UpperLeg_R", (-78.0, 0.0, -4.0)', source)
        self.assertIn('"LowerLeg_L", (82.0, 0.0, 0.0)', source)
        self.assertIn('"LowerLeg_R", (82.0, 0.0, 0.0)', source)
        self.assertNotIn("scaleX(-1", source)
        self.assertNotIn("rotateY(180", source)


if __name__ == "__main__":
    unittest.main()
