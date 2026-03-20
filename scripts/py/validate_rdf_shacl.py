#!/usr/bin/env python3
"""Validate FEGA JSON-LD metadata against SHACL shapes (e.g., HealthDCAT-AP).

Converts JSON-LD documents to RDF and validates them against SHACL constraints,
reporting violations and type coverage metrics in JSON format.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set

try:
    from fega_tools.io import collect_candidate_json
    from fega_tools.logging_utils import configure_logging
    from fega_tools.rdf_utils import (
        jsonld_to_rdf_graph,
        load_rdf_from_file,
        validate_against_shacl,
        extract_types_from_graph,
        collect_candidate_rdf,
    )
except ModuleNotFoundError as exc:
    msg = (
        "ERROR:  The helper package 'fega_tools' is not importable.\n"
        "Make sure you have installed the repo in *editable* mode first. Run the following command from the repository root:\n"
        "    pip install -e .\n"
        "Also ensure dependencies are installed:\n"
        "    pip install -r requirements.txt"
    )
    raise ModuleNotFoundError(msg) from exc

logger = logging.getLogger(Path(__file__).stem)

# -------
# Discovery helpers
# -------

def filter_metadata_files(json_files: Sequence[Path]) -> List[Path]:
    """Keep only those JSON files that expose 'data' and 'schema' keys.

    This filters for FEGA metadata documents that contain both schema
    and data sections, which is the format expected by this validator.
    """
    valid: List[Path] = []
    for fp in json_files:
        try:
            with fp.open("r", encoding="utf-8") as handle:
                obj = json.load(handle)
            if isinstance(obj, dict) and {"data", "schema"}.issubset(obj):
                valid.append(fp)
            else:
                logger.debug(f"Missing 'data'/'schema' - skipping '{fp}'")
        except (json.JSONDecodeError, IOError) as exc:
            logger.warning(f"Cannot read file '{fp}': {exc}")
    return valid

def extract_data_section(metadata_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the 'data' section from a FEGA metadata document.

    The 'data' section contains the actual JSON-LD document to validate,
    while 'schema' contains the schema reference.
    """
    if "data" not in metadata_doc:
        raise ValueError("Metadata document is missing 'data' section")
    return metadata_doc["data"]

def _build_violation_summary(violations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build a concise, deduplicated violation summary.

    Groups violations by message and shows unique constraint violations
    without verbose repetition.

    Args:
        violations: List of violation dictionaries from SHACL validation.

    Returns:
        A concise list of unique violation types with their counts.
    """
    if not violations:
        return []
    
    # Group violations by message
    message_counts: Dict[str, int] = {}
    unique_violations: List[Dict[str, Any]] = []
    
    for viol in violations:
        msg = viol.get("message", "unknown")
        
        # Skip pure "unknown" violations without meaningful info
        if msg == "unknown" and "constraint_type" not in viol:
            continue
            
        # Use constraint type or message as the summary key
        key = msg if msg != "unknown" else viol.get("constraint_type", "unknown")
        
        if key not in message_counts:
            message_counts[key] = 0
            unique_violations.append({
                "message": msg,
                "constraint_type": viol.get("constraint_type", ""),
                "count": 1
            })
        else:
            message_counts[key] += 1
    
    # Update counts in the list
    result = []
    for viol in unique_violations:
        key = viol["message"] if viol["message"] != "unknown" else viol["constraint_type"]
        viol["count"] = message_counts[key] + 1
        result.append(viol)
    
    # Return first 10 unique violations
    return result[:10]

# -------
# Type metrics
# -------

def extract_expected_types_from_shapes(shape_graphs: List[Any]) -> Set[str]:
    """Extract expected @types from SHACL shape graphs.

    Analyses the shapes to determine what target classes (types) they validate.
    """
    from rdflib import Namespace
    
    SH = Namespace("http://www.w3.org/ns/shacl#")
    expected_types: Set[str] = set()
    
    for graph in shape_graphs:
        for target_class in graph.objects(predicate=SH.targetClass):
            expected_types.add(str(target_class))
    
    return expected_types

def build_type_metrics(
    documents: Dict[str, Dict[str, Any]],
    expected_types: Set[str]
) -> Dict[str, Any]:
    """Build metrics about @types found in documents vs expected by shapes.

    Returns a dictionary with:
        - types_found: set of types discovered in documents
        - types_expected: set of types required by shapes
        - types_missing: expected but not found
        - types_unexpected: found but not expected
        - type_coverage: fraction of expected types found
    """
    types_found: Set[str] = set()
    
    for doc_types in documents.values():
        for typ in doc_types.get("types", set()):
            types_found.add(typ)
    
    types_missing = expected_types - types_found
    types_unexpected = types_found - expected_types
    coverage = len(types_found & expected_types) / len(expected_types) if expected_types else 1.0
    
    return {
        "types_found": sorted(types_found),
        "types_expected": sorted(expected_types),
        "types_missing": sorted(types_missing),
        "types_unexpected": sorted(types_unexpected),
        "type_coverage": f"{coverage * 100:.1f}%",
    }

# -------
# Core validation routine
# -------

def validate_documents(
    input_paths: Sequence[Path],
    shapes_paths: Sequence[Path],
) -> Dict[str, Any]:
    """Validate metadata documents against SHACL shapes.

    Args:
        input_paths: Paths to JSON metadata files/directories.
        shapes_paths: Paths to RDF shape files/directories.

    Returns:
        A summary dictionary with validation results and metrics.
    """
    # Discover metadata files
    all_json = collect_candidate_json(input_paths)
    metadata_files = filter_metadata_files(all_json)

    if not metadata_files:
        logger.error(
            "No JSON metadata files with 'data' and 'schema' keys were found under the given inputs."
        )
        sys.exit(1)

    logger.info(
        f"Discovered {len(all_json)} JSON file(s); {len(metadata_files)} qualify for validation"
    )

    # Discover and load shape files
    all_shapes = collect_candidate_rdf(shapes_paths)
    
    if not all_shapes:
        logger.error(
            "No RDF shape files were found under the given inputs."
        )
        sys.exit(1)

    logger.info(f"Discovered {len(all_shapes)} RDF shape file(s)")

    # Load all shape graphs
    shape_graphs = []
    for shape_path in all_shapes:
        try:
            logger.debug(f"Loading shapes from '{shape_path}'")
            graph = load_rdf_from_file(shape_path)
            shape_graphs.append(graph)
        except ValueError as exc:
            logger.error(f"Failed to load shape file '{shape_path}': {exc}")
            sys.exit(1)

    # Merge all shape graphs into one
    from rdflib import Graph
    merged_shapes = Graph()
    for graph in shape_graphs:
        merged_shapes += graph

    expected_types = extract_expected_types_from_shapes(shape_graphs)
    logger.debug(f"Expected types from shapes: {expected_types}")

    # Validate each metadata file
    failed_files: List[str] = []
    errors_of_failed_files: Dict[str, List[str]] = {}
    documents_info: Dict[str, Dict[str, Any]] = {}
    shacl_reports: Dict[str, str] = {}  # Store raw SHACL reports

    for input_path in metadata_files:
        logger.debug(f"Validating '{input_path}'")
        
        try:
            with input_path.open("r", encoding="utf-8") as handle:
                metadata_doc = json.load(handle)

            # Extract the data section
            jsonld_data = extract_data_section(metadata_doc)

            # Convert JSON-LD to RDF
            data_graph = jsonld_to_rdf_graph(jsonld_data)
            
            # Extract types from the data graph for metrics
            found_types = extract_types_from_graph(data_graph)
            documents_info[str(input_path)] = {
                "types": found_types,
                "conforms": False,
                "violations": []
            }

            logger.debug(f"Found types in document: {found_types}")

            # Validate against shapes
            conforms, report_text, report_dict = validate_against_shacl(
                data_graph=data_graph,
                shapes_graph=merged_shapes
            )

            documents_info[str(input_path)]["conforms"] = conforms
            documents_info[str(input_path)]["violations"] = report_dict.get("violations", [])
            
            # Store raw SHACL report for optional output
            shacl_reports[str(input_path)] = report_text

            if conforms:
                logger.info(f"Validation PASSED for '{input_path}'")
            else:
                failed_files.append(str(input_path))
                # Extract unique error messages
                violations = report_dict.get("violations", [])
                unique_messages: Dict[str, int] = {}
                for v in violations:
                    msg = v.get("message", "")
                    if msg and msg != "unknown":
                        unique_messages[msg] = unique_messages.get(msg, 0) + 1
                
                # Create concise error list: show unique messages with counts if needed
                error_messages = []
                for msg, count in sorted(unique_messages.items(), key=lambda x: x[1], reverse=True):
                    if count > 1:
                        error_messages.append(f"{msg} ({count})")
                    else:
                        error_messages.append(msg)
                
                errors_of_failed_files[str(input_path)] = error_messages if error_messages else ["Validation failed"]
                logger.error(f"Validation FAILED for '{input_path}' with {len(violations)} violation(s)")

        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            failed_files.append(str(input_path))
            error_msg = str(exc)
            errors_of_failed_files[str(input_path)] = [error_msg]
            logger.error(f"Validation FAILED (processing error) for '{input_path}': {error_msg}")

    # Build summary
    type_metrics = build_type_metrics(documents_info, expected_types)

    summary = {
        "timestamp": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds"),
        "shapes_paths": [str(p) for p in shapes_paths],
        "input_paths": [str(p) for p in input_paths],
        "n_total_files": len(metadata_files),
        "n_failed_files": len(failed_files),
        "failed_files": failed_files,
        "errors_of_failed_files": errors_of_failed_files,
        "type_metrics": type_metrics,
        "documents_info": {
            k: {
                "types": sorted(list(v["types"])),
                "conforms": v["conforms"],
                "n_violations": len(v["violations"]),
                "violation_summary": _build_violation_summary(v.get("violations", [])),
            }
            for k, v in documents_info.items()
        },
        "shacl_reports": shacl_reports,
    }

    return summary

# -------
# CLI helpers
# -------

def make_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate_rdf_shacl",
        description="Validate FEGA JSON-LD metadata using SHACL shapes.",
        epilog=(
            "Examples:\n"
            "  validate_rdf_shacl entities/dataset/examples --shapes standards/rdf/healthdcat-ap\n"
            "  validate_rdf_shacl entities/dataset/examples/valid/dataset-valid_1.json --shapes standards/rdf/healthdcat-ap/release-6.0.0/shacl/non-public-shapes-v6.ttl"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "metadata",
        nargs="+",
        type=Path,
        help="Metadata files or directories to validate (JSON with 'schema' and 'data' keys).",
    )
    parser.add_argument(
        "--shapes",
        "-s",
        dest="shapes",
        nargs="+",
        type=Path,
        required=True,
        help="SHACL shape files or directories (TTL, RDF/XML, JSON-LD, etc.).",
    )
    parser.add_argument(
        "--verbosity",
        "-v",
        action="count",
        default=0,
        help="Increase log verbosity: '-v' for debug, '-vv' for all messages.",
    )
    parser.add_argument(
        "--shacl-report",
        action="store_true",
        help="Print raw pySHACL validation reports after the summary.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = make_arg_parser()
    args = parser.parse_args(argv)

    configure_logging(args.verbosity)

    summary = validate_documents(args.metadata, args.shapes)
    
    # Remove shacl_reports from summary for clean JSON output
    shacl_reports = summary.pop("shacl_reports", {})

    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")

    # Print raw SHACL reports if requested
    if args.shacl_report and shacl_reports:
        sys.stdout.write("\n" + "="*80 + "\n")
        sys.stdout.write("RAW pySHACL VALIDATION REPORTS\n")
        sys.stdout.write("="*80 + "\n\n")
        for filepath, report in shacl_reports.items():
            sys.stdout.write(f"File: {filepath}\n")
            sys.stdout.write("-"*80 + "\n")
            sys.stdout.write(report)
            sys.stdout.write("\n\n")

    sys.exit(0 if summary["n_failed_files"] == 0 else 1)


if __name__ == "__main__":
    main()
