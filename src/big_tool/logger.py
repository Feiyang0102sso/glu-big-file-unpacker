"""Shared logging configuration for big-tool."""

import logging
import sys
from pathlib import Path


LOGGER_NAME = "BigTool"


class _StdoutFilter(logging.Filter):
    """Allow only records below ERROR on standard output."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.ERROR


class ColoredFormatter(logging.Formatter):
    """Add simple level colors to terminal logs."""

    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[41m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        log_format = f"{color}[%(asctime)s.%(msecs)03d] [%(levelname)s]"

        if record.levelno >= logging.ERROR:
            log_format += " [%(name)s - %(filename)s:%(lineno)d]"

        log_format += f" %(message)s{self.RESET}"
        formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)


def setup_logger() -> logging.Logger:
    """Initialize terminal log handlers."""
    configured_logger = logging.getLogger(LOGGER_NAME)
    configured_logger.setLevel(logging.DEBUG)
    configured_logger.propagate = False

    if not configured_logger.handlers:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(logging.DEBUG)
        stdout_handler.addFilter(_StdoutFilter())
        stdout_handler.setFormatter(ColoredFormatter())

        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.ERROR)
        stderr_handler.setFormatter(ColoredFormatter())

        configured_logger.addHandler(stdout_handler)
        configured_logger.addHandler(stderr_handler)

    return configured_logger


logger = setup_logger()


def add_file_handler(log_path: Path) -> None:
    """Add a file handler and remove stale file handlers."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    configured_logger = logging.getLogger(LOGGER_NAME)
    for handler in configured_logger.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            handler.close()
            configured_logger.removeHandler(handler)

    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] [%(levelname)s] "
        "[%(filename)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_format)
    configured_logger.addHandler(file_handler)
