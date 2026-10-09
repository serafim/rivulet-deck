"""Telemetry readers, tested against fake /proc, sysfs and nvidia-smi output."""

import pathlib
import subprocess
import types

import pytest

from rivulet_deck import metrics


def test_read_int_accepts_numbers_and_shrugs_at_everything_else(fake_files):
    fake_files({"/sys/a": "42\n", "/sys/b": "not a number"})
    assert metrics._read_int(pathlib.Path("/sys/a")) == 42
    assert metrics._read_int(pathlib.Path("/sys/b")) is None
    assert metrics._read_int(pathlib.Path("/sys/absent")) is None


def test_cpu_times_treat_idle_and_iowait_as_not_busy(fake_files):
    fake_files({"/proc/stat": "cpu  10 20 30 400 50 60 70 0 0 0\nintr 1\n"})
    assert metrics._cpu_times() == (190, 640)


def test_cpu_percent_is_the_busy_delta_between_two_samples(monkeypatch):
    samples = iter([(100, 1000), (300, 2000), (400, 2200)])
    monkeypatch.setattr(metrics, "_cpu_times", lambda: next(samples))
    monkeypatch.setattr(metrics.time, "sleep", lambda *_: None)

    usage = metrics.CpuUsage()
    assert usage.sample() == pytest.approx(20.0)
    assert usage.sample() == pytest.approx(50.0)


def test_cpu_percent_is_none_when_no_cpu_time_passed(monkeypatch):
    monkeypatch.setattr(metrics, "_cpu_times", lambda: (100, 1000))
    monkeypatch.setattr(metrics.time, "sleep", lambda *_: None)
    assert metrics.CpuUsage().sample() is None


@pytest.fixture
def hwmon_tree(tmp_path, monkeypatch):
    """Build a fake /sys/class/hwmon tree and point the reader at it."""

    def build(chip_dir: str, name: str, sensors: dict[str, str]) -> None:
        chip = tmp_path / chip_dir
        chip.mkdir()
        (chip / "name").write_text(name)
        for filename, content in sensors.items():
            (chip / filename).write_text(content)

    monkeypatch.setattr(metrics, "_HWMON", tmp_path)
    return build


def test_cpu_temp_reads_the_labelled_sensor_of_a_cpu_chip(hwmon_tree):
    hwmon_tree("hwmon1", "k10temp\n", {"temp1_input": "45000\n", "temp1_label": "Tctl\n"})
    assert metrics.cpu_temp_c() == pytest.approx(45.0)


def test_cpu_temp_skips_chips_that_are_not_the_cpu(hwmon_tree):
    hwmon_tree("hwmon0", "nvme\n", {"temp1_input": "47000\n", "temp1_label": "Composite\n"})
    assert metrics.cpu_temp_c() is None


def test_cpu_temp_needs_a_label_the_code_recognises(hwmon_tree):
    hwmon_tree("hwmon0", "k10temp\n", {"temp1_input": "45000\n"})
    assert metrics.cpu_temp_c() is None


def test_cpu_temp_prefers_the_chip_the_code_knows_over_ones_it_does_not(hwmon_tree):
    hwmon_tree("hwmon0", "amdgpu\n", {"temp1_input": "53000\n", "temp1_label": "Tctl\n"})
    hwmon_tree("hwmon1", "k10temp\n", {"temp1_input": "78000\n", "temp1_label": "Tctl\n"})
    assert metrics.cpu_temp_c() == pytest.approx(78.0)


def test_cpu_ghz_averages_every_core(fake_files):
    fake_files(
        {
            "/proc/cpuinfo": (
                "processor : 0\ncpu MHz : 3000.000\nprocessor : 1\ncpu MHz : 3400.000\n"
            )
        }
    )
    assert metrics.cpu_ghz() == pytest.approx(3.2)


def test_cpu_ghz_falls_back_to_scaling_cur_freq(fake_files):
    fake_files(
        {
            "/proc/cpuinfo": "processor : 0\nmodel name : AMD Ryzen 9 5950X\n",
            "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq": "2400000\n",
        }
    )
    assert metrics.cpu_ghz() == pytest.approx(2.4)


def test_cpu_ghz_is_none_when_neither_source_is_readable(fake_files):
    fake_files({})
    assert metrics.cpu_ghz() is None


def test_cpu_max_ghz_is_the_boost_ceiling(fake_files):
    fake_files({"/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq": "5660000\n"})
    assert metrics.cpu_max_ghz() == pytest.approx(5.66)

    fake_files({})
    assert metrics.cpu_max_ghz() is None


def test_memory_used_excludes_mem_available(fake_files):
    fake_files(
        {"/proc/meminfo": "MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\nMemFree: 100 kB\n"}
    )
    assert metrics.memory_gib() == (8.0, 16.0)


def test_memory_falls_back_to_mem_free(fake_files):
    fake_files({"/proc/meminfo": "MemTotal: 16777216 kB\nMemFree: 4194304 kB\n"})
    assert metrics.memory_gib() == (12.0, 16.0)


@pytest.fixture
def fake_nvidia(monkeypatch):
    """Swap the subprocess module inside metrics so nvidia-smi is never executed."""
    calls: list[list[str]] = []

    def install(
        stdout: str = "", returncode: int = 0, error: Exception | None = None
    ) -> list[list[str]]:
        def run(command, **kwargs):
            calls.append(command)
            if error is not None:
                raise error
            return subprocess.CompletedProcess(
                args=command, returncode=returncode, stdout=stdout, stderr=""
            )

        monkeypatch.setattr(
            metrics,
            "subprocess",
            types.SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired),
        )
        return calls

    return install


def test_nvidia_stats_parses_the_csv_and_turns_mib_into_gib(fake_nvidia):
    calls = fake_nvidia(
        stdout="NVIDIA GeForce RTX 4070 Ti SUPER, 20, 60, 8192, 4096, 100.50, 285.00\n"
    )
    stats = metrics.nvidia_stats()

    assert stats.name == "NVIDIA GeForce RTX 4070 Ti SUPER"
    assert (stats.percent, stats.temp_c, stats.power_w, stats.power_limit_w) == (
        20.0,
        60.0,
        100.5,
        285.0,
    )
    assert (stats.mem_used_gib, stats.mem_total_gib) == (4.0, 8.0)
    assert calls[0][1] == f"--query-gpu={metrics._NVIDIA_QUERY}"


def test_nvidia_stats_turns_unreported_fields_into_none(fake_nvidia):
    fake_nvidia(stdout="Fake GPU, N/A, 60, 8192, N/A, 100.00, N/A\n")
    stats = metrics.nvidia_stats()

    assert (stats.percent, stats.mem_used_gib, stats.power_limit_w) == (None, None, None)
    assert stats.temp_c == 60.0


@pytest.mark.parametrize(
    ("stdout", "returncode"),
    [("", 0), ("NVIDIA-SMI has failed because it couldn't communicate", 1)],
)
def test_nvidia_stats_is_none_when_the_tool_reports_nothing(
    fake_nvidia, stdout, returncode
):
    fake_nvidia(stdout=stdout, returncode=returncode)
    assert metrics.nvidia_stats() is None


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("nvidia-smi"), subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5.0)],
)
def test_nvidia_stats_is_none_when_the_tool_is_missing_or_hangs(fake_nvidia, error):
    fake_nvidia(error=error)
    assert metrics.nvidia_stats() is None


def test_collect_maps_a_missing_gpu_into_empty_snapshot_fields(
    fake_nvidia, fake_files, hwmon_tree, monkeypatch
):
    fake_nvidia(error=FileNotFoundError("nvidia-smi"))
    fake_files(
        {
            "/proc/stat": "cpu  1 2 3 4 5\n",
            "/proc/cpuinfo": "cpu MHz : 1000.000\n",
            "/proc/meminfo": "MemTotal: 1048576 kB\nMemAvailable: 524288 kB\n",
        }
    )
    monkeypatch.setattr(metrics.time, "sleep", lambda *_: None)

    snapshot = metrics.collect(metrics.CpuUsage())

    assert (snapshot.gpu_name, snapshot.gpu_percent, snapshot.gpu_power_w) == (None, None, None)
    assert snapshot.gpu_mem_percent is None
    assert (snapshot.ram_used_gib, snapshot.ram_total_gib) == (0.5, 1.0)
    assert snapshot.cpu_ghz == pytest.approx(1.0)
    assert snapshot.cpu_temp_c is None
