"""Rolling history of recent fractions, one window per slot. No device I/O, no telemetry."""

from collections import deque


class Trends:
    """Per-slot windows of recent fractions, oldest first, capped at `samples` entries."""

    def __init__(self, samples: int) -> None:
        self.samples = samples
        self._windows: dict[int, deque[float]] = {}

    def record(self, slot: int, fraction: float | None) -> tuple[float, ...]:
        """Add this frame's fraction and return the slot's window.

        A missing reading drops the window instead of leaving a stale trend lit on the key, so
        the graph only ever shows data the deck actually has.
        """
        if fraction is None:
            self._windows.pop(slot, None)
            return ()

        window = self._windows.setdefault(slot, deque(maxlen=self.samples))
        window.append(fraction)
        return tuple(window)
