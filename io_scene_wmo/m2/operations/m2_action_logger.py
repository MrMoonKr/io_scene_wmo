from datetime import datetime
from enum import IntEnum

from ...ui.preferences import get_project_preferences
from . import m2_export_validation

class LogLevel(IntEnum):
    """Logging severity levels."""
    ERROR = 1
    WARN = 2
    INFO = 3
    DEBUG = 4

# ---------------------------
# Storage
# ---------------------------

errors = []
warnings = []
infos = []
debugs = []
master_log = []

# ---------------------------
# Utility
# ---------------------------

def clear():
    """Reset all stored logs."""
    warnings.clear()
    infos.clear()
    errors.clear()
    debugs.clear()
    master_log.clear()


def get_verbosity_level() -> int:
    """
    Retrieve verbosity setting from addon preferences.
    Defaults to INFO level (3) if unavailable.
    """
    try:
        prefs = get_project_preferences()
        return int(prefs.verbosity_level)
    except Exception:
        return 3  # INFO fallback
        

# ---------------------------
# Core logging
# ---------------------------

def add(level: LogLevel, msg: str, print_now: bool = False):
    """
    Store a log entry and optionally print immediately.

    Args:
        level (LogLevel): severity of message
        msg (str): log message string
        print_now (bool): force console print immediately
    """
    verbosity = get_verbosity_level()
    timestamp = datetime.now().strftime("%H:%M:%S")

    # --- Record per-level ---
    if level == LogLevel.ERROR:
        errors.append(msg)
    elif level == LogLevel.WARN:
        warnings.append(msg)
    elif level == LogLevel.INFO:
        infos.append(msg)
    elif level == LogLevel.DEBUG:
        debugs.append(msg)

    # --- Append chronological record ---
    master_log.append((level, msg, timestamp))

    # --- Live print if enabled ---
    if print_now and verbosity >= level:
        print(f"[{timestamp}] [{level.name}] {msg}")


def _print_log_summary(title: str, validation_fn=None):
    """
    Print combined summary for import/export logs.

    Args:
        title (str): label ("Import" or "Export")
        validation_fn (callable, optional): optional validation hook

    Returns:
        tuple(bool, bool): (warnings_present, errors_present)
    """
    verbosity = get_verbosity_level()

    print("\n##############################################################")
    print(f"          {title} Log Summary")
    print("##############################################################")

    # --- Optional validation ---
    if callable(validation_fn):
        for name, descriptions, items in validation_fn():
            print(f"\n== {name} ==")
            for d in descriptions:
                print(f"  {d}")
            for item in items:
                add(LogLevel.WARN, f"[{name}] {item}", print_now=True)

    # --- Errors & Warnings ---
    if errors:
        print(f"\n== {title} Errors ==")
        for msg in errors:
            print(f"  [ERROR] {msg}")

    if warnings:
        print(f"\n== {title} Warnings ==")
        for msg in warnings:
            print(f"  [WARN] {msg}")

    # --- Full chronological log ---
    print(f"\n== {title} Log ==")
    for level, msg, timestamp in master_log:
        if verbosity >= level:
            print(f"  [{timestamp}] [{level.name}] {msg}")

    # --- Summary footer ---
    print("\n##############################################################")
    print(f"  Summary: {len(errors)} errors, {len(warnings)} warnings, "
          f"{len(infos)} info, {len(debugs)} debug messages")
    print("##############################################################\n")

    return bool(warnings), bool(errors)


def print_export_log():
    """
    Print export summary and run export validation checks.
    Returns: (warnings_present, errors_present)
    """
    return _print_log_summary("Export", validation_fn=m2_export_validation.run_validations)


def print_import_log():
    """
    Print import summary only.
    Returns: (warnings_present, errors_present)
    """
    return _print_log_summary("Import")

# ---------------------------
# Shorthands
# ---------------------------

error = lambda msg, print_now=False, **kw: add(LogLevel.ERROR, msg, print_now=print_now, **kw)
warn  = lambda msg, print_now=False, **kw: add(LogLevel.WARN, msg, print_now=print_now, **kw)
info  = lambda msg, print_now=False, **kw: add(LogLevel.INFO, msg, print_now=print_now, **kw)
debug = lambda msg, print_now=False, **kw: add(LogLevel.DEBUG, msg, print_now=print_now, **kw)
