"""
Bridge between the project logger and the log pane of the app.

The pipeline runs on a worker thread, so records reach the pane through a
callback that the UI hands over. Each record travels as a ``(level, message)``
pair: the pane colors the line by its level instead of parsing escape codes.
"""

from collections.abc import Callable
import logging

from big_tool.logger import (
    ColoredFormatter,
    ConsoleRecordFilter,
    LOGGER_NAME,
    STDERR_HANDLER_NAME,
    STDOUT_HANDLER_NAME,
)

PANE_HANDLER_NAME = "app_log_pane"


class LogPaneHandler(logging.Handler):
    """Send every formatted record to the log pane."""

    def __init__(self, append_record: Callable[[tuple[int, str]], None]) -> None:
        super().__init__(logging.DEBUG)
        self._append_record = append_record
        # The pane colors by level, so the ANSI codes would only be noise.
        self.setFormatter(ColoredFormatter(use_color=False))
        self.addFilter(ConsoleRecordFilter())
        self.set_name(PANE_HANDLER_NAME)

    def emit(self, record: logging.LogRecord) -> None:
        self._append_record((record.levelno, self.format(record)))


def attach_log_pane(append_record: Callable[[tuple[int, str]], None]) -> None:
    """Route the project logger into the pane instead of the console.

    The stdout and stderr handlers have to go: a windowed build has no console
    to write to, and their streams are gone with it.
    """
    project_logger = logging.getLogger(LOGGER_NAME)
    console_handler_names = {STDOUT_HANDLER_NAME, STDERR_HANDLER_NAME}

    for handler in project_logger.handlers[:]:
        if handler.get_name() in console_handler_names:
            project_logger.removeHandler(handler)

    project_logger.addHandler(LogPaneHandler(append_record))
