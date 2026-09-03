import io
import unittest

import fitz
from PIL import Image, ImageDraw

from artwork_archive import ArchiveEntry
from artwork_rendering import ArtworkRenderError, render_artwork


class ArtworkRenderingTests(unittest.TestCase):
    def test_trims_transparent_margin(self):
        image = Image.new("RGBA", (200, 160), (255, 255, 255, 0))
        ImageDraw.Draw(image).rectangle((70, 50, 129, 109), fill=(10, 80, 180, 255))
        stream = io.BytesIO(); image.save(stream, "PNG")
        rendered = render_artwork(ArchiveEntry("Front/UNC.png", stream.getvalue()))
        self.assertLess(rendered.width, 100)
        self.assertGreater(rendered.width, 60)

    def test_rejects_blank_raster(self):
        image = Image.new("RGB", (200, 160), "white")
        stream = io.BytesIO(); image.save(stream, "JPEG")
        with self.assertRaisesRegex(ArtworkRenderError, "blank"):
            render_artwork(ArchiveEntry("Front/UNC.jpg", stream.getvalue()))

    def test_renders_first_pdf_page(self):
        document = fitz.open(); page = document.new_page(width=200, height=100)
        page.draw_rect((40, 20, 160, 80), color=(0, 0, 1), fill=(0, 0, 1))
        rendered = render_artwork(ArchiveEntry("Back/UNC.pdf", document.tobytes()))
        self.assertTrue(rendered.png.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
