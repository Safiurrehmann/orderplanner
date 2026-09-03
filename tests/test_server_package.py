import unittest
import io
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

import server


class ServerPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)

    def test_belvedere_zip_enriches_generated_workbook(self):
        root = Path("/Users/mac/Documents/personal projects/primeKnitwear/docs")
        po = root / "PurchaseOrder 73498 Belvedere.pdf"
        package = root / "PK73498 [IBS] [PBX].zip"
        with po.open("rb") as handle:
            response = self.client.post(
                "/api/convert", data={"format": "belvedere"},
                files={"pdfs": (po.name, handle, "application/pdf")},
            )
        self.assertEqual(200, response.status_code, response.text)
        session_id = response.json()["session_id"]
        with package.open("rb") as handle:
            response = self.client.post(
                "/api/enrich", data={"session_id": session_id},
                files={"package": (package.name, handle, "application/zip")},
            )
        self.assertEqual(200, response.status_code, response.text)
        result = response.json()
        self.assertEqual(18, result["matched_count"])
        self.assertEqual(33, result["slot_count"])
        workbook = self.client.get(result["download_url"])
        self.assertEqual(200, workbook.status_code)
        self.assertTrue(workbook.content.startswith(b"PK"))
        with ZipFile(io.BytesIO(workbook.content)) as archive:
            embedded = [name for name in archive.namelist() if name.startswith("xl/media/")]
        self.assertEqual(18, len(embedded))


if __name__ == "__main__":
    unittest.main()
