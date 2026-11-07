import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
WHOLE_TREE = re.compile(
    r"^\s*\$\{\{\s*env\.(?:PRODUCT_ROOT|REPORT_DIR|PRODUCT_RUNTIME|"
    r"PRODUCT_AUDIT|CANDIDATE_DIR|RELEASE_DIR)\s*\}\}\s*$",
    re.MULTILINE,
)


def upload_blocks(text: str) -> list[str]:
    return re.findall(
        r"uses:\s*actions/upload-artifact@[^\n]+(?P<body>.*?)(?=\n\s*-\s+(?:name:|uses:|run:)|\Z)",
        text,
        flags=re.DOTALL,
    )


class ArtifactStoragePolicyTests(unittest.TestCase):
    def test_artifact_workflows_keep_only_latest_minimal_output(self) -> None:
        checked = 0
        for workflow in sorted(WORKFLOWS.glob("*.y*ml")):
            text = workflow.read_text(encoding="utf-8")
            blocks = upload_blocks(text)
            if not blocks:
                continue
            checked += len(blocks)
            self.assertIn("actions: write", text, workflow)
            self.assertTrue(
                "tools/delete_previous_artifacts.py" in text
                or "github.rest.actions.deleteArtifact" in text,
                workflow,
            )
            for block in blocks:
                self.assertRegex(block, r"retention-days:\s*1(?:\s|$)", workflow)
                self.assertIn("overwrite: true", block, workflow)
                self.assertNotRegex(
                    block,
                    r"name:[^\n]*(?:github\.run_id|github\.run_number|github\.run_attempt)",
                    workflow,
                )
                self.assertIsNone(WHOLE_TREE.search(block), workflow)
                self.assertNotIn(".png", block.lower(), workflow)
                self.assertNotIn(".blend1", block.lower(), workflow)
                self.assertNotIn(".blend2", block.lower(), workflow)
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
