from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import visual_quality


class FakeScene(SimpleNamespace):
    def get(self, key: str, default=None):
        return getattr(self, key, default)


def fake_scene(
    *,
    width: int = 640,
    height: int = 480,
    samples: int = 16,
    threshold: float = 0.1,
) -> FakeScene:
    return FakeScene(
        render=SimpleNamespace(
            engine="BLENDER_EEVEE_NEXT",
            resolution_x=width,
            resolution_y=height,
            resolution_percentage=50,
            image_settings=SimpleNamespace(
                file_format="JPEG",
                color_mode="RGB",
                color_depth="8",
            ),
            film_transparent=True,
        ),
        cycles=SimpleNamespace(
            samples=samples,
            use_denoising=False,
            use_adaptive_sampling=False,
            adaptive_threshold=threshold,
        ),
        view_settings=SimpleNamespace(
            view_transform="Standard",
            look="Medium High Contrast",
        ),
    )


class VisualQualityDefaultsTest(unittest.TestCase):
    def test_profile_loads(self) -> None:
        profile = visual_quality.load_profile()
        self.assertEqual(profile["schemaVersion"], 1)
        self.assertEqual(profile["profileId"], "product-render-quality-v1")
        self.assertEqual(profile["render"]["engine"], "CYCLES")

    def test_scene_defaults_raise_quality_floor_and_preserve_aspect(self) -> None:
        scene = fake_scene()
        report = visual_quality.apply_scene_defaults(scene)

        self.assertTrue(report["applied"])
        self.assertEqual(scene.render.engine, "CYCLES")
        self.assertEqual(
            (scene.render.resolution_x, scene.render.resolution_y), (1024, 768)
        )
        self.assertEqual(scene.render.resolution_percentage, 100)
        self.assertEqual(scene.cycles.samples, 64)
        self.assertEqual(scene.cycles.adaptive_threshold, 0.02)
        self.assertTrue(scene.cycles.use_denoising)
        self.assertTrue(scene.cycles.use_adaptive_sampling)
        self.assertEqual(scene.render.image_settings.file_format, "PNG")
        self.assertEqual(scene.view_settings.view_transform, "AgX")

    def test_scene_defaults_do_not_lower_existing_quality(self) -> None:
        scene = fake_scene(width=2048, height=1024, samples=192, threshold=0.008)
        visual_quality.apply_scene_defaults(scene)

        self.assertEqual(
            (scene.render.resolution_x, scene.render.resolution_y), (2048, 1024)
        )
        self.assertEqual(scene.cycles.samples, 192)
        self.assertEqual(scene.cycles.adaptive_threshold, 0.008)

    def test_scene_can_explicitly_opt_out(self) -> None:
        scene = fake_scene()
        scene.image2outfit_visual_quality_opt_out = True
        report = visual_quality.apply_scene_defaults(scene)

        self.assertFalse(report["applied"])
        self.assertEqual(scene.render.engine, "BLENDER_EEVEE_NEXT")
        self.assertEqual(
            (scene.render.resolution_x, scene.render.resolution_y), (640, 480)
        )

    def test_invalid_profile_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps({"schemaVersion": 2}), encoding="utf-8")
            with self.assertRaises(ValueError):
                visual_quality.load_profile(path)


if __name__ == "__main__":
    unittest.main()
