"""main()'s shutdown path: both SIGINT and a plain SIGTERM blank the keys before exiting."""

import os
import signal
import threading

import pytest
from StreamDeck.ImageHelpers.PILHelper import to_native_key_format

import rivulet_deck
from rivulet_deck import render


@pytest.fixture
def blank_key(neo):
    return to_native_key_format(neo, render.render_key(neo, ""))


@pytest.fixture
def writes(neo, monkeypatch):
    """Record main()'s deck traffic in order, without opening the dummy transport."""
    events: list[tuple[int, bytes]] = []
    lifecycle: list[bool] = []
    monkeypatch.setattr(neo, "set_key_image", lambda key, image: events.append((key, image)))
    monkeypatch.setattr(neo, "set_screen_image", lambda image: None)
    monkeypatch.setattr(neo, "open", lambda: lifecycle.append(True))
    monkeypatch.setattr(neo, "close", lambda: lifecycle.append(False))
    return events, lifecycle


@pytest.fixture
def fast_dashboard(dashboard, make_config):
    """The shipped layout, refreshed fast enough for a test to interrupt it mid-run."""
    return make_config(*dashboard.slots, refresh_seconds=0.05, strip_format=dashboard.strip_format)


@pytest.fixture
def run_main(neo, fast_dashboard, snapshot, monkeypatch):
    """Run main() against the simulated Neo: no transport I/O and no real telemetry."""
    monkeypatch.setattr(rivulet_deck, "find_decks", lambda transport=None: [neo])
    monkeypatch.setattr(rivulet_deck.config, "load", lambda path=None: fast_dashboard)
    monkeypatch.setattr(rivulet_deck.metrics, "collect", lambda usage: snapshot)

    def run(signum: int) -> None:
        timer = threading.Timer(0.15, lambda: os.kill(os.getpid(), signum))
        timer.daemon = True
        timer.start()
        rivulet_deck.main()

    return run


def _last_frame(events: list[tuple[int, bytes]], key_count: int) -> list[bytes]:
    return [image for _, image in events[-key_count:]]


def test_sigterm_blanks_the_keys_before_main_returns(neo, run_main, writes, blank_key):
    events, lifecycle = writes
    run_main(signal.SIGTERM)

    assert any(image != blank_key for image in events), "main() should paint before shutting down"
    assert sorted(key for key, _ in events[-neo.key_count():]) == list(range(neo.key_count()))
    assert _last_frame(events, neo.key_count()) == [blank_key] * neo.key_count()
    assert lifecycle == [True, False], "the deck must be closed after the keys are cleared"


def test_sigint_blanks_the_keys_before_main_returns(neo, run_main, writes, blank_key):
    events, lifecycle = writes
    run_main(signal.SIGINT)

    assert _last_frame(events, neo.key_count()) == [blank_key] * neo.key_count()
    assert lifecycle == [True, False]


def test_main_restores_the_signal_handlers_it_replaced(run_main, writes):
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    run_main(signal.SIGTERM)

    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == before
