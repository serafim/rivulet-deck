"""Shared fixtures: a simulated Neo, the shipped config, and a synthetic snapshot."""

import pathlib

import pytest
from StreamDeck.DeviceManager import DeviceManager

from rivulet_deck import config, metrics
from rivulet_deck.trend import Trends

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "rivulet.toml"

# Values a real host could plausibly report; fixed so assertions stay deterministic.
_SNAPSHOT_DEFAULTS = {
    "cpu_percent": 10.0,
    "cpu_temp_c": 50.0,
    "cpu_ghz": 3.0,
    "cpu_max_ghz": 5.66,
    "ram_used_gib": 8.0,
    "ram_total_gib": 16.0,
    "gpu_name": "Fake GPU 4000",
    "gpu_percent": 20.0,
    "gpu_temp_c": 60.0,
    "gpu_mem_used_gib": 4.0,
    "gpu_mem_total_gib": 8.0,
    "gpu_power_w": 100.0,
    "gpu_power_limit_w": 285.0,
    "uptime_seconds": 1_234_567.89,
}


@pytest.fixture(scope="session")
def neo():
    """A simulated Stream Deck Neo from the dummy transport, never opened (no transport I/O)."""
    decks = [
        deck for deck in DeviceManager(transport="dummy").enumerate()
        if deck.deck_type() == "Stream Deck Neo"
    ]
    if not decks:
        raise RuntimeError("the dummy transport did not enumerate a Stream Deck Neo")
    return decks[0]


@pytest.fixture
def dashboard() -> config.Config:
    return config.load(CONFIG_PATH)


@pytest.fixture
def snapshot(make_snapshot) -> metrics.Snapshot:
    return make_snapshot()


@pytest.fixture
def make_snapshot():
    def build(**overrides) -> metrics.Snapshot:
        values = dict(_SNAPSHOT_DEFAULTS)
        values.update(overrides)
        return metrics.Snapshot(**values)

    return build


@pytest.fixture
def make_slot():
    def build(**overrides) -> config.Slot:
        fields = {
            "label": "T",
            "source": "cpu_percent",
            "unit": "%",
            "precision": 0,
            "warn": 50.0,
            "critical": 85.0,
            "total": None,
            "bar_max": None,
        }
        fields.update(overrides)
        return config.Slot(**fields)

    return build


@pytest.fixture
def make_config():
    def build(*slots: config.Slot, **overrides) -> config.Config:
        fields = {
            "refresh_seconds": 1.0,
            "strip_format": "{deck} {time}",
            "trend_samples": 30,
            "slots": slots,
        }
        fields.update(overrides)
        return config.Config(**fields)

    return build


@pytest.fixture
def make_trends():
    def build(samples: int = 30) -> Trends:
        return Trends(samples)

    return build


@pytest.fixture
def trends(make_trends) -> Trends:
    """Fresh trend history, as main() would build it from the config."""
    return make_trends()


@pytest.fixture
def write_config(tmp_path):
    def write(text: str) -> pathlib.Path:
        path = tmp_path / "rivulet.toml"
        path.write_text(text)
        return path

    return write


@pytest.fixture
def fake_files(monkeypatch):
    """Serve fixed contents for absolute paths, so the /proc and sysfs readers can be tested."""

    def install(files: dict[str, str]) -> None:
        def read_text(self, *args, **kwargs):
            try:
                return files[str(self)]
            except KeyError:
                raise FileNotFoundError(str(self))

        monkeypatch.setattr(pathlib.Path, "read_text", read_text)

    return install
