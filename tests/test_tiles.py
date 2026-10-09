"""How a slot becomes a tile: bar ceiling, threshold colours, units and missing data."""

import pytest

import rivulet_deck


@pytest.fixture
def tile(make_slot, make_config):
    def build(snapshot, **slot_kwargs) -> rivulet_deck.Tile:
        slot = make_slot(**slot_kwargs)
        return rivulet_deck.tiles(snapshot, make_config(slot))[0]

    return build


@pytest.fixture
def tiles(make_slot, make_config):
    def build(snapshot, *slot_kwargs) -> list[rivulet_deck.Tile]:
        slots = [make_slot(**kwargs) for kwargs in slot_kwargs]
        return rivulet_deck.tiles(snapshot, make_config(*slots))

    return build


def test_tiles_follow_the_order_of_the_slots(tiles, snapshot):
    rendered = tiles(
        snapshot,
        {"label": "first", "source": "cpu_percent"},
        {"label": "second", "source": "cpu_temp_c", "unit": "°C"},
    )
    assert [item.label for item in rendered] == ["first", "second"]
    assert [item.value for item in rendered] == ["10", "50"]


def test_ceiling_is_total_then_bar_max_then_100(make_snapshot, tile):
    snapshot = make_snapshot(gpu_power_w=142.5, cpu_ghz=2.83, cpu_percent=25.0)

    by_total = tile(snapshot, source="gpu_power_w", total="gpu_power_limit_w", unit="W")
    by_bar_max = tile(
        snapshot,
        source="cpu_ghz",
        bar_max="cpu_max_ghz",
        unit="GHz",
        warn=None,
        critical=None,
    )
    by_default = tile(snapshot, source="cpu_percent", unit="%")

    assert (by_total.fraction, by_bar_max.fraction, by_default.fraction) == (0.5, 0.5, 0.25)


def test_thresholds_are_percentages_of_the_ceiling(make_snapshot, tile):
    # 70 % and 90 % of the 285 W power limit, not 70 W and 90 W.
    def color(watts):
        return tile(
            make_snapshot(gpu_power_w=watts),
            source="gpu_power_w",
            total="gpu_power_limit_w",
            unit="W",
            warn=70.0,
            critical=90.0,
        ).color

    assert color(199.4) == rivulet_deck._OK
    assert color(199.5) == rivulet_deck._WARN
    assert color(256.4) == rivulet_deck._WARN
    assert color(256.5) == rivulet_deck._CRITICAL


def test_heat_scale_boundaries(make_snapshot, tile):
    def color(percent):
        return tile(make_snapshot(cpu_percent=percent), source="cpu_percent", unit="%").color

    assert color(49.9) == rivulet_deck._OK
    assert color(50.0) == rivulet_deck._WARN
    assert color(84.9) == rivulet_deck._WARN
    assert color(85.0) == rivulet_deck._CRITICAL


def test_slot_without_thresholds_is_neutral(tile, snapshot):
    rendered = tile(
        snapshot,
        source="cpu_ghz",
        bar_max="cpu_max_ghz",
        unit="GHz",
        warn=None,
        critical=None,
    )
    assert rendered.color == rivulet_deck._NEUTRAL
    assert rendered.fraction == pytest.approx(3.0 / 5.66)


def test_missing_value_is_grey_and_leaves_the_bar_empty(make_snapshot, tile):
    rendered = tile(make_snapshot(cpu_percent=None), source="cpu_percent", unit="%")
    assert (rendered.value, rendered.unit, rendered.color, rendered.fraction) == (
        "n/a",
        "%",
        rivulet_deck._MISSING,
        None,
    )


def test_total_is_shown_as_the_unit_suffix(tile, snapshot):
    rendered = tile(snapshot, source="ram_used_gib", total="ram_total_gib", unit="G", precision=1)
    assert (rendered.value, rendered.unit) == ("8.0", "/16G")


def test_unavailable_ceiling_blanks_the_unit_and_the_bar(make_snapshot, tile):
    rendered = tile(
        make_snapshot(gpu_power_limit_w=None),
        source="gpu_power_w",
        total="gpu_power_limit_w",
        unit="W",
    )
    assert (rendered.value, rendered.unit, rendered.color, rendered.fraction) == (
        "100",
        "n/a",
        rivulet_deck._NEUTRAL,
        None,
    )


def test_precision_controls_the_value_text(tile, snapshot):
    assert tile(snapshot, source="cpu_ghz", unit="GHz", precision=2).value == "3.00"
    assert tile(snapshot, source="cpu_temp_c", unit="°C").value == "50"


def test_a_host_without_a_gpu_renders_every_gpu_tile_as_missing(make_snapshot, tiles):
    no_gpu = make_snapshot(
        gpu_name=None,
        gpu_percent=None,
        gpu_temp_c=None,
        gpu_mem_used_gib=None,
        gpu_mem_total_gib=None,
        gpu_power_w=None,
        gpu_power_limit_w=None,
    )
    rendered = tiles(
        no_gpu,
        {"source": "gpu_percent", "unit": "%"},
        {"source": "gpu_power_w", "total": "gpu_power_limit_w", "unit": "W"},
    )
    assert [item.value for item in rendered] == ["n/a", "n/a"]
    assert all(item.color == rivulet_deck._MISSING for item in rendered)


def test_shipped_slots_render_the_units_the_user_fixed(dashboard, snapshot):
    rendered = rivulet_deck.tiles(snapshot, dashboard)
    assert [(item.label, item.value, item.unit) for item in rendered] == [
        ("CPU", "10", "%"),
        ("CPU TEMP", "50", "°C"),
        ("CPU CLOCK", "3.00", "GHz"),
        ("RAM", "8.0", "/16G"),
        ("GPU", "20", "%"),
        ("GPU TEMP", "60", "°C"),
        ("GPU POWER", "100", "/285W"),
        ("VRAM", "4.0", "/8G"),
    ]


def test_snapshot_percent_helpers_match_the_bar_fractions(snapshot):
    assert snapshot.ram_percent == pytest.approx(50.0)
    assert snapshot.gpu_mem_percent == pytest.approx(50.0)


def test_gpu_mem_percent_is_none_without_a_total(make_snapshot):
    assert make_snapshot(gpu_mem_total_gib=None).gpu_mem_percent is None
    assert make_snapshot(gpu_mem_total_gib=0.0).gpu_mem_percent is None
    assert make_snapshot(gpu_mem_used_gib=None).gpu_mem_percent is None
