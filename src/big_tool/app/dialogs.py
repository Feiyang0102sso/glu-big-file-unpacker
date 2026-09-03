"""
Modal dialogs in the application's own dark look.

``tkinter.messagebox`` hands the job to Windows, which draws a light dialog no
matter what the application looks like, so these are built from a Toplevel.
"""

import tkinter
from tkinter import ttk

from big_tool.app.theme import (
    TEXT_COLOR,
    WINDOW_BACKGROUND,
    apply_dark_title_bar,
)

DIALOG_PADDING = 16
BUTTON_WIDTH = 10
BUTTON_GAP = 8

# Wrap the message at this width so a long path cannot stretch the dialog off
# the screen. In pixels, before the display scale is applied.
MESSAGE_WRAP_LENGTH = 460


def ask_yes_no(parent, title: str, message: str, scale: float = 1.0) -> bool:
    """Show a modal yes/no question and return what the user chose.

    Closing the dialog by its title bar counts as no: the caller is always
    about to do something the user has not agreed to yet.
    """
    answer = _run_dialog(parent, title, message, scale, with_cancel=True)
    return answer


def show_info(parent, title: str, message: str, scale: float = 1.0) -> None:
    """Show a modal message with a single acknowledging button."""
    _run_dialog(parent, title, message, scale, with_cancel=False)


def _run_dialog(parent, title: str, message: str, scale: float, with_cancel: bool) -> bool:
    """Build the dialog, wait for it, and report whether it was accepted."""
    dialog = tkinter.Toplevel(parent)
    dialog.title(title)
    dialog.configure(background=WINDOW_BACKGROUND)
    dialog.resizable(False, False)
    # Keep it above its parent and take every key and click while it is open.
    dialog.transient(parent)

    accepted = tkinter.BooleanVar(value=False)

    body = ttk.Frame(dialog, padding=round(DIALOG_PADDING * scale))
    body.pack(fill="both", expand=True)

    message_label = ttk.Label(
        body,
        text=message,
        justify="left",
        wraplength=round(MESSAGE_WRAP_LENGTH * scale),
        foreground=TEXT_COLOR,
    )
    message_label.pack(anchor="w")

    button_row = ttk.Frame(body)
    button_row.pack(anchor="e", pady=(round(DIALOG_PADDING * scale), 0))

    def accept() -> None:
        """Close the dialog with a positive answer."""
        accepted.set(True)
        dialog.destroy()

    def reject() -> None:
        """Close the dialog with a negative answer."""
        accepted.set(False)
        dialog.destroy()

    if with_cancel:
        no_button = ttk.Button(button_row, text="No", width=BUTTON_WIDTH, command=reject)
        no_button.pack(side="right")

        yes_button = ttk.Button(button_row, text="Yes", width=BUTTON_WIDTH, command=accept)
        yes_button.pack(side="right", padx=(0, round(BUTTON_GAP * scale)))
        yes_button.focus_set()
    else:
        ok_button = ttk.Button(button_row, text="OK", width=BUTTON_WIDTH, command=accept)
        ok_button.pack(side="right")
        ok_button.focus_set()

    def on_escape(_event) -> None:
        """Treat the escape key as a refusal."""
        reject()

    def on_return(_event) -> None:
        """Treat the enter key as the button that has the focus."""
        accept()

    dialog.protocol("WM_DELETE_WINDOW", reject)
    dialog.bind("<Escape>", on_escape)
    dialog.bind("<Return>", on_return)

    apply_dark_title_bar(dialog)
    _center_on_parent(dialog, parent)

    dialog.grab_set()
    parent.wait_window(dialog)
    return accepted.get()


def _center_on_parent(dialog, parent) -> None:
    """Place the dialog in the middle of the window that raised it."""
    dialog.update_idletasks()

    dialog_width = dialog.winfo_width()
    dialog_height = dialog.winfo_height()
    left = parent.winfo_rootx() + (parent.winfo_width() - dialog_width) // 2
    top = parent.winfo_rooty() + (parent.winfo_height() - dialog_height) // 3

    dialog.geometry(f"+{left}+{top}")
