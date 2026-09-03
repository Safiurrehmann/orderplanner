import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from extract_to_plan_sheet import extract_artwork_crops


class ArtworkExtractionTests(unittest.TestCase):
    def _save_fixture(self, draw_fixture):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        path = Path(temporary_directory.name) / "spec-sheet.png"
        image = Image.new("RGB", (1508, 1134), "white")
        draw_fixture(ImageDraw.Draw(image))
        image.save(path)
        return path

    def test_belvedere_keeps_complete_panels_separate(self):
        def draw(drawer):
            # Real Belvedere panel interiors: front x=26..416, back x=439..1484,
            # both y=638..923. The colored edge bands catch either a clipped
            # panel or one crop leaking into its neighbour.
            drawer.rectangle((23, 634, 419, 926), outline="black", width=4)
            drawer.rectangle((26, 638, 416, 923), fill=(80, 130, 220))
            drawer.rectangle((397, 638, 416, 923), fill=(70, 190, 110))
            drawer.rectangle((435, 634, 1488, 926), outline="black", width=4)
            drawer.rectangle((439, 638, 1484, 923), fill=(210, 90, 90))
            drawer.rectangle((439, 638, 458, 923), fill=(240, 190, 20))

        crops = extract_artwork_crops(self._save_fixture(draw))

        self.assertIsNotNone(crops)
        front = Image.open(io.BytesIO(crops[0]))
        back = Image.open(io.BytesIO(crops[1]))
        self.assertEqual((391, 286), front.size)
        self.assertEqual((1046, 286), back.size)
        self.assertEqual((70, 190, 110), front.getpixel((front.width - 1, 100)))
        self.assertEqual((240, 190, 20), back.getpixel((0, 100)))

    def test_flannigan_uses_its_wider_and_higher_front_panel(self):
        def draw(drawer):
            # Flannigan's artwork row starts higher and its divider is farther
            # right than Belvedere's.
            drawer.rectangle((23, 605, 513, 926), outline="black", width=4)
            drawer.rectangle((26, 609, 509, 923), fill=(85, 125, 215))
            drawer.rectangle((490, 609, 509, 923), fill=(70, 185, 105))
            drawer.rectangle((548, 605, 1488, 926), outline="black", width=4)
            drawer.rectangle((551, 609, 1484, 923), fill=(205, 85, 85))
            drawer.rectangle((551, 609, 570, 923), fill=(235, 185, 15))

        crops = extract_artwork_crops(self._save_fixture(draw))

        self.assertIsNotNone(crops)
        front = Image.open(io.BytesIO(crops[0]))
        back = Image.open(io.BytesIO(crops[1]))
        self.assertEqual((484, 315), front.size)
        self.assertEqual((934, 315), back.size)
        self.assertEqual((70, 185, 105), front.getpixel((front.width - 1, 100)))
        self.assertEqual((235, 185, 15), back.getpixel((0, 100)))


if __name__ == "__main__":
    unittest.main()
