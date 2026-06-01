#!/usr/bin/env python3
"""Validate FEGA example suites against a running Biovalidator endpoint."""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

import requests
from requests.exceptions import ConnectionError, Timeout

try:
    from fega_tools.io import collect_candidate_json
    from fega_tools.logging_utils import configure_logging
except ModuleNotFoundError as exc:
    msg = (
        "ERROR: The helper package 'fega_tools' is not importable.\n"
        "Make sure you have installed the repo in editable mode first. Run this from the repository root:\n"
        "    pip install -e ."
    )
    raise ModuleNotFoundError(msg) from exc


LOGGER = logging.getLogger(Path(__file__).stem)

try:
    from colorama import Fore as _Fore, Style as _Style
    _BOLD_GREEN = _Style.BRIGHT + _Fore.GREEN
    _BOLD_RED = _Style.BRIGHT + _Fore.RED
    _ANSI_RESET = _Style.RESET_ALL
except ModuleNotFoundError:
    _BOLD_GREEN = _BOLD_RED = _ANSI_RESET = ""

DEFAULT_ROOT = Path("schemas/entities")
DEFAULT_VALIDATOR_URL = "http://localhost:3020/validate"
SUMMARY_FILENAME = "summary.json"
VALID_STATUS = "validation_passed"
INVALID_STATUS = "validation_failed"
REQUEST_ERROR_STATUS = "request_error"
UNKNOWN_STATUS = "unknown_response"
SCRIPT_ERROR_STATUS = "script_error"
CATEGORIES = ("valid", "invalid")
COUNT_KEYS = (
    "total_files",
    "completed_runs",
    "validation_passed",
    "validation_failed",
    "request_errors",
    "unknown_responses",
    "script_errors",
)


def assert_validator_reachable(url: str, timeout_seconds: int = 5) -> None:
    """Raise RuntimeError if the Biovalidator endpoint is not reachable."""
    try:
        requests.get(url, timeout=timeout_seconds)
    except (ConnectionError, Timeout, requests.RequestException) as exc:
        raise RuntimeError(f"Cannot reach Biovalidator endpoint '{url}': {exc}") from exc


def find_entity_dirs(root: Path, entity: str | None) -> List[Path]:
    """Return entity directories to validate."""
    if entity:
        entity_dir = root / entity
        if not entity_dir.is_dir():
            raise FileNotFoundError(f"Entity directory not found: {entity_dir}")
        return [entity_dir]

    if not root.is_dir():
        raise FileNotFoundError(f"Entity root not found: {root}")

    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "schema.json").is_file()
    )


def find_coverage_gaps(entity_dirs: Sequence[Path]) -> List[Dict[str, Any]]:
    """Report missing or empty valid/invalid example directories without failing the suite."""
    gaps: List[Dict[str, Any]] = []

    for entity_dir in entity_dirs:
        missing: List[str] = []
        empty: List[str] = []

        for category in CATEGORIES:
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
    coverage_gaps: Sequence[Dict[str, Any]], entity: str, category: str
) -> List[Dict[str, Any]]:
    """Return the coverage gaps for one entity and one example category."""
    return [
        gap
        for gap in coverage_gaps
        if gap.get("entity") == entity and coverage_gap_applies_to(gap, category)
    ]


def example_dirs(entity_dirs: Sequence[Path], category: str) -> List[Path]:
    """Return existing example directories for one category."""
    return [
        entity_dir / "examples" / category
        for entity_dir in entity_dirs
        if (entity_dir / "examples" / category).is_dir()
    ]


def load_example(path: Path) -> Dict[str, Any]:
    """Load an example wrapper document and require data/schema keys."""
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)

    if not isinstance(document, dict) or not {"data", "schema"}.issubset(document):
        raise ValueError("Expected a JSON object containing both 'data' and 'schema' keys")

    return document


def post_to_validator(document: Dict[str, Any], url: str) -> Any:
    """Send a wrapper document to Biovalidator and return the parsed response."""
    response = requests.post(
        url,
        json=document,
        headers={"Content-Type": "application/json"},
        timeout=300,
    )
    response.raise_for_status()
    return response.json()


def classify_response(response: Any) -> str:
    """Classify Biovalidator's response shape."""
    if isinstance(response, list) and len(response) == 0:
        return VALID_STATUS
    if isinstance(response, list):
        return INVALID_STATUS
    return UNKNOWN_STATUS


def validate_file(path: Path, validator_url: str) -> Dict[str, Any]:
    """Validate one example file and return a result record."""
    result: Dict[str, Any] = {"file": str(path)}

    try:
        document = load_example(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        result.update({"status": SCRIPT_ERROR_STATUS, "errors": [str(exc)]})
        return result

    try:
        response = post_to_validator(document, validator_url)
    except requests.RequestException as exc:
        result.update({"status": REQUEST_ERROR_STATUS, "errors": [str(exc)]})
        return result
    except (json.JSONDecodeError, ValueError) as exc:
        result.update({"status": UNKNOWN_STATUS, "errors": [f"Malformed validator response: {exc}"]})
        return result

    status = classify_response(response)
    result["status"] = status
    if status != VALID_STATUS:
        result["errors"] = response if isinstance(response, list) else [response]

    return result


def category_passed(summary: Dict[str, Any], expectation: str) -> bool:
    """Apply the strict pass/fail rules for valid and invalid example suites."""
    total_files = summary["total_files"]
    common_ok = (
        summary["completed_runs"] == total_files
        and summary["request_errors"] == 0
        and summary["unknown_responses"] == 0
        and summary["script_errors"] == 0
    )

    if expectation == "valid":
        return (
            common_ok
            and summary["validation_passed"] == total_files
            and summary["validation_failed"] == 0
        )

    return (
        common_ok
        and summary["validation_failed"] == total_files
        and summary["validation_passed"] == 0
    )


def empty_counts() -> Dict[str, int]:
    """Create a zero-filled counter block for validation result totals."""
    return {key: 0 for key in COUNT_KEYS}


def expected_status_for(expectation: str) -> str:
    """Return the validator status that satisfies one example category."""
    return VALID_STATUS if expectation == "valid" else INVALID_STATUS


def add_counts(target: Dict[str, int], source: Dict[str, Any]) -> None:
    """Add validation counters from one summary into another."""
    for key in COUNT_KEYS:
        target[key] += source[key]


def summarize_category(
    entity_dir: Path,
    category: str,
    validator_url: str,
    coverage_gaps: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Validate one entity's examples for a category and summarize the result."""
    category_dir = entity_dir / "examples" / category
    files = collect_candidate_json([category_dir]) if category_dir.is_dir() else []
    expected_status = expected_status_for(category)
    results = []
    for path in files:
        result = validate_file(path, validator_url)
        results.append(result)
        outcome = "passed" if result["status"] == expected_status else "failed"
        LOGGER.debug("Validated '%s' [expected: %s] -> %s", path.name, category, outcome)
    status_counts = {
        VALID_STATUS: 0,
        INVALID_STATUS: 0,
        REQUEST_ERROR_STATUS: 0,
        UNKNOWN_STATUS: 0,
        SCRIPT_ERROR_STATUS: 0,
    }

    for result in results:
        status_counts[result["status"]] += 1

    expectation_failed_files = [
        result["file"] for result in results if result["status"] != expected_status
    ]

    summary: Dict[str, Any] = {
        "expectation": category,
        "input_path": str(category_dir),
        "coverage_gaps": coverage_gaps_for_entity_category(
            coverage_gaps, entity_dir.name, category
        ),
        "total_files": len(files),
        "completed_runs": status_counts[VALID_STATUS] + status_counts[INVALID_STATUS],
        "validation_passed": status_counts[VALID_STATUS],
        "validation_failed": status_counts[INVALID_STATUS],
        "request_errors": status_counts[REQUEST_ERROR_STATUS],
        "unknown_responses": status_counts[UNKNOWN_STATUS],
        "script_errors": status_counts[SCRIPT_ERROR_STATUS],
        "files": results,
        "expectation_failed_files": expectation_failed_files,
        "n_total_files": len(files),
        "n_failed_files": status_counts[INVALID_STATUS],
    }
    summary["passed"] = category_passed(summary, category)
    return summary


def summarize_entity(
    entity_dir: Path,
    validator_url: str,
    coverage_gaps: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Validate and summarize all example categories for one entity."""
    return {
        "entity": entity_dir.name,
        "categories": {
            category: summarize_category(
                entity_dir,
                category,
                validator_url,
                coverage_gaps,
            )
            for category in CATEGORIES
        },
    }


def summarize_totals(entity_summaries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate validation counters across all entities and categories."""
    category_totals: Dict[str, Dict[str, Any]] = {
        category: {"expectation": category, **empty_counts()} for category in CATEGORIES
    }
    totals = empty_counts()

    for entity_summary in entity_summaries:
        for category in CATEGORIES:
            category_summary = entity_summary["categories"][category]
            add_counts(category_totals[category], category_summary)
            add_counts(totals, category_summary)

    for category in CATEGORIES:
        category_totals[category]["passed"] = category_passed(
            category_totals[category], category
        )

    totals["category_totals"] = category_totals
    return totals


def validate_examples(
    root: Path,
    entity: str | None,
    validator_url: str,
) -> Dict[str, Any]:
    """Validate valid and invalid example suites under an entity root."""
    assert_validator_reachable(validator_url)

    entity_dirs = find_entity_dirs(root, entity)
    if not entity_dirs:
        raise FileNotFoundError(f"No entity schema directories found under {root}")

    coverage_gaps = find_coverage_gaps(entity_dirs)
    for gap in coverage_gaps:
        details = []
        if gap.get("missing"):
            details.append(f"missing {', '.join(gap['missing'])} examples")
        if gap.get("empty"):
            details.append(f"empty {', '.join(gap['empty'])} examples")
        LOGGER.warning(
            "Coverage gap for %s: %s",
            gap["entity"],
            "; ".join(details),
        )

    file_summaries = [
        summarize_entity(entity_dir, validator_url, coverage_gaps)
        for entity_dir in entity_dirs
    ]
    totals = summarize_totals(file_summaries)
    category_totals = totals.pop("category_totals")
    input_paths = [
        entity_summary["categories"][category]["input_path"]
        for entity_summary in file_summaries
        for category in CATEGORIES
    ]
    valid_examples_passed = category_totals["valid"]["passed"]
    invalid_examples_passed = category_totals["invalid"]["passed"]

    return {
        "timestamp": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds"),
        "validator_url": validator_url,
        "root": str(root),
        "passed": valid_examples_passed and invalid_examples_passed,
        "entity": entity,
        "entity_names": [path.name for path in entity_dirs],
        "total_valid_files": category_totals["valid"]["total_files"],
        "total_invalid_files": category_totals["invalid"]["total_files"],
        **totals,
        "valid_examples_passed": valid_examples_passed,
        "invalid_examples_passed": invalid_examples_passed,
        "input_paths": input_paths,
        "category_totals": category_totals,
        "coverage_gaps": coverage_gaps,
        "files": file_summaries,
    }


def _log_results(summary: Dict[str, Any]) -> None:
    """Emit INFO-level result lines for the validation run."""
    cat = summary["category_totals"]
    valid_passed = cat["valid"]["validation_passed"]
    valid_total = cat["valid"]["total_files"]
    invalid_passed = cat["invalid"]["validation_failed"]
    invalid_total = cat["invalid"]["total_files"]

    LOGGER.info("%d / %d valid files passed validation", valid_passed, valid_total)
    LOGGER.info("%d / %d invalid files passed validation", invalid_passed, invalid_total)

    if summary["passed"]:
        LOGGER.info("Tests %spassed%s", _BOLD_GREEN, _ANSI_RESET)
    else:
        LOGGER.info("Tests %sfailed%s", _BOLD_RED, _ANSI_RESET)


def write_summary(summary: Dict[str, Any], summary_dir: Path) -> None:
    """Write the combined validation summary to the artifact directory."""
    summary_dir.mkdir(parents=True, exist_ok=True)
    with (summary_dir / SUMMARY_FILENAME).open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")


def make_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the validation runner."""
    parser = argparse.ArgumentParser(
        prog="validate_examples",
        description="Validate FEGA valid/invalid examples using a Biovalidator endpoint.",
        epilog=(
            "Examples:\n"
            "  validate_examples --entity cohort\n"
            "  validate_examples --root schemas/entities --summary-dir ."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"Entity schema root (default: {DEFAULT_ROOT})",
    )
    parser.add_argument(
        "--entity",
        help="Validate one entity by directory name, e.g. 'cohort'.",
    )
    parser.add_argument(
        "--url",
        "-u",
        dest="validator_url",
        default=DEFAULT_VALIDATOR_URL,
        help=f"Biovalidator /validate endpoint (default: {DEFAULT_VALIDATOR_URL})",
    )
    parser.add_argument(
        "--summary-dir",
        type=Path,
        help=f"Optional directory where {SUMMARY_FILENAME} is written.",
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        default=False,
        help="Print the full JSON summary to stdout (default: off).",
    )
    parser.add_argument(
        "--verbosity",
        "-v",
        action="count",
        default=0,
        help="Increase log verbosity by adding more 'v's.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the command-line interface and exit with the suite status code."""
    parser = make_arg_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbosity)

    try:
        summary = validate_examples(args.root, args.entity, args.validator_url)
    except (FileNotFoundError, RuntimeError) as exc:
        LOGGER.error(str(exc))
        sys.exit(2)

    _log_results(summary)

    if args.summary_dir:
        write_summary(summary, args.summary_dir)

    if args.print_summary:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")

    sys.exit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
