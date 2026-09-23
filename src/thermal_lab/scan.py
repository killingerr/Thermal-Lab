from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import subprocess
from typing import Optional


_PLACEHOLDERS = {
    "",
    "n/a",
    "na",
    "none",
    "not applicable",
    "to be filled by o.e.m.",
    "default string",
    "unknown",
    "system serial number",
    "system product name",
}


@dataclass
class HardwareScan:
    cpu: str = ""
    gpu: str = ""
    ram: str = ""
    storage: str = ""
    fan_type: str = ""
    fan_count: Optional[int] = None
    sku: str = ""
    serial: str = ""
    psu: str = ""
    notes: list[str] = field(default_factory=list)

    def rows(self) -> list[tuple[str, str]]:
        fans = ""
        if self.fan_type and self.fan_count:
            fans = f"{self.fan_type} × {self.fan_count}"
        elif self.fan_type:
            fans = self.fan_type
        elif self.fan_count:
            fans = str(self.fan_count)
        return [
            ("Chassis / SKU", self.sku or "not detected"),
            ("Serial", self.serial or "not detected"),
            ("CPU", self.cpu or "not detected"),
            ("GPU", self.gpu or "not detected"),
            ("PSU", self.psu or "not detected"),
            ("RAM", self.ram or "not detected"),
            ("Storage", self.storage or "not detected"),
            ("Fans", fans or "not detected"),
        ]


def usable_dmi(value: str) -> str:
    text = " ".join((value or "").split())
    if text.lower() in _PLACEHOLDERS:
        return ""
    return text


def parse_cpu_model(cpuinfo: str) -> str:
    for line in cpuinfo.splitlines():
        if line.lower().startswith("model name"):
            _, _, name = line.partition(":")
            return name.strip()
    return ""


def parse_gpu_names(lspci_text: str) -> str:
    names: list[str] = []
    for line in lspci_text.splitlines():
        if not re.search(r"VGA compatible controller|3D controller|Display controller", line):
            continue
        name = _gpu_marketing_name(line)
        if name and name not in names:
            names.append(name)
    return " + ".join(names)


def _gpu_marketing_name(line: str) -> str:
    brackets = re.findall(r"\[([^\]]+)\]", line)
    marketing = [item for item in brackets if not re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{4}", item)]
    if marketing:
        return marketing[-1].strip()
    _, _, rest = line.partition(": ")
    rest = re.sub(r"\[[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\]", "", rest)
    return rest.strip()


def format_ram_kib(total_kib: int) -> str:
    if total_kib <= 0:
        return ""
    gib = total_kib / (1024 * 1024)
    if gib >= 1:
        rounded = round(gib, 1)
        if abs(rounded - round(rounded)) < 0.05:
            return f"{int(round(rounded))} GiB"
        return f"{rounded:.1f} GiB"
    mib = total_kib / 1024
    return f"{mib:.0f} MiB"


def parse_meminfo(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return format_ram_kib(int(parts[1]))
    return ""


def parse_lsblk_pairs(text: str) -> str:
    drives: list[str] = []
    for raw in text.splitlines():
        fields = _lsblk_fields(raw)
        if not fields:
            continue
        name = fields.get("NAME", "")
        kind = fields.get("TYPE", "")
        if kind != "disk":
            continue
        if name.startswith(("zram", "loop")):
            continue
        if fields.get("RM", "0") == "1":
            continue
        size = fields.get("SIZE", "")
        model = fields.get("MODEL", "")
        tran = fields.get("TRAN", "")
        if model in {"-", ""}:
            model = ""
        label = " ".join(bit for bit in (size, model) if bit)
        if tran and tran != "-":
            label = f"{label} ({tran})" if label else tran
        if label:
            drives.append(label)
    return "; ".join(drives)


def _lsblk_fields(line: str) -> dict[str, str]:
    return {key: value.strip() for key, value in re.findall(r'([A-Z]+)="([^"]*)"', line)}


def parse_fans(labels: list[str]) -> tuple[str, Optional[int]]:
    cleaned = [label.strip() for label in labels if label and label.strip()]
    if not cleaned:
        return "", None
    # Preserve order, drop duplicates.
    unique: list[str] = []
    for label in cleaned:
        if label not in unique:
            unique.append(label)
    return ", ".join(unique), len(cleaned)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _run(args: list[str], timeout: float = 2.0) -> str:
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0 and not completed.stdout:
        return ""
    return completed.stdout


def _dmi(name: str) -> str:
    return usable_dmi(_read_text(Path("/sys/class/dmi/id") / name))


def _scan_fans() -> tuple[str, Optional[int]]:
    labels: list[str] = []
    root = Path("/sys/class/hwmon")
    if not root.is_dir():
        return "", None
    for chip in sorted(root.glob("hwmon*")):
        chip_name = _read_text(chip / "name").strip() or chip.name
        for fan in sorted(chip.glob("fan*_input")):
            label_path = chip / fan.name.replace("_input", "_label")
            label = _read_text(label_path).strip()
            labels.append(label or chip_name)
    return parse_fans(labels)


def _scan_psu() -> str:
    text = _run(["dmidecode", "-t", "39"], timeout=2.0)
    if not text or "Permission denied" in text:
        return ""
    names = re.findall(r"Name:\s*(.+)", text)
    usable = [usable_dmi(name) for name in names]
    usable = [name for name in usable if name]
    return "; ".join(usable)


def scan_hardware() -> HardwareScan:
    cpu = parse_cpu_model(_read_text(Path("/proc/cpuinfo")))
    gpu = parse_gpu_names(_run(["lspci", "-nn"]))
    ram = parse_meminfo(_read_text(Path("/proc/meminfo")))
    storage = parse_lsblk_pairs(
        _run(["lsblk", "-d", "-n", "-P", "-o", "NAME,SIZE,MODEL,TRAN,TYPE,RM"])
    )
    fan_type, fan_count = _scan_fans()

    vendor = _dmi("sys_vendor")
    product = _dmi("product_name")
    version = _dmi("product_version")
    sku_field = _dmi("product_sku")
    if sku_field:
        sku = sku_field
    else:
        sku = " ".join(bit for bit in (vendor, product, version) if bit)

    serial = _dmi("product_serial") or _dmi("chassis_serial") or _dmi("board_serial")
    psu = _scan_psu()

    notes: list[str] = []
    if not psu:
        notes.append("PSU is not exposed by this system without extra privileges.")
    if not serial:
        notes.append("Serial is blank or hidden in DMI.")

    return HardwareScan(
        cpu=cpu,
        gpu=gpu,
        ram=ram,
        storage=storage,
        fan_type=fan_type,
        fan_count=fan_count,
        sku=sku,
        serial=serial,
        psu=psu,
        notes=notes,
    )
