#!/usr/bin/env bash
# Clone Thermal Lab and stress-scripts if they are missing, then install
# any missing system packages and Python dependencies.
set -euo pipefail

THERMAL_LAB_URL="${THERMAL_LAB_URL:-https://github.com/killingerr/Thermal-Lab.git}"
STRESS_SCRIPTS_URL="${STRESS_SCRIPTS_URL:-https://git.karner.dev/jacobvktm/stress-scripts.git}"
SETTINGS_PATH="${HOME}/.local/share/thermal-lab/settings.json"

info() { printf '%s\n' "$*" >&2; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

have_pkg() {
  dpkg -s "$1" >/dev/null 2>&1
}

install_missing_packages() {
  local missing=()
  local pkg
  for pkg in "$@"; do
    if ! have_pkg "$pkg"; then
      missing+=("$pkg")
    fi
  done
  if ((${#missing[@]} == 0)); then
    info "System packages already installed."
    return
  fi
  command -v sudo >/dev/null 2>&1 || die "Missing packages: ${missing[*]}. Install them, then re-run."
  info "Installing missing packages: ${missing[*]}"
  sudo apt-get update
  sudo apt-get install -y "${missing[@]}"
}

script_dir() {
  (unset CDPATH; builtin cd -- "$(dirname -- "$0")" && pwd)
}

is_thermal_lab() {
  [[ -f "$1/requirements.txt" && -d "$1/src/thermal_lab" ]]
}

ensure_thermal_lab() {
  local here dest
  here="$(script_dir)"
  if is_thermal_lab "$here"; then
    THERMAL_LAB_ROOT="$here"
    return
  fi
  dest="${THERMAL_LAB_DIR:-${HOME}/Thermal-Lab}"
  if is_thermal_lab "$dest"; then
    info "Thermal Lab already present at ${dest}"
  else
    command -v git >/dev/null 2>&1 || install_missing_packages git
    info "Cloning Thermal Lab into ${dest}"
    git clone "$THERMAL_LAB_URL" "$dest" >&2
  fi
  THERMAL_LAB_ROOT="$dest"
}

settings_stress_path() {
  [[ -f "$SETTINGS_PATH" ]] || return 0
  python3 - "$SETTINGS_PATH" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(0)
value = data.get("stress_scripts_path") or ""
if value:
    print(value)
PY
}

ensure_stress_scripts() {
  local candidate configured
  configured="$(settings_stress_path || true)"
  local candidates=()
  [[ -n "${STRESS_SCRIPTS_DIR:-}" ]] && candidates+=("$STRESS_SCRIPTS_DIR")
  [[ -n "$configured" ]] && candidates+=("$configured")
  candidates+=("${HOME}/stress-scripts" "${HOME}/src/stress-scripts")
  for candidate in "${candidates[@]}"; do
    if [[ -f "${candidate}/s76-stress-tests.sh" ]]; then
      info "stress-scripts already present at ${candidate}"
      STRESS_ROOT="$candidate"
      return
    fi
  done
  local dest="${STRESS_SCRIPTS_DIR:-${HOME}/stress-scripts}"
  command -v git >/dev/null 2>&1 || install_missing_packages git
  info "Cloning stress-scripts into ${dest}"
  if ! git clone --recurse-submodules "$STRESS_SCRIPTS_URL" "$dest" >&2; then
    info "Submodules were not cloned. Cloning the stress-scripts tree without them."
    rm -rf "$dest"
    git clone "$STRESS_SCRIPTS_URL" "$dest" >&2
  fi
  if command -v git-lfs >/dev/null 2>&1 || have_pkg git-lfs; then
    git -C "$dest" lfs install --local >/dev/null 2>&1 || true
    git -C "$dest" lfs pull >&2 || true
  fi
  STRESS_ROOT="$dest"
}

ensure_venv() {
  local root="$1"
  if [[ ! -d "${root}/.venv" ]]; then
    info "Creating Python virtual environment"
    python3 -m venv "${root}/.venv"
  fi
  if ! "${root}/.venv/bin/python" -c "import customtkinter, PIL" >/dev/null 2>&1; then
    info "Installing Python dependencies"
    "${root}/.venv/bin/pip" install -r "${root}/requirements.txt"
  else
    info "Python dependencies already installed."
  fi
}

remember_stress_path() {
  local stress_dir="$1"
  python3 - "$SETTINGS_PATH" "$stress_dir" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
stress = sys.argv[2].strip()
path.parent.mkdir(parents=True, exist_ok=True)
data = {}
if path.is_file():
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}
existing = data.get("stress_scripts_path") or ""
existing_ok = Path(existing).expanduser().joinpath("s76-stress-tests.sh").is_file()
if not existing_ok:
    data["stress_scripts_path"] = stress
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Saved stress-scripts path to {path}", file=sys.stderr)
else:
    print(f"Keeping existing stress-scripts path: {existing}", file=sys.stderr)
PY
}

install_missing_packages git python3 python3-venv python3-pip python3-tk git-lfs

THERMAL_LAB_ROOT=""
STRESS_ROOT=""
ensure_thermal_lab
ensure_stress_scripts
ensure_venv "$THERMAL_LAB_ROOT"
remember_stress_path "$STRESS_ROOT"

info "Ready."
info "  Thermal Lab: ${THERMAL_LAB_ROOT}"
info "  stress-scripts: ${STRESS_ROOT}"
info "Start the app with: ${THERMAL_LAB_ROOT}/run.sh"
