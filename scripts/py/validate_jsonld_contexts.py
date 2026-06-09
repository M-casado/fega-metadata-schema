#!/usr/bin/env python3
"""Validate JSON-LD contexts in FEGA valid examples using rdflib.

Resolves all context references locally (no network calls) and parses each
example's data as RDF, checking that the graph contains at least one triple
and at least one rdf:type triple.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

import rdflib
from rdflib.namespace import RDF

try:
    from fega_tools.io import collect_candidate_json
    from fega_tools.logging_utils import configure_logging
    from fega_tools.jsonld_utils import (
        GITHUB_RAW_PREFIX,
        find_repo_root,
        build_id_to_path_map,
        resolve_ref,
        materialize_context,
    )
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
SUMMARY_FILENAME = "jsonld_summary.json"

VALID_STATUS = "validation_passed"
INVALID_STATUS = "validation_failed"
REQUEST_ERROR_STATUS = "request_error"
UNKNOWN_STATUS = "unknown_response"
SCRIPT_ERROR_STATUS = "script_error"

COUNT_KEYS = (
    "total_files",
    "completed_runs",
    "validation_passed",
    "validation_failed",
    "request_errors",
    "unknown_responses",
    "script_errors",
)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_entity_dirs(root: Path, entity: Optional[str]) -> List[Path]:
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
    """Report missing or empty valid example directories without failing the suite."""
    gaps: List[Dict[str, Any]] = []
    for entity_dir in entity_dirs:
        valid_dir = entity_dir / "examples" / "valid"
        if not valid_dir.is_dir():
            gaps.append({"entity": entity_dir.name, "missing": ["valid"], "empty": []})
        elif not collect_candidate_json([valid_dir]):
            gaps.append({"entity": entity_dir.name, "missing": [], "empty": ["valid"]})
    return gaps


# ---------------------------------------------------------------------------
# Per-file validation
# ---------------------------------------------------------------------------

def _context_url_is_acceptable(context: Any, schema_ref: str) -> bool:
    """Return True if *context* is the schema $ref URL or the matching context.jsonld URL."""
    if not isinstance(context, str):
        return False
    if context == schema_ref:
        return True
    # Accept the corresponding context.jsonld URL derived from schema.$ref.
    if schema_ref.endswith("schema.json"):
        context_jsonld_url = schema_ref[: -len("schema.json")] + "context.jsonld"
        return context == context_jsonld_url
    return False


def validate_file_jsonld(
    path: Path,
    id_to_path_map: Dict[str, Path],
) -> Dict[str, Any]:
    """Validate one example file and return a result record."""
    result: Dict[str, Any] = {"file": str(path)}

    # Step 1: Load and check wrapper structure.
    try:
        with path.open("r", encoding="utf-8") as fh:
            document = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        result.update({"status": SCRIPT_ERROR_STATUS, "errors": [str(exc)]})
        return result

    if not isinstance(document, dict) or not {"data", "schema"}.issubset(document):
        result.update(
            {
                "status": SCRIPT_ERROR_STATUS,
                "errors": ["Expected a JSON object with both 'data' and 'schema' keys"],
            }
        )
        return result

    data = document["data"]
    schema = document["schema"]

    if not isinstance(data, dict):
        result.update({"status": SCRIPT_ERROR_STATUS, "errors": ["'data' must be a JSON object"]})
        return result

    errors: List[str] = []

    # Step 2: schema.$ref
    schema_ref: str = schema.get("$ref", "") if isinstance(schema, dict) else ""
    if not schema_ref:
        errors.append("Missing schema.$ref")

    # Step 3: data.@context present
    context = data.get("@context")
    if context is None:
        errors.append("Missing data.@context")

    # Step 4: data.@context value check
    if context is not None and schema_ref and not _context_url_is_acceptable(context, schema_ref):
        errors.append(
            f"data.@context '{context}' does not match schema.$ref '{schema_ref}' "
            f"nor the expected context.jsonld URL"
        )

    # Step 5: data.@type
    if "@type" not in data:
        errors.append("Missing data.@type")

    if errors:
        result.update({"status": INVALID_STATUS, "errors": errors})
        return result

    # Step 6: Materialize context locally.
    try:
        materialized_ctx = materialize_context(context, path, id_to_path_map)
    except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
        result.update(
            {"status": INVALID_STATUS, "errors": [f"Context materialization failed: {exc}"]}
        )
        return result

    # Step 7: RDF parse – replace @context with materialized version.
    data_copy: Dict[str, Any] = json.loads(json.dumps(data))
    data_copy["@context"] = materialized_ctx

    try:
        graph = rdflib.Graph()
        graph.parse(data=json.dumps(data_copy), format="json-ld", base=schema_ref)
    except Exception as exc:  # noqa: BLE001 – rdflib raises diverse exceptions
        result.update({"status": INVALID_STATUS, "errors": [f"RDF parse failed: {exc}"]})
        return result

    if len(graph) == 0:
        result.update({"status": INVALID_STATUS, "errors": ["RDF graph contains no triples"]})
        return result

    rdf_type_triples = list(graph.triples((None, RDF.type, None)))
    if not rdf_type_triples:
        result.update(
            {"status": INVALID_STATUS, "errors": ["RDF graph contains no rdf:type triples"]}
        )
        return result

    result.update(
        {
            "status": VALID_STATUS,
            "n_triples": len(graph),
            "n_type_triples": len(rdf_type_triples),
        }
    )
    return result


# ---------------------------------------------------------------------------
# Summarization helpers
# ---------------------------------------------------------------------------

def empty_counts() -> Dict[str, int]:
    """Return a zero-filled counter block matching COUNT_KEYS."""
    return {key: 0 for key in COUNT_KEYS}


def add_counts(target: Dict[str, int], source: Dict[str, Any]) -> None:
    """Accumulate validation counters from *source* into *target*."""
    for key in COUNT_KEYS:
        target[key] += source.get(key, 0)


def category_passed(summary: Dict[str, Any]) -> bool:
    """Return True when the valid-example suite passes.

    Fails if any file did not pass validation, if there are script/request
    errors, or if the entity has coverage gaps (missing or empty valid
    examples directory — all valid examples must include @context).
    """
    return (
        len(summary["coverage_gaps"]) == 0
        and summary["script_errors"] == 0
        and summary["request_errors"] == 0
        and summary["unknown_responses"] == 0
        and summary["validation_failed"] == 0
    )


def summarize_entity(
    entity_dir: Path,
    id_to_path_map: Dict[str, Path],
    coverage_gaps: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Validate and summarise valid examples for one entity."""
    valid_dir = entity_dir / "examples" / "valid"
    files = collect_candidate_json([valid_dir]) if valid_dir.is_dir() else []

    entity_coverage_gaps = [g for g in coverage_gaps if g.get("entity") == entity_dir.name]

    results: List[Dict[str, Any]] = []
    for path in files:
        file_result = validate_file_jsonld(path, id_to_path_map)
        results.append(file_result)
        outcome = "passed" if file_result["status"] == VALID_STATUS else "failed"
        LOGGER.debug("Validated '%s' -> %s", path.name, outcome)

    status_counts = {
        VALID_STATUS: 0,
        INVALID_STATUS: 0,
        REQUEST_ERROR_STATUS: 0,
        UNKNOWN_STATUS: 0,
        SCRIPT_ERROR_STATUS: 0,
    }
    for file_result in results:
        status_counts[file_result["status"]] += 1

    expectation_failed_files = [
        r["file"] for r in results if r["status"] != VALID_STATUS
    ]

    summary: Dict[str, Any] = {
        "entity": entity_dir.name,
        "input_path": str(valid_dir),
        "coverage_gaps": entity_coverage_gaps,
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
        "n_failed_files": len(expectation_failed_files),
    }
    summary["passed"] = category_passed(summary)
    return summary


def summarize_totals(
    entity_summaries: Sequence[Dict[str, Any]],
) -> Dict[str, int]:
    """Aggregate validation counters across all entity summaries."""
    totals = empty_counts()
    for entity_summary in entity_summaries:
        add_counts(totals, entity_summary)
    return totals


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

def validate_jsonld_contexts(
    root: Path,
    entity: Optional[str],
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run JSON-LD context smoke tests for all valid examples under *root*.

    Parameters
    ----------
    root:       Entity schema root (default: schemas/entities).
    entity:     Restrict to one entity directory by name.
    repo_root:  Repository root used to resolve local schema paths. When
                *None*, auto-detected by walking up from *root*.
    """
    if repo_root is None:
        repo_root = find_repo_root(root.resolve())

    id_to_path_map = build_id_to_path_map(repo_root)
    LOGGER.debug("Loaded %d entries in schema/context map", len(id_to_path_map))

    entity_dirs = find_entity_dirs(root, entity)
    if not entity_dirs:
        raise FileNotFoundError(f"No entity schema directories found under {root}")

    coverage_gaps = find_coverage_gaps(entity_dirs)
    for gap in coverage_gaps:
        details: List[str] = []
        if gap.get("missing"):
            details.append(f"missing {', '.join(gap['missing'])} examples")
        if gap.get("empty"):
            details.append(f"empty {', '.join(gap['empty'])} examples")
        LOGGER.error(
            "Coverage gap for %s: %s — all valid examples must include @context",
            gap["entity"],
            "; ".join(details),
        )

    entity_summaries = [
        summarize_entity(entity_dir, id_to_path_map, coverage_gaps)
        for entity_dir in entity_dirs
    ]

    totals = summarize_totals(entity_summaries)
    overall_passed = all(s["passed"] for s in entity_summaries)

    input_paths = [s["input_path"] for s in entity_summaries]

    return {
        "timestamp": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds"),
        "root": str(root),
        "passed": overall_passed,
        "entity": entity,
        "entity_names": [path.name for path in entity_dirs],
        "total_valid_files": totals["total_files"],
        **totals,
        "valid_examples_passed": overall_passed,
        "input_paths": input_paths,
        "coverage_gaps": coverage_gaps,
        "files": entity_summaries,
    }


# ---------------------------------------------------------------------------
# Logging / output
# ---------------------------------------------------------------------------

def _log_results(summary: Dict[str, Any]) -> None:
    """Emit INFO-level result lines for the validation run."""
    passed_count = summary["validation_passed"]
    total_count = summary["total_valid_files"]
    LOGGER.info("%d / %d valid files passed JSON-LD context checks", passed_count, total_count)

    if summary["passed"]:
        LOGGER.info("Tests %spassed%s", _BOLD_GREEN, _ANSI_RESET)
    else:
        LOGGER.info("Tests %sfailed%s", _BOLD_RED, _ANSI_RESET)


def write_summary(summary: Dict[str, Any], summary_dir: Path) -> None:
    """Write the validation summary to *summary_dir/jsonld_summary.json*."""
    summary_dir.mkdir(parents=True, exist_ok=True)
    with (summary_dir / SUMMARY_FILENAME).open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
        fh.write("\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def make_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="validate_jsonld_contexts",
        description=(
            "Validate JSON-LD contexts in FEGA valid examples.\n"
            "Resolves all context references locally; does not require Biovalidator."
        ),
        epilog=(
            "Examples:\n"
            "  validate_jsonld_contexts --entity cohort\n"
            "  validate_jsonld_contexts --root schemas/entities --summary-dir ."
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
        help="Increase log verbosity: -v for INFO, -vv for DEBUG.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Run the CLI and exit with the suite status code."""
    parser = make_arg_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbosity)

    try:
        summary = validate_jsonld_contexts(args.root, args.entity)
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
