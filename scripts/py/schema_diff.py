#!/usr/bin/env python3
"""schema_diff.py - Compare JSON Schemas for semantic versioning changes

This script compares two sets of JSON Schemas (files or directories) and reports
whether changes require major, minor, or patch version bumps according to semver rules.

Typical usage
------------
# Compare two schema files
python scripts/py/schema_diff.py v1/FEGA.cohort.json v2/FEGA.cohort.json -v

# Compare all schemas in two directories
python scripts/py/schema_diff.py v1/schemas v2/schemas --output report.json -v

# Quick check between branches (from repo root)
python scripts/py/schema_diff.py schemas dev/schemas -v
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from typing import Dict, Any, Sequence

try:
    from jsonschema import validators
except ImportError:
    print("ERROR: Install jsonschema: pip install jsonschema")
    sys.exit(1)

try:
    from fega_tools.io import collect_candidate_json
    from fega_tools.logging_utils import configure_logging
except ModuleNotFoundError as exc:
    msg = (
        "ERROR: The helper package 'fega_tools' is not importable.\n"
        "Make sure you have installed the repo in *editable* mode first. Run:\n"
        "    pip install -e ."
    )
    raise ModuleNotFoundError(msg) from exc

logger = logging.getLogger(Path(__file__).stem)

DESCRIPTION_FIELDS = {"description", "title", "$comment", "examples", "meta:version"}
# Keywords that are part of the JSON Schema specification
#   and should be compared for breaking changes:
SCHEMA_KEYWORDS = {
    "type", "properties", "required", "additionalProperties", "items", "$id", "$ref",
    "allOf", "anyOf", "oneOf", "not", "if", "then", "else",
    "minItems", "maxItems", "minimum", "maximum", "pattern", "@context"
}

# -------
# Schema comparison logic
# -------

def compare_schemas(schema1: Dict[str, Any], schema2: Dict[str, Any]) -> Dict[str, Any]:
    """Custom schema comparison logic."""
    changes = {
        "breaking_changes": [],
        "non_breaking_changes": [],
        "description_changes": []
    }

    def compare_properties(props1: Dict[str, Any], props2: Dict[str, Any], path: str) -> None:
        """Compare schema properties specifically."""
        # Check for new properties
        new_props = set(props2.keys()) - set(props1.keys())
        if new_props:
            changes["non_breaking_changes"].append({
                "path": path,
                "change": f"new properties added: {sorted(new_props)}"
            })
        
        # Check for removed properties
        removed_props = set(props1.keys()) - set(props2.keys())
        if removed_props:
            changes["breaking_changes"].append({
                "path": path,
                "change": f"properties removed: {sorted(removed_props)}"
            })

        # Compare common properties recursively
        common_props = set(props1.keys()) & set(props2.keys())
        for prop in common_props:
            prop_path = f"{path}/{prop}"
            compare_recursively(props1[prop], props2[prop], prop_path)

    def compare_arrays(arr1: list, arr2: list, path: str) -> None:
        """Compare arrays of schema elements."""
        if len(arr1) != len(arr2):
            changes["breaking_changes"].append({
                "path": path,
                "change": f"array length changed from {len(arr1)} to {len(arr2)}"
            })
            return
        
        # For schema arrays, order usually matters
        for i, (item1, item2) in enumerate(zip(arr1, arr2)):
            if isinstance(item1, dict) and isinstance(item2, dict):
                compare_recursively(item1, item2, f"{path}[{i}]")
            elif item1 != item2:
                changes["breaking_changes"].append({
                    "path": f"{path}[{i}]",
                    "old": item1,
                    "new": item2
                })

    def compare_recursively(s1: Dict[str, Any], s2: Dict[str, Any], path: str = "") -> None:
        """Compare two schema elements recursively."""
        # Handle non-dict values
        if not isinstance(s1, dict) or not isinstance(s2, dict):
            if s1 != s2:
                if isinstance(s1, bool) or isinstance(s2, bool):
                    # Special handling for boolean properties (e.g., "required": false)
                    changes["breaking_changes"].append({
                        "path": path,
                        "old": s1,
                        "new": s2,
                        "change": "property constraint changed"
                    })
                else:
                    changes["breaking_changes"].append({
                        "path": path,
                        "old": s1,
                        "new": s2
                    })
            return

        # Continue with normal dict comparison
        for key in set(s1.keys()) | set(s2.keys()):
            current_path = f"{path}/{key}" if path else key
            
            # Handle missing keys
            if key not in s1:
                if key in SCHEMA_KEYWORDS:
                    changes["breaking_changes"].append({
                        "path": current_path,
                        "change": "added schema keyword"
                    })
                elif key in DESCRIPTION_FIELDS:
                    changes["description_changes"].append({
                        "path": current_path,
                        "change": "added description field",
                        "new": s2[key]
                    })
                continue

            if key not in s2:
                if key in SCHEMA_KEYWORDS:
                    changes["breaking_changes"].append({
                        "path": current_path,
                        "change": "removed schema keyword"
                    })
                elif key in DESCRIPTION_FIELDS:
                    changes["description_changes"].append({
                        "path": current_path,
                        "change": "removed description field",
                        "old": s1[key]
                    })
                continue

            # Compare values
            if isinstance(s1[key], dict) and isinstance(s2[key], dict):
                if key == "properties":
                    compare_properties(s1[key], s2[key], current_path)
                else:
                    compare_recursively(s1[key], s2[key], current_path)
            elif isinstance(s1[key], list) and isinstance(s2[key], list):
                # Special handling for array-type keywords
                if key in {"allOf", "anyOf", "oneOf"}:
                    compare_arrays(s1[key], s2[key], current_path)
                elif key == "required":
                    # Special handling for required arrays
                    added = set(s2[key]) - set(s1[key])
                    removed = set(s1[key]) - set(s2[key])
                    if added:
                        changes["breaking_changes"].append({
                            "path": current_path,
                            "change": f"new required fields: {sorted(added)}"
                        })
                    if removed:
                        changes["non_breaking_changes"].append({
                            "path": current_path, 
                            "change": f"removed required fields: {sorted(removed)}"
                        })
                else:
                    # Default array comparison
                    compare_arrays(s1[key], s2[key], current_path)
            else:
                # Direct value comparison
                compare_recursively(s1[key], s2[key], current_path)

    compare_recursively(schema1, schema2)
    return changes

def load_json(path: Path) -> Dict[str, Any]:
    """Load and parse a JSON file."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error(f"Invalid JSON in '{path}': {exc}")
        raise

def find_schema_files(path: Path) -> Dict[str, Path]:
    """Find all JSON files under path."""
    if path.is_dir():
        return {p.name: p for p in collect_candidate_json([path])}
    elif path.is_file():
        return {path.name: path}
    else:
        return {}

def classify_change(diff: Dict[str, Any]) -> str:
    """Classify the type of change based on the diff results."""
    if diff["breaking_changes"]:
        return "major"
    elif diff["non_breaking_changes"]:
        return "minor"
    elif diff["description_changes"]:
        return "patch"
    return "same"

def determine_overall_status(summary: Dict[str, int]) -> str:
    """Determine overall status based on most significant change."""
    if summary.get("major", 0) > 0:
        return "major"
    elif summary.get("minor", 0) > 0:
        return "minor"
    elif summary.get("patch", 0) > 0:
        return "patch"
    return "unchanged"

def write_report(report: Dict[str, Any], output_path: Path | None, verbosity: int) -> str:
    """Write report to file and/or stdout based on arguments."""
    if output_path:
        logger.info(f"Writing report to '{output_path}'")
        output_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )
        if verbosity >= 1:
            print(f"Report written to: {output_path}")
    elif verbosity >= 1:
        print(json.dumps(report, indent=2))

    return report["overall_status"]


# -------
# Argument parsing
# -------

def build_arg_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        prog="schema_diff",
        description="Compare two sets of JSON Schemas and report semantic versioning changes.",
        epilog=(
            "Examples:\n"
            "  schema_diff schemas/v1 schemas/v2         # compare directories\n"
            "  schema_diff old.json new.json -v         # compare files with details\n"
            "  schema_diff dev/schemas main/schemas -o report.json  # save report"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "set1",
        type=Path,
        help="First file or directory to compare. Meant to be the 'old' version.",
    )
    parser.add_argument(
        "set2",
        type=Path,
        help="Second file or directory to compare. Meant to be the 'new' version.",
    )
    parser.add_argument(
        "--verbosity",
        "-v",
        action="count",
        default=0,
        help="Increase log verbosity: -v for debug, -vv for all messages",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Write machine-readable JSON report to file",
    )
    return parser

# -------
# Main driver
# -------

def main(argv: Sequence[str] | None = None) -> None:
    """Main entry point."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbosity)

    logger.debug(f"Comparing '{args.set1}' vs '{args.set2}'")
    
    files1 = find_schema_files(args.set1)
    files2 = find_schema_files(args.set2)
    
    if not files1 or not files2:
        logger.error("No JSON files found in one or both inputs")
        sys.exit(1)

    all_files = set(files1.keys()) | set(files2.keys())
    results = []
    summary = defaultdict(int)

    for fname in sorted(all_files):
        path1 = files1.get(fname)
        path2 = files2.get(fname)
        
        if not path1 or not path2:
            change_type = "added" if path2 and not path1 else "removed"
            logger.info(f"File '{fname}' was {change_type}")
            results.append({
                "file": fname,
                "status": change_type,
                "detail": f"File {change_type}"
            })
            summary[change_type] += 1
            continue

        try:
            schema1 = load_json(path1)
            schema2 = load_json(path2)
        except json.JSONDecodeError:
            logger.debug(f"Skipping '{fname}' due to JSON decode error")
            continue

        logger.debug(f"Comparing schemas in '{fname}'")
        diff = compare_schemas(schema1, schema2)
        change_type = classify_change(diff)
        results.append({
            "file": fname,
            "status": change_type,
            "diff": diff
        })
        summary[change_type] += 1
        if change_type == "same":
            logger.info(f"No changes in '{fname}'")
        else:
            logger.info(f"Changes in '{fname}': {change_type}")

        if change_type != "same":
            logger.debug(f"Changes in '{fname}':\n{json.dumps(diff, indent=2)}")

    # Determine and add overall status to report
    overall_status = determine_overall_status(summary)

    report = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "overall_status": str(overall_status),
        "inputs": {
            "set1 (old)": str(args.set1),
            "set2 (new)": str(args.set2)
        },
        "summary": dict(summary),
        "results": results
    }

    # Write report and handle output
    write_report(report, args.output, args.verbosity)

    # Exit with appropriate code for CI/CD
    sys.exit(1 if overall_status == "major" else 0)

if __name__ == "__main__":
    main()