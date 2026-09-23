from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from thermal_lab.compare import compare_sessions
from thermal_lab.models import Configuration, Session
from thermal_lab.scan import (
    format_ram_kib,
    parse_cpu_model,
    parse_fans,
    parse_gpu_names,
    parse_lsblk_pairs,
    scan_hardware,
    usable_dmi,
)
from thermal_lab.protocol import build_steps, next_step
from thermal_lab.store import Store
from thermal_lab.suite import SuiteError, SuiteRunner, find_suite_script, suite_script_path


class ConfigurationTests(unittest.TestCase):
    def test_fans_and_extra_parts_in_label(self):
        cfg = Configuration(
            name="stock",
            cpu="7950X",
            cpu_cooler="NH-D15",
            gpu="4080",
            psu="850W",
            ram="64GB DDR5",
            storage="2TB NVMe",
            fan_type="NF-A14",
            fan_count=3,
        )
        self.assertEqual(cfg.fans_label(), "NF-A14 × 3")
        self.assertIn("NH-D15", cfg.parts_label())
        self.assertIn("64GB DDR5", cfg.parts_label())
        self.assertIn("2TB NVMe", cfg.parts_label())
        self.assertIn("NF-A14 × 3", cfg.parts_label())

    def test_old_session_without_new_fields(self):
        cfg = Configuration.from_dict({"name": "legacy", "cpu": "5800X"})
        self.assertEqual(cfg.cpu_cooler, "")
        self.assertEqual(cfg.ram, "")
        self.assertEqual(cfg.storage, "")
        self.assertEqual(cfg.fan_type, "")
        self.assertIsNone(cfg.fan_count)
        self.assertEqual(cfg.parts_label(), "5800X")


class ScanTests(unittest.TestCase):
    def test_parsers(self):
        cpu = parse_cpu_model("vendor_id : GenuineIntel\nmodel name : Intel(R) Core(TM) i7-8750H CPU @ 2.20GHz\n")
        self.assertEqual(cpu, "Intel(R) Core(TM) i7-8750H CPU @ 2.20GHz")
        gpus = parse_gpu_names(
            "00:02.0 VGA compatible controller: Intel Corporation CoffeeLake-H GT2 [UHD Graphics 630] [8086:3e9b]\n"
            "01:00.0 VGA compatible controller: NVIDIA Corporation TU106M [GeForce RTX 2060 Mobile] [10de:1f11]\n"
        )
        self.assertEqual(gpus, "UHD Graphics 630 + GeForce RTX 2060 Mobile")
        self.assertEqual(format_ram_kib(65547540), "62.5 GiB")
        storage = parse_lsblk_pairs(
            'NAME="nvme0n1" SIZE="953.9G" MODEL="T-FORCE TM8FFE001T" TRAN="nvme" TYPE="disk" RM="0"\n'
            'NAME="sda" SIZE="7.5G" MODEL="USB" TRAN="usb" TYPE="disk" RM="1"\n'
            'NAME="zram0" SIZE="16G" MODEL="" TRAN="" TYPE="disk" RM="0"\n'
        )
        self.assertEqual(storage, "953.9G T-FORCE TM8FFE001T (nvme)")
        self.assertEqual(parse_fans(["CPU fan", "GPU fan"]), ("CPU fan, GPU fan", 2))
        self.assertEqual(usable_dmi("Not Applicable"), "")
        self.assertEqual(usable_dmi("oryp5"), "oryp5")

    def test_live_scan_finds_a_cpu(self):
        scan = scan_hardware()
        self.assertTrue(scan.cpu)


class ProtocolTests(unittest.TestCase):
    def test_two_runs_include_warmup_and_done(self):
        steps = build_steps(2, 7, "thermal")
        ids = [s.id for s in steps]
        self.assertEqual(ids[0], "warmup")
        self.assertNotIn("idle_db", ids)
        self.assertNotIn("stressed", ids)
        self.assertIn("run_1", ids)
        self.assertIn("run_2", ids)
        self.assertNotIn("run_3", ids)
        self.assertEqual(ids[-1], "done")
        warmup = next(s for s in steps if s.id == "warmup")
        self.assertEqual(warmup.duration_seconds, 7 * 60)
        self.assertEqual(warmup.kind, "timer_suite")

    def test_three_runs_clamped_warmup(self):
        steps = build_steps(9, 2, "thermal")
        ids = [s.id for s in steps]
        self.assertIn("run_3", ids)
        warmup = next(s for s in steps if s.id == "warmup")
        self.assertEqual(warmup.duration_seconds, 5 * 60)
        self.assertEqual(next_step(steps, "cap_3").id, "done")

    def test_acoustic_session_is_separate(self):
        steps = build_steps(2, 7, "acoustic")
        ids = [s.id for s in steps]
        self.assertEqual(ids, ["acoustic_setup", "idle_db", "stressed", "done"])
        session = Session.create(Configuration(name="quiet"), kind="acoustic")
        self.assertEqual(session.kind, "acoustic")
        self.assertEqual(session.runs, [])
        self.assertEqual(session.current_step_id, "acoustic_setup")


class StoreAndCompareTests(unittest.TestCase):
    def _session(self, name: str, cpu: float, gpu: float, idle: float, ambient: float) -> Session:
        session = Session.create(
            Configuration(name=name, cpu="CPU-A", gpu="GPU-A", psu="PSU-A", ambient_temp_c=ambient),
            run_count=2,
        )
        session.acoustic.idle_db = idle
        session.acoustic.stressed_db = idle + 10
        session.run(1).cpu_tap_c = cpu
        session.run(1).gpu_tap_c = gpu
        session.run(2).cpu_tap_c = cpu + 1
        session.run(2).gpu_tap_c = gpu + 1
        session.status = "completed"
        return session

    def test_roundtrip_and_compare_deltas(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            a = self._session("stock PSU", 70, 65, 30, 22)
            b = self._session("1200W PSU", 74, 68, 33, 22)
            store.save_session(a)
            store.save_session(b)
            loaded = {s.configuration.name: s for s in store.list_sessions()}
            self.assertIn("stock PSU", loaded)
            result = compare_sessions([loaded["stock PSU"], loaded["1200W PSU"]])
            self.assertFalse(result.ambient_mismatch)
            cpu_avg = next(row for row in result.rows if row.label == "CPU tap average")
            self.assertAlmostEqual(cpu_avg.cells[0].value, 70.5)
            self.assertAlmostEqual(cpu_avg.cells[1].value, 74.5)
            self.assertAlmostEqual(cpu_avg.cells[1].delta, 4.0)

    def test_ambient_mismatch_warning(self):
        a = self._session("cool room", 70, 65, 30, 22)
        b = self._session("hot room", 74, 68, 33, 28)
        result = compare_sessions([a, b])
        self.assertTrue(result.ambient_mismatch)


class SuiteTests(unittest.TestCase):
    def test_missing_checkout_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SuiteError):
                suite_script_path(tmp)

    def test_valid_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "s76-stress-tests.sh"
            script.write_text("#!/bin/bash\n", encoding="utf-8")
            self.assertEqual(suite_script_path(tmp), script.resolve())
            runner = SuiteRunner()
            self.assertFalse(runner.is_running())
            runner.validate(tmp)

    def test_finds_checkout_inside_a_garbled_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / "stress-scripts"
            checkout.mkdir()
            script = checkout / "s76-stress-tests.sh"
            script.write_text("#!/bin/bash\n", encoding="utf-8")
            garbled = (
                "/home/system76/Thermal-Lab/Not in a git repository.\n"
                f"{checkout}"
            )
            self.assertEqual(find_suite_script(garbled, extra_dirs=[]), script.resolve())


if __name__ == "__main__":
    unittest.main()
