"""Structured stdout logging.

Discipline: log message IDs, field *names*, counts, and status — never full
email bodies, client PII beyond what is necessary, or any secret value.
"""
from __future__ import annotations

import logging
import sys

def get_logger(name: str = "email_drafter", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:  # configure each named logger once
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    return logger
