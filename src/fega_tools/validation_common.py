"""Shared helpers for FEGA validation CLI scripts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

from fega_tools.io import collect_candidate_json

DEFAULT_ROOT = Path("schemas/entities")

VALID_STATUS = "validation_passed"
INVALID_STATUS = "validation_failed"
REQUEST_ERROR_STATUS = "request_error"
UNKNOWN_STATUS = "unknown_response"
SCRIPT_ERROR_STATUS = "script_error"

CATEGORIES = ("valid", "invalid")
BASIC_COUNT_KEYS = (
    "total_files",
    "completed_runs",
    "validation_passed",
    "validation_failed",
    "script_errors",
)
BIVALIDATOR_COUNT_KEYS = (
    "total_files",
    "completed_runs",
    "validation_passed",
    "validation_failed",
    "request_errors",
    "unknown_responses",
    "script_errors",
)


def find_entity_dirs(
    root: Path,
    entity: str | None,
    *,
    all_entities: bool = False,
    require_explicit: bool = False,
    require_schema: bool = False,
) -> List[Path]:
    """Return selected entity directories under an entity schema root."""
    if entity:
        entity_dir = root / entity
        if not entity_dir.is_dir():
            raise FileNotFoundError(f"Entity directory not found: {entity_dir}")
        schema_path = entity_dir / "schema.json"
        if require_schema and not schema_path.is_file():
            raise FileNotFoundError(f"Entity schema not found: {schema_path}")
        return [entity_dir]

    if require_explicit and not all_entities:
        raise ValueError("Choose exactly one suite scope: --entity NAME or --all-entities")

    if not root.is_dir():
        raise FileNotFoundError(f"Entity root not found: {root}")

    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "schema.json").is_file()
    )


def find_example_coverage_gaps(
    entity_dirs: Sequence[Path],
    categories: Sequence[str],
) -> List[Dict[str, Any]]:
    """Report missing or empty example directories for the requested categories."""
    gaps: List[Dict[str, Any]] = []

    for entity_dir in entity_dirs:
        missing: List[str] = []
        empty: List[str] = []

        for category in categories:
            category_dir = entity_dir / "examples" / category
            if not category_dir.is_dir():
                missing.append(category)
            elif not collect_candidate_json([category_dir]):
                empty.append(category)

        if missing or empty:
            gaps.append({"entity": entity_dir.name, "missing": missing, "empty": empty})

    return gaps


def coverage_gap_applies_to(gap: Dict[str, Any], category: str) -> bool:
    """Return whether a coverage gap affects one example category."""
    return category in gap.get("missing", []) or category in gap.get("empty", [])


def coverage_gaps_for_entity_category(
    coverage_gaps: Sequence[Dict[str, Any]],
    entity: str,
    category: str,
) -> List[Dict[str, Any]]:
    """Return coverage gaps for one entity/category pair."""
    return [
        gap
        for gap in coverage_gaps
        if gap.get("entity") == entity and coverage_gap_applies_to(gap, category)
    ]


def load_wrapped_example(path: Path) -> Dict[str, Any]:
    """Load a wrapped FEGA example and require top-level data/schema keys."""
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)

    if not isinstance(document, dict) or not {"data", "schema"}.issubset(document):
        raise ValueError("Expected a JSON object containing both 'data' and 'schema' keys")

    return document


def empty_counts(count_keys: Sequence[str]) -> Dict[str, int]:
    """Create a zero-filled validation counter block."""
    return {key: 0 for key in count_keys}


def add_counts(
    target: Dict[str, int],
    source: Dict[str, Any],
    count_keys: Sequence[str],
) -> None:
    """Add validation counters from one summary into another."""
    for key in count_keys:
        target[key] += source.get(key, 0)


def write_json_summary(summary: Dict[str, Any], summary_dir: Path, filename: str) -> None:
    """Write a machine-readable JSON summary file to an artifact directory."""
    summary_dir.mkdir(parents=True, exist_ok=True)
    with (summary_dir / filename).open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")
