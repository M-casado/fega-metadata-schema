"""logging_utils.py - centralised logging configuration for FEGA tools
---------------------------------------------------------------------

Usage
~~~~~
>>> from fega_tools.logging_utils import configure_logging
>>> configure_logging(verbosity=1)        # INFO+, coloured if possible
>>> logger = logging.getLogger(__name__)
>>> logger.info("Something happened")
"""
from __future__ import annotations

import logging
import sys
import time
from typing import Final

# -------
# Optional colour support
# -------
try:
    from colorama import Fore, Style, init as _c_init

    _c_init()
    _HAVE_COLORAMA: Final = True
except ModuleNotFoundError:
    _HAVE_COLORAMA = False

# -------
# Internal helpers
# -------
_DATE_FMT: Final = "%Y-%m-%d %H:%M:%S"
_PLAIN_FMT: Final = "%(" "asctime)s [%(levelname)s] %(name)s:%(lineno)d: %(message)s"


def _build_colour_formatter() -> logging.Formatter:
    """Return a colourised formatter (or plain fallback if colourama missing)."""
    if not _HAVE_COLORAMA:
        return logging.Formatter(_PLAIN_FMT, datefmt=_DATE_FMT)

    colour_map = {
        "DEBUG": Fore.CYAN,
        "INFO": Fore.GRAY,
        "WARNING": Fore.YELLOW,
        "ERROR": Fore.RED,
        "CRITICAL": Fore.MAGENTA,
    }

    class _Colour(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            colour = colour_map.get(record.levelname, "")
            record.levelname = f"{colour}{record.levelname}{Style.RESET_ALL}"
            return super().format(record)

    return _Colour(_PLAIN_FMT, datefmt=_DATE_FMT)

# -------
# Logging configuration
# -------

def configure_logging(verbosity: int = 0) -> None:
    """Configure root logger with UTC timestamps and optional colours.

    Parameters
    ----------
    verbosity : int, optional
        0 → WARNING & above (default)
        1 → INFO & above
        2+ → DEBUG & above
    """
    if not isinstance(verbosity, int) or verbosity < 0:
        raise ValueError("verbosity must be a non-negative integer")

    level = logging.WARNING if verbosity == 0 else logging.INFO if verbosity == 1 else logging.DEBUG

    # Always use UTC timestamps
    logging.Formatter.converter = time.gmtime

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_build_colour_formatter())

    root = logging.getLogger()
    root.handlers.clear()  # Avoid duplicate logs if configure_logging() runs twice
    root.setLevel(level)
    root.addHandler(handler)