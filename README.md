# Thermal Lab

Desktop companion for thermal and acoustic hardware checks. It walks the lab SOP, launches the existing [stress-scripts](https://git.karner.dev/jacobvktm/stress-scripts) suite, stores each pass as a named configuration, and compares configs side by side.

It does not reimplement stressing. The engine is a local checkout of stress-scripts.

## What it does

1. Name a **configuration** (CPU / GPU / PSU / RAM / storage / fans / chassis, room and ambient temp).
2. Confirm acoustic mic placement (2 ft from the CPU side, center height and width, quiet space) and record **idle dB**.
3. **Warm-up** 5–10 minutes with `s76-stress-tests.sh -l` (skip LLVM).
4. **Shut off / 3 minute cooldown**, then a 10-minute thermal run, then capture CPU and GPU tap from the test_gui tabs (optional photos). Repeat 2–3 times.
5. Record **stressed dB** during one of the thermal runs.
6. **Compare** two or more saved configurations (per-run and average taps, idle/stressed dB, deltas vs the first selected). Ambient mismatch is flagged.

Sessions are saved under `~/.local/share/thermal-lab/` so you can resume after a reboot.

## Requirements

- Linux with Python 3.10+
- System Tk (`sudo apt install python3-tk`) — required by the desktop UI
- A local clone of [stress-scripts](https://git.karner.dev/jacobvktm/stress-scripts)
- The suite’s own dependencies (`s76-stress-tests.sh` starts test_gui, stress-ng, and on NVIDIA gpu_burn)

## Run

```bash
./run.sh
```

On first launch, set **stress-scripts checkout** on the Home screen to the clone directory (the folder that contains `s76-stress-tests.sh`).

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
