"""
The dark look shared by the window and its dialogs.

Tk draws message boxes through the system, and ttk's native Windows themes
ignore configured colors, so everything here has to be built by hand on top of
the 'clam' theme.
"""

import ctypes
import sys
from tkinter import ttk

# Only clam and alt allow their colors to be overridden. clam is the one whose
# checkbox and scrollbar actually follow.
TTK_THEME = "clam"

WINDOW_BACKGROUND = "#252526"
CONTROL_BACKGROUND = "#3c3c3c"
CONTROL_ACTIVE_BACKGROUND = "#4a4a4a"
FIELD_BACKGROUND = "#1e1e1e"
TEXT_COLOR = "#e0e0e0"
HEADER_COLOR = "#ffffff"
# Secondary text still has to be readable on the dark ground.
MUTED_COLOR = "#b0b0b0"
DISABLED_COLOR = "#8a8a8a"
ACCENT_COLOR = "#4ea1d3"
HINT_COLOR = "#e06c75"
DROP_HINT_COLOR = "#98c379"

UI_FONT = ("Segoe UI", 10)
GROUP_FONT = ("Segoe UI", 10, "bold")
HEADER_FONT = ("Segoe UI", 11, "bold")

# The checkbox itself, and the gap between it and its label.
CHECKBOX_SIZE = 14
CHECKBOX_LABEL_GAP = 6

# Dark title bar, supported from Windows 10 build 1809 on. Builds before 2004
# read the flag from attribute 19 instead of 20.
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY = 19

# One window that never travels between monitors only needs system awareness.
PROCESS_SYSTEM_DPI_AWARE = 1

# The density every unscaled Windows length is written against.
REFERENCE_DPI = 96.0

# Tk sizes its fonts in points, of which there are 72 per inch.
POINTS_PER_INCH = 72.0


def enable_high_dpi_awareness() -> None:
    """Render at the screen's real pixel density instead of a stretched bitmap.

    Windows scales an unaware process by blowing up a 96 DPI bitmap, which
    blurs every label on a scaled display. This has to run before the first
    window exists, and a machine older than Windows 8.1 simply has no shcore.
    """
    if sys.platform != "win32":
        return

    shcore = getattr(ctypes.windll, "shcore", None)
    if shcore is None:
        return

    shcore.SetProcessDpiAwareness(PROCESS_SYSTEM_DPI_AWARE)


def apply_display_scale(root) -> float:
    """Match the screen density and return its factor against 96 DPI.

    ``enable_high_dpi_awareness`` stopped Windows from stretching the window,
    which leaves Tk drawing at 96 DPI on a denser screen. Telling Tk the real
    density puts the fonts back to their intended size.
    """
    pixels_per_inch = root.winfo_fpixels("1i")
    root.tk.call("tk", "scaling", pixels_per_inch / POINTS_PER_INCH)
    return pixels_per_inch / REFERENCE_DPI


def apply_dark_title_bar(window) -> None:
    """Ask the desktop manager to paint a window's title bar dark.

    Older Windows 10 builds read the flag from a different attribute, and
    anything before 1809 ignores both, which only costs a light title bar.
    """
    if sys.platform != "win32":
        return

    # The window must exist before the desktop manager knows its handle.
    window.update_idletasks()
    window_handle = ctypes.windll.user32.GetParent(window.winfo_id())
    dark_mode = ctypes.c_int(1)

    for attribute in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY):
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            window_handle,
            attribute,
            ctypes.byref(dark_mode),
            ctypes.sizeof(dark_mode),
        )
        if result == 0:
            return


def apply_dark_theme(root, scale: float) -> None:
    """Repaint every ttk widget of this application dark."""
    style = ttk.Style(root)
    style.theme_use(TTK_THEME)

    style.configure(
        ".",
        background=WINDOW_BACKGROUND,
        foreground=TEXT_COLOR,
        fieldbackground=FIELD_BACKGROUND,
        font=UI_FONT,
        borderwidth=0,
    )
    style.configure("TFrame", background=WINDOW_BACKGROUND)
    style.configure("TLabel", background=WINDOW_BACKGROUND, foreground=TEXT_COLOR)
    style.configure("Header.TLabel", font=HEADER_FONT, foreground=HEADER_COLOR)
    style.configure("Group.TLabel", font=GROUP_FONT, foreground=TEXT_COLOR)
    style.configure("Hint.TLabel", foreground=HINT_COLOR)
    style.configure("Status.TLabel", foreground=MUTED_COLOR)
    style.configure("Drop.TLabel", foreground=DROP_HINT_COLOR)

    style.configure(
        "TButton",
        background=CONTROL_BACKGROUND,
        foreground=TEXT_COLOR,
        padding=(10, 6),
        relief="flat",
    )
    style.map(
        "TButton",
        background=[
            ("active", CONTROL_ACTIVE_BACKGROUND),
            ("disabled", WINDOW_BACKGROUND),
        ],
        foreground=[("disabled", DISABLED_COLOR)],
    )

    style.configure(
        "TEntry",
        fieldbackground=FIELD_BACKGROUND,
        foreground=TEXT_COLOR,
        insertcolor=TEXT_COLOR,
        padding=6,
    )

    # The clam checkbox names its box 'indicatorbackground' and the mark inside
    # it 'indicatorforeground'; the generic indicatorcolor is ignored. The box
    # is drawn in raw pixels and would stay tiny next to scaled text.
    style.configure(
        "TCheckbutton",
        background=WINDOW_BACKGROUND,
        foreground=TEXT_COLOR,
        indicatorbackground=FIELD_BACKGROUND,
        indicatorforeground=ACCENT_COLOR,
        indicatorsize=round(CHECKBOX_SIZE * scale),
        indicatormargin=(0, 0, round(CHECKBOX_LABEL_GAP * scale), 0),
        focuscolor=WINDOW_BACKGROUND,
    )
    style.map(
        "TCheckbutton",
        background=[("active", WINDOW_BACKGROUND)],
        foreground=[("disabled", DISABLED_COLOR)],
        indicatorbackground=[
            ("disabled", WINDOW_BACKGROUND),
            ("active", CONTROL_BACKGROUND),
            ("!active", FIELD_BACKGROUND),
        ],
        indicatorforeground=[
            ("disabled", DISABLED_COLOR),
            ("selected", ACCENT_COLOR),
        ],
    )
