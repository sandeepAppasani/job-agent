"""Logging configuration for the Job Search Agent."""
import logging
import os
import sys
from pathlib import Path
from datetime import datetime

# Resolve LOG_DIR relative to this file so it works anywhere
LOG_DIR = Path(os.getenv("PROJECT_DIR", Path(__file__).parent.parent)) / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger writing to console + daily log file."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    log_file = LOG_DIR / f"agent_{datetime.now().strftime('%Y%m%d')}.log"
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
