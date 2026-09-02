"""
Diagnose console ANSI support and print one colored sample of every level.

Run it with: python -m big_tool.logger.check_console_color
"""

import ctypes
import logging
import sys

from big_tool.logger import (
    configure_console_logging,
    console_color,
    logger,
)


def read_console_mode(std_handle_id: int) -> str:
    """Report the raw console mode of one standard handle."""
    if sys.platform != "win32":
        return "not windows"

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(std_handle_id)
    mode = ctypes.c_uint32()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return "not a console (redirected)"

    vt_on = bool(mode.value & console_color.ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    return f"mode=0x{mode.value:04X} VT={vt_on}"


def main():
    """Print the detection result, then a colored line per log level."""
    print("--- console color diagnosis ---")
    print(f"stdout isatty      : {sys.stdout.isatty()}")
    print(f"stderr isatty      : {sys.stderr.isatty()}")
    print(f"stdout console mode: {read_console_mode(console_color.STD_OUTPUT_HANDLE)}")
    print(f"stderr console mode: {read_console_mode(console_color.STD_ERROR_HANDLE)}")
    print(f"supports_color out : {console_color.supports_color(sys.stdout)}")
    print(f"supports_color err : {console_color.supports_color(sys.stderr)}")
    print("--- sample log lines ---")

    configure_console_logging(True)
    logger.debug("debug line should be cyan")
    logger.info("info line should be green")
    logger.warning("warning line should be yellow")
    logger.error("error line should be red")
    logger.critical("critical line should be on a red background")


if __name__ == "__main__":
    main()
