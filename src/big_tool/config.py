"""
Runtime and path configuration for big-tool.

Path detection supports scripts, module entry points, and packaged EXE files.
"""

import __main__
import os
import sys
from pathlib import Path

from big_tool.logger import add_file_handler, logger


def is_packaged_app() -> bool:
    """Return whether the process runs as a packaged application."""
    if getattr(sys, "frozen", False):
        return True

    return bool(os.environ.get("NUITKA_ONEFILE_PARENT"))


def get_app_root() -> Path:
    """Return the application root directory."""
    if is_packaged_app():
        return Path(sys.argv[0]).parent.resolve()

    if hasattr(__main__, "__file__"):
        main_file = Path(__main__.__file__)
        if main_file.parent.is_dir():
            return main_file.parent.resolve()

    return Path.cwd().resolve()


def get_runtime_mode_message() -> str:
    """Return a short runtime mode message for logs."""
    if is_packaged_app():
        return "currently running as a packaged EXE"

    if hasattr(__main__, "__file__"):
        return "currently running as a python script"

    return "currently running as a CLI Wrapper / Shim"


def get_resource_root(app_root: Path) -> Path:
    """Return the packaged or project resource root."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).resolve()

    if is_packaged_app():
        if hasattr(__main__, "__file__"):
            return Path(__main__.__file__).resolve().parent

        return app_root

    return app_root


ROOT_DIR = get_app_root()
RESOURCE_ROOT = get_resource_root(ROOT_DIR)
LOG_FILE_NAME = "big-tool.log"
LOG_FILE_PATH = ROOT_DIR / LOG_FILE_NAME


def get_output_dir(input_dir: Path) -> Path:
    """Return the sibling ``*_out`` directory for an input directory."""
    input_dir = input_dir.resolve()
    return input_dir.with_name(f"{input_dir.name}_out")


def init_app_env() -> None:
    """Initialize the log file and record the runtime environment."""
    add_file_handler(LOG_FILE_PATH)
    logger.debug(get_runtime_mode_message())
    logger.debug(f"Root Path: {ROOT_DIR}")
    logger.debug(f"Log File Path: {LOG_FILE_PATH}")
    # logger.debug(f"changed")
