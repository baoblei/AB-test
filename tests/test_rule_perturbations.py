import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.rule_perturbations import (
    clone_region,
    save_jpeg_contract,
    tint_region,
    warp_region,
)


class RulePerturbationTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new("RGB", (100, 100), "white")
        for x in range(20, 40):
            for y in range(20, 40):
                self.image.putpixel((x, y), (200, 20, 20))

    def test_warp_region_changes_only_requested_box(self):
        result = warp_region(self.image, (20, 20, 40, 40), x_scale=0.55, y_shift=3)
        self.assertEqual(result.getpixel((5, 5)), (255, 255, 255))
        self.assertNotEqual(
            list(result.crop((20, 20, 40, 40)).getdata()),
            list(self.image.crop((20, 20, 40, 40)).getdata()),
        )

    def test_clone_region_moves_copy_to_target(self):
        result = clone_region(self.image, (20, 20, 40, 40), (60, 60, 80, 80))
        self.assertEqual(result.getpixel((70, 70)), (200, 20, 20))
        self.assertEqual(result.getpixel((10, 10)), (255, 255, 255))

    def test_tint_region_preserves_pixels_outside_box(self):
        result = tint_region(self.image, (20, 20, 40, 40), (0, 0, 255), 0.75)
        self.assertEqual(result.getpixel((5, 5)), (255, 255, 255))
        self.assertGreater(result.getpixel((25, 25))[2], self.image.getpixel((25, 25))[2])

    def test_save_jpeg_contract_writes_normalized_fixture(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "result.jpg"
            save_jpeg_contract(Image.new("RGBA", (320, 640), (30, 60, 90, 128)), destination)
            with Image.open(destination) as saved:
                self.assertEqual(saved.format, "JPEG")
                self.assertEqual(saved.mode, "RGB")
                self.assertEqual(saved.size, (768, 768))
                self.assertFalse(saved.getexif())


if __name__ == "__main__":
    unittest.main()
