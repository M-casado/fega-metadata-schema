#!/usr/bin/env python3
"""validate_metadata.py - FEGA CLI validator (ASCII-only).

Validate one or many FEGA JSON metadata records against a running
Biovalidator instance.
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
    """Raise SystemExit if the Biovalidator endpoint *url* is unreachable.

    We issue a lightweight GET request; any connection error or timeout means
    continuing would be pointless.
    """
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
                logger.debug(f"Missing 'data'/'schema' - skipping '{fp}'")
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


def response_has_errors(resp: Dict[str, Any]) -> bool:
    """Return True if the validator response contains any errors."""
    for key in ("errors", "validationMessages"):
        if key in resp and isinstance(resp[key], list) and resp[key]:
            return True
    return False

###############################################################################
# Core routine
###############################################################################

def validate_paths(inputs: Sequence[Path], validator_url: str) -> Dict[str, Any]:
    """Validate metadata located at *inputs* and build a summary dictionary."""
    # Abort early if endpoint is unreachable
    assert_validator_reachable(validator_url)

    all_json = collect_candidate_files(inputs)
    targets = filter_metadata_files(all_json)

    if not targets:
        logger.error("No JSON metadata files with 'data' and 'schema' keys were found under the given inputs.")
        sys.exit(1)

    logger.info(
        f"Discovered {len(all_json)} JSON file(s); {len(targets)} qualify for validation"
    )

    failed_files: List[str] = []

    for fp in targets:
        r_error = False
        logger.debug(f"Validating '{fp}'")
        with fp.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        try:
            resp = post_to_validator(document, validator_url)
        except (requests.RequestException, json.JSONDecodeError) as exc:
            logger.error(f"Request failed for '{fp}': {exc}")
            r_error = True

        if r_error:
            failed_files.append(str(fp))
            logger.error(f"Validation FAILED with error at REQUEST for '{fp}'")
        elif isinstance(resp, list) and len(resp) > 0:
            failed_files.append(str(fp))
            logger.error(f"Validation FAILED for '{fp}'")
        elif isinstance(resp, list) and len(resp) == 0:
            logger.debug(f"Validation PASSED for '{fp}'")
        else:
            failed_files.append(str(fp))
            logger.error(f"Unrecognised REQUEST RESPONSE for '{fp}'")

    summary = {
        "timestamp": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds"),
        "validator_url": validator_url,
        "input_paths": [str(p) for p in inputs],
        "n_total_files": len(targets),
        "n_failed_files": len(failed_files),
        "failed_files": failed_files,
    }

    return summary

###############################################################################
# CLI
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

    json.dump(summary, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")

    sys.exit(0 if summary["n_failed_files"] == 0 else 1)


if __name__ == "__main__":
    main()
