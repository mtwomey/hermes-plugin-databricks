#!/usr/bin/env python3
"""
logging_utils.py — Shared logging setup for Hermes plugins.

Bundled copy — each plugin repo carries its own copy so it is fully self-contained.

Usage in a native plugin (__init__.py):
    from logging_utils import setup_logging
    log = setup_logging("databricks", _get_log_level())

    # Then in tools.py (get the same logger by name):
    import logging
    log = logging.getLogger("databricks")
    log.debug("tool called: arg=%s", value)
    log.error("call failed: %s", e)

Log file location:  ~/.hermes/logs/<tool_name>.log
Log rotation:       5 MB per file, 3 backups kept  (so max ~20 MB on disk)
Default level:      WARNING  (silent in normal operation)

Toggle:
    ./setup.sh log debug   →  sets plugins.config.databricks.log_level=DEBUG in config.yaml
    ./setup.sh log quiet   →  removes plugins.config.databricks.log_level from config.yaml
    (both require a Hermes restart to take effect)

IMPORTANT: Never log to stdout — stdout is the MCP JSON-RPC wire for MCP servers.
           This module only ever writes to a rotating file + stderr (at WARNING+).
"""

import logging
import logging.handlers
import os
from pathlib import Path


def setup_logging(tool_name: str, level: str = "WARNING") -> logging.Logger:
    """
    Configure and return a logger for a Hermes plugin.

    Args:
        tool_name:  Short name used for the log file, e.g. "databricks".
                    Log file will be at ~/.hermes/logs/<tool_name>.log
        level:      Logging level string: DEBUG | INFO | WARNING | ERROR | CRITICAL.
                    Default WARNING (quiet in normal operation).

    Returns:
        logging.Logger — use log.debug(), log.info(), log.warning(), log.error()
    """
    numeric_level = getattr(logging, level.upper(), logging.WARNING)

    # --- log directory -------------------------------------------------------
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    log_dir = hermes_home / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{tool_name}.log"

    # --- logger --------------------------------------------------------------
    logger = logging.getLogger(tool_name)
    logger.setLevel(numeric_level)

    # Avoid duplicate handlers if setup_logging is called more than once
    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler — 5 MB × 3 backups ≈ 20 MB max on disk
    fh = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(numeric_level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # stderr handler for WARNING and above — visible in Hermes server logs
    sh = logging.StreamHandler(stream=__import__("sys").stderr)
    sh.setLevel(logging.WARNING)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    logger.debug("Logging initialised: tool=%s level=%s file=%s", tool_name, level, log_file)
    return logger
