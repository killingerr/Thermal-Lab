from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Optional
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _from_dict(cls, data: dict[str, Any]):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class Configuration:
    name: str
    operator: str = ""
    sku: str = ""
    serial: str = ""
    cpu: str = ""
    gpu: str = ""
    psu: str = ""
    ram: str = ""
    storage: str = ""
    fan_type: str = ""
    fan_count: Optional[int] = None
    notes: str = ""
    room_temp_c: Optional[float] = None
    ambient_temp_c: Optional[float] = None
    parts_swapped: bool = False

    def fans_label(self) -> str:
        if self.fan_type and self.fan_count:
            return f"{self.fan_type} × {self.fan_count}"
        if self.fan_type:
            return self.fan_type
        if self.fan_count:
            return f"{self.fan_count} fans"
        return ""

    def parts_label(self) -> str:
        bits = [p for p in (self.cpu, self.gpu, self.psu, self.ram, self.storage, self.fans_label()) if p]
        return " / ".join(bits) if bits else "—"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Configuration:
        payload = dict(data or {})
        count = payload.get("fan_count")
        if count in ("", "—", None):
            payload["fan_count"] = None
        elif count is not None:
            payload["fan_count"] = int(count)
        return _from_dict(cls, payload)


@dataclass
class Acoustic:
    setup_confirmed: bool = False
    idle_db: Optional[float] = None
    stressed_db: Optional[float] = None
    stressed_during_run: Optional[int] = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Acoustic:
        return _from_dict(cls, data or {})


@dataclass
class ThermalRun:
    index: int
    cpu_tap_c: Optional[float] = None
    gpu_tap_c: Optional[float] = None
    cpu_photo: Optional[str] = None
    gpu_photo: Optional[str] = None
    notes: str = ""
    started_at: Optional[str] = None
    ended_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThermalRun:
        return _from_dict(cls, data or {"index": 1})


@dataclass
class Session:
    id: str
    created_at: str
    updated_at: str
    configuration: Configuration
    run_count: int = 2
    warmup_minutes: int = 7
    current_step_id: str = "acoustic_setup"
    completed_step_ids: list[str] = field(default_factory=list)
    acoustic: Acoustic = field(default_factory=Acoustic)
    runs: list[ThermalRun] = field(default_factory=list)
    status: str = "in_progress"

    @classmethod
    def create(
        cls,
        configuration: Configuration,
        run_count: int = 2,
        warmup_minutes: int = 7,
    ) -> Session:
        now = utc_now()
        run_count = 3 if run_count >= 3 else 2
        warmup_minutes = min(10, max(5, int(warmup_minutes)))
        return cls(
            id=uuid.uuid4().hex[:12],
            created_at=now,
            updated_at=now,
            configuration=configuration,
            run_count=run_count,
            warmup_minutes=warmup_minutes,
            runs=[ThermalRun(index=i) for i in range(1, run_count + 1)],
        )

    def run(self, index: int) -> ThermalRun:
        for item in self.runs:
            if item.index == index:
                return item
        raise KeyError(f"No thermal run {index}")

    def touch(self) -> None:
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "configuration": self.configuration.to_dict(),
            "run_count": self.run_count,
            "warmup_minutes": self.warmup_minutes,
            "current_step_id": self.current_step_id,
            "completed_step_ids": list(self.completed_step_ids),
            "acoustic": self.acoustic.to_dict(),
            "runs": [run.to_dict() for run in self.runs],
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        runs = [ThermalRun.from_dict(item) for item in data.get("runs") or []]
        run_count = int(data.get("run_count") or len(runs) or 2)
        if not runs:
            runs = [ThermalRun(index=i) for i in range(1, run_count + 1)]
        return cls(
            id=data["id"],
            created_at=data.get("created_at") or utc_now(),
            updated_at=data.get("updated_at") or utc_now(),
            configuration=Configuration.from_dict(data.get("configuration") or {}),
            run_count=run_count,
            warmup_minutes=int(data.get("warmup_minutes") or 7),
            current_step_id=data.get("current_step_id") or "acoustic_setup",
            completed_step_ids=list(data.get("completed_step_ids") or []),
            acoustic=Acoustic.from_dict(data.get("acoustic") or {}),
            runs=runs,
            status=data.get("status") or "in_progress",
        )


@dataclass
class Settings:
    stress_scripts_path: str = ""
    last_operator: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        return _from_dict(cls, data or {})
