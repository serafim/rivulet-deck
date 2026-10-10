"""Artwork: sizes match what the deck asks for, and the trend graph tracks the window."""

import pytest
from PIL import ImageColor

from rivulet_deck import render

SHIPPED_LABELS = ["CPU", "CPU TEMP", "CPU CLOCK", "RAM", "GPU", "GPU TEMP", "GPU POWER", "VRAM"]


def _band(image):
    """The rectangle render_metric reserves for the trend graph, recomputed from its own geometry."""
    width, height = image.size
    padding = max(3, height // 16)
    bottom = height - padding
    return padding, bottom - max(14, height // 4), width - padding, bottom


def _graph_ink(image) -> list[tuple[int, int]]:
    """Band pixels the graph drew over.

    The band is rendered supersampled and downscaled with LANCZOS, so blended pixels rarely match
    the requested colour exactly; "not the empty track" is the assertion that survives that.
    """
    left, top, right, bottom = _band(image)
    track = ImageColor.getrgb(render._TREND_TRACK)
    pixels = image.convert("RGB").load()
    return [
        (x, y)
        for y in range(top, bottom + 1)
        for x in range(left, right + 1)
        if pixels[x, y] != track
    ]


def _band_pixels(image) -> list[tuple[int, int, int]]:
    left, top, right, bottom = _band(image)
    pixels = image.convert("RGB").load()
    return [pixels[x, y] for y in range(top, bottom + 1) for x in range(left, right + 1)]


def _exact(image, rgb: tuple[int, int, int]) -> list[tuple[int, int]]:
    pixels = image.convert("RGB").load()
    return [
        (x, y)
        for y in range(image.height)
        for x in range(image.width)
        if pixels[x, y] == rgb
    ]


def _bbox(points: list[tuple[int, int]]) -> tuple[int, int, int, int]:
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def _distance(a, b) -> float:
    return sum((p - q) ** 2 for p, q in zip(a, b, strict=True)) ** 0.5


def _metric(neo, value="10", unit="%", color=render._FOREGROUND, samples=()):
    return render.render_metric(neo, "T", value, unit, color, samples)


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


def test_an_empty_window_leaves_the_graph_band_empty(neo):
    left, top, right, bottom = _band(_metric(neo))
    band = _band_pixels(_metric(neo))

    assert set(band) == {ImageColor.getrgb(render._TREND_TRACK)}
    assert ImageColor.getrgb(render._TREND_TRACK) != ImageColor.getrgb(render._BACKGROUND)
    assert (left, top, right, bottom) == (6, 66, 90, 90)


def test_the_graph_grows_as_history_accumulates(neo):
    def filled(samples) -> int:
        return len(_graph_ink(_metric(neo, samples=samples)))

    assert filled((0.5,)) < filled((0.1, 0.4, 0.2, 0.9, 0.5, 0.7)) < filled(
        [index / 29 for index in range(30)]
    )


def test_the_newest_reading_sits_on_the_right_edge(neo):
    _, top, right, bottom = _band(_metric(neo))
    box = _bbox(_graph_ink(_metric(neo, samples=(0.5,))))

    # One reading is a dot, not a line, and the graph grows leftwards from "now".
    assert box[2] == right
    assert box[2] - box[0] < 12
    assert top <= box[1] <= box[3] <= bottom


def test_the_window_is_stretched_to_its_own_min_and_max(neo):
    top = _band(_metric(neo))[1]

    def highest(samples):
        return _bbox(_graph_ink(_metric(neo, samples=samples)))[1]

    # A window that only moved between 45 % and 55 % uses the band as fully as one that
    # swung from 0 % to 100 %: the shape is readable at any absolute level.
    assert highest((0.45, 0.55)) <= top + 1
    assert highest((0.0, 1.0)) <= top + 1


def test_a_flat_window_draws_a_level_line_through_the_middle(neo):
    _, top, _, bottom = _band(_metric(neo))
    box = _bbox(_graph_ink(_metric(neo, samples=(0.5,) * 10)))
    middle = (top + bottom) / 2

    assert abs(box[1] - middle) <= 5
    assert box[1] > top


def test_the_graph_is_tinted_with_the_slot_colour(neo):
    samples = (0.2, 0.6, 0.4, 0.35)
    amber = ImageColor.getrgb("#f7d154")
    blue = ImageColor.getrgb("#4c9be8")
    track = ImageColor.getrgb(render._TREND_TRACK)

    warm = _band_pixels(_metric(neo, color="#f7d154", samples=samples))
    cold = _band_pixels(_metric(neo, color="#4c9be8", samples=samples))

    assert warm != cold
    brightest = max(warm, key=lambda pixel: _distance(pixel, track))
    assert _distance(brightest, amber) < _distance(brightest, blue)


def test_the_value_is_lifted_into_the_space_left_by_the_graph(neo):
    amber = ImageColor.getrgb("#f7d154")
    band_top = _band(_metric(neo))[1]
    box = _bbox(_exact(_metric(neo, color="#f7d154"), amber))

    assert box[3] < band_top
    assert (box[1] + box[3]) / 2 < neo.key_image_format()["size"][1] / 2


def test_the_unit_changes_the_artwork(neo):
    with_unit = _metric(neo, value="8.0", unit="/16G").tobytes()
    without_unit = _metric(neo, value="8.0", unit="").tobytes()
    assert with_unit != without_unit
