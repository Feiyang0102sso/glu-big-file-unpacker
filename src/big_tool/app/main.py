"""
Entry point of the packaged executable.

The release build starts here instead of at ``cli.py``: double clicking an exe
gives no arguments, so the tasks are picked in the window instead.
"""

import time

# Loading tkinter, PIL and the drag and drop extension is the slow half of
# startup, so the clock starts before them and is handed to the window.
_IMPORT_CLOCK_START = time.perf_counter()

from big_tool.app.gui import run_gui

IMPORT_SECONDS = time.perf_counter() - _IMPORT_CLOCK_START


def main() -> int:
    """Run the window and report whether every resource came out."""
    failed_count = run_gui(IMPORT_SECONDS)

    if failed_count:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
