"""公开项目日志配置及控制台颜色支持。"""

from . import console_color
from .console_color import (
    enable_console_color,
    supports_color,
)
from .log_config import (
    ANSI_RESET,
    BelowErrorFilter,
    ColoredFormatter,
    ConsoleRecordFilter,
    ConsoleStreamHandler,
    FILE_ONLY_RECORD_ATTRIBUTE,
    LEVEL_COLORS,
    LOGGER_NAME,
    LevelColor,
    STDERR_HANDLER_NAME,
    STDOUT_HANDLER_NAME,
    add_file_handler,
    ansi_color_of,
    configure_console_logging,
    log_file_only,
    logger,
    set_console_output_hooks,
)

__all__ = [
    "ANSI_RESET",
    "BelowErrorFilter",
    "ColoredFormatter",
    "ConsoleRecordFilter",
    "ConsoleStreamHandler",
    "FILE_ONLY_RECORD_ATTRIBUTE",
    "LEVEL_COLORS",
    "LOGGER_NAME",
    "LevelColor",
    "STDERR_HANDLER_NAME",
    "STDOUT_HANDLER_NAME",
    "add_file_handler",
    "ansi_color_of",
    "configure_console_logging",
    "console_color",
    "enable_console_color",
    "log_file_only",
    "logger",
    "set_console_output_hooks",
    "supports_color",
]
