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


def test_paint_writes_one_image_per_key_and_one_strip(neo, written, snapshot, dashboard):
    keys, screens = written
    rivulet_deck.paint(neo, snapshot, dashboard)

    assert sorted(keys) == list(range(neo.key_count()))
    assert all(isinstance(image, bytes) and image for image in keys.values())
    assert len(screens) == 1 and isinstance(screens[0], bytes)


def test_keys_without_a_slot_are_blanked(neo, written, blank_key, make_config, make_slot, snapshot):
    keys, _ = written
    rivulet_deck.paint(neo, snapshot, make_config(*(make_slot() for _ in range(3))))

    assert sorted(keys) == list(range(neo.key_count()))
    assert [keys[key] for key in range(3, neo.key_count())] == [blank_key] * (neo.key_count() - 3)
    assert keys[0] != blank_key


def test_slots_beyond_the_key_count_are_ignored(neo, written, make_config, make_slot, snapshot):
    keys, _ = written
    rivulet_deck.paint(neo, snapshot, make_config(*(make_slot() for _ in range(neo.key_count() + 2))))

    assert sorted(keys) == list(range(neo.key_count()))


def test_the_threshold_colour_reaches_the_artwork(neo, written, make_snapshot, dashboard):
    keys, _ = written
    rivulet_deck.paint(neo, make_snapshot(cpu_percent=10.0), dashboard)
    calm = keys[0]
    rivulet_deck.paint(neo, make_snapshot(cpu_percent=95.0), dashboard)

    assert keys[0] != calm


def test_the_strip_shows_the_deck_type_and_a_clock(neo, written, dashboard, snapshot, monkeypatch):
    seen: list[str] = []
    draw_strip = render.render_screen

    def recording(deck, text, **kwargs):
        seen.append(text)
        return draw_strip(deck, text, **kwargs)

    monkeypatch.setattr(rivulet_deck, "render_screen", recording)
    rivulet_deck.paint(neo, snapshot, dashboard)

    assert len(seen) == 1
    assert neo.deck_type() in seen[0]
    assert re.search(r"\d{2}:\d{2}:\d{2}", seen[0])


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
