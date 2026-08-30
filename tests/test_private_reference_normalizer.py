from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import run_private_reference_normalizer as MODULE


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PrivateReferenceNormalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_root = MODULE.ROOT
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        MODULE.ROOT = self.root
        (self.root / "config/products/garment").mkdir(parents=True)
        (self.root / "Assets/_Local").mkdir(parents=True)
        self.source = self.root / "Assets/_Local/reference.png"
        image = Image.new("RGB", (8, 6), (10, 20, 30))
        for x in range(4, 8):
            for y in range(6):
                image.putpixel((x, y), (200, 40, 60))
        image.save(self.source)
        self.sha = digest(self.source)
        self.audit_path = self.root / "config/products/garment/reference-audit.json"
        self.audit_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "productId": "garment",
                    "source": {
                        "originalSha256": self.sha,
                        "widthPx": 8,
                        "heightPx": 6,
                    },
                    "variants": [
                        {"variantId": "left", "boundingBoxPx": [0, 0, 4, 6]},
                        {"variantId": "right", "boundingBoxPx": [4, 0, 8, 6]},
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.job = {
            "id": "garment",
            "privateSourceRoots": ["Assets/_Local"],
            "garmentPipeline": {
                "referenceAuditPath": "config/products/garment/reference-audit.json"
            },
        }
        self.request = {
            "sourceReference": f"private-reference://sha256/{self.sha}",
            "variables": {},
        }
        self.result = self.root / ".image2outfit/result.json"

    def tearDown(self) -> None:
        MODULE.ROOT = self.previous_root
        self.temp.cleanup()

    def test_normalize_discovers_actual_source_pixels_by_hash(self) -> None:
        payload = MODULE.normalize(self.job, self.request, self.result)
        self.assertTrue(payload["sourceBytesVerified"])
        self.assertEqual(payload["normalizationMethod"], "crop-from-private-source")

        left_path = self.root / ".image2outfit/products/garment/normalized/left.png"
        right_path = self.root / ".image2outfit/products/garment/normalized/right.png"
        with Image.open(left_path) as left, Image.open(right_path) as right:
            self.assertEqual(left.size, (4, 6))
            self.assertEqual(right.size, (4, 6))
            self.assertEqual(left.getpixel((1, 1)), (10, 20, 30))
            self.assertEqual(right.getpixel((1, 1)), (200, 40, 60))

    def test_missing_matching_private_source_fails_loudly(self) -> None:
        self.source.unlink()
        with self.assertRaisesRegex(FileNotFoundError, "no private reference image"):
            MODULE.normalize(self.job, self.request, self.result)

    def test_explicit_hash_mismatch_is_rejected(self) -> None:
        request = {
            "sourceReference": "private-reference://sha256/" + "0" * 64,
            "variables": {"privateReferencePath": str(self.source)},
        }
        audit = json.loads(self.audit_path.read_text(encoding="utf-8"))
        audit["source"]["originalSha256"] = "0" * 64
        self.audit_path.write_text(json.dumps(audit), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "private reference hash mismatch"):
            MODULE.normalize(self.job, request, self.result)

    def test_repository_local_source_outside_private_roots_is_rejected(self) -> None:
        public_source = self.root / "config/reference.png"
        public_source.parent.mkdir(parents=True, exist_ok=True)
        public_source.write_bytes(self.source.read_bytes())
        request = {
            "sourceReference": f"private-reference://sha256/{self.sha}",
            "variables": {"privateReferencePath": str(public_source)},
        }
        with self.assertRaisesRegex(ValueError, "privateSourceRoots"):
            MODULE.normalize(self.job, request, self.result)

    def test_duplicate_hash_matches_require_explicit_binding(self) -> None:
        duplicate = self.root / "Assets/_Local/duplicate.png"
        duplicate.write_bytes(self.source.read_bytes())
        with self.assertRaisesRegex(ValueError, "multiple private reference images"):
            MODULE.normalize(self.job, self.request, self.result)


if __name__ == "__main__":
    unittest.main()
