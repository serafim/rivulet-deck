"""Dashboard layout loaded from rivulet.toml: which gauge sits on which key, and its thresholds."""

import pathlib
import tomllib
from dataclasses import dataclass

DEFAULT_PATH = pathlib.Path("rivulet.toml")

# Snapshot attributes a slot may read; also valid as a bar ceiling.
GAUGES = (
    "cpu_percent",
    "cpu_temp_c",
    "cpu_ghz",
    "cpu_max_ghz",
    "ram_used_gib",
    "ram_total_gib",
    "gpu_percent",
    "gpu_temp_c",
    "gpu_mem_used_gib",
    "gpu_mem_total_gib",
    "gpu_power_w",
    "gpu_power_limit_w",
)


class ConfigError(ValueError):
    """The configuration file exists but cannot be used as a dashboard layout."""


@dataclass(frozen=True)
class Slot:
    label: str
    source: str
    unit: str
    precision: int
    warn: float | None
    critical: float | None
    total: str | None
    bar_max: str | None


@dataclass(frozen=True)
class Config:
    refresh_seconds: float
    strip_format: str
    slots: tuple[Slot, ...]


def load(path: pathlib.Path = DEFAULT_PATH) -> Config:
    try:
        raw = path.read_text()
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    try:
        table = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from error

    slots = tuple(_slot(entry, index) for index, entry in enumerate(table.get("slot", ())))
    if not slots:
        raise ConfigError(f"{path}: expected at least one [[slot]] block")

    return Config(
        refresh_seconds=float(table.get("refresh_seconds", 2.0)),
        strip_format=table.get("strip", {}).get("format", "{deck}  {time:%H:%M:%S}"),
        slots=slots,
    )


def _slot(entry: dict[str, object], index: int) -> Slot:
    label = str(entry.get("label") or f"slot {index}")

    for field in ("source", "total", "bar_max"):
        gauge = entry.get(field)
        if gauge is None:
            continue
        if gauge not in GAUGES:
            raise ConfigError(
                f"slot {label!r}: unknown {field} {gauge!r}; available gauges: {', '.join(GAUGES)}"
            )
    if entry.get("source") is None:
        raise ConfigError(f"slot {label!r}: 'source' is required")

    warn, critical = entry.get("warn"), entry.get("critical")
    if (warn is None) != (critical is None):
        raise ConfigError(f"slot {label!r}: warn and critical must be given together")

    return Slot(
        label=label,
        source=str(entry["source"]),
        unit=str(entry.get("unit", "")),
        precision=int(entry.get("precision", 0)),
        warn=None if warn is None else float(warn),
        critical=None if critical is None else float(critical),
        total=entry.get("total"),
        bar_max=entry.get("bar_max"),
    )
