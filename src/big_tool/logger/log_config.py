"""big-tool universal config"""
from collections.abc import Callable
from dataclasses import dataclass
import logging
from pathlib import Path
import sys

from .console_color import supports_color

LOGGER_NAME = "BigTool"
STDOUT_HANDLER_NAME = "console_stdout"
STDERR_HANDLER_NAME = "console_stderr"
FILE_ONLY_RECORD_ATTRIBUTE = "file_only"

ANSI_RESET = "\033[0m"


@dataclass(frozen=True)
class LevelColor:
    """One log level in both flavours a view may need."""

    # The console escape sequence.
    ansi: str
    # The same color as a widget reads it, plus an optional band behind it.
    foreground: str
    background: str = ""


# The one color table of the project: the console formatter takes the escape
# codes, a window takes the hex values, and neither can drift from the other.
LEVEL_COLORS = {
    logging.DEBUG: LevelColor(ansi="\033[36m", foreground="#56b6c2"),
    logging.INFO: LevelColor(ansi="\033[32m", foreground="#98c379"),
    logging.WARNING: LevelColor(ansi="\033[33m", foreground="#e5c07b"),
    logging.ERROR: LevelColor(ansi="\033[31m", foreground="#e06c75"),
    logging.CRITICAL: LevelColor(
        ansi="\033[41m",
        foreground="#ffffff",
        background="#a00000",
    ),
}


def ansi_color_of(level: int) -> str:
    """Return the console escape that colors one log level."""
    level_color = LEVEL_COLORS.get(level)
    if level_color is None:
        return ""
    return level_color.ansi

_before_console_output: Callable[[], None] | None = None
_after_console_output: Callable[[], None] | None = None


class ColoredFormatter(logging.Formatter):
    """
    Provide different colors based on log levels.
    """

    def __init__(self, use_color: bool = True):
        """Drop the color codes when the console cannot parse them."""
        super().__init__()
        self._use_color = use_color

    def format(self, record):
        color = ""
        reset = ""
        if self._use_color:
            color = ansi_color_of(record.levelno)
            reset = ANSI_RESET

        log_fmt = f"{color}[%(asctime)s.%(msecs)03d] [%(levelname)s]"

        if record.levelno >= logging.ERROR:
            log_fmt += " [%(name)s - %(filename)s:%(lineno)d]"

        log_fmt += f" %(message)s{reset}"

        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)


class ConsoleStreamHandler(logging.StreamHandler):
    """Run optional callbacks around each console log record."""

    def emit(self, record):
        if _before_console_output is not None:
            _before_console_output()

        try:
            super().emit(record)
        finally:
            if _after_console_output is not None:
                _after_console_output()


class ConsoleRecordFilter(logging.Filter):
    """Hide records intended only for the complete log file."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, FILE_ONLY_RECORD_ATTRIBUTE, False)


class BelowErrorFilter(logging.Filter):
    """只允许错误级别以下的记录写入标准输出。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.ERROR


def setup_logger() -> logging.Logger:
    """
    Initialize a logger with console handlers for stdout and stderr.
    """
    project_logger = logging.getLogger(LOGGER_NAME)
    project_logger.setLevel(logging.DEBUG)
    project_logger.propagate = False

    if not project_logger.handlers:
        stdout_handler = ConsoleStreamHandler(sys.stdout)
        stdout_handler.set_name(STDOUT_HANDLER_NAME)
        stdout_handler.setLevel(logging.DEBUG)
        stdout_handler.addFilter(BelowErrorFilter())
        stdout_handler.addFilter(ConsoleRecordFilter())
        stdout_handler.setFormatter(
            ColoredFormatter(supports_color(sys.stdout))
        )

        stderr_handler = ConsoleStreamHandler(sys.stderr)
        stderr_handler.set_name(STDERR_HANDLER_NAME)
        stderr_handler.setLevel(logging.ERROR)
        stderr_handler.addFilter(ConsoleRecordFilter())
        stderr_handler.setFormatter(
            ColoredFormatter(supports_color(sys.stderr))
        )

        project_logger.addHandler(stdout_handler)
        project_logger.addHandler(stderr_handler)

    return project_logger


logger: logging.Logger = setup_logger()


def configure_console_logging(verbose: bool) -> None:
    """Select warning-only or complete console logging."""
    stdout_level = logging.WARNING
    if verbose:
        stdout_level = logging.DEBUG

    project_logger = logging.getLogger(LOGGER_NAME)
    for handler in project_logger.handlers:
        if handler.get_name() == STDOUT_HANDLER_NAME:
            handler.setLevel(stdout_level)


def log_file_only(message: str, level: int = logging.INFO) -> None:
    """Write a record to file handlers without duplicating console output."""
    logger.log(
        level,
        message,
        extra={FILE_ONLY_RECORD_ATTRIBUTE: True},
        stacklevel=2,
    )


def set_console_output_hooks(
    before_output: Callable[[], None] | None,
    after_output: Callable[[], None] | None,
) -> None:
    """Set optional callbacks around console log output."""
    global _before_console_output
    global _after_console_output

    _before_console_output = before_output
    _after_console_output = after_output


def add_file_handler(log_path: Path) -> None:
    """
    Add a file handler and remove any old file handler first.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    project_logger = logging.getLogger(LOGGER_NAME)

    for handler in project_logger.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            handler.close()
            project_logger.removeHandler(handler)

    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    project_logger.addHandler(file_handler)
