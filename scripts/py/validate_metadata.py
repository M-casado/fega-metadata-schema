#!/usr/bin/env python3
"""validate_metadata.py - FEGA CLI validator

Validate one or many FEGA JSON metadata records against a running
Biovalidator instance and emit a machine-readable summary.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set

import requests
from requests.exceptions import ConnectionError, Timeout

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DEFAULT_VALIDATOR_URL = "http://localhost:3020/validate"

###############################################################################
# Endpoint check
###############################################################################
def assert_validator_reachable(url: str, timeout_seconds: int = 5) -> None:
    """Abort (exit-code 2) if *url* does not respond within *timeout_seconds*."""
    try:
        requests.get(url, timeout=timeout_seconds)
    except (ConnectionError, Timeout) as exc:
        logger.error(f"Cannot reach Biovalidator endpoint '{url}': {exc}")
        sys.exit(2)

###############################################################################
# Discovery helpers
###############################################################################
def collect_candidate_files(paths: Sequence[Path]) -> List[Path]:
    """Return every *.json file found in *paths* (files or directories)."""
    files: Set[Path] = set()
    for path in paths:
        if path.is_dir():
            files.update(child.resolve() for child in path.rglob("*.json"))
        elif path.is_file() and path.suffix.lower() == ".json":
            files.add(path.resolve())
        else:
            logger.debug(f"Skipping non-JSON path: {path}")
    return sorted(files)


def filter_metadata_files(json_files: Sequence[Path]) -> List[Path]:
    """Keep only those JSON files that expose 'data' and 'schema' keys."""
    valid: List[Path] = []
    for fp in json_files:
        try:
            with fp.open("r", encoding="utf-8") as handle:
                obj = json.load(handle)
            if isinstance(obj, dict) and {"data", "schema"}.issubset(obj):
                valid.append(fp)
            else:
                logger.debug(f"Missing 'data'/'schema' – skipping '{fp}'")
        except json.JSONDecodeError as exc:
            logger.warning(f"Not valid JSON file ('{fp}'). Error: {exc}")
    return valid

###############################################################################
# Biovalidator interaction
###############################################################################
def post_to_validator(document: Dict[str, Any], url: str) -> Dict[str, Any]:
    """Send *document* to *url* and return the parsed JSON response."""
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=document, headers=headers, timeout=300)
    response.raise_for_status()
    return response.json()

###############################################################################
# Core routine
###############################################################################
def validate_paths(inputs: Sequence[Path], validator_url: str) -> Dict[str, Any]:
    """Validate metadata located at *inputs* and build a summary dictionary."""
    assert_validator_reachable(validator_url)

    all_json = collect_candidate_files(inputs)
    targets = filter_metadata_files(all_json)

    if not targets:
        logger.error(
            "No JSON metadata files with 'data' and 'schema' keys were found under the given inputs."
        )
        sys.exit(1)

    logger.info(
        f"Discovered {len(all_json)} JSON file(s); {len(targets)} qualify for validation"
    )

    failed_files: List[str] = []
    errors_of_failed_files: Dict[str, Any] = {}

    for fp in targets:
        logger.debug(f"Validating '{fp}'")
        with fp.open("r", encoding="utf-8") as handle:
            document = json.load(handle)

        try:
            resp = post_to_validator(document, validator_url)
            request_error = False
        except (requests.RequestException, json.JSONDecodeError) as exc:
            request_error = True
            resp = str(exc)

        if request_error:
            failed_files.append(str(fp))
            errors_of_failed_files[str(fp)] = [resp]
            logger.error(f"Validation FAILED (request error) for '{fp}'")

        elif isinstance(resp, list) and resp:  # non-empty list --> errors
            failed_files.append(str(fp))
            errors_of_failed_files[str(fp)] = resp
            logger.error(f"Validation FAILED for '{fp}'")

        elif isinstance(resp, list) and len(resp) == 0:
            logger.debug(f"Validation PASSED for '{fp}'")

        else:
            failed_files.append(str(fp))
            errors_of_failed_files[str(fp)] = ["Unrecognised validator response"]
            logger.error(f"Validation FAILED (unknown response) for '{fp}'")

    summary = {
        "timestamp": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds"),
        "validator_url": validator_url,
        "input_paths": [str(p) for p in inputs],
        "n_total_files": len(targets),
        "n_failed_files": len(failed_files),
        "failed_files": failed_files,
        "errors_of_failed_files": errors_of_failed_files,
    }

    return summary

###############################################################################
# CLI helpers
###############################################################################
def make_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate_metadata",
        description="Validate FEGA JSON metadata using a Biovalidator endpoint.",
        epilog=(
            "Examples:\n"
            "  validate_metadata data             # walk default data dir\n"
            "  validate_metadata data/jsonld/cohort-valid_1.json -u http://localhost:3020/validate"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Files or directories to validate (at least one, e.g., 'data').",
    )
    parser.add_argument(
        "--url",
        "-u",
        dest="validator_url",
        default=DEFAULT_VALIDATOR_URL,
        help=f"Biovalidator /validate endpoint (default: {DEFAULT_VALIDATOR_URL})",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="Increase log verbosity by adding more 'v's: '-v' for debug, '-vv' for all messages (trace).",
    )
    return parser


def configure_logging(verbosity: int) -> None:
    if verbosity == 0:
        logging.getLogger().setLevel(logging.INFO)
    elif verbosity == 1:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.NOTSET)


def main(argv: Sequence[str] | None = None) -> None:
    parser = make_arg_parser()
    args = parser.parse_args(argv)

    configure_logging(args.verbose)

    summary = validate_paths(args.inputs, args.validator_url)

    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")

    sys.exit(0 if summary["n_failed_files"] == 0 else 1)


if __name__ == "__main__":
    main()
