from enum import IntEnum

class LogLevel(IntEnum):
    """Logging severity levels."""
    ERROR = 1
    WARN = 2
    INFO = 3
    DEBUG = 4