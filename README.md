# Thermal Lab

Desktop companion for thermal and acoustic hardware checks. It walks the lab SOP, launches the existing [stress-scripts](https://git.karner.dev/jacobvktm/stress-scripts) suite, stores each pass as a named configuration, and compares configs side by side.

It does not reimplement stressing. The engine is a local checkout of stress-scripts.

## What it does

1. On launch, scan this machine (CPU, GPU, RAM, storage, fans, chassis) and prefill a **configuration**. CPU cooler is entered by hand. PSU and serial are filled only when the system exposes them.
2. Start either a **thermal** session or an **acoustic** session. They are separate passes on the same kind of configuration.
3. Thermal: **warm-up** 5–10 minutes with `s76-stress-tests.sh -l` (skip LLVM), then a 3-minute cooldown and a 10-minute run. Capture CPU and GPU tap from the test_gui tabs (optional photos). Repeat 2–3 times.
4. Acoustic: confirm mic placement (2 ft from the CPU side, center height and width, quiet space), record **idle dB**, then start the suite and record **stressed dB**.
5. **Compare** two or more sessions of the same type. Thermal compare shows taps. Acoustic compare shows idle and stressed dB. Ambient mismatch is flagged.

Sessions are saved under `~/.local/share/thermal-lab/` so you can resume after a reboot.

## Requirements

- Linux with Python 3.10+
- System Tk (`sudo apt install python3-tk`) — required by the desktop UI
- The stress suite’s own dependencies (`s76-stress-tests.sh` starts test_gui, stress-ng, and on NVIDIA gpu_burn)

## Run

```bash
./install.sh
./run.sh
```

`install.sh` clones Thermal Lab if needed, installs missing packages, and downloads the stress test tools. The app uses those tools when a test starts. There is no folder to configure.

The app starts `s76-stress-tests.sh -l` for warmup and each thermal run, then stops the process tree when the timer ends. The suite itself wants to run for hours; the timer is what ends a 10-minute pass.

On NVIDIA, that exact command also starts gpu_burn. It is killed with everything else when the timer finishes.

## Protocol defaults

| Step | Duration | Suite |
| --- | --- | --- |
| Warm-up | 5–10 min (default 7) | `s76-stress-tests.sh -l` |
| Cooldown | 3 min | stopped |
| Thermal run | 10 min | `s76-stress-tests.sh -l` |
| Runs per session | 2 or 3 | |

“Shut off” can mean stop the suite or power the machine down. State is saved after every step.
