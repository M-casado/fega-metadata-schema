"""JSON-LD context and frame coverage helpers for EGA metadata schemas."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urldefrag
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from fega_tools.jsonld_utils import (
    JSONLD_KEYWORDS,
    build_id_to_path_map,
    context_terms_and_prefixes,
    find_repo_root,
    is_known_jsonld_key,
    materialize_context,
    validate_context_term_mappings,
)
from fega_tools.validation_common import find_entity_dirs

IGNORED_SCHEMA_PROPERTIES = {"@context", "@id", "@type", "@graph"}
TRAVERSAL_KEYS = (
    "allOf",
    "anyOf",
    "oneOf",
    "if",
    "then",
    "else",
    "items",
    "contains",
)
LOGGER = logging.getLogger(__name__)

def load_json_object(path: Path) -> Dict[str, Any]:
    """Load a JSON file and require the top-level value to be an object."""
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _json_pointer_parts(fragment: str) -> List[str]:
    """Return decoded JSON Pointer parts from a URI fragment."""
    if not fragment:
        return []
    if not fragment.startswith("/"):
        raise ValueError(f"Unsupported non-pointer schema fragment '#{fragment}'")
    return [
        part.replace("~1", "/").replace("~0", "~")
        for part in fragment.lstrip("/").split("/")
        if part != ""
    ]


def _get_pointer(document: Any, parts: Sequence[str]) -> Any:
    """Resolve a decoded JSON Pointer inside a JSON document."""
    current = document
    for part in parts:
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise KeyError(part)
    return current


def _is_fega_schema_path(path: Path, repo_root: Path) -> bool:
    """Return whether *path* is a maintained EGA metadata schema in coverage scope."""
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    rel_parts = rel.parts
    return (
        len(rel_parts) >= 3
        and rel_parts[0] == "schemas"
        and rel_parts[1] in {"common", "entities"}
        and rel_parts[-1] == "schema.json"
    )


def _resolve_schema_ref(
    ref: str,
    current_file: Path,
    id_to_path_map: Dict[str, Path],
    repo_root: Path,
) -> Optional[Tuple[Path, List[str]]]:
    """Resolve a JSON Schema ref to an in-scope local schema target."""
    base, fragment = urldefrag(ref)
    if not base:
        target_path = current_file
    elif base in id_to_path_map:
        target_path = id_to_path_map[base]
    elif not base.startswith(("http://", "https://")):
        target_path = (current_file.parent / base).resolve()
    else:
        return None

    if not target_path.exists() or not _is_fega_schema_path(target_path, repo_root):
        return None
    return target_path, _json_pointer_parts(fragment)


def _add_property_path(
    property_paths: Dict[str, Set[str]],
    path: str,
    property_name: str,
) -> None:
    """Record a schema-facing property path."""
    if property_name in IGNORED_SCHEMA_PROPERTIES or property_name.startswith("$"):
        return
    property_paths.setdefault(property_name, set()).add(path)


def _load_schema(path: Path) -> Dict[str, Any]:
    """Load a schema object from disk."""
    loaded = load_json_object(path)
    return loaded


def collect_schema_property_paths(
    schema: Dict[str, Any],
    schema_path: Path,
    id_to_path_map: Dict[str, Path],
    repo_root: Path,
) -> Dict[str, Set[str]]:
    """Return FEGA-maintained schema-facing property names and JSON paths.

    Traversal follows local refs under ``schemas/common`` and
    ``schemas/entities`` and stops at standards or other external refs.
    """
    property_paths: Dict[str, Set[str]] = {}
    loaded_schemas: Dict[Path, Dict[str, Any]] = {schema_path.resolve(): schema}
    seen_refs: Set[Tuple[Path, Tuple[str, ...], str]] = set()

    def schema_for(path: Path) -> Dict[str, Any]:
        resolved = path.resolve()
        if resolved not in loaded_schemas:
            loaded_schemas[resolved] = _load_schema(resolved)
        return loaded_schemas[resolved]

    def visit(value: Any, current_file: Path, data_path: str) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item, current_file, data_path)
            return
        if not isinstance(value, dict):
            return

        ref = value.get("$ref")
        if isinstance(ref, str):
            resolved = _resolve_schema_ref(ref, current_file, id_to_path_map, repo_root)
            if resolved is not None:
                ref_path, pointer_parts = resolved
                ref_key = (ref_path.resolve(), tuple(pointer_parts), data_path)
                if ref_key not in seen_refs:
                    seen_refs.add(ref_key)
                    ref_schema = schema_for(ref_path)
                    try:
                        target = _get_pointer(ref_schema, pointer_parts)
                    except (KeyError, IndexError, TypeError, ValueError) as exc:
                        raise ValueError(
                            f"Cannot resolve schema ref '{ref}' from '{current_file}': {exc}"
                        ) from exc
                    visit(target, ref_path.resolve(), data_path)

        properties = value.get("properties")
        if isinstance(properties, dict):
            for property_name, property_schema in properties.items():
                child_path = (
                    f"{data_path}.{property_name}" if data_path else property_name
                )
                _add_property_path(property_paths, child_path, property_name)
                visit(property_schema, current_file, child_path)

        for key in TRAVERSAL_KEYS:
            child = value.get(key)
            if isinstance(child, (dict, list)):
                visit(child, current_file, data_path)

    visit(schema, schema_path.resolve(), "")
    return property_paths


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
        "schema_property_paths": [],
        "root_frame_properties": [],
        "context_terms": [],
        "frame_keys": [],
        "missing_context_terms": [],
        "missing_context_term_paths": {},
        "missing_frame_keys": [],
        "missing_frame_key_paths": {},
        "unknown_frame_keys": [],
        "context_errors": [],
        "frame_errors": [],
        "script_errors": [],
    }


def validate_entity_coverage(
    entity_dir: Path,
    id_to_path_map: Dict[str, Path],
    repo_root: Path,
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

    try:
        property_path_map = collect_schema_property_paths(
            schema,
            schema_path.resolve(),
            id_to_path_map,
            repo_root,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        result["script_errors"].append(f"Cannot collect schema properties: {exc}")
        return result

    schema_properties = sorted(property_path_map)
    root_frame_properties = sorted(
        property_name
        for property_name, paths in property_path_map.items()
        if any("." not in path for path in paths)
    )
    result["schema_properties"] = schema_properties
    result["root_frame_properties"] = root_frame_properties
    result["schema_property_paths"] = [
        {"property": property_name, "path": path}
        for property_name in schema_properties
        for path in sorted(property_path_map[property_name])
    ]
    LOGGER.debug(
        "Entity '%s': schema properties requiring context coverage: %s",
        entity_dir.name,
        schema_properties,
    )
    LOGGER.debug(
        "Entity '%s': root schema properties requiring frame coverage: %s",
        entity_dir.name,
        root_frame_properties,
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

    result["missing_context_terms"] = sorted(
        key for key in schema_properties if key not in terms
    )
    result["missing_context_term_paths"] = {
        key: sorted(property_path_map[key])
        for key in result["missing_context_terms"]
    }
    if not result["context_errors"]:
        result["context_errors"].extend(
            validate_context_term_mappings(materialized_context, set(schema_properties))
        )
    result["context_coverage_passed"] = (
        not result["missing_context_terms"]
        and not result["context_errors"]
    )

    if not frame_path.is_file():
        result["missing_frame_keys"] = root_frame_properties
        result["missing_frame_key_paths"] = {
            key: sorted(path for path in property_path_map[key] if "." not in path)
            for key in result["missing_frame_keys"]
        }
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
        key for key in root_frame_properties if key not in frame_keys
    ]
    result["missing_frame_key_paths"] = {
        key: sorted(path for path in property_path_map[key] if "." not in path)
        for key in result["missing_frame_keys"]
    }
    if not result["context_errors"]:
        root_frame_property_set = set(root_frame_properties)
        result["unknown_frame_keys"] = [
            key
            for key in frame_keys
            if key not in root_frame_property_set
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
    entity_dirs = find_entity_dirs(root, entity, require_schema=True)
    if not entity_dirs:
        raise FileNotFoundError(f"No entity schema directories found under {root}")
    LOGGER.debug(
        "Loaded %d schema/context map entrie(s); validating entities: %s",
        len(id_to_path_map),
        [path.name for path in entity_dirs],
    )

    entity_results = [
        validate_entity_coverage(entity_dir, id_to_path_map, repo_root)
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
