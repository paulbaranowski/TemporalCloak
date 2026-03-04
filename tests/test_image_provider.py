import unittest
import os
from temporal_cloak.image_provider import ImageProvider, ImageFile


class TestImageFile(unittest.TestCase):
    """Tests for the ImageFile dataclass."""

    def test_fields(self):
        img = ImageFile(path="/tmp/test.jpg", size=1024)
        self.assertEqual(img.path, "/tmp/test.jpg")
        self.assertEqual(img.size, 1024)

    def test_str_contains_path_and_size(self):
        img = ImageFile(path="content/images/photo.jpg", size=2048)
        s = str(img)
        self.assertIn("photo.jpg", s)
        self.assertIn("2.00 KiB" if "KiB" in s else "KB", s)


class TestImageProvider(unittest.TestCase):
    """Tests for ImageProvider using the real images directory."""

    def setUp(self):
        self.provider = ImageProvider()

    def test_get_random_image_returns_imagefile(self):
        image = self.provider.get_random_image()
        self.assertIsInstance(image, ImageFile)

    def test_image_has_valid_path(self):
        image = self.provider.get_random_image()
        self.assertTrue(os.path.isfile(image.path))

    def test_image_has_positive_size(self):
        image = self.provider.get_random_image()
        self.assertGreater(image.size, 0)

    def test_missing_directory_raises(self):
        provider = ImageProvider(images_dir="nonexistent/")
        with self.assertRaises(FileNotFoundError):
            provider.get_random_image()

    def test_str(self):
        self.assertIn("ImageProvider", str(self.provider))

    def test_repr(self):
        self.assertIn("images_dir=", repr(self.provider))


if __name__ == '__main__':
    unittest.main()
