"""
The window shown by the packaged executable.

A narrow portrait window, dark throughout: the sections stack from the input
row down to the log view, which takes every pixel the others leave.

The task chain runs on a worker thread, so its log records travel through a
queue that the Tk main loop drains on a timer. The same timer asks the
questions the worker cannot ask itself, since only the main loop may open a
dialog.
"""

from functools import partial
from pathlib import Path
import queue
import threading
import time
import tkinter
from tkinter import filedialog, scrolledtext, ttk

from tkinterdnd2 import DND_FILES, TkinterDnD

from big_tool.app.dialogs import ask_yes_no, show_info
from big_tool.app.log_bridge import attach_log_pane
from big_tool.app.options import (
    OptionSet,
    collect_problems,
    collect_task_problems,
    parse_input_path,
)
from big_tool.app.pipeline import PipelineRequest, build_request, run_pipeline
from big_tool.app.theme import (
    CONTROL_ACTIVE_BACKGROUND,
    CONTROL_BACKGROUND,
    WINDOW_BACKGROUND,
    apply_dark_theme,
    apply_dark_title_bar,
    apply_display_scale,
    enable_high_dpi_awareness,
)
from big_tool.config import init_app_env
from big_tool.logger import LEVEL_COLORS, logger
from big_tool.version import __version__

WINDOW_TITLE = f"Big Tool {__version__}"
WINDOW_WIDTH = 620
WINDOW_HEIGHT = 700
WINDOW_MIN_WIDTH = 520
WINDOW_MIN_HEIGHT = 560

# A tall window still has to fit on the screen it opens on.
SCREEN_HEIGHT_SHARE = 0.88

# How often the Tk main loop drains the log queue, in milliseconds.
LOG_POLL_INTERVAL_MS = 100

# The button column keeps every section aligned, in text units.
BUTTON_WIDTH = 14

# One indent level of a nested checkbox, in pixels.
INDENT_PIXELS = 22

SCROLLBAR_WIDTH = 14
LOG_PADDING = 6

LOG_FONT = ("Consolas", 10)
# The log view keeps the console look: a dark ground, and the level colors that
# LEVEL_COLORS already defines for the console formatter.
LOG_BACKGROUND = "#1e1e1e"
LOG_FOREGROUND = "#d4d4d4"
LOG_SELECT_BACKGROUND = "#3a4a5a"

HEADER_INPUT = "Input options:"
HEADER_TASKS = "Task options:"
HEADER_LOG = "Log:"

BROWSE_BUTTON_TEXT = "Browse ..."
RUN_BUTTON_TEXT = "▶ Run"
RUN_BUTTON_BUSY_TEXT = "Running ..."
DROP_HINT = "Drop a folder anywhere on this window"

STATUS_IDLE = "Idle"
STATUS_RUNNING = "Running, please wait ..."
STATUS_FAILED = "Stopped by an error, see the log"

BUSY_TITLE = "Big Tool is busy"
BUSY_MESSAGE = "A task is still running.\nWait for it to finish before closing."

CLEANUP_TITLE = "Clear the output directories?"
CLEANUP_MESSAGE = "The following output directories will be cleared:"
CLEANUP_QUESTION = "Continue?"

# A long directory list would push the buttons off a dialog.
CLEANUP_PREVIEW_LIMIT = 12


class BigToolWindow:
    """The application window and the worker thread behind its Run button."""

    def __init__(self) -> None:
        self.option_set = OptionSet()
        self.checkbox_variables: dict[str, tkinter.BooleanVar] = {}
        self.checkbox_widgets: dict[str, ttk.Checkbutton] = {}
        self.log_queue: queue.Queue = queue.Queue()
        self.failed_count = 0
        # Written by the worker thread, read by the main loop timer.
        self.run_summary = STATUS_IDLE
        self._worker: threading.Thread | None = None
        # A question the worker raised, waiting for the main loop to ask it.
        self._cleanup_question: tuple | None = None

        # TkinterDnD.Tk() is the plain Tk root plus the drag and drop bindings.
        self.root = TkinterDnD.Tk()
        self.display_scale = apply_display_scale(self.root)
        apply_dark_theme(self.root, self.display_scale)

        self.root.title(WINDOW_TITLE)
        self.root.geometry(self._initial_geometry())
        self.root.minsize(self._scaled(WINDOW_MIN_WIDTH), self._scaled(WINDOW_MIN_HEIGHT))
        self.root.configure(background=WINDOW_BACKGROUND)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        container = ttk.Frame(self.root, padding=self._scaled(12))
        container.pack(fill="both", expand=True)
        self._build_input_section(container)
        self._build_task_section(container)
        self._build_run_section(container)
        self._build_log_section(container)

        self._register_drop_targets()
        self._refresh_checkbox_states()
        self._refresh_hint()
        apply_dark_title_bar(self.root)

        attach_log_pane(self.log_queue.put)
        self.root.after(LOG_POLL_INTERVAL_MS, self._drain_log_queue)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _scaled(self, length: int) -> int:
        """Return one 96 DPI length in the pixels this screen actually has."""
        return round(length * self.display_scale)

    def _initial_geometry(self) -> str:
        """Return the window size, trimmed to what the screen can show.

        A portrait window this tall would run off a scaled 1080p display.
        """
        width = self._scaled(WINDOW_WIDTH)
        height = self._scaled(WINDOW_HEIGHT)

        largest_height = round(self.root.winfo_screenheight() * SCREEN_HEIGHT_SHARE)
        if height > largest_height:
            height = largest_height

        return f"{width}x{height}"

    def _add_header(self, parent: ttk.Frame, text: str, top_padding: int) -> None:
        """Add one section title."""
        header = ttk.Label(parent, text=text, style="Header.TLabel")
        header.pack(anchor="w", pady=(self._scaled(top_padding), self._scaled(6)))

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    def _build_input_section(self, parent: ttk.Frame) -> None:
        """Create the browse button, the path entry and the drop hint."""
        self._add_header(parent, HEADER_INPUT, 0)

        row = ttk.Frame(parent)
        row.pack(fill="x")

        browse_button = ttk.Button(
            row,
            text=BROWSE_BUTTON_TEXT,
            width=BUTTON_WIDTH,
            command=self._on_browse,
        )
        browse_button.pack(side="left")

        self.path_variable = tkinter.StringVar()
        self.path_variable.trace_add("write", self._on_path_changed)
        self.path_entry = ttk.Entry(row, textvariable=self.path_variable)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(self._scaled(8), 0))

        hint = ttk.Label(parent, text=DROP_HINT, style="Drop.TLabel")
        hint.pack(anchor="w", pady=(self._scaled(4), 0))

    def _build_task_section(self, parent: ttk.Frame) -> None:
        """Create one checkbox per option row, headers included."""
        self._add_header(parent, HEADER_TASKS, 14)

        for row in self.option_set.rows:
            padding_left = self._scaled(INDENT_PIXELS * row.indent)

            if row.is_header:
                label = ttk.Label(parent, text=row.label, style="Group.TLabel")
                label.pack(anchor="w", padx=padding_left, pady=(self._scaled(10), 2))
                continue

            variable = tkinter.BooleanVar(value=row.checked)
            checkbox = ttk.Checkbutton(
                parent,
                text=row.label,
                variable=variable,
                command=partial(self._on_checkbox_changed, row.key),
            )
            checkbox.pack(anchor="w", padx=padding_left, pady=2)

            self.checkbox_variables[row.key] = variable
            self.checkbox_widgets[row.key] = checkbox

    def _build_run_section(self, parent: ttk.Frame) -> None:
        """Create the run button, the status text and the hint line."""
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(self._scaled(16), 0))

        self.run_button = ttk.Button(
            row,
            text=RUN_BUTTON_TEXT,
            width=BUTTON_WIDTH,
            command=self.start_run,
        )
        self.run_button.pack(side="left")

        self.status_variable = tkinter.StringVar(value=STATUS_IDLE)
        status_label = ttk.Label(
            row,
            textvariable=self.status_variable,
            style="Status.TLabel",
        )
        status_label.pack(side="left", padx=(self._scaled(12), 0))

        # Says why Run would refuse, the way the red note does in similar tools.
        self.hint_variable = tkinter.StringVar()
        hint_label = ttk.Label(parent, textvariable=self.hint_variable, style="Hint.TLabel")
        hint_label.pack(anchor="w", pady=(self._scaled(6), 0))

    def _build_log_section(self, parent: ttk.Frame) -> None:
        """Create the read-only log view."""
        self._add_header(parent, HEADER_LOG, 14)

        self.log_text = scrolledtext.ScrolledText(
            parent,
            font=LOG_FONT,
            state="disabled",
            # Long resource paths must stay readable without a sideways scroll.
            wrap="word",
            background=LOG_BACKGROUND,
            foreground=LOG_FOREGROUND,
            selectbackground=LOG_SELECT_BACKGROUND,
            insertbackground=LOG_FOREGROUND,
            borderwidth=0,
            highlightthickness=0,
            padx=self._scaled(LOG_PADDING),
            pady=self._scaled(LOG_PADDING),
        )
        self.log_text.pack(fill="both", expand=True)

        # ScrolledText builds a classic Tk scrollbar, which needs its own colors
        # and its own width: it is not a themed widget.
        self.log_text.vbar.configure(
            background=CONTROL_BACKGROUND,
            troughcolor=WINDOW_BACKGROUND,
            activebackground=CONTROL_ACTIVE_BACKGROUND,
            width=self._scaled(SCROLLBAR_WIDTH),
            borderwidth=0,
            highlightthickness=0,
        )

        for level, color in LEVEL_COLORS.items():
            self.log_text.tag_configure(
                self._level_tag(level),
                foreground=color.foreground,
                background=color.background,
            )

    # ------------------------------------------------------------------
    # Option handling
    # ------------------------------------------------------------------

    def _on_checkbox_changed(self, key: str) -> None:
        """Copy one checkbox into its option row and refresh the dependents."""
        self.option_set.set_checked(key, self.checkbox_variables[key].get())
        self._refresh_checkbox_states()
        self._refresh_hint()

    def _refresh_checkbox_states(self) -> None:
        """Grey out every checkbox whose parent option is off."""
        for row in self.option_set.rows:
            if row.is_header:
                continue

            state = "disabled"
            if self.option_set.is_enabled(row):
                state = "normal"
            self.checkbox_widgets[row.key].configure(state=state)

    def _refresh_hint(self) -> None:
        """Show the first reason why the run would be refused.

        An empty field gets no red note: the green line under it is already
        asking for a folder, and saying it twice helps nobody.
        """
        path_text = self.path_variable.get()

        if parse_input_path(path_text) is None:
            problems = collect_task_problems(self.option_set)
        else:
            problems = collect_problems(self.option_set, path_text)

        if problems:
            self.hint_variable.set(problems[0])
            return
        self.hint_variable.set("")

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def _on_path_changed(self, *_trace_arguments) -> None:
        """React to any edit of the path entry."""
        self._refresh_hint()

    def _on_browse(self) -> None:
        """Pick the input directory from a folder dialog."""
        selected = filedialog.askdirectory(title="Select the directory holding the .big files")
        if selected:
            self.path_variable.set(str(Path(selected)))

    def _register_drop_targets(self) -> None:
        """Accept a dropped folder anywhere on the window."""
        for widget in (self.root, self.path_entry, self.log_text):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event) -> None:
        """Take the first dropped item as the input directory."""
        # Tk hands over a brace quoted list, which only the Tcl splitter parses
        # correctly when a path contains spaces.
        dropped_items = self.root.tk.splitlist(event.data)
        if not dropped_items:
            return

        dropped_path = Path(dropped_items[0])
        # Dropping a file inside the folder is the common slip, so accept it.
        if dropped_path.is_file():
            dropped_path = dropped_path.parent

        self.path_variable.set(str(dropped_path))

    # ------------------------------------------------------------------
    # Log handling
    # ------------------------------------------------------------------

    def _level_tag(self, level: int) -> str:
        """Return the text tag name that colors one log level."""
        return f"level_{level}"

    def _drain_log_queue(self) -> None:
        """Move every queued record into the log view."""
        while True:
            try:
                level, message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log_line(level, message)

        # The same timer asks whatever the worker cannot ask itself, and
        # notices that the worker thread has finished.
        self._ask_pending_cleanup()
        self._refresh_run_state()
        self.root.after(LOG_POLL_INTERVAL_MS, self._drain_log_queue)

    def _append_log_line(self, level: int, message: str) -> None:
        """Add one record, keeping the view pinned to the end when it was."""
        # Scrolling up means the user is reading, so the view stays put.
        view_bottom = self.log_text.yview()[1]
        follows_tail = view_bottom > 0.999

        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n", self._level_tag(level))
        self.log_text.configure(state="disabled")

        if follows_tail:
            self.log_text.see("end")

    # ------------------------------------------------------------------
    # Cleanup confirmation
    # ------------------------------------------------------------------

    def _confirm_cleanup(self, target_dirs: list[Path]) -> bool:
        """Ask before the existing output directories are cleared.

        Runs on the worker thread, where no dialog may be opened, so the
        question is parked for the main loop and the worker waits on the answer.
        """
        answer: list[bool] = []
        answered = threading.Event()
        self._cleanup_question = (target_dirs, answer, answered)
        answered.wait()
        return answer[0]

    def _ask_pending_cleanup(self) -> None:
        """Put the worker's cleanup question on screen and hand back the answer."""
        question = self._cleanup_question
        if question is None:
            return

        self._cleanup_question = None
        target_dirs, answer, answered = question

        answer.append(
            ask_yes_no(
                self.root,
                CLEANUP_TITLE,
                self._cleanup_text(target_dirs),
                self.display_scale,
            )
        )
        answered.set()

    def _cleanup_text(self, target_dirs: list[Path]) -> str:
        """Return the message body listing the directories to be cleared."""
        lines = [CLEANUP_MESSAGE, ""]

        for target_dir in target_dirs[:CLEANUP_PREVIEW_LIMIT]:
            lines.append(str(target_dir))

        remaining_count = len(target_dirs) - CLEANUP_PREVIEW_LIMIT
        if remaining_count > 0:
            lines.append(f"... and {remaining_count} more")

        lines.append("")
        lines.append(CLEANUP_QUESTION)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Running the pipeline
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Return whether the worker thread is still busy."""
        return self._worker is not None and self._worker.is_alive()

    def start_run(self) -> None:
        """Validate the selection and start the task chain."""
        if self.is_running:
            return

        problems = collect_problems(self.option_set, self.path_variable.get())
        if problems:
            self._refresh_hint()
            for problem in problems:
                logger.warning(problem)
            return

        input_dir = parse_input_path(self.path_variable.get())
        request = build_request(self.option_set, input_dir)

        self.status_variable.set(STATUS_RUNNING)
        self.run_button.configure(state="disabled", text=RUN_BUTTON_BUSY_TEXT)
        self._worker = threading.Thread(
            target=self._run_worker,
            args=(request,),
            daemon=True,
        )
        self._worker.start()

    def _run_worker(self, request: PipelineRequest) -> None:
        """Run the pipeline, leaving every widget to the main loop.

        Tk widgets may only be touched from the thread running the main loop,
        so the outcome is left in ``run_summary`` for the timer to pick up.
        """
        try:
            self.failed_count = run_pipeline(request, self._confirm_cleanup)
            self.run_summary = f"{STATUS_IDLE}, {self.failed_count} resources failed"
        except Exception as error:
            # A worker thread dies silently otherwise, leaving the window idle
            # with no explanation in the log.
            self.run_summary = STATUS_FAILED
            logger.exception(f"[Pipeline] Stopped by an unexpected error: {error}")

    def _refresh_run_state(self) -> None:
        """Put the window back into its idle state once the worker is gone."""
        if self._worker is None or self.is_running:
            return

        self._worker = None
        self.status_variable.set(self.run_summary)
        self.run_button.configure(state="normal", text=RUN_BUTTON_TEXT)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        """Close the window, unless a task chain is still running.

        Killing the process would take the daemon worker with it and leave
        half written files behind.
        """
        if self.is_running:
            show_info(self.root, BUSY_TITLE, BUSY_MESSAGE, self.display_scale)
            return
        self.root.destroy()

    def run(self) -> int:
        """Show the window and return the number of failed resources."""
        self.root.mainloop()
        return self.failed_count


def run_gui(import_seconds: float = 0.0) -> int:
    """Build the window, start logging into it and run the main loop.

    ``import_seconds`` is what the entry point already spent loading modules;
    it is logged next to the build time to show where startup went.
    """
    build_start = time.perf_counter()

    enable_high_dpi_awareness()
    window = BigToolWindow()
    # Runs after the log handler is attached, so its own lines show up too.
    init_app_env()

    build_seconds = time.perf_counter() - build_start
    logger.debug(
        f"UI startup: {import_seconds:.2f}s imports + {build_seconds:.2f}s window "
        f"= {import_seconds + build_seconds:.2f}s"
    )
    return window.run()
