import random
from pathlib import Path

from palworld_bot import pals


def _make_files(directory: Path, names: list[str]) -> None:
    for name in names:
        (directory / name).write_bytes(b"fake-image-bytes")


def test_list_filters_by_extension_and_sorts(tmp_path: Path) -> None:
    _make_files(tmp_path, ["b.JPG", "a.png", "c.webp", "notes.txt", "d.gif"])
    (tmp_path / "sub").mkdir()  # directories are ignored
    names = [p.name for p in pals.list_pal_images(tmp_path)]
    assert names == ["a.png", "b.JPG", "c.webp", "d.gif"]


def test_list_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert pals.list_pal_images(tmp_path / "does-not-exist") == []


def test_draw_returns_a_member(tmp_path: Path) -> None:
    _make_files(tmp_path, ["a.png", "b.png", "c.png"])
    picked = pals.draw_pal_image(tmp_path)
    assert picked is not None
    assert picked.parent == tmp_path
    assert picked.suffix.lower() in pals.IMAGE_EXTENSIONS


def test_draw_is_deterministic_with_seed(tmp_path: Path) -> None:
    _make_files(tmp_path, ["a.png", "b.png", "c.png", "d.png"])
    first = pals.draw_pal_image(tmp_path, random.Random(42))  # noqa: S311 - deterministic test
    second = pals.draw_pal_image(tmp_path, random.Random(42))  # noqa: S311 - deterministic test
    assert first == second


def test_draw_empty_returns_none(tmp_path: Path) -> None:
    assert pals.draw_pal_image(tmp_path) is None


def test_is_mystery_pal_matches_only_question_marks() -> None:
    assert pals.is_mystery_pal(Path("？？？.png"))  # full-width U+FF1F
    assert pals.is_mystery_pal(Path("？.png"))
    assert pals.is_mystery_pal(Path("???.jpg"))  # half-width
    assert not pals.is_mystery_pal(Path("pal1.png"))
    assert not pals.is_mystery_pal(Path("pal？.png"))
