"""Pal image pool for the ``/取引`` (trade) command.

The pool is simply whatever image files live in the trade directory, so the
number of possible Pals grows just by dropping more images in. No network
access and no shell; picking is a pure function for easy testing.
"""

from __future__ import annotations

import random
from pathlib import Path

DEFAULT_PAL_IMAGE_DIR = Path(__file__).resolve().parent / "assets" / "pals"

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})

# The "mystery" Pal: an image whose filename is nothing but question marks
# (full-width ？ U+FF1F or half-width ?). Drawing it earns a special line.
_QUESTION_MARKS = frozenset("？?")


def is_mystery_pal(path: Path) -> bool:
    """True when the image's filename (without extension) is only question marks."""
    stem = path.stem
    return bool(stem) and all(char in _QUESTION_MARKS for char in stem)


def list_pal_images(directory: Path) -> list[Path]:
    """Return image files in ``directory`` (non-recursive), sorted by name."""
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def draw_pal_image(directory: Path, rng: random.Random | None = None) -> Path | None:
    """Pick a random image from ``directory``; return None when there are none."""
    images = list_pal_images(directory)
    if not images:
        return None
    chooser = rng if rng is not None else random
    return chooser.choice(images)
