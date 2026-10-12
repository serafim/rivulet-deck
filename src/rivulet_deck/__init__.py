"""Live system dashboard on a Stream Deck: telemetry in, key artwork out."""

import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.Devices.StreamDeck import StreamDeck
from StreamDeck.ImageHelpers.PILHelper import (
    to_native_key_format,
    to_native_screen_format,
)

from . import config, metrics
from .render import render_key, render_metric, render_screen
from .trend import Trends

_OK = "#9ad36f"
_WARN = "#f7d154"
_CRITICAL = "#e66767"
_NEUTRAL = "#4c9be8"
_MISSING = "#5b6672"


@dataclass(frozen=True)
class Tile:
    label: str
    value: str
    unit: str
    color: str
    fraction: float | None


def find_decks(transport: str | None = None) -> list[StreamDeck]:
    """Return attached decks that can show artwork on their keys.

    Pass a transport name ("dummy") only for testing; None autoprobes.
    """
    return [deck for deck in DeviceManager(transport=transport).enumerate() if deck.is_visual()]


def _heat(value: float | None, warn: float, critical: float) -> str:
    if value is None:
        return _MISSING
    if value >= critical:
        return _CRITICAL
    if value >= warn:
        return _WARN
    return _OK


def tiles(snapshot: metrics.Snapshot, dashboard: config.Config) -> list[Tile]:
    """Key artwork in the order the [[slot]] blocks appear in rivulet.toml."""
    return [_tile(snapshot, slot) for slot in dashboard.slots]


def _tile(snapshot: metrics.Snapshot, slot: config.Slot) -> Tile:
    value = getattr(snapshot, slot.source)
    ceiling_name = slot.total or slot.bar_max
    ceiling = None if ceiling_name is None else getattr(snapshot, ceiling_name)
    if ceiling is None and ceiling_name is None:
        ceiling = 100.0

    fraction = None if value is None or not ceiling else value / ceiling
    unit = slot.unit
    if slot.total:
        unit = "n/a" if not ceiling else f"/{ceiling:.0f}{slot.unit}"

    if value is None:
        color = _MISSING
    elif fraction is None or slot.warn is None:
        color = _NEUTRAL
    else:
        # warn/critical are percentages of the bar ceiling, not absolute units.
        color = _heat(100.0 * fraction, slot.warn, slot.critical)

    return Tile(
        label=slot.label,
        value="n/a" if value is None else f"{value:.{slot.precision}f}",
        unit=unit,
        color=color,
        fraction=fraction,
    )


def _format_uptime(seconds: float | None) -> str:
    """Days:hours:minutes:seconds — days as they come, the rest zero-padded to two digits."""
    if seconds is None:
        return "n/a"
    days, remainder = divmod(int(seconds), 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, secs = divmod(remainder, 60)
    return f"{days}:{hours:02d}:{minutes:02d}:{secs:02d}"


def paint(
    deck: StreamDeck, snapshot: metrics.Snapshot, dashboard: config.Config, trends: Trends
) -> None:
    slots = tiles(snapshot, dashboard)

    if deck.screen_image_format()["size"][0]:
        clock = datetime.now(UTC).astimezone()
        strip = render_screen(
            deck,
            dashboard.strip_format.format(
                deck=deck.deck_type(),
                time=clock,
                uptime=_format_uptime(snapshot.uptime_seconds),
            ),
        )
        deck.set_screen_image(to_native_screen_format(deck, strip))

    for key, tile in enumerate(slots[: deck.key_count()]):
        samples = trends.record(key, tile.fraction)
        image = render_metric(deck, tile.label, tile.value, tile.unit, tile.color, samples)
        deck.set_key_image(key, to_native_key_format(deck, image))

    for key in range(len(slots), deck.key_count()):
        deck.set_key_image(key, to_native_key_format(deck, render_key(deck, "")))


def clear(deck: StreamDeck) -> None:
    for key in range(deck.key_count()):
        deck.set_key_image(key, to_native_key_format(deck, render_key(deck, "")))


def _line(snapshot: metrics.Snapshot, dashboard: config.Config) -> str:
    gpu = snapshot.gpu_name or "no GPU"
    rendered = "  ".join(f"{t.label} {t.value}{t.unit}" for t in tiles(snapshot, dashboard))
    return f"{gpu}: {rendered}"


class _Shutdown(Exception):
    """Raised out of a signal handler so the refresh loop can blank the keys before exiting."""


def _install_shutdown_handlers() -> dict[int, object]:
    """Route SIGINT and SIGTERM through _Shutdown; return the handlers being replaced."""

    def handler(signum: int, frame: object) -> None:
        raise _Shutdown(signum)

    previous: dict[int, object] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, handler)
    return previous


def _restore_shutdown_handlers(previous: dict[int, object]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def main() -> None:
    try:
        dashboard = config.load()
    except config.ConfigError as error:
        print(error)
        raise SystemExit(1)

    decks = find_decks()
    if not decks:
        print("No visual Stream Deck found. Check the USB cable and the udev rule.")
        raise SystemExit(1)

    deck = decks[0]
    usage = metrics.CpuUsage(interval=min(1.0, dashboard.refresh_seconds))
    trends = Trends(dashboard.trend_samples)

    # The context manager only takes the deck's update lock; the transport
    # handshake is open()/close(), which must wrap every image write.
    deck.open()
    previous_handlers = _install_shutdown_handlers()
    try:
        with deck:
            print(
                f"{deck.deck_type()} [{deck.id()}]: {deck.key_count()} keys, "
                f"{len(dashboard.slots)} slots, refresh {dashboard.refresh_seconds:.0f}s, "
                f"trend {dashboard.trend_samples} readings. Ctrl+C or SIGTERM to clear."
            )
            try:
                while deck.connected():
                    snapshot = metrics.collect(usage)
                    paint(deck, snapshot, dashboard, trends)
                    print(_line(snapshot, dashboard))
                    time.sleep(dashboard.refresh_seconds)
            except (KeyboardInterrupt, _Shutdown):
                clear(deck)
                print("Cleared.")
    finally:
        # A plain `kill` must leave the deck usable for the next run, and a library
        # embedding must not inherit our handlers.
        _restore_shutdown_handlers(previous_handlers)
        deck.close()
