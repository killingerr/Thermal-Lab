from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Optional

import customtkinter as ctk
from tkinter import filedialog, messagebox

from thermal_lab.compare import CompareResult, compare_sessions
from thermal_lab.models import Configuration, Session, utc_now
from thermal_lab.protocol import Step, build_steps, next_step, step_index
from thermal_lab.scan import scan_hardware
from thermal_lab.store import Store
from thermal_lab.suite import SuiteError, SuiteRunner, suite_script_path


ACCENT = "#c45c26"
DELTA_HOT = "#e05d5d"
DELTA_COOL = "#3dba7a"
MUTED = "#8b93a7"
FAN_COUNT_CHOICES = ["—"] + [str(n) for n in range(1, 13)]


def parse_float(text: str) -> Optional[float]:
    text = (text or "").strip()
    if not text:
        return None
    return float(text)


def fmt_num(value: Optional[float], unit: str = "") -> str:
    if value is None:
        return "—"
    suffix = f" {unit}" if unit else ""
    return f"{value:g}{suffix}"


def _num_text(value: Optional[float]) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def fmt_delta(delta: Optional[float], unit: str) -> str:
    if delta is None:
        return ""
    if abs(delta) < 0.005:
        return f"0 {unit}"
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:g} {unit}"


def notify(title: str, body: str) -> None:
    try:
        subprocess.Popen(
            ["notify-send", "-a", "Thermal Lab", title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


class ThermalLabApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Thermal Lab")
        self.geometry("1280x820")
        self.minsize(1100, 720)

        self.store = Store()
        self.settings = self.store.load_settings()
        self.suite = SuiteRunner(log_path=self.store.suite_log_path())
        self.session: Optional[Session] = None
        self.steps: list[Step] = []
        self._timer_job: Optional[str] = None
        self._remaining = 0
        self._timer_running = False
        self._compare_vars: dict[str, ctk.BooleanVar] = {}
        self.hardware = scan_hardware()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_shell()
        self.show_home()

    def _build_shell(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(
            self.sidebar,
            text="Thermal Lab",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(padx=16, pady=(22, 4), anchor="w")
        ctk.CTkLabel(
            self.sidebar,
            text="Guided tests + compare",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).pack(padx=16, pady=(0, 18), anchor="w")

        for label, command in (
            ("Home", self.show_home),
            ("Thermal session", lambda: self.show_setup("Thermal")),
            ("Acoustic session", lambda: self.show_setup("Acoustic")),
            ("Resume", self._resume_last),
            ("History", self.show_history),
            ("Compare", self.show_compare),
        ):
            ctk.CTkButton(
                self.sidebar,
                text=label,
                command=command,
                fg_color="transparent",
                hover_color=("#2a2a2a", "#2a2a2a"),
                anchor="w",
                height=36,
            ).pack(fill="x", padx=10, pady=2)

        self.suite_status = ctk.CTkLabel(
            self.sidebar,
            text="Suite: stopped",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
            wraplength=190,
            justify="left",
        )
        self.suite_status.pack(side="bottom", padx=16, pady=20, anchor="w")

        self.main = ctk.CTkFrame(self, fg_color="transparent")
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(0, weight=1)

    def _clear_main(self) -> None:
        for child in self.main.winfo_children():
            child.destroy()

    def _page(self) -> ctk.CTkFrame:
        self._clear_main()
        page = ctk.CTkFrame(self.main, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew", padx=24, pady=20)
        page.grid_columnconfigure(0, weight=1)
        return page

    def _heading(self, parent, title: str, subtitle: str = "") -> None:
        ctk.CTkLabel(parent, text=title, font=ctk.CTkFont(size=26, weight="bold")).pack(anchor="w")
        if subtitle:
            ctk.CTkLabel(parent, text=subtitle, text_color=MUTED).pack(anchor="w", pady=(4, 16))
        else:
            ctk.CTkLabel(parent, text="").pack(pady=8)

    def _refresh_suite_status(self) -> None:
        path = self.settings.stress_scripts_path
        try:
            if path:
                suite_script_path(path)
                loc = Path(path).name
            else:
                loc = "path not set"
        except SuiteError:
            loc = "invalid path"
        state = "running" if self.suite.is_running() else "stopped"
        self.suite_status.configure(text=f"Suite: {state}\n{loc}")

    # --- Home / settings -------------------------------------------------

    def show_home(self) -> None:
        self._stop_timer()
        page = self._page()
        self._heading(page, "Thermal Lab", "Walk the SOP, launch stress-scripts, compare configurations.")

        actions = ctk.CTkFrame(page, fg_color="transparent")
        actions.pack(fill="x", pady=(0, 18))
        ctk.CTkButton(
            actions,
            text="Thermal session",
            width=160,
            fg_color=ACCENT,
            hover_color="#a34b1e",
            command=lambda: self.show_setup("Thermal"),
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            actions,
            text="Acoustic session",
            width=170,
            command=lambda: self.show_setup("Acoustic"),
        ).pack(side="left", padx=(0, 8))
        resume = self.store.latest_in_progress()
        if resume:
            ctk.CTkButton(
                actions,
                text=f"Resume: {resume.configuration.name or resume.id}",
                width=260,
                command=lambda: self._open_session(resume),
            ).pack(side="left", padx=8)
        ctk.CTkButton(actions, text="Compare configs", width=160, command=self.show_compare).pack(side="left", padx=8)

        box = ctk.CTkFrame(page)
        box.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(box, text="stress-scripts checkout", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            box,
            text="Path to the local clone of git.karner.dev/jacobvktm/stress-scripts. Required to start a run.",
            text_color=MUTED,
            wraplength=800,
            justify="left",
        ).pack(anchor="w", padx=16)

        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(8, 16))
        self.path_entry = ctk.CTkEntry(row, placeholder_text="/path/to/stress-scripts")
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        if self.settings.stress_scripts_path:
            self.path_entry.insert(0, self.settings.stress_scripts_path)
        ctk.CTkButton(row, text="Browse", width=90, command=self._browse_suite).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="Save path", width=100, command=self._save_suite_path).pack(side="left")
        self._hardware_panel(page)
        self._refresh_suite_status()

    def _hardware_panel(self, page) -> None:
        box = ctk.CTkFrame(page)
        box.pack(fill="both", expand=True, pady=(16, 0))
        header = ctk.CTkFrame(box, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(header, text="Detected hardware", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="Rescan", width=90, command=self._rescan_hardware).pack(side="right")
        ctk.CTkLabel(
            box,
            text="Scanned when Thermal Lab starts. New sessions are prefilled from this machine.",
            text_color=MUTED,
            wraplength=800,
            justify="left",
        ).pack(anchor="w", padx=16)

        grid = ctk.CTkFrame(box, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(8, 8))
        grid.grid_columnconfigure(1, weight=1)
        for row, (label, value) in enumerate(self.hardware.rows()):
            ctk.CTkLabel(grid, text=label, text_color=MUTED, width=120, anchor="w").grid(row=row, column=0, sticky="w", pady=2)
            ctk.CTkLabel(grid, text=value, anchor="w", wraplength=720, justify="left").grid(row=row, column=1, sticky="w", pady=2)
        if self.hardware.notes:
            ctk.CTkLabel(
                box,
                text=" ".join(self.hardware.notes),
                text_color=MUTED,
                wraplength=800,
                justify="left",
            ).pack(anchor="w", padx=16, pady=(0, 14))
        else:
            ctk.CTkLabel(box, text="").pack(pady=6)

    def _rescan_hardware(self) -> None:
        self.hardware = scan_hardware()
        self.show_home()

    def _browse_suite(self) -> None:
        chosen = filedialog.askdirectory(title="Select stress-scripts checkout")
        if not chosen:
            return
        self.path_entry.delete(0, "end")
        self.path_entry.insert(0, chosen)
        self._save_suite_path()

    def _save_suite_path(self) -> None:
        path = self.path_entry.get().strip()
        if not path:
            messagebox.showerror("stress-scripts", "Choose the checkout directory.")
            return
        try:
            suite_script_path(path)
        except SuiteError as exc:
            messagebox.showerror("stress-scripts", str(exc))
            return
        self.settings.stress_scripts_path = path
        self.store.save_settings(self.settings)
        self._refresh_suite_status()
        messagebox.showinfo("stress-scripts", "Path saved. Ready to launch s76-stress-tests.sh -l.")

    # --- Setup -----------------------------------------------------------

    def show_setup(self, kind: str = "Thermal") -> None:
        self._stop_timer()
        if kind not in ("Thermal", "Acoustic"):
            kind = "Thermal"
        page = self._page()
        self._heading(
            page,
            "New session",
            "Choose thermal or acoustic. Reuse a saved configuration, or start from this machine.",
        )

        self.session_kind = ctk.CTkSegmentedButton(
            page,
            values=["Thermal", "Acoustic"],
            command=self._on_session_kind_change,
            width=280,
        )
        self.session_kind.set(kind)
        self.session_kind.pack(anchor="w", pady=(0, 12))

        self._reuse_choices = self._saved_config_choices()
        if len(self._reuse_choices) > 1:
            reuse_row = ctk.CTkFrame(page, fg_color="transparent")
            reuse_row.pack(anchor="w", fill="x", pady=(0, 12))
            ctk.CTkLabel(reuse_row, text="Saved configuration").pack(side="left", padx=(0, 8))
            self.reuse_menu = ctk.CTkOptionMenu(
                reuse_row,
                values=list(self._reuse_choices),
                command=self._on_reuse_config,
                width=520,
                dynamic_resizing=False,
            )
            self.reuse_menu.set("This machine")
            self.reuse_menu.pack(side="left")

        form = ctk.CTkScrollableFrame(page)
        form.pack(fill="both", expand=True)
        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(3, weight=1)

        self._fields: dict[str, ctk.CTkEntry] = {}

        def add(row: int, col: int, key: str, label: str, value: str = "") -> None:
            ctk.CTkLabel(form, text=label).grid(row=row, column=col, sticky="w", padx=8, pady=(10, 2))
            entry = ctk.CTkEntry(form)
            entry.grid(row=row + 1, column=col, sticky="ew", padx=8, pady=(0, 6))
            if value:
                entry.insert(0, value)
            self._fields[key] = entry

        hw = self.hardware
        add(0, 0, "name", "Configuration name")
        add(0, 1, "operator", "Operator", self.settings.last_operator)
        add(2, 0, "sku", "Chassis / SKU", hw.sku)
        add(2, 1, "serial", "Serial", hw.serial)
        add(4, 0, "cpu", "CPU", hw.cpu)
        add(4, 1, "cpu_cooler", "CPU cooler")
        add(6, 0, "gpu", "GPU", hw.gpu)
        add(6, 1, "psu", "PSU", hw.psu)
        add(8, 0, "ram", "RAM", hw.ram)
        add(8, 1, "storage", "Storage", hw.storage)
        add(10, 0, "notes", "Notes")

        ctk.CTkLabel(form, text="Fans (type)").grid(row=12, column=0, sticky="w", padx=8, pady=(10, 2))
        ctk.CTkLabel(form, text="How many fans").grid(row=12, column=1, sticky="w", padx=8, pady=(10, 2))
        fan_type = ctk.CTkEntry(form, placeholder_text="e.g. Noctua NF-A14, stock chassis")
        fan_type.grid(row=13, column=0, sticky="ew", padx=8, pady=(0, 6))
        if hw.fan_type:
            fan_type.insert(0, hw.fan_type)
        self._fields["fan_type"] = fan_type
        self.fan_count_menu = ctk.CTkOptionMenu(form, values=FAN_COUNT_CHOICES, width=90)
        if hw.fan_count and 1 <= hw.fan_count <= 12:
            self.fan_count_menu.set(str(hw.fan_count))
        else:
            self.fan_count_menu.set("—")
        self.fan_count_menu.grid(row=13, column=1, sticky="w", padx=8, pady=(0, 6))

        add(14, 0, "room", "Room temp °C")
        add(14, 1, "ambient", "Ambient temp °C")

        self.swapped_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            form,
            text="Parts were swapped — this is a new combo that needs a full re-test",
            variable=self.swapped_var,
        ).grid(row=16, column=0, columnspan=2, sticky="w", padx=8, pady=12)

        opts = ctk.CTkFrame(form, fg_color="transparent")
        opts.grid(row=18, column=0, columnspan=2, sticky="w", padx=8, pady=8)
        self.thermal_opts = opts
        ctk.CTkLabel(opts, text="Thermal runs").pack(side="left", padx=(0, 8))
        self.run_count_menu = ctk.CTkOptionMenu(opts, values=["2", "3"], width=70)
        self.run_count_menu.set("2")
        self.run_count_menu.pack(side="left", padx=(0, 18))
        ctk.CTkLabel(opts, text="Warm-up minutes").pack(side="left", padx=(0, 8))
        self.warmup_menu = ctk.CTkOptionMenu(opts, values=[str(n) for n in range(5, 11)], width=70)
        self.warmup_menu.set("7")
        self.warmup_menu.pack(side="left")

        actions = ctk.CTkFrame(form, fg_color="transparent")
        actions.grid(row=19, column=0, columnspan=2, sticky="w", padx=8, pady=18)
        ctk.CTkButton(actions, text="Start session", fg_color=ACCENT, hover_color="#a34b1e", command=self._start_session).pack(side="left", padx=(0, 8))
        ctk.CTkButton(actions, text="Rescan this machine", command=self._rescan_into_setup).pack(side="left")
        self._on_session_kind_change(kind)

    def _start_session(self) -> None:
        name = self._fields["name"].get().strip()
        if not name:
            messagebox.showerror("Session", "Give this configuration a name.")
            return
        try:
            room = parse_float(self._fields["room"].get())
            ambient = parse_float(self._fields["ambient"].get())
        except ValueError:
            messagebox.showerror("Session", "Room and ambient temps must be numbers.")
            return
        configuration = Configuration(
            name=name,
            operator=self._fields["operator"].get().strip(),
            sku=self._fields["sku"].get().strip(),
            serial=self._fields["serial"].get().strip(),
            cpu=self._fields["cpu"].get().strip(),
            cpu_cooler=self._fields["cpu_cooler"].get().strip(),
            gpu=self._fields["gpu"].get().strip(),
            psu=self._fields["psu"].get().strip(),
            ram=self._fields["ram"].get().strip(),
            storage=self._fields["storage"].get().strip(),
            fan_type=self._fields["fan_type"].get().strip(),
            fan_count=self._fan_count_value(),
            notes=self._fields["notes"].get().strip(),
            room_temp_c=room,
            ambient_temp_c=ambient,
            parts_swapped=bool(self.swapped_var.get()),
        )
        self.settings.last_operator = configuration.operator
        self.store.save_settings(self.settings)
        kind = "acoustic" if self.session_kind.get() == "Acoustic" else "thermal"
        session = Session.create(
            configuration,
            run_count=int(self.run_count_menu.get()),
            warmup_minutes=int(self.warmup_menu.get()),
            kind=kind,
        )
        self.store.save_session(session)
        self._open_session(session)

    def _saved_config_choices(self) -> dict[str, Optional[Session]]:
        choices: dict[str, Optional[Session]] = {"This machine": None}
        used = {"This machine"}
        for session in self.store.list_sessions():
            name = session.configuration.name or session.id
            kind = "acoustic" if session.kind == "acoustic" else "thermal"
            when = (session.updated_at or "")[:10]
            label = f"{name} · {kind} · {when}"
            if label in used:
                label = f"{label} · {session.id}"
            used.add(label)
            choices[label] = session
        return choices

    def _on_reuse_config(self, label: str) -> None:
        session = self._reuse_choices.get(label)
        if session is None:
            self._fill_from_machine()
            return
        self._fill_from_configuration(session.configuration)
        if session.kind == "thermal" and self.session_kind.get() == "Thermal":
            if session.run_count in (2, 3):
                self.run_count_menu.set(str(session.run_count))
            if 5 <= session.warmup_minutes <= 10:
                self.warmup_menu.set(str(session.warmup_minutes))

    def _fill_from_machine(self) -> None:
        hw = self.hardware
        self._fill_fields(
            {
                "name": "",
                "operator": self.settings.last_operator,
                "sku": hw.sku,
                "serial": hw.serial,
                "cpu": hw.cpu,
                "cpu_cooler": "",
                "gpu": hw.gpu,
                "psu": hw.psu,
                "ram": hw.ram,
                "storage": hw.storage,
                "fan_type": hw.fan_type,
                "notes": "",
                "room": "",
                "ambient": "",
            },
            fan_count=hw.fan_count,
            parts_swapped=False,
        )

    def _fill_from_configuration(self, cfg: Configuration) -> None:
        self._fill_fields(
            {
                "name": cfg.name,
                "operator": cfg.operator,
                "sku": cfg.sku,
                "serial": cfg.serial,
                "cpu": cfg.cpu,
                "cpu_cooler": cfg.cpu_cooler,
                "gpu": cfg.gpu,
                "psu": cfg.psu,
                "ram": cfg.ram,
                "storage": cfg.storage,
                "fan_type": cfg.fan_type,
                "notes": cfg.notes,
                "room": _num_text(cfg.room_temp_c),
                "ambient": _num_text(cfg.ambient_temp_c),
            },
            fan_count=cfg.fan_count,
            parts_swapped=cfg.parts_swapped,
        )

    def _fill_fields(self, values: dict[str, str], fan_count: Optional[int], parts_swapped: bool) -> None:
        for key, value in values.items():
            entry = self._fields[key]
            entry.delete(0, "end")
            if value:
                entry.insert(0, value)
        if fan_count and 1 <= fan_count <= 12:
            self.fan_count_menu.set(str(fan_count))
        else:
            self.fan_count_menu.set("—")
        self.swapped_var.set(bool(parts_swapped))

    def _rescan_into_setup(self) -> None:
        previous = self.hardware
        self.hardware = scan_hardware()
        self._replace_scanned_field("sku", previous.sku, self.hardware.sku)
        self._replace_scanned_field("serial", previous.serial, self.hardware.serial)
        self._replace_scanned_field("cpu", previous.cpu, self.hardware.cpu)
        self._replace_scanned_field("gpu", previous.gpu, self.hardware.gpu)
        self._replace_scanned_field("psu", previous.psu, self.hardware.psu)
        self._replace_scanned_field("ram", previous.ram, self.hardware.ram)
        self._replace_scanned_field("storage", previous.storage, self.hardware.storage)
        self._replace_scanned_field("fan_type", previous.fan_type, self.hardware.fan_type)
        current_count = self.fan_count_menu.get()
        previous_count = str(previous.fan_count) if previous.fan_count else "—"
        if current_count in {"—", previous_count}:
            if self.hardware.fan_count and 1 <= self.hardware.fan_count <= 12:
                self.fan_count_menu.set(str(self.hardware.fan_count))
            else:
                self.fan_count_menu.set("—")

    def _replace_scanned_field(self, key: str, previous: str, current: str) -> None:
        entry = self._fields[key]
        existing = entry.get().strip()
        if existing and existing != (previous or ""):
            return
        entry.delete(0, "end")
        if current:
            entry.insert(0, current)

    def _on_session_kind_change(self, value: str) -> None:
        if value == "Acoustic":
            self.thermal_opts.grid_remove()
        else:
            self.thermal_opts.grid()

    def _fan_count_value(self) -> Optional[int]:
        raw = self.fan_count_menu.get().strip()
        if not raw or raw == "—":
            return None
        return int(raw)

    # --- Run / protocol --------------------------------------------------

    def _resume_last(self) -> None:
        session = self.store.latest_in_progress()
        if session is None:
            messagebox.showinfo("Resume", "No in-progress session.")
            return
        self._open_session(session)

    def _open_session(self, session: Session) -> None:
        self.session = session
        self.steps = build_steps(session.run_count, session.warmup_minutes, session.kind)
        if session.current_step_id not in {step.id for step in self.steps}:
            session.current_step_id = self.steps[0].id
        self.show_run()

    def show_run(self) -> None:
        if self.session is None:
            self.show_setup()
            return
        page = self._page()
        cfg = self.session.configuration
        if self.session.kind == "acoustic":
            subtitle = f"{cfg.parts_label()}   ·   acoustic"
        else:
            subtitle = (
                f"{cfg.parts_label()}   ·   thermal   ·   "
                f"{self.session.run_count} runs   ·   warmup {self.session.warmup_minutes} min"
            )
        self._heading(page, cfg.name, subtitle)

        body = ctk.CTkFrame(page, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self.step_list = ctk.CTkScrollableFrame(body, width=260)
        self.step_list.grid(row=0, column=0, sticky="nsew", padx=(0, 16))

        self.step_panel = ctk.CTkFrame(body)
        self.step_panel.grid(row=0, column=1, sticky="nsew")
        self.step_panel.grid_columnconfigure(0, weight=1)

        self._render_step_list()
        self._render_current_step()
        self._refresh_suite_status()

    def current_step(self) -> Step:
        assert self.session is not None
        idx = step_index(self.steps, self.session.current_step_id)
        return self.steps[idx]

    def _render_step_list(self) -> None:
        for child in self.step_list.winfo_children():
            child.destroy()
        assert self.session is not None
        for step in self.steps:
            done = step.id in self.session.completed_step_ids
            current = step.id == self.session.current_step_id
            mark = "●" if current else ("✓" if done else "○")
            color = ACCENT if current else ("#3dba7a" if done else MUTED)
            btn = ctk.CTkButton(
                self.step_list,
                text=f"{mark}  {step.title}",
                anchor="w",
                fg_color="transparent",
                text_color=color,
                hover_color=("#2a2a2a", "#2a2a2a"),
                command=lambda sid=step.id: self._goto_step(sid),
            )
            btn.pack(fill="x", pady=2)

    def _goto_step(self, step_id: str) -> None:
        if self.session is None:
            return
        self._stop_timer()
        self.session.current_step_id = step_id
        self.store.save_session(self.session)
        self._render_step_list()
        self._render_current_step()

    def _render_current_step(self) -> None:
        for child in self.step_panel.winfo_children():
            child.destroy()
        step = self.current_step()
        pad = {"padx": 24, "pady": 6}

        ctk.CTkLabel(self.step_panel, text=step.title, font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", padx=24, pady=(20, 4))
        ctk.CTkLabel(self.step_panel, text=step.detail, wraplength=680, justify="left", text_color=MUTED).pack(anchor="w", **pad)

        if step.kind == "checklist":
            self._render_checklist()
        elif step.kind == "field":
            self._render_idle_fields()
        elif step.kind in {"timer_suite", "timer_cooldown"}:
            self._render_timer(step)
        elif step.kind == "capture":
            self._render_capture(step)
        elif step.kind == "done":
            self._render_done()

        nav = ctk.CTkFrame(self.step_panel, fg_color="transparent")
        nav.pack(anchor="w", padx=24, pady=20)
        if step.kind != "done":
            ctk.CTkButton(nav, text="Complete step", fg_color=ACCENT, hover_color="#a34b1e", command=self._complete_step).pack(side="left")

    def _render_checklist(self) -> None:
        self.check_vars = []
        items = (
            "Quiet space",
            "Microphone 2 ft from the CPU side of the chassis",
            "About the center height of the chassis",
            "About the center width of the chassis",
        )
        box = ctk.CTkFrame(self.step_panel, fg_color="transparent")
        box.pack(anchor="w", padx=24, pady=12)
        already = bool(self.session and self.session.acoustic.setup_confirmed)
        for item in items:
            var = ctk.BooleanVar(value=already)
            ctk.CTkCheckBox(box, text=item, variable=var).pack(anchor="w", pady=4)
            self.check_vars.append(var)

    def _render_idle_fields(self) -> None:
        assert self.session is not None
        wrap = ctk.CTkFrame(self.step_panel, fg_color="transparent")
        wrap.pack(anchor="w", padx=24, pady=12)
        ctk.CTkLabel(wrap, text="Idle dB").pack(anchor="w")
        self.idle_entry = ctk.CTkEntry(wrap, width=160)
        self.idle_entry.pack(anchor="w", pady=(0, 10))
        if self.session.acoustic.idle_db is not None:
            self.idle_entry.insert(0, str(self.session.acoustic.idle_db))
        ctk.CTkLabel(wrap, text="Notes").pack(anchor="w")
        self.idle_notes = ctk.CTkEntry(wrap, width=420)
        self.idle_notes.pack(anchor="w")
        if self.session.acoustic.notes:
            self.idle_notes.insert(0, self.session.acoustic.notes)

    def _render_timer(self, step: Step) -> None:
        if not self._timer_running:
            self._remaining = step.duration_seconds
        self.timer_label = ctk.CTkLabel(
            self.step_panel,
            text=self._mmss(self._remaining),
            font=ctk.CTkFont(size=64, weight="bold"),
        )
        self.timer_label.pack(anchor="w", padx=24, pady=(16, 8))

        btns = ctk.CTkFrame(self.step_panel, fg_color="transparent")
        btns.pack(anchor="w", padx=24, pady=8)
        start_label = "Start suite + timer" if step.kind == "timer_suite" else "Start cooldown timer"
        ctk.CTkButton(btns, text=start_label, fg_color=ACCENT, hover_color="#a34b1e", command=lambda: self._start_timer(step)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Pause timer", command=self._pause_timer).pack(side="left", padx=8)
        if step.kind == "timer_suite":
            ctk.CTkButton(btns, text="Stop suite", command=self._stop_suite_clicked).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="Reset timer", command=lambda: self._reset_timer(step)).pack(side="left", padx=8)

        if step.id == "stressed":
            assert self.session is not None
            extra = ctk.CTkFrame(self.step_panel, fg_color="transparent")
            extra.pack(anchor="w", padx=24, pady=(16, 0))
            ctk.CTkLabel(extra, text="Stressed dB").pack(anchor="w")
            self.stress_db_entry = ctk.CTkEntry(extra, width=160)
            self.stress_db_entry.pack(anchor="w")
            if self.session.acoustic.stressed_db is not None:
                self.stress_db_entry.insert(0, str(self.session.acoustic.stressed_db))

    def _render_capture(self, step: Step) -> None:
        assert self.session is not None and step.run_index
        run = self.session.run(step.run_index)
        grid = ctk.CTkFrame(self.step_panel, fg_color="transparent")
        grid.pack(anchor="w", padx=24, pady=12)

        ctk.CTkLabel(grid, text="CPU tap °C").grid(row=0, column=0, sticky="w", pady=4)
        self.cpu_tap = ctk.CTkEntry(grid, width=140)
        self.cpu_tap.grid(row=0, column=1, padx=8)
        if run.cpu_tap_c is not None:
            self.cpu_tap.insert(0, str(run.cpu_tap_c))

        ctk.CTkLabel(grid, text="GPU tap °C").grid(row=1, column=0, sticky="w", pady=4)
        self.gpu_tap = ctk.CTkEntry(grid, width=140)
        self.gpu_tap.grid(row=1, column=1, padx=8)
        if run.gpu_tap_c is not None:
            self.gpu_tap.insert(0, str(run.gpu_tap_c))

        self.cpu_photo_lbl = ctk.CTkLabel(grid, text=Path(run.cpu_photo).name if run.cpu_photo else "No CPU tab photo", text_color=MUTED)
        self.cpu_photo_lbl.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ctk.CTkButton(grid, text="Attach CPU tab photo", command=lambda: self._attach_photo(step.run_index, "cpu")).grid(row=3, column=0, sticky="w", pady=4)

        self.gpu_photo_lbl = ctk.CTkLabel(grid, text=Path(run.gpu_photo).name if run.gpu_photo else "No GPU tab photo", text_color=MUTED)
        self.gpu_photo_lbl.grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ctk.CTkButton(grid, text="Attach GPU tab photo", command=lambda: self._attach_photo(step.run_index, "gpu")).grid(row=5, column=0, sticky="w", pady=4)

        ctk.CTkLabel(grid, text="Notes").grid(row=6, column=0, sticky="w", pady=(12, 2))
        self.capture_notes = ctk.CTkEntry(grid, width=360)
        self.capture_notes.grid(row=7, column=0, columnspan=2, sticky="w")
        if run.notes:
            self.capture_notes.insert(0, run.notes)

    def _render_done(self) -> None:
        assert self.session is not None
        if self.session.configuration.parts_swapped:
            ctk.CTkLabel(
                self.step_panel,
                text="Parts were marked swapped. Run a new session for the next configuration before you compare.",
                text_color="#e0b35d",
                wraplength=640,
                justify="left",
            ).pack(anchor="w", padx=24, pady=8)
        btns = ctk.CTkFrame(self.step_panel, fg_color="transparent")
        btns.pack(anchor="w", padx=24, pady=16)
        ctk.CTkButton(btns, text="Compare configs", fg_color=ACCENT, hover_color="#a34b1e", command=self.show_compare).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="New session", command=lambda: self.show_setup("Thermal")).pack(side="left")

    def _attach_photo(self, run_index: int, kind: str) -> None:
        assert self.session is not None
        path = filedialog.askopenfilename(
            title=f"Attach {kind.upper()} tab photo",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")],
        )
        if not path:
            return
        dest = self.store.attach_photo(self.session.id, f"run{run_index}_{kind}", path)
        run = self.session.run(run_index)
        if kind == "cpu":
            run.cpu_photo = dest
            self.cpu_photo_lbl.configure(text=Path(dest).name)
        else:
            run.gpu_photo = dest
            self.gpu_photo_lbl.configure(text=Path(dest).name)
        self.store.save_session(self.session)

    def _complete_step(self) -> None:
        if self.session is None:
            return
        step = self.current_step()
        try:
            if step.kind == "checklist":
                if not all(var.get() for var in self.check_vars):
                    messagebox.showerror("Acoustic setup", "Confirm every microphone placement item.")
                    return
                self.session.acoustic.setup_confirmed = True
            elif step.kind == "field":
                self.session.acoustic.idle_db = parse_float(self.idle_entry.get())
                if self.session.acoustic.idle_db is None:
                    messagebox.showerror("Idle dB", "Enter the idle decibel reading.")
                    return
                self.session.acoustic.notes = self.idle_notes.get().strip()
            elif step.kind == "timer_suite":
                self._stop_suite_clicked()
                if step.id == "stressed":
                    stressed = parse_float(self.stress_db_entry.get())
                    if stressed is None:
                        messagebox.showerror("Stressed dB", "Enter the stressed decibel reading.")
                        return
                    self.session.acoustic.stressed_db = stressed
            elif step.kind == "timer_cooldown":
                self._stop_suite_clicked()
            elif step.kind == "capture":
                assert step.run_index
                run = self.session.run(step.run_index)
                run.cpu_tap_c = parse_float(self.cpu_tap.get())
                run.gpu_tap_c = parse_float(self.gpu_tap.get())
                run.notes = self.capture_notes.get().strip()
                if run.cpu_tap_c is None or run.gpu_tap_c is None:
                    messagebox.showerror("Capture", "Enter both CPU tap and GPU tap temperatures.")
                    return
        except ValueError:
            messagebox.showerror("Values", "Numeric fields must be numbers.")
            return

        if step.id not in self.session.completed_step_ids:
            self.session.completed_step_ids.append(step.id)
        nxt = next_step(self.steps, step.id)
        if nxt is None or nxt.kind == "done":
            self.session.status = "completed"
            self.session.current_step_id = "done"
            if nxt and nxt.id not in self.session.completed_step_ids:
                self.session.completed_step_ids.append(nxt.id)
        else:
            self.session.current_step_id = nxt.id
        self._stop_timer()
        self.store.save_session(self.session)
        self._render_step_list()
        self._render_current_step()

    # --- Timer / suite ---------------------------------------------------

    def _mmss(self, seconds: int) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _start_timer(self, step: Step) -> None:
        if step.kind == "timer_suite":
            try:
                self.suite.start(self.settings.stress_scripts_path)
            except SuiteError as exc:
                messagebox.showerror("stress-scripts", str(exc))
                return
        else:
            try:
                self.suite.stop()
            except OSError:
                pass
        if self.session and step.run_index and step.kind == "timer_suite":
            run = self.session.run(step.run_index)
            if not run.started_at:
                run.started_at = utc_now()
            self.store.save_session(self.session)
        if not self._timer_running and self._remaining <= 0:
            self._remaining = step.duration_seconds
        self._timer_running = True
        self._tick()
        self._refresh_suite_status()

    def _pause_timer(self) -> None:
        self._timer_running = False
        if self._timer_job:
            self.after_cancel(self._timer_job)
            self._timer_job = None

    def _reset_timer(self, step: Step) -> None:
        self._pause_timer()
        self._remaining = step.duration_seconds
        if hasattr(self, "timer_label"):
            self.timer_label.configure(text=self._mmss(self._remaining))

    def _stop_suite_clicked(self) -> None:
        try:
            self.suite.stop()
        except OSError:
            pass
        self._refresh_suite_status()

    def _tick(self) -> None:
        if not self._timer_running:
            return
        if hasattr(self, "timer_label"):
            try:
                self.timer_label.configure(text=self._mmss(self._remaining))
            except Exception:
                return
        if self._remaining <= 0:
            self._timer_running = False
            step = self.current_step()
            if step.kind == "timer_suite":
                self._stop_suite_clicked()
            if self.session and step.run_index and step.kind == "timer_suite":
                self.session.run(step.run_index).ended_at = utc_now()
                self.store.save_session(self.session)
            self.bell()
            notify("Thermal Lab", f"{step.title} finished")
            messagebox.showinfo("Timer", f"{step.title} is done.")
            return
        self._remaining -= 1
        self._timer_job = self.after(1000, self._tick)

    def _stop_timer(self) -> None:
        self._timer_running = False
        if self._timer_job:
            try:
                self.after_cancel(self._timer_job)
            except Exception:
                pass
            self._timer_job = None

    # --- History ---------------------------------------------------------

    def show_history(self) -> None:
        self._stop_timer()
        page = self._page()
        self._heading(page, "History", "Open a session to resume or review captures.")
        sessions = self.store.list_sessions()
        if not sessions:
            ctk.CTkLabel(page, text="No sessions yet.", text_color=MUTED).pack(anchor="w")
            return
        scroller = ctk.CTkScrollableFrame(page)
        scroller.pack(fill="both", expand=True)
        for session in sessions:
            row = ctk.CTkFrame(scroller)
            row.pack(fill="x", pady=6)
            summary = compare_sessions([session]).summaries[0]
            if session.kind == "acoustic":
                text = (
                    f"{summary.name}   ·   acoustic   ·   {session.status}   ·   "
                    f"idle {fmt_num(summary.idle_db, 'dB')}   stressed {fmt_num(summary.stressed_db, 'dB')}"
                )
            else:
                text = (
                    f"{summary.name}   ·   thermal   ·   {session.status}   ·   "
                    f"CPU avg {fmt_num(summary.cpu_avg, '°C')}   GPU avg {fmt_num(summary.gpu_avg, '°C')}"
                )
            ctk.CTkLabel(row, text=text, anchor="w").pack(side="left", padx=12, pady=10, fill="x", expand=True)
            ctk.CTkButton(row, text="Open", width=80, command=lambda s=session: self._open_session(s)).pack(side="right", padx=8)

    # --- Compare ---------------------------------------------------------

    def show_compare(self) -> None:
        self._stop_timer()
        page = self._page()
        self._heading(
            page,
            "Compare configurations",
            "Select 2 or more sessions of the same type. Deltas are versus the first selected.",
        )

        sessions = self.store.list_sessions()
        if len(sessions) < 2:
            ctk.CTkLabel(page, text="Save at least two sessions to compare.", text_color=MUTED).pack(anchor="w")
            return

        picker = ctk.CTkScrollableFrame(page, height=160)
        picker.pack(fill="x", pady=(0, 12))
        self._compare_vars = {}
        for session in sessions:
            var = ctk.BooleanVar(value=False)
            kind_label = "acoustic" if session.kind == "acoustic" else "thermal"
            label = (
                f"{session.configuration.name}  ({kind_label})  "
                f"({session.configuration.parts_label()})  ·  {session.updated_at[:10]}"
            )
            ctk.CTkCheckBox(picker, text=label, variable=var).pack(anchor="w", pady=3)
            self._compare_vars[session.id] = var

        ctk.CTkButton(page, text="Compare selected", fg_color=ACCENT, hover_color="#a34b1e", command=self._render_compare_table).pack(anchor="w", pady=(0, 12))
        self.compare_host = ctk.CTkScrollableFrame(page)
        self.compare_host.pack(fill="both", expand=True)

    def _render_compare_table(self) -> None:
        for child in self.compare_host.winfo_children():
            child.destroy()
        chosen_ids = [sid for sid, var in self._compare_vars.items() if var.get()]
        sessions = [s for s in self.store.list_sessions() if s.id in chosen_ids]
        sessions.sort(key=lambda s: chosen_ids.index(s.id))
        if len(sessions) < 2:
            ctk.CTkLabel(self.compare_host, text="Select at least two configurations.", text_color=MUTED).pack(anchor="w")
            return
        kinds = {session.kind for session in sessions}
        if len(kinds) > 1:
            ctk.CTkLabel(
                self.compare_host,
                text="Compare thermal sessions with thermal sessions, and acoustic sessions with acoustic sessions.",
                text_color="#e0b35d",
            ).pack(anchor="w")
            return
        result = compare_sessions(sessions)
        self._draw_compare(self.compare_host, result)

    def _draw_compare(self, host: ctk.CTkScrollableFrame, result: CompareResult) -> None:
        if result.ambient_mismatch:
            ctk.CTkLabel(host, text=result.ambient_note, text_color="#e0b35d", wraplength=900, justify="left").grid(
                row=0, column=0, columnspan=len(result.summaries) + 1, sticky="w", pady=(0, 10)
            )

        header_row = 1
        ctk.CTkLabel(host, text="Metric", font=ctk.CTkFont(weight="bold")).grid(row=header_row, column=0, sticky="w", padx=8, pady=6)
        for col, summary in enumerate(result.summaries, start=1):
            title = summary.name
            subtitle = summary.parts
            box = ctk.CTkFrame(host, fg_color="transparent")
            box.grid(row=header_row, column=col, sticky="w", padx=8)
            ctk.CTkLabel(box, text=title, font=ctk.CTkFont(weight="bold")).pack(anchor="w")
            ctk.CTkLabel(box, text=subtitle, text_color=MUTED, font=ctk.CTkFont(size=12)).pack(anchor="w")

        for r, row in enumerate(result.rows, start=header_row + 1):
            ctk.CTkLabel(host, text=row.label).grid(row=r, column=0, sticky="w", padx=8, pady=4)
            for c, cell in enumerate(row.cells, start=1):
                text = fmt_num(cell.value, row.unit)
                if c > 1 and cell.delta is not None and cell.value is not None:
                    text = f"{text}   ({fmt_delta(cell.delta, row.unit)})"
                color = None
                if c > 1 and cell.delta is not None and abs(cell.delta) >= 0.05:
                    worse = cell.delta > 0 if row.higher_is_worse else cell.delta < 0
                    color = DELTA_HOT if worse else DELTA_COOL
                ctk.CTkLabel(host, text=text, text_color=color or ("#d6d6d6", "#d6d6d6")).grid(row=r, column=c, sticky="w", padx=8)

    def _on_close(self) -> None:
        self._stop_timer()
        try:
            self.suite.stop()
        except OSError:
            pass
        if self.session is not None:
            self.store.save_session(self.session)
        self.destroy()


def main() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = ThermalLabApp()
    app.mainloop()
