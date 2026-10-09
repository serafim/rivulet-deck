"""System telemetry readers: /proc, sysfs hwmon and nvidia-smi. No device I/O."""

import pathlib
import subprocess
import time
from dataclasses import dataclass

_HWMON = pathlib.Path("/sys/class/hwmon")

_CPU_TEMP_CHIPS = frozenset({"k10temp", "zenpower", "coretemp", "k8temp"})
_CPU_TEMP_LABELS = frozenset({"tctl", "package id 0", "physical id 0", "tcore"})

_NVIDIA_QUERY = (
    "name,utilization.gpu,temperature.gpu,memory.total,memory.used,power.draw,power.limit"
)


@dataclass(frozen=True)
class GpuStats:
    name: str
    percent: float | None
    temp_c: float | None
    mem_used_gib: float | None
    mem_total_gib: float | None
    power_w: float | None
    power_limit_w: float | None


@dataclass(frozen=True)
class Snapshot:
    cpu_percent: float | None
    cpu_temp_c: float | None
    cpu_ghz: float | None
    cpu_max_ghz: float | None
    ram_used_gib: float
    ram_total_gib: float
    gpu_name: str | None
    gpu_percent: float | None
    gpu_temp_c: float | None
    gpu_mem_used_gib: float | None
    gpu_mem_total_gib: float | None
    gpu_power_w: float | None
    gpu_power_limit_w: float | None

    @property
    def ram_percent(self) -> float:
        return 100.0 * self.ram_used_gib / self.ram_total_gib

    @property
    def gpu_mem_percent(self) -> float | None:
        if self.gpu_mem_total_gib in (None, 0.0) or self.gpu_mem_used_gib is None:
            return None
        return 100.0 * self.gpu_mem_used_gib / self.gpu_mem_total_gib


def _read_int(path: pathlib.Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _chip_name(chip: pathlib.Path) -> str:
    try:
        return (chip / "name").read_text().strip()
    except OSError:
        return ""


def _hwmon_sensors():
    for chip in sorted(_HWMON.iterdir()):
        name = _chip_name(chip)
        for input_file in sorted(chip.glob("*_input")):
            yield name, input_file


def _label_of(input_file: pathlib.Path) -> str:
    label_file = input_file.with_name(input_file.name.removesuffix("_input") + "_label")
    try:
        return label_file.read_text().strip().lower()
    except OSError:
        return ""


class CpuUsage:
    """Percent of CPU time spent busy, measured between consecutive samples."""

    def __init__(self, interval: float = 0.5) -> None:
        self._interval = interval
        self._previous: tuple[int, int] | None = None

    def sample(self) -> float | None:
        previous = self._previous
        if previous is None:
            previous = _cpu_times()
            time.sleep(self._interval)
        current = _cpu_times()
        self._previous = current

        busy_delta = current[0] - previous[0]
        total_delta = current[1] - previous[1]
        if total_delta <= 0:
            return None
        return 100.0 * busy_delta / total_delta


def _cpu_times() -> tuple[int, int]:
    fields = pathlib.Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    values = [int(field) for field in fields]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values) - idle, sum(values)


def cpu_temp_c() -> float | None:
    for name, input_file in _hwmon_sensors():
        if name not in _CPU_TEMP_CHIPS or not input_file.name.startswith("temp"):
            continue
        if _label_of(input_file) in _CPU_TEMP_LABELS:
            value = _read_int(input_file)
            if value is not None:
                return value / 1000.0
    return None


def cpu_ghz() -> float | None:
    megahertz: list[float] = []
    try:
        for line in pathlib.Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("cpu MHz"):
                megahertz.append(float(line.split(":", 1)[1]))
    except (OSError, ValueError):
        pass
    if megahertz:
        return sum(megahertz) / len(megahertz) / 1000.0

    kilohertz = _read_int(pathlib.Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"))
    return kilohertz / 1_000_000.0 if kilohertz is not None else None


def cpu_max_ghz() -> float | None:
    """Hardware boost ceiling, used as the top of the current-frequency bar."""
    kilohertz = _read_int(pathlib.Path("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq"))
    return kilohertz / 1_000_000.0 if kilohertz is not None else None


def memory_gib() -> tuple[float, float]:
    values: dict[str, int] = {}
    for line in pathlib.Path("/proc/meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        values[key] = int(rest.split()[0])
    total = values["MemTotal"]
    used = total - values.get("MemAvailable", values.get("MemFree", 0))
    return used / 1_048_576.0, total / 1_048_576.0


def nvidia_stats() -> GpuStats | None:
    """First GPU reported by nvidia-smi; None when the tool or driver is absent."""
    try:
        completed = subprocess.run(
            ["nvidia-smi", f"--query-gpu={_NVIDIA_QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None

    name, *numbers = completed.stdout.strip().splitlines()[0].split(",")
    values: list[float | None] = []
    for raw in numbers:
        try:
            values.append(float(raw.strip()))
        except ValueError:
            values.append(None)
    utilization, temperature, memory_total, memory_used, power_draw, power_limit = values
    return GpuStats(
        name=name.strip(),
        percent=utilization,
        temp_c=temperature,
        mem_used_gib=None if memory_used is None else memory_used / 1024.0,
        mem_total_gib=None if memory_total is None else memory_total / 1024.0,
        power_w=power_draw,
        power_limit_w=power_limit,
    )


def collect(usage: CpuUsage) -> Snapshot:
    gpu = nvidia_stats()
    ram_used, ram_total = memory_gib()
    return Snapshot(
        cpu_percent=usage.sample(),
        cpu_temp_c=cpu_temp_c(),
        cpu_ghz=cpu_ghz(),
        cpu_max_ghz=cpu_max_ghz(),
        ram_used_gib=ram_used,
        ram_total_gib=ram_total,
        gpu_name=None if gpu is None else gpu.name,
        gpu_percent=None if gpu is None else gpu.percent,
        gpu_temp_c=None if gpu is None else gpu.temp_c,
        gpu_mem_used_gib=None if gpu is None else gpu.mem_used_gib,
        gpu_mem_total_gib=None if gpu is None else gpu.mem_total_gib,
        gpu_power_w=None if gpu is None else gpu.power_w,
        gpu_power_limit_w=None if gpu is None else gpu.power_limit_w,
    )
