"""公开项目日志配置及控制台颜色支持。"""

from . import console_color
from .console_color import (
    enable_console_color,
    supports_color,
)
from .log_config import (
    BelowErrorFilter,
    ColoredFormatter,
    ConsoleRecordFilter,
    ConsoleStreamHandler,
    FILE_ONLY_RECORD_ATTRIBUTE,
    LOGGER_NAME,
    STDERR_HANDLER_NAME,
    STDOUT_HANDLER_NAME,
    add_file_handler,
    configure_console_logging,
    log_file_only,
    logger,
    set_console_output_hooks,
)

__all__ = [
    "BelowErrorFilter",
    "ColoredFormatter",
    "ConsoleRecordFilter",
    "ConsoleStreamHandler",
    "FILE_ONLY_RECORD_ATTRIBUTE",
    "LOGGER_NAME",
    "STDERR_HANDLER_NAME",
    "STDOUT_HANDLER_NAME",
    "add_file_handler",
    "configure_console_logging",
    "console_color",
    "enable_console_color",
    "log_file_only",
    "logger",
    "set_console_output_hooks",
    "supports_color",
]
