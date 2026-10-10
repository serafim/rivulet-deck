"""rivulet.toml is the single source of truth for the layout, and bad configs must be rejected."""

import dataclasses

import pytest

from rivulet_deck import config

EXPECTED_LABELS = ["CPU", "CPU TEMP", "CPU CLOCK", "RAM", "GPU", "GPU TEMP", "GPU POWER", "VRAM"]
EXPECTED_SOURCES = [
    "cpu_percent",
    "cpu_temp_c",
    "cpu_ghz",
    "ram_used_gib",
    "gpu_percent",
    "gpu_temp_c",
    "gpu_power_w",
    "gpu_mem_used_gib",
]


def test_shipped_layout_is_the_fixed_eight_slots(dashboard):
    assert [slot.label for slot in dashboard.slots] == EXPECTED_LABELS
    assert [slot.source for slot in dashboard.slots] == EXPECTED_SOURCES


def test_shipped_layout_fills_every_neo_key(dashboard, neo):
    assert len(dashboard.slots) == neo.key_count()


def test_shipped_refresh_strip_and_trend(dashboard):
    assert dashboard.refresh_seconds == 2.0
    assert dashboard.strip_format == "{deck}  {time:%H:%M:%S}"
    assert dashboard.trend_samples == 30


def test_defaults_when_optional_keys_are_omitted(write_config):
    loaded = config.load(write_config('[[slot]]\nsource = "cpu_percent"\n'))

    assert loaded.refresh_seconds == 2.0
    assert loaded.strip_format == "{deck}  {time:%H:%M:%S}"
    assert loaded.trend_samples == 30
    assert loaded.slots == (
        config.Slot(
            label="slot 0",
            source="cpu_percent",
            unit="",
            precision=0,
            warn=None,
            critical=None,
            total=None,
            bar_max=None,
        ),
    )


@pytest.mark.parametrize("gauge", config.GAUGES)
def test_every_gauge_name_is_usable_as_source_and_ceiling(write_config, gauge):
    loaded = config.load(
        write_config(f'[[slot]]\nsource = "{gauge}"\ntotal = "{gauge}"\n')
    )
    assert loaded.slots[0].source == gauge
    assert loaded.slots[0].total == gauge


def test_the_trend_window_length_comes_from_the_file(write_config):
    loaded = config.load(write_config('trend_samples = 5\n[[slot]]\nsource = "cpu_percent"\n'))

    assert loaded.trend_samples == 5


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('[[slot]]\nsource = "cpu_speed"\n', "unknown source"),
        ('[[slot]]\nsource = "cpu_percent"\ntotal = "nope"\n', "unknown total"),
        ('[[slot]]\nsource = "cpu_percent"\nbar_max = "nope"\n', "unknown bar_max"),
        ('[[slot]]\nsource = "cpu_percent"\nwarn = 40\n', "warn and critical"),
        ('[[slot]]\nsource = "cpu_percent"\ncritical = 90\n', "warn and critical"),
        ("refresh_seconds = 1.0\n", "at least one [[slot]]"),
        (
            'trend_samples = 1\n[[slot]]\nsource = "cpu_percent"\n',
            "trend_samples must be at least 2",
        ),
        ("[[slot\nsource = 1\n", "not valid TOML"),
    ],
)
def test_bad_config_raises_instead_of_silently_falling_back(write_config, text, expected):
    with pytest.raises(config.ConfigError) as raised:
        config.load(write_config(text))
    assert expected in str(raised.value)


def test_unknown_gauge_error_lists_the_alternatives(write_config):
    with pytest.raises(config.ConfigError) as raised:
        config.load(write_config('[[slot]]\nsource = "fan_rpm"\n'))
    message = str(raised.value)
    assert all(gauge in message for gauge in config.GAUGES)


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(config.ConfigError) as raised:
        config.load(tmp_path / "absent.toml")
    assert "cannot read" in str(raised.value)


def test_loaded_config_is_immutable(make_config):
    dashboard = make_config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        dashboard.refresh_seconds = 9.0
