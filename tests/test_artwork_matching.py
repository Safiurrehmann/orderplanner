import unittest

from artwork_matching import classify_candidate, required_positions


class ArtworkMatchingTests(unittest.TestCase):
    def test_belvedere_uses_folder_and_prefix(self):
        candidate = classify_candidate(
            "PK/Hood/AD EMBLUNC-6C.psd", {"UNC66804BCQ"}, "belvedere"
        )
        self.assertEqual(("UNC66804BCQ", "hood", "psd"),
                         (candidate.contract, candidate.position, candidate.kind))
        self.assertFalse(candidate.ambiguous)

    def test_flannigan_generic_artwork_folder_needs_no_position(self):
        candidate = classify_candidate(
            "PO/Artwork/AD CAL-1C.jpg", {"CAL65999FGA"}, "flannigan"
        )
        self.assertEqual(("CAL65999FGA", "front"),
                         (candidate.contract, candidate.position))

    def test_unrelated_substring_is_not_a_team_match(self):
        candidate = classify_candidate(
            "PO/Artwork/recall-notes.jpg", {"CAL65999FGA"}, "flannigan"
        )
        self.assertIsNone(candidate.contract)

    def test_conflicting_folder_and_prefix_is_ambiguous(self):
        candidate = classify_candidate(
            "PO/Hood/JR APFGNUNC-2C.pdf", {"UNC66804BCQ"}, "belvedere"
        )
        self.assertTrue(candidate.ambiguous)

    def test_required_positions_follow_format(self):
        self.assertEqual(("front",), required_positions("flannigan"))
        self.assertEqual(("back", "front"), required_positions("mocktail"))
        self.assertEqual(("back", "front", "hood"), required_positions("belvedere"))


if __name__ == "__main__":
    unittest.main()
