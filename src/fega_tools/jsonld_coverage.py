"""JSON-LD context and frame coverage helpers for FEGA schemas."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from fega_tools.jsonld_utils import (
    JSONLD_KEYWORDS,
    build_id_to_path_map,
    context_terms_and_prefixes,
    find_repo_root,
    is_known_jsonld_key,
    materialize_context,
)

IGNORED_SCHEMA_PROPERTIES = {"@context", "@id", "@type"}
LOGGER = logging.getLogger(__name__)


def find_entity_dirs(root: Path, entity: Optional[str]) -> List[Path]:
    """Return entity directories containing a local schema.json."""
    if entity:
        entity_dir = root / entity
        if not entity_dir.is_dir():
            raise FileNotFoundError(f"Entity directory not found: {entity_dir}")
        if not (entity_dir / "schema.json").is_file():
            raise FileNotFoundError(f"Entity schema not found: {entity_dir / 'schema.json'}")
        return [entity_dir]

    if not root.is_dir():
        raise FileNotFoundError(f"Entity root not found: {root}")

    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "schema.json").is_file()
    )


def load_json_object(path: Path) -> Dict[str, Any]:
    """Load a JSON file and require the top-level value to be an object."""
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def schema_coverage_properties(schema: Dict[str, Any]) -> List[str]:
    """Return direct schema properties that need context/frame coverage."""
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return []
    return sorted(
        key
        for key in properties
        if key not in IGNORED_SCHEMA_PROPERTIES and not key.startswith("$")
    )


def frame_coverage_keys(frame: Dict[str, Any]) -> List[str]:
    """Return top-level frame keys that represent schema-facing properties."""
    return sorted(key for key in frame if key not in JSONLD_KEYWORDS)


def _empty_entity_result(entity_dir: Path) -> Dict[str, Any]:
    schema_path = entity_dir / "schema.json"
    frame_path = entity_dir / "frame.jsonld"
    return {
        "entity": entity_dir.name,
        "schema": str(schema_path),
        "context": None,
        "frame": str(frame_path),
        "passed": False,
        "context_coverage_passed": False,
        "frame_coverage_passed": False,
        "schema_properties": [],
        "context_terms": [],
        "frame_keys": [],
        "missing_context_terms": [],
        "missing_frame_keys": [],
        "unknown_frame_keys": [],
        "context_errors": [],
        "frame_errors": [],
        "script_errors": [],
    }


def validate_entity_coverage(
    entity_dir: Path,
    id_to_path_map: Dict[str, Path],
) -> Dict[str, Any]:
    """Validate context and frame coverage for one entity directory."""
    result = _empty_entity_result(entity_dir)
    schema_path = entity_dir / "schema.json"
    frame_path = entity_dir / "frame.jsonld"

    try:
        schema = load_json_object(schema_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        result["script_errors"].append(f"Cannot load schema: {exc}")
        return result

    schema_properties = schema_coverage_properties(schema)
    result["schema_properties"] = schema_properties
    LOGGER.debug(
        "Entity '%s': direct schema properties requiring coverage: %s",
        entity_dir.name,
        schema_properties,
    )

    terms: Set[str] = set()
    prefixes: Set[str] = set()
    context_value = schema.get("@context")
    result["context"] = str(context_value) if context_value is not None else None
    if context_value is None:
        result["context_errors"].append("Schema is missing @context")
    else:
        try:
            materialized_context = materialize_context(
                context_value,
                schema_path,
                id_to_path_map,
            )
            terms, prefixes = context_terms_and_prefixes(materialized_context)
            result["context_terms"] = sorted(terms)
            LOGGER.debug(
                "Entity '%s': materialized context has %d term(s) and %d prefix(es)",
                entity_dir.name,
                len(terms),
                len(prefixes),
            )
        except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
            result["context_errors"].append(f"Cannot materialize schema @context: {exc}")

    result["missing_context_terms"] = [
        key for key in schema_properties if key not in terms
    ]
    result["context_coverage_passed"] = (
        not result["missing_context_terms"]
        and not result["context_errors"]
    )

    if not frame_path.is_file():
        result["missing_frame_keys"] = schema_properties
        result["frame_errors"].append(f"Frame file not found: {frame_path}")
        return result

    try:
        frame = load_json_object(frame_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        result["script_errors"].append(f"Cannot load frame: {exc}")
        return result

    frame_keys = frame_coverage_keys(frame)
    result["frame_keys"] = frame_keys
    LOGGER.debug(
        "Entity '%s': top-level frame keys requiring coverage: %s",
        entity_dir.name,
        frame_keys,
    )
    result["missing_frame_keys"] = [
        key for key in schema_properties if key not in frame_keys
    ]
    if not result["context_errors"]:
        schema_property_set = set(schema_properties)
        result["unknown_frame_keys"] = [
            key
            for key in frame_keys
            if key not in schema_property_set
            and not is_known_jsonld_key(key, terms, prefixes)
        ]
    result["frame_coverage_passed"] = (
        not result["missing_frame_keys"]
        and not result["unknown_frame_keys"]
        and not result["frame_errors"]
    )
    result["passed"] = (
        result["context_coverage_passed"]
        and result["frame_coverage_passed"]
        and not result["script_errors"]
    )
    LOGGER.debug(
        "Entity '%s': missing_context_terms=%s missing_frame_keys=%s unknown_extra_frame_keys=%s",
        entity_dir.name,
        result["missing_context_terms"],
        result["missing_frame_keys"],
        result["unknown_frame_keys"],
    )
    return result


def summarize_coverage(entity_results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate entity-level coverage results into suite totals."""
    return {
        "total_entities": len(entity_results),
        "passed_entities": sum(1 for item in entity_results if item["passed"]),
        "failed_entities": sum(1 for item in entity_results if not item["passed"]),
        "context_coverage_failures": sum(
            1 for item in entity_results if not item["context_coverage_passed"]
        ),
        "frame_coverage_failures": sum(
            1 for item in entity_results if not item["frame_coverage_passed"]
        ),
        "missing_context_terms": sum(
            len(item["missing_context_terms"]) for item in entity_results
        ),
        "missing_frame_keys": sum(
            len(item["missing_frame_keys"]) for item in entity_results
        ),
        "unknown_frame_keys": sum(
            len(item["unknown_frame_keys"]) for item in entity_results
        ),
        "context_errors": sum(len(item["context_errors"]) for item in entity_results),
        "frame_errors": sum(len(item["frame_errors"]) for item in entity_results),
        "script_errors": sum(len(item["script_errors"]) for item in entity_results),
    }


def validate_jsonld_coverage(
    root: Path,
    entity: Optional[str],
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validate schema-driven JSON-LD context and frame coverage."""
    if repo_root is None:
        repo_root = find_repo_root(root.resolve())

    id_to_path_map = build_id_to_path_map(repo_root)
    entity_dirs = find_entity_dirs(root, entity)
    if not entity_dirs:
        raise FileNotFoundError(f"No entity schema directories found under {root}")
    LOGGER.debug(
        "Loaded %d schema/context map entrie(s); validating entities: %s",
        len(id_to_path_map),
        [path.name for path in entity_dirs],
    )

    entity_results = [
        validate_entity_coverage(entity_dir, id_to_path_map)
        for entity_dir in entity_dirs
    ]
    totals = summarize_coverage(entity_results)

    return {
        "root": str(root),
        "entity": entity,
        "entity_names": [path.name for path in entity_dirs],
        "passed": totals["failed_entities"] == 0 and totals["script_errors"] == 0,
        **totals,
        "files": entity_results,
    }
