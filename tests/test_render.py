"""Artwork: sizes match what the deck asks for, and the bar tracks the fraction."""

import pytest
from PIL import ImageColor

from rivulet_deck import render

SHIPPED_LABELS = ["CPU", "CPU TEMP", "CPU CLOCK", "RAM", "GPU", "GPU TEMP", "GPU POWER", "VRAM"]


def _bar_band(image):
    """The rows render_metric reserves for the fill bar, recomputed from its own geometry."""
    _, height = image.size
    padding = max(3, height // 16)
    bar_bottom = height - padding
    return bar_bottom - max(3, height // 24), bar_bottom


def _pixels_in_bar_band(image, rgb: tuple[int, int, int]) -> int:
    top, bottom = _bar_band(image)
    width = image.size[0]
    pixels = image.convert("RGB").load()
    return sum(1 for y in range(top, bottom + 1) for x in range(width) if pixels[x, y] == rgb)


def test_artwork_matches_the_formats_the_deck_asks_for(neo):
    assert render.render_key(neo, "CPU").size == neo.key_image_format()["size"]
    assert render.render_metric(neo, "CPU", "10", "%").size == neo.key_image_format()["size"]
    assert render.render_screen(neo, "Stream Deck Neo  12:34:56").size == (
        neo.screen_image_format()["size"]
    )


@pytest.mark.parametrize("label", SHIPPED_LABELS)
def test_every_shipped_label_is_drawn_as_ink(neo, label):
    darkest, lightest = render.render_key(neo, label).convert("L").getextrema()
    assert darkest < lightest


def test_a_blank_key_is_a_flat_background(neo):
    image = render.render_key(neo, "").convert("L")
    assert image.getextrema()[0] == image.getextrema()[1]


def test_the_strip_is_drawn_as_ink(neo):
    strip = render.render_screen(neo, "Stream Deck Neo  12:34:56").convert("L")
    darkest, lightest = strip.getextrema()
    assert darkest < lightest


def test_the_bar_grows_with_the_fraction(neo):
    ink = ImageColor.getrgb(render._FOREGROUND)

    def filled(fraction):
        image = render.render_metric(neo, "T", "10", "%", fraction=fraction)
        return _pixels_in_bar_band(image, ink)

    assert filled(0.0) < filled(0.25) < filled(0.5) < filled(1.0)


def test_a_full_bar_leaves_no_track_visible(neo):
    image = render.render_metric(neo, "T", "10", "%", fraction=1.0)
    assert _pixels_in_bar_band(image, ImageColor.getrgb(render._BAR_TRACK)) == 0


def test_fractions_outside_the_bar_are_clamped(neo):
    def tile(fraction):
        return render.render_metric(neo, "T", "10", "%", fraction=fraction).tobytes()

    assert tile(1.5) == tile(1.0)
    assert tile(-0.5) == tile(0.0)


def test_no_fraction_means_no_bar(neo):
    image = render.render_metric(neo, "T", "10", "%", fraction=None)
    assert _pixels_in_bar_band(image, ImageColor.getrgb(render._BAR_TRACK)) == 0


def test_the_unit_changes_the_artwork(neo):
    with_unit = render.render_metric(neo, "RAM", "8.0", "/16G").tobytes()
    without_unit = render.render_metric(neo, "RAM", "8.0").tobytes()
    assert with_unit != without_unit


def test_the_colour_is_used_for_the_value_and_the_bar(neo):
    amber = ImageColor.getrgb("#f7d154")
    image = render.render_metric(neo, "T", "90", "%", foreground="#f7d154", fraction=0.5)
    assert _pixels_in_bar_band(image, amber) > 0
