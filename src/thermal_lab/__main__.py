import sys


def _missing_tkinter() -> bool:
    try:
        import tkinter  # noqa: F401
        return False
    except ModuleNotFoundError:
        return True


if _missing_tkinter():
    sys.exit(
        "Thermal Lab needs the system Tk package.\n"
        "Install it, then re-run ./run.sh:\n"
        "  sudo apt install python3-tk"
    )

from thermal_lab.app import main

if __name__ == "__main__":
    main()
