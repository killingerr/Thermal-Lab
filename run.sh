#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
export PYTHONPATH=src
if ! .venv/bin/python -c "import tkinter" >/dev/null 2>&1; then
  echo "Thermal Lab needs the system Tk package."
  echo "Install it, then re-run:"
  echo "  sudo apt install python3-tk"
  exit 1
fi
exec .venv/bin/python -m thermal_lab
