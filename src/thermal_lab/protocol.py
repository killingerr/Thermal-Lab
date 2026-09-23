from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


StepKind = Literal["checklist", "field", "timer_suite", "timer_cooldown", "capture", "done"]


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    detail: str
    kind: StepKind
    duration_seconds: int = 0
    run_index: Optional[int] = None


def build_steps(run_count: int, warmup_minutes: int, kind: str = "thermal") -> list[Step]:
    if kind == "acoustic":
        return _acoustic_steps()
    return _thermal_steps(run_count, warmup_minutes)


def _acoustic_steps() -> list[Step]:
    return [
        Step(
            id="acoustic_setup",
            title="Acoustic setup",
            detail=(
                "Quiet space. Place the microphone 2 ft from the CPU side of the "
                "chassis, at about the center height and width of the chassis."
            ),
            kind="checklist",
        ),
        Step(
            id="idle_db",
            title="Idle decibels",
            detail="Record idle dB before any stress starts.",
            kind="field",
        ),
        Step(
            id="stressed",
            title="Stressed decibels",
            detail=(
                "Start s76-stress-tests.sh -l and record dB while the system is "
                "stressed. Complete this step once you have the reading. The "
                "timer stops the suite after 10 minutes if it is still running."
            ),
            kind="timer_suite",
            duration_seconds=10 * 60,
        ),
        Step(
            id="done",
            title="Session complete",
            detail="This acoustic session is ready to compare with other acoustic sessions.",
            kind="done",
        ),
    ]


def _thermal_steps(run_count: int, warmup_minutes: int) -> list[Step]:
    run_count = 3 if run_count >= 3 else 2
    warmup_minutes = min(10, max(5, int(warmup_minutes)))
    warmup_s = warmup_minutes * 60
    cool_s = 3 * 60
    run_s = 10 * 60

    steps = [
        Step(
            id="warmup",
            title="Warm-up",
            detail=(
                f"Run s76-stress-tests.sh -l for {warmup_minutes} minutes to warm "
                "the desktop. The suite is stopped when the timer ends."
            ),
            kind="timer_suite",
            duration_seconds=warmup_s,
        ),
    ]

    for index in range(1, run_count + 1):
        steps.extend(
            [
                Step(
                    id=f"cool_{index}",
                    title=f"Shut off / cooldown {index}",
                    detail=(
                        "Stop the suite (and power off the machine if that is your "
                        "process). Wait 3 minutes before the next thermal run. "
                        "Session state is saved if you reboot."
                    ),
                    kind="timer_cooldown",
                    duration_seconds=cool_s,
                    run_index=index,
                ),
                Step(
                    id=f"run_{index}",
                    title=f"Thermal run {index}",
                    detail=(
                        "Start test 1: s76-stress-tests.sh -l for 10 minutes. "
                        "Photograph the CPU and GPU tabs on test_gui when the run "
                        "finishes."
                    ),
                    kind="timer_suite",
                    duration_seconds=run_s,
                    run_index=index,
                ),
                Step(
                    id=f"cap_{index}",
                    title=f"Capture run {index}",
                    detail=(
                        "Enter CPU tap °C and GPU tap °C from the test_gui tabs. "
                        "Attach the photos you took."
                    ),
                    kind="capture",
                    run_index=index,
                ),
            ]
        )

    steps.append(
        Step(
            id="done",
            title="Session complete",
            detail=(
                "This thermal session is ready to compare. If parts were swapped, "
                "start a new session for the new combo."
            ),
            kind="done",
        )
    )
    return steps


def step_index(steps: list[Step], step_id: str) -> int:
    for i, step in enumerate(steps):
        if step.id == step_id:
            return i
    return 0


def next_step(steps: list[Step], step_id: str) -> Optional[Step]:
    i = step_index(steps, step_id)
    if i + 1 < len(steps):
        return steps[i + 1]
    return None
