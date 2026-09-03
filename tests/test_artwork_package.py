import unittest
from pathlib import Path

from artwork_package import resolve_artwork_package


class ArtworkPackageTests(unittest.TestCase):
    def test_supplied_belvedere_zip_resolves_three_positions_for_six_teams(self):
        package = Path("/Users/mac/Documents/personal projects/primeKnitwear/docs/PK73498 [IBS] [PBX].zip")
        contracts = {
            "ECU66804BCQ", "NCS66804BCQ", "PSU66804BCQ",
            "UKY66804BCQ", "UNC66804BCQ", "UTN66804BCQ",
        }
        result = resolve_artwork_package(package.read_bytes(), "belvedere", contracts)
        self.assertEqual(18, len(result.slots))
        self.assertFalse([record for record in result.records if record.status != "matched"])
        self.assertTrue(all(record.path.lower().endswith(".pdf") for record in result.records))


if __name__ == "__main__":
    unittest.main()
