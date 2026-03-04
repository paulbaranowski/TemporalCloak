import os
import random
from dataclasses import dataclass
import humanize


@dataclass
class ImageFile:
    path: str
    size: int

    def __str__(self) -> str:
        return "Size: {}  Path: {}".format(
            humanize.naturalsize(self.size, True, False, "%.2f"), self.path
        )


class ImageProvider:
    def __init__(self, images_dir: str = "content/images/"):
        self._images_dir = images_dir

    @property
    def images_dir(self) -> str:
        return self._images_dir

    def get_random_image(self) -> ImageFile:
        """Returns a random ImageFile from the images directory."""
        files = os.listdir(self._images_dir)
        random_file = random.choice(files)
        full_path = os.path.join(self._images_dir, random_file)
        file_size = os.path.getsize(full_path)
        image = ImageFile(path=full_path, size=file_size)
        print(image)
        return image

    def __str__(self) -> str:
        return f"ImageProvider(images_dir='{self._images_dir}')"

    def __repr__(self) -> str:
        return f"ImageProvider(images_dir='{self._images_dir}')"
