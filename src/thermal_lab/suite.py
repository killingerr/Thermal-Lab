from __future__ import annotations

from pathlib import Path
import os
import signal
import subprocess
import time
from typing import Optional


SUITE_SCRIPT = "s76-stress-tests.sh"
SUITE_ARGS = ["-l"]

# Patterns that belong to this suite. Narrow on purpose so we do not
# kill unrelated desktop processes.
_PKILL_PATTERNS = (
    "s76-stress-tests.sh",
    "s76-stress.sh",
    "s76-stress-ng.sh",
    "s76-gpu-burn.sh",
    "s76-testguipy.sh",
    "s76-llvm-stress.sh",
    "s76-disable-suspend.sh",
    "s76-journalctl.sh",
    "s76-unigine-valley.sh",
    "--name=s76-stress",
    "--title=System76-stress",
)

_PKILL_EXACT = (
    "stress-ng",
    "gpu_burn",
    "gpu-burn",
    "test_gui",
)


class SuiteError(Exception):
    pass


def suite_script_path(repo: str | Path) -> Path:
    path = Path(repo).expanduser().resolve()
    script = path / SUITE_SCRIPT
    if not path.is_dir() or not script.is_file():
        raise SuiteError(
            f"stress-scripts checkout not found. Expected {SUITE_SCRIPT} under {path}"
        )
    return script


class SuiteRunner:
    """Start and stop `s76-stress-tests.sh -l` from a local checkout."""

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path
        self._proc: Optional[subprocess.Popen] = None
        self._pgid: Optional[int] = None
        self._log_handle = None

    def validate(self, repo: str | Path) -> Path:
        return suite_script_path(repo)

    def is_running(self) -> bool:
        if self._proc is None:
            return False
        code = self._proc.poll()
        return code is None

    def start(self, repo: str | Path) -> None:
        if self.is_running():
            return
        script = self.validate(repo)
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = open(self.log_path, "ab")
            self._log_handle.write(f"\n--- start {script} {' '.join(SUITE_ARGS)} ---\n".encode())
            self._log_handle.flush()
        try:
            self._proc = subprocess.Popen(
                ["bash", str(script), *SUITE_ARGS],
                cwd=str(script.parent),
                start_new_session=True,
                stdout=self._log_handle or subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            self._close_log()
            raise SuiteError(f"Could not start {SUITE_SCRIPT}: {exc}") from exc
        try:
            self._pgid = os.getpgid(self._proc.pid)
        except OSError:
            self._pgid = self._proc.pid

    def stop(self) -> None:
        started = self._proc is not None or self._pgid is not None
        self._stop_process_group()
        if started:
            self._reap_suite_children()
        self._close_log()
        self._proc = None
        self._pgid = None

    def _close_log(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None

    def _stop_process_group(self) -> None:
        if self._proc is None and self._pgid is None:
            return
        pgid = self._pgid
        if pgid is not None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(pgid, sig)
                except OSError:
                    break
                time.sleep(0.4 if sig == signal.SIGTERM else 0.1)
        if self._proc is not None:
            try:
                self._proc.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                pass

    def _reap_suite_children(self) -> None:
        """Kill suite processes that escaped the process group (sudo, gnome-terminal)."""
        for pattern in _PKILL_PATTERNS:
            subprocess.run(
                ["pkill", "-f", pattern],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        for name in _PKILL_EXACT:
            subprocess.run(
                ["pkill", "-x", name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
