"""Trends: the rolling per-slot windows every graph is drawn from."""

from rivulet_deck.trend import Trends


def test_a_window_keeps_the_newest_readings_oldest_first():
    trends = Trends(4)
    for value in (0.1, 0.2, 0.3, 0.4, 0.5):
        window = trends.record(0, value)

    assert window == (0.2, 0.3, 0.4, 0.5)


def test_each_slot_has_its_own_window():
    trends = Trends(3)
    trends.record(0, 0.25)
    trends.record(1, 0.75)

    assert trends.record(0, 0.5) == (0.25, 0.5)
    assert trends.record(1, 0.5) == (0.75, 0.5)


def test_a_missing_reading_drops_the_window():
    trends = Trends(3)
    trends.record(0, 0.2)
    trends.record(0, 0.4)

    assert trends.record(0, None) == ()
    assert trends.record(0, 0.6) == (0.6,)
