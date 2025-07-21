"""
io.py - file-system helpers for FEGA tools
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Sequence, Set

LOGGER = logging.getLogger(__name__)

def collect_candidate_json(paths: Sequence[Path]) -> List[Path]:
    """Return every *.json file found in *paths* (files **or** directories)."""
    files: Set[Path] = set()

    for p in paths:
        if not p.exists():
            LOGGER.warning(f"Path not found: {p}")
            continue

        if p.is_dir():
            for fp in p.rglob("*.json"):
                if fp.is_file():
                    files.add(fp.resolve())
        elif p.is_file() and p.suffix.lower() == ".json":
            files.add(p.resolve())
        else:
            LOGGER.debug(f"Ignoring non-JSON path: {p}")

    return sorted(files)
