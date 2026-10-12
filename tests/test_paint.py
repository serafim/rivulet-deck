"""paint() and clear() against a simulated Neo: what gets written, and in which format."""

import re

import pytest
from StreamDeck.ImageHelpers.PILHelper import to_native_key_format

import rivulet_deck
from rivulet_deck import render


@pytest.fixture
def written(neo, monkeypatch):
    """Capture the deck writes instead of opening the dummy transport."""
    keys: dict[int, bytes] = {}
    screens: list[bytes] = []
    monkeypatch.setattr(neo, "set_key_image", lambda key, image: keys.__setitem__(key, image))
    monkeypatch.setattr(neo, "set_screen_image", lambda image: screens.append(image))
    return keys, screens


@pytest.fixture
def blank_key(neo):
    return to_native_key_format(neo, render.render_key(neo, ""))


def test_paint_writes_one_image_per_key_and_one_strip(neo, written, snapshot, dashboard, trends):
    keys, screens = written
    rivulet_deck.paint(neo, snapshot, dashboard, trends)

    assert sorted(keys) == list(range(neo.key_count()))
    assert all(isinstance(image, bytes) and image for image in keys.values())
    assert len(screens) == 1 and isinstance(screens[0], bytes)


def test_keys_without_a_slot_are_blanked(
    neo, written, blank_key, make_config, make_slot, snapshot, trends
):
    keys, _ = written
    rivulet_deck.paint(neo, snapshot, make_config(*(make_slot() for _ in range(3))), trends)

    assert sorted(keys) == list(range(neo.key_count()))
    assert [keys[key] for key in range(3, neo.key_count())] == [blank_key] * (neo.key_count() - 3)
    assert keys[0] != blank_key


def test_slots_beyond_the_key_count_are_ignored(
    neo, written, make_config, make_slot, snapshot, trends
):
    keys, _ = written
    rivulet_deck.paint(
        neo, snapshot, make_config(*(make_slot() for _ in range(neo.key_count() + 2))), trends
    )

    assert sorted(keys) == list(range(neo.key_count()))


def test_the_threshold_colour_reaches_the_artwork(
    neo, written, make_snapshot, dashboard, make_trends
):
    keys, _ = written
    rivulet_deck.paint(neo, make_snapshot(cpu_percent=10.0), dashboard, make_trends())
    calm = keys[0]
    # A fresh history each time, so the only thing that can change the artwork is the colour.
    rivulet_deck.paint(neo, make_snapshot(cpu_percent=95.0), dashboard, make_trends())

    assert keys[0] != calm


def test_the_graph_accumulates_across_frames(neo, written, snapshot, dashboard, trends):
    keys, _ = written
    rivulet_deck.paint(neo, snapshot, dashboard, trends)
    first = keys[0]
    rivulet_deck.paint(neo, snapshot, dashboard, trends)

    # Same telemetry, so the only difference is the second reading joining the window.
    assert keys[0] != first


def test_a_slot_without_telemetry_keeps_an_empty_graph(
    neo, written, make_snapshot, dashboard, trends
):
    keys, _ = written
    for _ in range(3):
        rivulet_deck.paint(neo, make_snapshot(cpu_percent=None), dashboard, trends)

    # A dropped reading clears the window rather than leaving a stale trend lit on the key.
    expected = to_native_key_format(
        neo, render.render_metric(neo, "CPU", "n/a", "%", rivulet_deck._MISSING)
    )
    assert keys[0] == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (None, "n/a"),
        (0.0, "0:00:00:00"),
        (59.9, "0:00:00:59"),
        (3600.0, "0:01:00:00"),
        (86_399.0, "0:23:59:59"),
        (86_400.0, "1:00:00:00"),
        (1_234_567.89, "14:06:56:07"),
        (950_400.0, "11:00:00:00"),
    ],
)
def test_uptime_is_days_hours_minutes_seconds_with_zero_padded_tail(seconds, expected):
    assert rivulet_deck._format_uptime(seconds) == expected


def test_the_strip_shows_the_uptime_and_a_clock(
    neo, written, dashboard, snapshot, trends, monkeypatch
):
    seen: list[str] = []
    draw_strip = render.render_screen

    def recording(deck, text, **kwargs):
        seen.append(text)
        return draw_strip(deck, text, **kwargs)

    monkeypatch.setattr(rivulet_deck, "render_screen", recording)
    rivulet_deck.paint(neo, snapshot, dashboard, trends)

    assert len(seen) == 1
    assert "14:06:56:07" in seen[0]
    assert re.search(r"\d{2}:\d{2}:\d{2}$", seen[0])


def test_the_strip_template_still_offers_the_deck_type(
    neo, written, make_config, make_slot, snapshot, trends, monkeypatch
):
    seen: list[str] = []
    draw_strip = render.render_screen

    def recording(deck, text, **kwargs):
        seen.append(text)
        return draw_strip(deck, text, **kwargs)

    monkeypatch.setattr(rivulet_deck, "render_screen", recording)
    layout = make_config(make_slot(), strip_format="{deck} {uptime} {time:%H:%M:%S}")
    rivulet_deck.paint(neo, snapshot, layout, trends)

    assert re.fullmatch(r"Stream Deck Neo 14:06:56:07 \d{2}:\d{2}:\d{2}", seen[0])


def test_clear_blanks_every_key_and_leaves_the_strip_alone(neo, written, blank_key):
    keys, screens = written
    rivulet_deck.clear(neo)

    assert sorted(keys) == list(range(neo.key_count()))
    assert all(image == blank_key for image in keys.values())
    assert screens == []


def test_the_dummy_neo_reports_the_layout_the_dashboard_assumes(neo):
    assert neo.key_layout() == (2, 4)
    assert neo.key_count() == 8
    assert neo.is_visual()
    assert neo.screen_image_format()["size"] == (248, 58)
    assert neo.key_image_format()["size"] == (96, 96)
