"""Detect and enable ANSI color support for the current console."""

import ctypes
import os
import sys
from typing import TextIO

# Windows console API constants, see SetConsoleMode documentation.
STD_OUTPUT_HANDLE = -11
STD_ERROR_HANDLE = -12
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
INVALID_HANDLE_VALUE = -1

# https://no-color.org : any non-empty value disables coloring.
NO_COLOR_ENV = "NO_COLOR"

# Cache the one-shot Windows enabling result, it never changes at runtime.
_windows_vt_enabled: bool | None = None


def _enable_windows_virtual_terminal(std_handle_id: int) -> bool:
    """
    Turn on ANSI escape parsing for one Windows standard output handle.

    The legacy Windows console (conhost, used by cmd.exe and the classic
    PowerShell window) prints escape sequences literally until a process
    opts in through SetConsoleMode. Windows Terminal already opts in.
    """
    kernel32 = ctypes.windll.kernel32

    handle = kernel32.GetStdHandle(std_handle_id)
    if handle == INVALID_HANDLE_VALUE or handle == 0:
        return False

    current_mode = ctypes.c_uint32()
    # Fails when the handle is not a console, for example a redirected file.
    if not kernel32.GetConsoleMode(handle, ctypes.byref(current_mode)):
        return False

    if current_mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING:
        return True

    new_mode = current_mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
    # Fails before Windows 10 build 10586, where VT is not supported at all.
    return bool(kernel32.SetConsoleMode(handle, new_mode))


def enable_console_color() -> bool:
    """
    Prepare the console for ANSI colors and report whether it accepts them.

    Non-Windows terminals always understand ANSI, so nothing is done there.
    """
    global _windows_vt_enabled

    if sys.platform != "win32":
        return True

    if _windows_vt_enabled is None:
        stdout_enabled = _enable_windows_virtual_terminal(STD_OUTPUT_HANDLE)
        stderr_enabled = _enable_windows_virtual_terminal(STD_ERROR_HANDLE)
        _windows_vt_enabled = stdout_enabled or stderr_enabled

    return _windows_vt_enabled


def supports_color(stream: TextIO) -> bool:
    """
    Decide whether colored output is safe to write to one stream.

    Colors are dropped when the user opted out, when the stream is not a
    terminal (redirected to a file or a pipe), or when the console cannot
    parse ANSI escapes at all.
    """
    if os.environ.get(NO_COLOR_ENV):
        return False

    # Detached streams under a GUI build have no isatty at all.
    stream_isatty = getattr(stream, "isatty", None)
    if stream_isatty is None or not stream_isatty():
        return False

    return enable_console_color()
