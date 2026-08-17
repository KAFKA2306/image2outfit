import unittest

from tools.delete_previous_artifacts import is_previous


class ArtifactReplacementTests(unittest.TestCase):
    def test_current_name_matches(self) -> None:
        self.assertTrue(is_previous("image2outfit-hosted-demo", "image2outfit-hosted-demo"))

    def test_legacy_run_suffix_matches(self) -> None:
        self.assertTrue(
            is_previous(
                "image2outfit-hosted-demo-31778430459",
                "image2outfit-hosted-demo",
            )
        )

    def test_other_logical_output_does_not_match(self) -> None:
        self.assertFalse(
            is_previous(
                "image2outfit-hosted-other-31778430459",
                "image2outfit-hosted-demo",
            )
        )

    def test_non_run_suffix_does_not_match(self) -> None:
        self.assertFalse(
            is_previous(
                "image2outfit-hosted-demo-preview",
                "image2outfit-hosted-demo",
            )
        )


if __name__ == "__main__":
    unittest.main()
