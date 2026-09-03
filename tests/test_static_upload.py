import unittest
from pathlib import Path


APP_JS = (Path(__file__).parents[1] / "static" / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (Path(__file__).parents[1] / "static" / "index.html").read_text(encoding="utf-8")


class StaticUploadTests(unittest.TestCase):
    def test_file_picker_does_not_reassign_its_file_list(self):
        """Picker selections must work where constructing DataTransfer is unsupported."""
        self.assertIn(
            "input.addEventListener('change', () => displayFiles(input.files));",
            APP_JS,
        )

    def test_upload_script_url_is_versioned_to_refresh_cached_browsers(self):
        self.assertIn('src="/static/app.js?v=2"', INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
