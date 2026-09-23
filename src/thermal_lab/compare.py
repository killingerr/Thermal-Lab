from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Optional

from thermal_lab.models import Session


AMBIENT_WARN_DELTA_C = 1.5


def _avg(values: list[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return round(mean(present), 2)


def _delta(value: Optional[float], baseline: Optional[float]) -> Optional[float]:
    if value is None or baseline is None:
        return None
    return round(value - baseline, 2)


@dataclass
class ConfigSummary:
    session_id: str
    name: str
    parts: str
    sku: str
    serial: str
    room_temp_c: Optional[float]
    ambient_temp_c: Optional[float]
    cpu_taps: list[Optional[float]]
    gpu_taps: list[Optional[float]]
    cpu_avg: Optional[float]
    gpu_avg: Optional[float]
    idle_db: Optional[float]
    stressed_db: Optional[float]
    parts_swapped: bool
    run_count: int


@dataclass
class CompareCell:
    value: Optional[float]
    delta: Optional[float]


@dataclass
class CompareRow:
    label: str
    unit: str
    cells: list[CompareCell]
    higher_is_worse: bool = True


@dataclass
class CompareResult:
    summaries: list[ConfigSummary]
    rows: list[CompareRow]
    ambient_mismatch: bool
    ambient_note: str


def summarize(session: Session) -> ConfigSummary:
    cpu = [run.cpu_tap_c for run in session.runs]
    gpu = [run.gpu_tap_c for run in session.runs]
    cfg = session.configuration
    return ConfigSummary(
        session_id=session.id,
        name=cfg.name or session.id,
        parts=cfg.parts_label(),
        sku=cfg.sku,
        serial=cfg.serial,
        room_temp_c=cfg.room_temp_c,
        ambient_temp_c=cfg.ambient_temp_c,
        cpu_taps=cpu,
        gpu_taps=gpu,
        cpu_avg=_avg(cpu),
        gpu_avg=_avg(gpu),
        idle_db=session.acoustic.idle_db,
        stressed_db=session.acoustic.stressed_db,
        parts_swapped=cfg.parts_swapped,
        run_count=session.run_count,
    )


def compare_sessions(sessions: list[Session]) -> CompareResult:
    summaries = [summarize(session) for session in sessions]
    max_runs = max((s.run_count for s in summaries), default=0)

    kinds = {session.kind for session in sessions}
    acoustic = kinds == {"acoustic"}
    thermal = kinds == {"thermal"}

    metric_rows: list[tuple[str, str, list[Optional[float]]]] = []
    if not acoustic:
        for i in range(max_runs):
            metric_rows.append(
                (f"CPU tap run {i + 1}", "°C", [s.cpu_taps[i] if i < len(s.cpu_taps) else None for s in summaries])
            )
            metric_rows.append(
                (f"GPU tap run {i + 1}", "°C", [s.gpu_taps[i] if i < len(s.gpu_taps) else None for s in summaries])
            )
        metric_rows.extend(
            [
                ("CPU tap average", "°C", [s.cpu_avg for s in summaries]),
                ("GPU tap average", "°C", [s.gpu_avg for s in summaries]),
            ]
        )
    if not thermal:
        metric_rows.extend(
            [
                ("Idle dB", "dB", [s.idle_db for s in summaries]),
                ("Stressed dB", "dB", [s.stressed_db for s in summaries]),
            ]
        )
    metric_rows.extend(
        [
            ("Room temp", "°C", [s.room_temp_c for s in summaries]),
            ("Ambient temp", "°C", [s.ambient_temp_c for s in summaries]),
        ]
    )

    rows: list[CompareRow] = []
    for label, unit, values in metric_rows:
        baseline = values[0] if values else None
        rows.append(
            CompareRow(
                label=label,
                unit=unit,
                cells=[CompareCell(value=v, delta=_delta(v, baseline) if i else 0.0 if v is not None else None) for i, v in enumerate(values)],
                higher_is_worse=True,
            )
        )

    ambients = [s.ambient_temp_c for s in summaries if s.ambient_temp_c is not None]
    ambient_mismatch = False
    ambient_note = ""
    if len(ambients) >= 2:
        spread = max(ambients) - min(ambients)
        if spread > AMBIENT_WARN_DELTA_C:
            ambient_mismatch = True
            ambient_note = (
                f"Ambient temps differ by {spread:.1f} °C. "
                "Do not treat this as a like-for-like compare."
            )
    return CompareResult(
        summaries=summaries,
        rows=rows,
        ambient_mismatch=ambient_mismatch,
        ambient_note=ambient_note,
    )
