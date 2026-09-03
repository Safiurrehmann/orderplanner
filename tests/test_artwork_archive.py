import io
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from artwork_archive import ArchiveError, read_artwork_archive


def make_zip(entries):
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for path, data in entries:
            archive.writestr(path, data)
    return stream.getvalue()


class ArtworkArchiveTests(unittest.TestCase):
    def test_reads_supported_files_recursively(self):
        entries = read_artwork_archive(make_zip([
            ("PO/Back/UNC.pdf", b"%PDF-test"),
            ("PO/.DS_Store", b"metadata"),
            ("PO/notes.txt", b"notes"),
        ]))
        self.assertEqual(["PO/Back/UNC.pdf"], [entry.path for entry in entries])

    def test_rejects_parent_traversal(self):
        with self.assertRaisesRegex(ArchiveError, "unsafe path"):
            read_artwork_archive(make_zip([("../outside.jpg", b"image")]))

    def test_rejects_nested_archive(self):
        with self.assertRaisesRegex(ArchiveError, "nested archive"):
            read_artwork_archive(make_zip([("PO/more.zip", b"PK")]))


if __name__ == "__main__":
    unittest.main()
