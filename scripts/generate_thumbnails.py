#!/usr/bin/env python3
"""Generate thumbnail images for the frontend image picker.

Usage:
    uv run python scripts/generate_thumbnails.py

Requires Pillow (included in project dependencies).
"""

import os
from PIL import Image

IMAGES_DIR = os.path.join(os.path.dirname(__file__), "..", "content", "images")
THUMBNAILS_DIR = os.path.join(IMAGES_DIR, "thumbnails")
MAX_SIZE = 400  # max dimension in pixels


def main():
    os.makedirs(THUMBNAILS_DIR, exist_ok=True)

    extensions = (".jpg", ".jpeg", ".png", ".gif", ".webp")
    count = 0

    for fname in sorted(os.listdir(IMAGES_DIR)):
        if not fname.lower().endswith(extensions):
            continue
        src = os.path.join(IMAGES_DIR, fname)
        if not os.path.isfile(src):
            continue

        dst = os.path.join(THUMBNAILS_DIR, fname)
        img = Image.open(src)
        img.thumbnail((MAX_SIZE, MAX_SIZE), Image.LANCZOS)
        img.save(dst, quality=85)
        count += 1
        print(f"  {fname}: {os.path.getsize(src) // 1024}KB -> {os.path.getsize(dst) // 1024}KB")

    print(f"\nGenerated {count} thumbnails in {THUMBNAILS_DIR}")


if __name__ == "__main__":
    main()
