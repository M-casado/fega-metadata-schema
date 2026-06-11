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
from typing import Any, Dict, List, Sequence

import requests

try:
    from fega_tools.biovalidator import (
        DEFAULT_VALIDATOR_URL,
        assert_validator_reachable,
        classify_response,
        post_to_validator,
    )
    from fega_tools.io import collect_candidate_json
    from fega_tools.logging_utils import configure_logging
    from fega_tools.validation_common import load_wrapped_example
except ModuleNotFoundError as exc:
    msg = (
        "ERROR:  The helper package 'fega_tools' is not importable.\n"
        "Make sure you have installed the repo in *editable* mode first. Run the following command from the repository root:\n"
        "    pip install -e ."
    )
    raise ModuleNotFoundError(msg) from exc

logger = logging.getLogger(Path(__file__).stem)

# -------
# Discovery helpers
# -------
def filter_metadata_files(json_files: Sequence[Path]) -> List[Path]:
    """Keep only those JSON files that expose 'data' and 'schema' keys."""
    valid: List[Path] = []
    for fp in json_files:
        try:
            load_wrapped_example(fp)
            valid.append(fp)
        except json.JSONDecodeError as exc:
            logger.warning(f"Not valid JSON file ('{fp}'). Error: {exc}")
        except (OSError, ValueError) as exc:
            logger.debug(f"Skipping '{fp}': {exc}")
    return valid

# -------
# Core routine
# -------
def validate_paths(inputs: Sequence[Path], validator_url: str) -> Dict[str, Any]:
    """Validate metadata located at *inputs* and build a summary dictionary."""
    try:
        assert_validator_reachable(validator_url)
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(2)

    all_json = collect_candidate_json(inputs)
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
        document = load_wrapped_example(fp)

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

        elif classify_response(resp) == "validation_failed":
            failed_files.append(str(fp))
            errors_of_failed_files[str(fp)] = resp
            logger.error(f"Validation FAILED for '{fp}'")

        elif classify_response(resp) == "validation_passed":
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

# -------
# CLI helpers
# -------
def make_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate_metadata",
        description="Validate FEGA JSON metadata using a Biovalidator endpoint.",
        epilog=(
            "Examples:\n"
            "  validate_metadata schemas/entities             # walk entity schema dir\n"
            "  validate_metadata schemas/entities/cohort/examples/valid/cohort-valid-detailed-study-defined.json -u http://localhost:3020/validate"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Files or directories to validate (at least one, e.g., 'schemas/entities/cohort/examples/valid/cohort-valid-detailed-study-defined.json').",
    )
    parser.add_argument(
        "--url",
        "-u",
        dest="validator_url",
        default=DEFAULT_VALIDATOR_URL,
        help=f"Biovalidator /validate endpoint (default: {DEFAULT_VALIDATOR_URL})",
    )
    parser.add_argument(
        "--verbosity",
        "-v",
        action="count",
        default=0,
        help="Increase log verbosity by adding more 'v's: '-v' for debug, '-vv' for all messages (trace).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = make_arg_parser()
    args = parser.parse_args(argv)

    configure_logging(args.verbosity)

    summary = validate_paths(args.inputs, args.validator_url)

    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")

    sys.exit(0 if summary["n_failed_files"] == 0 else 1)


if __name__ == "__main__":
    main()
