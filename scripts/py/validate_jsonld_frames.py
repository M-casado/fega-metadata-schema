#!/usr/bin/env python3
"""Validate JSON-LD frame round-trips for FEGA valid examples.

This test checks that our JSON-LD frames can rebuild the
nested JSON shape expected by the JSON Schemas from graph-like JSON-LD input.
It starts from each valid example, flattens it, adds an unrelated noise node,
frames it back into schema-shaped JSON-LD, and validates that result.

The RDF/N-Quads route checks meaning, not formatting. JSON-LD, flattened
JSON-LD, framed JSON-LD, and RDF/N-Quads can all describe the same graph in
different syntaxes. The script canonicalizes the original and framed data as
N-Quads (triplets) so it can detect semantic information loss even when the JSON layout
changes. JSON Schema validation then checks that the final JSON has the shape
our metadata model expects.

Each input is checked through two routes:

1. JSON-LD flattening followed by framing.
    Valid example → flatten → add unrelated noise → frame → verify noise removal and RDF meaning → JSON Schema validation.
2. JSON-LD -> RDF/N-Quads -> JSON-LD reconstruction followed by framing.
    Valid example → RDF triples → reconstruct JSON-LD → flatten → add noise → frame → verify noise removal and RDF meaning → JSON Schema validation.

Both routes receive an unrelated noise node. The framed primary entity must
exclude that node, preserve the original canonical RDF graph, and pass the
target JSON Schema through Biovalidator.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import requests
from requests.exceptions import ConnectionError, Timeout

try:
    import pyld.jsonld as jsonld
except ImportError as exc:
    raise ImportError(
        "PyLD is required for frame validation. Install it with: pip install pyld"
    ) from exc

try:
    from fega_tools.io import collect_candidate_json
    from fega_tools.logging_utils import configure_logging
    from fega_tools.jsonld_utils import (
        build_id_to_path_map,
        find_repo_root,
        make_local_document_loader,
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
DEFAULT_VALIDATOR_URL = "http://localhost:3020/validate"
SUMMARY_FILENAME = "frame_summary.json"
TOTAL_STEPS = 10

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

ROUTE_FLATTENED = "flattened_jsonld"
ROUTE_RDF_GRAPH = "generated_rdf_graph"
ROUTES = (ROUTE_FLATTENED, ROUTE_RDF_GRAPH)

_JSONLD_KEYWORDS = {
    "@base",
    "@container",
    "@context",
    "@direction",
    "@graph",
    "@id",
    "@import",
    "@included",
    "@index",
    "@json",
    "@language",
    "@list",
    "@nest",
    "@none",
    "@prefix",
    "@propagate",
    "@protected",
    "@reverse",
    "@set",
    "@type",
    "@value",
    "@version",
    "@vocab",
}

_NOISE_TYPE = "https://example.org/FEGATestNoiseEntity"
_DROP = object()


# ---------------------------------------------------------------------------
# Basic IO and discovery
# ---------------------------------------------------------------------------


def assert_validator_reachable(url: str, timeout_seconds: int = 5) -> None:
    """Raise RuntimeError if the Biovalidator endpoint is not reachable."""
    try:
        requests.get(url, timeout=timeout_seconds)
    except (ConnectionError, Timeout, requests.RequestException) as exc:
        raise RuntimeError(f"Cannot reach Biovalidator endpoint '{url}': {exc}") from exc


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


def find_frame_gaps(entity_dirs: Sequence[Path]) -> List[str]:
    """Return entity directories missing frame.jsonld."""
    return [
        entity_dir.name
        for entity_dir in entity_dirs
        if not (entity_dir / "frame.jsonld").exists()
    ]


def _load_json(path: Path) -> Any:
    """Load a JSON file and return the parsed value."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _clone_json(value: Any) -> Any:
    """Make a JSON-safe deep copy."""
    return json.loads(json.dumps(value))


def resolve_file_entity(
    path: Path,
    root: Path,
    id_to_path_map: Dict[str, Path],
) -> Tuple[Path, Path]:
    """Resolve a single input's entity directory and frame via schema.$ref."""
    resolved_path = path.resolve()
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")
    if resolved_path.suffix.lower() != ".json":
        raise ValueError(f"Input file must be JSON: {path}")

    try:
        document = _load_json(resolved_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot load input file '{path}': {exc}") from exc

    schema = document.get("schema") if isinstance(document, dict) else None
    schema_ref = schema.get("$ref") if isinstance(schema, dict) else None
    if not isinstance(schema_ref, str) or not schema_ref:
        raise ValueError(f"Input file '{path}' is missing schema.$ref")

    schema_path = id_to_path_map.get(schema_ref)
    if schema_path is None:
        raise FileNotFoundError(
            f"Cannot map schema.$ref '{schema_ref}' from input file '{path}'"
        )

    entity_dir = schema_path.resolve().parent
    try:
        entity_dir.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"Input schema '{schema_path}' is not under entity root '{root}'"
        ) from exc

    frame_path = entity_dir / "frame.jsonld"
    if not frame_path.is_file():
        raise FileNotFoundError(f"Frame file not found: {frame_path}")
    return entity_dir, frame_path


def _discover_inputs(
    root: Path,
    entity: Optional[str],
    input_file: Optional[Path],
    id_to_path_map: Dict[str, Path],
) -> Tuple[List[Path], List[Dict[str, Path]], List[str]]:
    """Return selected entity dirs, file specifications, and frame gaps."""
    if input_file is not None:
        entity_dir, frame_path = resolve_file_entity(input_file, root, id_to_path_map)
        return (
            [entity_dir],
            [
                {
                    "path": input_file.resolve(),
                    "entity_dir": entity_dir,
                    "frame_path": frame_path,
                }
            ],
            [],
        )

    entity_dirs = find_entity_dirs(root, entity)
    if not entity_dirs:
        raise FileNotFoundError(f"No entity schema directories found under {root}")

    frame_gaps = find_frame_gaps(entity_dirs)
    specs: List[Dict[str, Path]] = []
    for entity_dir in entity_dirs:
        frame_path = entity_dir / "frame.jsonld"
        if not frame_path.is_file():
            continue
        valid_dir = entity_dir / "examples" / "valid"
        files = collect_candidate_json([valid_dir]) if valid_dir.is_dir() else []
        specs.extend(
            {
                "path": path,
                "entity_dir": entity_dir,
                "frame_path": frame_path,
            }
            for path in files
        )
    return entity_dirs, specs, frame_gaps


# ---------------------------------------------------------------------------
# Context preflight
# ---------------------------------------------------------------------------


def _context_terms_and_prefixes(context: Any) -> Tuple[Set[str], Set[str]]:
    """Return term and prefix names defined by a materialized context."""
    terms: Set[str] = set()
    prefixes: Set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return

        for key, definition in value.items():
            if key.startswith("@"):
                continue
            terms.add(key)
            iri = None
            if isinstance(definition, str):
                iri = definition
            elif isinstance(definition, dict) and isinstance(definition.get("@id"), str):
                iri = definition["@id"]
            if iri and (iri.endswith("/") or iri.endswith("#") or iri.endswith(":")):
                prefixes.add(key)

    visit(context)
    return terms, prefixes


def _walk_object_keys(value: Any, path: str = "") -> List[Tuple[str, str]]:
    """Return all object key paths from a JSON value."""
    keys: List[Tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}/{key}" if path else key
            keys.append((child_path, key))
            keys.extend(_walk_object_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            keys.extend(_walk_object_keys(child, f"{path}[{index}]"))
    return keys


def _is_known_key(key: str, terms: Set[str], prefixes: Set[str]) -> bool:
    """Return whether a JSON key is defined by JSON-LD terms or prefixes."""
    if key in _JSONLD_KEYWORDS or key in terms:
        return True
    if key.startswith(("http://", "https://")):
        return True
    if ":" in key:
        return key.split(":", 1)[0] in prefixes
    return False


def find_undefined_terms(data: Dict[str, Any], context: Any) -> List[str]:
    """Return JSON key paths that JSON-LD would ignore as undefined terms."""
    terms, prefixes = _context_terms_and_prefixes(context)
    return [
        path
        for path, key in _walk_object_keys(data)
        if not _is_known_key(key, terms, prefixes)
    ]


def find_invalid_context_type_mappings(context: Any) -> List[str]:
    """Return context paths with invalid JSON-LD @type mappings."""
    invalid: List[str] = []

    def visit(value: Any, path: str = "") -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
            return
        if not isinstance(value, dict):
            return

        type_value = value.get("@type")
        if isinstance(type_value, str) and not (
            type_value.startswith("@")
            or ":" in type_value
            or type_value.startswith(("http://", "https://"))
        ):
            invalid.append(f"{path or '<context>'}/@type={type_value!r}")

        for key, child in value.items():
            child_path = f"{path}/{key}" if path else key
            visit(child, child_path)

    visit(context)
    return invalid


def _data_with_context(data: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Copy data and replace its context with a materialized context."""
    data_copy = _clone_json(data)
    data_copy["@context"] = context
    return data_copy


# ---------------------------------------------------------------------------
# JSON-LD operations
# ---------------------------------------------------------------------------


def _as_graph_nodes(value: Any) -> List[Any]:
    """Normalize a JSON-LD result into a list of graph nodes."""
    if isinstance(value, dict) and isinstance(value.get("@graph"), list):
        return value["@graph"]
    if isinstance(value, list):
        return value
    return [value]


def _noise_entity(noise_id: str) -> Dict[str, Any]:
    """Build an unrelated node that frames should exclude."""
    return {
        "@id": noise_id,
        "@type": [_NOISE_TYPE],
        "https://example.org/hasNoise": [{"@value": "noise-test"}],
    }


def _walk_contains_id(value: Any, target_id: str) -> bool:
    """Return whether an id appears anywhere in a nested JSON value."""
    if isinstance(value, dict):
        if value.get("@id") == target_id or value.get("id") == target_id:
            return True
        return any(_walk_contains_id(child, target_id) for child in value.values())
    if isinstance(value, list):
        return any(_walk_contains_id(item, target_id) for item in value)
    return False


def _extract_candidates(framed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract possible primary entities from framed JSON-LD output."""
    graph = framed.get("@graph")
    if isinstance(graph, list):
        return [item for item in graph if isinstance(item, dict)]
    if isinstance(framed, dict):
        return [{key: value for key, value in framed.items() if key != "@context"}]
    return []


def _value_as_strings(value: Any) -> List[str]:
    """Return a string or list value as a clean list of strings."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _select_primary_entity(
    framed: Dict[str, Any],
    original_id: Optional[str],
    original_types: Sequence[str],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Pick the one framed entity that matches the original id or type."""
    candidates = _extract_candidates(framed)
    if not candidates:
        return None, "Framed output did not contain any candidate entities"

    if original_id:
        matches = [
            item
            for item in candidates
            if original_id in _value_as_strings(item.get("id"))
            or original_id in _value_as_strings(item.get("@id"))
        ]
        if len(matches) == 1:
            return matches[0], None
        if not matches:
            return None, f"No framed entity matched original id '{original_id}'"
        return None, f"Multiple framed entities matched original id '{original_id}'"

    expected_types = set(original_types)
    matches = [
        item
        for item in candidates
        if expected_types & set(_value_as_strings(item.get("@type")))
    ]
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, f"No framed entity matched expected @type values {sorted(expected_types)}"
    return None, f"Multiple framed entities matched expected @type values {sorted(expected_types)}"


def _canonicalize_jsonld(
    data: Dict[str, Any],
    inline_context: Any,
    document_loader: Any,
) -> str:
    """Normalize JSON-LD into canonical N-Quads for RDF comparison."""
    return jsonld.normalize(
        _data_with_context(data, inline_context),
        {
            "algorithm": "URDNA2015",
            "format": "application/n-quads",
            "documentLoader": document_loader,
        },
    )


def _summarize_nquads_difference(expected: str, actual: str) -> List[str]:
    """Describe the first RDF triples missing or added after framing."""
    expected_lines = set(expected.splitlines())
    actual_lines = set(actual.splitlines())
    missing = sorted(expected_lines - actual_lines)
    extra = sorted(actual_lines - expected_lines)
    errors = [
        f"Canonical RDF differs: {len(missing)} missing triple(s), {len(extra)} extra triple(s)"
    ]
    errors.extend(f"missing: {line}" for line in missing[:10])
    errors.extend(f"extra: {line}" for line in extra[:10])
    return errors


def _classify_validator_response(response: Any) -> str:
    """Map a Biovalidator response body to this script's status names."""
    if isinstance(response, list) and not response:
        return VALID_STATUS
    if isinstance(response, list):
        return INVALID_STATUS
    return UNKNOWN_STATUS


def _post_to_validator(document: Dict[str, Any], validator_url: str) -> Any:
    """Send one schema/data wrapper to Biovalidator and parse JSON output."""
    response = requests.post(
        validator_url,
        json=document,
        headers={"Content-Type": "application/json"},
        timeout=300,
    )
    response.raise_for_status()
    return response.json()


def _route_failure(
    route: str,
    status: str,
    stage: str,
    errors: Sequence[Any],
) -> Dict[str, Any]:
    """Create a consistent failure record for one route."""
    return {
        "route": route,
        "status": status,
        "failed_stage": stage,
        "errors": list(errors),
    }


def _strip_internal_blank_ids(value: Any) -> Any:
    """Remove generated blank-node identifiers from a schema-facing payload."""
    if isinstance(value, list):
        cleaned_items = []
        for item in value:
            cleaned = _strip_internal_blank_ids(item)
            if cleaned is not _DROP:
                cleaned_items.append(cleaned)
        return cleaned_items if cleaned_items else _DROP

    if not isinstance(value, dict):
        return value

    cleaned_object: Dict[str, Any] = {}
    for key, child in value.items():
        if key == "@id" and isinstance(child, str) and child.startswith("_:"):
            continue
        cleaned = _strip_internal_blank_ids(child)
        if cleaned is not _DROP:
            cleaned_object[key] = cleaned
    return cleaned_object if cleaned_object else _DROP


def _prepare_schema_payload(primary: Dict[str, Any], schema_ref: str) -> Dict[str, Any]:
    """Convert framed JSON-LD into the JSON shape sent to Biovalidator."""
    cleaned = _strip_internal_blank_ids(primary)
    if cleaned is _DROP or not isinstance(cleaned, dict):
        cleaned = {}

    root_id = cleaned.get("@id")
    if isinstance(root_id, str):
        if "id" not in cleaned:
            cleaned["id"] = root_id
        cleaned.pop("@id", None)

    cleaned["@context"] = schema_ref
    return cleaned


# ---------------------------------------------------------------------------
# Progress and debug output
# ---------------------------------------------------------------------------


def _log_step(step: int, message: str) -> None:
    """Emit one concise suite-level progress line."""
    LOGGER.info("Step %d/%d: %s", step, TOTAL_STEPS, message)


def _debug_snapshot(
    enabled: bool,
    path: Path,
    label: str,
    value: Any,
    route: Optional[str] = None,
    raw: bool = False,
) -> None:
    """Print a complete labeled transformation snapshot to stdout."""
    if not enabled:
        return
    route_text = f" [{route}]" if route else ""
    sys.stdout.write(f"\n===== [DEBUG]{route_text} {path.name}: {label} =====\n")
    if raw:
        sys.stdout.write(str(value))
        if not str(value).endswith("\n"):
            sys.stdout.write("\n")
    else:
        json.dump(value, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")


def _first_error_text(errors: Sequence[Any]) -> str:
    """Return a compact representation of a route's first error."""
    if not errors:
        return "unknown error"
    first = errors[0]
    if isinstance(first, str):
        return first
    return json.dumps(first, ensure_ascii=False, separators=(",", ":"))


def _suppress_third_party_debug() -> None:
    """Keep dependency connection chatter out of -vv output."""
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Staged validation pipeline
# ---------------------------------------------------------------------------


def _set_file_failure(
    state: Dict[str, Any],
    status: str,
    stage: str,
    errors: Sequence[Any],
) -> None:
    """Record a file-level failure from loading or preflight."""
    state["ready"] = False
    state["result"].update(
        {
            "status": status,
            "failed_stage": stage,
            "errors": list(errors),
        }
    )
    LOGGER.debug(
        "Frame file failed: file='%s' stage=%s error=%s",
        state["path"].name,
        stage,
        _first_error_text(errors),
    )


def _set_route_failure(
    state: Dict[str, Any],
    route: str,
    status: str,
    stage: str,
    errors: Sequence[Any],
) -> None:
    """Record and log the first failure for one route."""
    route_state = state["routes"][route]
    if route_state.get("result") is not None:
        return
    route_state["result"] = _route_failure(route, status, stage, errors)
    LOGGER.debug(
        "Frame route failed: file='%s' route=%s stage=%s error=%s",
        state["path"].name,
        route,
        stage,
        _first_error_text(errors),
    )


def _route_active(state: Dict[str, Any], route: str) -> bool:
    """Return whether a prepared route has not failed yet."""
    return state.get("ready", False) and state["routes"][route].get("result") is None


def _prepare_input(
    spec: Dict[str, Path],
    id_to_path_map: Dict[str, Path],
    document_loader: Any,
    debug_snapshots: bool,
) -> Dict[str, Any]:
    """Load and validate one file (input) for later batch stages."""
    path = spec["path"]
    frame_path = spec["frame_path"]
    state: Dict[str, Any] = {
        **spec,
        "ready": True,
        "result": {"file": str(path), "frame": str(frame_path)},
        "routes": {route: {"result": None} for route in ROUTES},
        "document_loader": document_loader,
    }

    try:
        document = _load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        _set_file_failure(state, SCRIPT_ERROR_STATUS, "load_file", [str(exc)])
        return state

    _debug_snapshot(debug_snapshots, path, "original input document", document)
    if not isinstance(document, dict) or not {"data", "schema"}.issubset(document):
        _set_file_failure(
            state,
            SCRIPT_ERROR_STATUS,
            "wrapper_shape",
            ["Expected a JSON object with 'data' and 'schema' keys"],
        )
        return state

    data = document["data"]
    schema = document["schema"]
    if not isinstance(data, dict):
        _set_file_failure(
            state,
            SCRIPT_ERROR_STATUS,
            "wrapper_shape",
            ["'data' must be a JSON object"],
        )
        return state

    errors: List[str] = []
    schema_ref = schema.get("$ref", "") if isinstance(schema, dict) else ""
    if not schema_ref:
        errors.append("Missing schema.$ref")
    context = data.get("@context")
    if context is None:
        errors.append("Missing data.@context")
    if "@type" not in data:
        errors.append("Missing data.@type")
    if errors:
        _set_file_failure(state, SCRIPT_ERROR_STATUS, "wrapper_shape", errors)
        return state

    try:
        inline_context = materialize_context(context, path, id_to_path_map)
    except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
        _set_file_failure(
            state,
            SCRIPT_ERROR_STATUS,
            "context_materialization",
            [str(exc)],
        )
        return state

    invalid_context_types = find_invalid_context_type_mappings(inline_context)
    undefined_terms = find_undefined_terms(data, inline_context)
    preflight_errors = []
    if invalid_context_types:
        preflight_errors.append(
            "Invalid JSON-LD @type mappings: " + ", ".join(invalid_context_types)
        )
    if undefined_terms:
        preflight_errors.append(
            "Undefined JSON-LD terms in data: " + ", ".join(undefined_terms)
        )
    if preflight_errors:
        _set_file_failure(
            state,
            INVALID_STATUS,
            "context_preflight",
            preflight_errors,
        )
        return state

    try:
        frame_doc = _load_json(frame_path)
        if not isinstance(frame_doc, dict):
            raise ValueError("Frame must be a JSON object")
        frame_context = frame_doc.get("@context")
        frame_inline = dict(frame_doc)
        if frame_context is not None:
            frame_inline["@context"] = materialize_context(
                frame_context,
                frame_path,
                id_to_path_map,
            )
    except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
        _set_file_failure(
            state,
            SCRIPT_ERROR_STATUS,
            "frame_materialization",
            [str(exc)],
        )
        return state

    state.update(
        {
            "document": document,
            "data": data,
            "schema_ref": schema_ref,
            "inline_context": inline_context,
            "frame_inline": frame_inline,
            "data_with_context": _data_with_context(data, inline_context),
            "original_id": (
                data.get("id")
                if isinstance(data.get("id"), str)
                else data.get("@id")
            ),
            "original_types": _value_as_strings(data.get("@type")),
        }
    )
    return state


def _frame_route(
    state: Dict[str, Any],
    route: str,
    debug_snapshots: bool,
) -> None:
    """Frame one prepared noisy graph and select its primary entity."""
    if not _route_active(state, route):
        return

    route_state = state["routes"][route]
    try:
        framed = jsonld.frame(
            route_state["framed_input"],
            state["frame_inline"],
            options={
                "documentLoader": state["document_loader"],
                "omitDefault": True,
            },
        )
    except Exception as exc:  # noqa: BLE001 - PyLD raises diverse exceptions
        _set_route_failure(
            state,
            route,
            SCRIPT_ERROR_STATUS,
            "framing",
            [str(exc)],
        )
        return

    route_state["framed"] = framed
    _debug_snapshot(
        debug_snapshots,
        state["path"],
        "framed output",
        framed,
        route=route,
    )
    if _walk_contains_id(framed, route_state["noise_id"]):
        _set_route_failure(
            state,
            route,
            INVALID_STATUS,
            "noise_exclusion",
            [f"Noise entity '{route_state['noise_id']}' appeared in framed output"],
        )
        return

    primary, selection_error = _select_primary_entity(
        framed,
        state["original_id"],
        state["original_types"],
    )
    if primary is None:
        _set_route_failure(
            state,
            route,
            INVALID_STATUS,
            "primary_selection",
            [selection_error or "Could not select primary framed entity"],
        )
        return

    route_state["primary"] = primary
    _debug_snapshot(
        debug_snapshots,
        state["path"],
        "selected primary entity",
        primary,
        route=route,
    )


def _validate_route_output(
    state: Dict[str, Any],
    route: str,
    validator_url: str,
    debug_snapshots: bool,
) -> None:
    """Check semantic equality, sanitize, and schema-validate one route."""
    if not _route_active(state, route):
        return

    route_state = state["routes"][route]
    semantic_data = dict(route_state["primary"])
    semantic_data["@context"] = state["schema_ref"]
    route_state["semantic_data"] = semantic_data
    _debug_snapshot(
        debug_snapshots,
        state["path"],
        "semantic framed document before payload sanitization",
        semantic_data,
        route=route,
    )

    try:
        framed_canonical = _canonicalize_jsonld(
            semantic_data,
            state["inline_context"],
            state["document_loader"],
        )
    except Exception as exc:  # noqa: BLE001
        _set_route_failure(
            state,
            route,
            SCRIPT_ERROR_STATUS,
            "canonicalize_framed",
            [str(exc)],
        )
        return

    route_state["framed_canonical"] = framed_canonical
    _debug_snapshot(
        debug_snapshots,
        state["path"],
        "canonical framed RDF/N-Quads",
        framed_canonical,
        route=route,
        raw=True,
    )
    if framed_canonical != state["original_canonical"]:
        _set_route_failure(
            state,
            route,
            INVALID_STATUS,
            "rdf_equivalence",
            _summarize_nquads_difference(
                state["original_canonical"],
                framed_canonical,
            ),
        )
        return

    framed_data = _prepare_schema_payload(route_state["primary"], state["schema_ref"])
    wrapper = {"schema": {"$ref": state["schema_ref"]}, "data": framed_data}
    route_state["framed_data"] = framed_data
    route_state["validator_request"] = wrapper
    _debug_snapshot(
        debug_snapshots,
        state["path"],
        "schema-facing framed payload",
        framed_data,
        route=route,
    )
    _debug_snapshot(
        debug_snapshots,
        state["path"],
        "Biovalidator request",
        wrapper,
        route=route,
    )

    try:
        validator_response = _post_to_validator(wrapper, validator_url)
    except requests.RequestException as exc:
        _set_route_failure(
            state,
            route,
            REQUEST_ERROR_STATUS,
            "schema_validation_request",
            [str(exc)],
        )
        return
    except (json.JSONDecodeError, ValueError) as exc:
        _set_route_failure(
            state,
            route,
            UNKNOWN_STATUS,
            "schema_validation_response",
            [f"Malformed Biovalidator response: {exc}"],
        )
        return

    route_state["validator_response"] = validator_response
    _debug_snapshot(
        debug_snapshots,
        state["path"],
        "Biovalidator response",
        validator_response,
        route=route,
    )
    validator_status = _classify_validator_response(validator_response)
    if validator_status == VALID_STATUS:
        route_state["result"] = {
            "route": route,
            "status": VALID_STATUS,
            "failed_stage": None,
            "canonical_nquads": len(state["original_canonical"].splitlines()),
        }
        return

    errors = (
        validator_response
        if isinstance(validator_response, list)
        else [validator_response]
    )
    _set_route_failure(
        state,
        route,
        validator_status,
        "schema_validation",
        errors,
    )


def _aggregate_route_status(route_results: Sequence[Dict[str, Any]]) -> str:
    """Collapse per-route statuses into one file-level status."""
    statuses = [result.get("status") for result in route_results]
    for status in (
        SCRIPT_ERROR_STATUS,
        REQUEST_ERROR_STATUS,
        UNKNOWN_STATUS,
        INVALID_STATUS,
    ):
        if status in statuses:
            return status
    return VALID_STATUS


def _finalize_file_result(
    state: Dict[str, Any],
    debug_snapshots: bool,
) -> Dict[str, Any]:
    """Build the public result record for one pipeline state."""
    if not state.get("ready", False):
        _debug_snapshot(
            debug_snapshots,
            state["path"],
            "final file result",
            state["result"],
        )
        return state["result"]

    route_results: List[Dict[str, Any]] = []
    for route in ROUTES:
        route_result = state["routes"][route].get("result")
        if route_result is None:
            route_result = _route_failure(
                route,
                SCRIPT_ERROR_STATUS,
                "pipeline",
                ["Route did not produce a result"],
            )
        route_results.append(route_result)

    status = _aggregate_route_status(route_results)
    state["result"].update(
        {
            "status": status,
            "routes": route_results,
            "canonical_nquads": len(state["original_canonical"].splitlines()),
        }
    )
    if status != VALID_STATUS:
        state["result"]["errors"] = [
            f"{route_result['route']}:{route_result.get('failed_stage')}"
            for route_result in route_results
            if route_result.get("status") != VALID_STATUS
        ]

    LOGGER.debug(
        "Frame-validated '%s' -> %s",
        state["path"].name,
        "passed" if status == VALID_STATUS else "failed",
    )
    _debug_snapshot(
        debug_snapshots,
        state["path"],
        "final file result",
        state["result"],
    )
    return state["result"]


def _run_pipeline(
    specs: Sequence[Dict[str, Path]],
    id_to_path_map: Dict[str, Path],
    validator_url: str,
    debug_snapshots: bool,
) -> List[Dict[str, Any]]:
    """Run all files through ten real, suite-level transformation phases."""
    total_files = len(specs)
    document_loader = make_local_document_loader(id_to_path_map)

    _log_step(1, f"Loading and validatiing {total_files} file(s) (inputs)")
    states = [
        _prepare_input(
            spec,
            id_to_path_map,
            document_loader,
            debug_snapshots,
        )
        for spec in specs
    ]

    _log_step(2, f"Converting {total_files} original JSON-LD file(s) into standardized RDF representation")
    for state in states:
        if not state.get("ready", False):
            continue
        try:
            state["original_canonical"] = _canonicalize_jsonld(
                state["data"],
                state["inline_context"],
                document_loader,
            )
        except Exception as exc:  # noqa: BLE001
            _set_file_failure(
                state,
                SCRIPT_ERROR_STATUS,
                "canonicalize_original",
                [str(exc)],
            )
            continue
        _debug_snapshot(
            debug_snapshots,
            state["path"],
            "canonical original RDF/N-Quads",
            state["original_canonical"],
            raw=True,
        )

    _log_step(3, f"Flattening {total_files} file(s) through direct JSON-LD")
    for state in states:
        if not _route_active(state, ROUTE_FLATTENED):
            continue
        try:
            flattened = jsonld.flatten(
                state["data_with_context"],
                options={"documentLoader": document_loader},
            )
            state["routes"][ROUTE_FLATTENED]["flat_nodes"] = _as_graph_nodes(
                flattened
            )
        except Exception as exc:  # noqa: BLE001
            _set_route_failure(
                state,
                ROUTE_FLATTENED,
                SCRIPT_ERROR_STATUS,
                "route_input",
                [str(exc)],
            )
            continue
        _debug_snapshot(
            debug_snapshots,
            state["path"],
            "flattened graph",
            flattened,
            route=ROUTE_FLATTENED,
        )

    _log_step(4, f"Adding noise to {total_files} direct-route graph(s)")
    for state in states:
        if not _route_active(state, ROUTE_FLATTENED):
            continue
        route_state = state["routes"][ROUTE_FLATTENED]
        route_state["noise_id"] = f"urn:uuid:{uuid.uuid4()}"
        route_state["framed_input"] = {
            "@graph": route_state["flat_nodes"]
            + [_noise_entity(route_state["noise_id"])]
        }
        _debug_snapshot(
            debug_snapshots,
            state["path"],
            "flattened graph with injected noise",
            route_state["framed_input"],
            route=ROUTE_FLATTENED,
        )

    _log_step(5, f"Framing and checking {total_files} direct-route graph(s)")
    for state in states:
        _frame_route(state, ROUTE_FLATTENED, debug_snapshots)

    _log_step(6, f"Generating RDF/N-Quads for {total_files} file(s)")
    for state in states:
        if not _route_active(state, ROUTE_RDF_GRAPH):
            continue
        try:
            nquads = jsonld.to_rdf(
                state["data_with_context"],
                options={
                    "format": "application/n-quads",
                    "documentLoader": document_loader,
                },
            )
            state["routes"][ROUTE_RDF_GRAPH]["nquads"] = nquads
        except Exception as exc:  # noqa: BLE001
            _set_route_failure(
                state,
                ROUTE_RDF_GRAPH,
                SCRIPT_ERROR_STATUS,
                "rdf_generation",
                [str(exc)],
            )
            continue
        _debug_snapshot(
            debug_snapshots,
            state["path"],
            "generated RDF/N-Quads",
            nquads,
            route=ROUTE_RDF_GRAPH,
            raw=True,
        )

    _log_step(7, f"Reconstructing and flattening {total_files} RDF graph(s)")
    for state in states:
        if not _route_active(state, ROUTE_RDF_GRAPH):
            continue
        route_state = state["routes"][ROUTE_RDF_GRAPH]
        try:
            reconstructed = jsonld.from_rdf(
                route_state["nquads"],
                options={
                    "format": "application/n-quads",
                    "useNativeTypes": True,
                },
            )
            flattened = jsonld.flatten(
                reconstructed,
                options={"documentLoader": document_loader},
            )
            route_state["reconstructed"] = reconstructed
            route_state["flat_nodes"] = _as_graph_nodes(flattened)
        except Exception as exc:  # noqa: BLE001
            _set_route_failure(
                state,
                ROUTE_RDF_GRAPH,
                SCRIPT_ERROR_STATUS,
                "rdf_reconstruction",
                [str(exc)],
            )
            continue
        _debug_snapshot(
            debug_snapshots,
            state["path"],
            "JSON-LD reconstructed from RDF",
            reconstructed,
            route=ROUTE_RDF_GRAPH,
        )
        _debug_snapshot(
            debug_snapshots,
            state["path"],
            "flattened reconstructed RDF graph",
            flattened,
            route=ROUTE_RDF_GRAPH,
        )

    _log_step(
        8,
        f"Adding noise, framing, and checking {total_files} RDF-route graph(s)",
    )
    for state in states:
        if not _route_active(state, ROUTE_RDF_GRAPH):
            continue
        route_state = state["routes"][ROUTE_RDF_GRAPH]
        route_state["noise_id"] = f"urn:uuid:{uuid.uuid4()}"
        route_state["framed_input"] = {
            "@graph": route_state["flat_nodes"]
            + [_noise_entity(route_state["noise_id"])]
        }
        _debug_snapshot(
            debug_snapshots,
            state["path"],
            "reconstructed RDF graph with injected noise",
            route_state["framed_input"],
            route=ROUTE_RDF_GRAPH,
        )
        _frame_route(state, ROUTE_RDF_GRAPH, debug_snapshots)

    _log_step(
        9,
        f"Checking RDF equivalence and validating {total_files} file(s) across 2 route(s)",
    )
    for state in states:
        for route in ROUTES:
            _validate_route_output(
                state,
                route,
                validator_url,
                debug_snapshots,
            )

    _log_step(10, f"Summarizing {total_files} file result(s)")
    return [
        _finalize_file_result(state, debug_snapshots)
        for state in states
    ]


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------


def empty_counts() -> Dict[str, int]:
    """Create a zero-filled counter block for summaries."""
    return {key: 0 for key in COUNT_KEYS}


def add_counts(target: Dict[str, int], source: Dict[str, Any]) -> None:
    """Add one summary's counters into another summary."""
    for key in COUNT_KEYS:
        target[key] += source.get(key, 0)


def entity_passed(summary: Dict[str, Any]) -> bool:
    """Return whether one entity has a fully passing frame suite."""
    return (
        summary["total_files"] > 0
        and summary["completed_runs"] == summary["total_files"]
        and summary["validation_passed"] == summary["total_files"]
        and summary["validation_failed"] == 0
        and summary["request_errors"] == 0
        and summary["unknown_responses"] == 0
        and summary["script_errors"] == 0
    )


def _summarize_entity_results(
    entity_dir: Path,
    frame_path: Path,
    results: Sequence[Dict[str, Any]],
    input_path: Path,
) -> Dict[str, Any]:
    """Build one entity summary from completed file result records."""
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
        result["file"] for result in results if result["status"] != VALID_STATUS
    ]
    summary: Dict[str, Any] = {
        "entity": entity_dir.name,
        "frame": str(frame_path),
        "input_path": str(input_path),
        "total_files": len(results),
        "completed_runs": status_counts[VALID_STATUS] + status_counts[INVALID_STATUS],
        "validation_passed": status_counts[VALID_STATUS],
        "validation_failed": status_counts[INVALID_STATUS],
        "request_errors": status_counts[REQUEST_ERROR_STATUS],
        "unknown_responses": status_counts[UNKNOWN_STATUS],
        "script_errors": status_counts[SCRIPT_ERROR_STATUS],
        "files": list(results),
        "expectation_failed_files": expectation_failed_files,
        "n_total_files": len(results),
        "n_failed_files": len(expectation_failed_files),
    }
    summary["passed"] = entity_passed(summary)
    return summary


def summarize_totals(entity_summaries: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Add all entity counters into one total counter block."""
    totals = empty_counts()
    for entity_summary in entity_summaries:
        add_counts(totals, entity_summary)
    return totals


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def validate_jsonld_frames(
    root: Path,
    entity: Optional[str],
    validator_url: str,
    repo_root: Optional[Path] = None,
    input_file: Optional[Path] = None,
    debug_snapshots: bool = False,
) -> Dict[str, Any]:
    """Run frame round-trip tests for a suite, entity, or single file."""
    assert_validator_reachable(validator_url)

    if repo_root is None:
        repo_root = find_repo_root(root.resolve())

    id_to_path_map = build_id_to_path_map(repo_root)
    LOGGER.debug("Loaded %d entries in schema/context map", len(id_to_path_map))

    entity_dirs, specs, frame_gaps = _discover_inputs(
        root,
        entity,
        input_file,
        id_to_path_map,
    )
    for gap in frame_gaps:
        LOGGER.error("Missing frame.jsonld for entity '%s'", gap)

    results = _run_pipeline(
        specs,
        id_to_path_map,
        validator_url,
        debug_snapshots,
    )
    results_by_path = {result["file"]: result for result in results}

    entity_summaries: List[Dict[str, Any]] = []
    for entity_dir in entity_dirs:
        frame_path = entity_dir / "frame.jsonld"
        if not frame_path.is_file():
            continue
        entity_specs = [
            spec for spec in specs if spec["entity_dir"].resolve() == entity_dir.resolve()
        ]
        entity_results = [
            results_by_path[str(spec["path"])]
            for spec in entity_specs
            if str(spec["path"]) in results_by_path
        ]
        input_path = (
            input_file.resolve()
            if input_file is not None
            else entity_dir / "examples" / "valid"
        )
        entity_summaries.append(
            _summarize_entity_results(
                entity_dir,
                frame_path,
                entity_results,
                input_path,
            )
        )

    totals = summarize_totals(entity_summaries)
    overall_passed = (
        bool(entity_summaries)
        and all(summary["passed"] for summary in entity_summaries)
        and not frame_gaps
    )
    mode = "file" if input_file is not None else "entity" if entity else "suite"
    resolved_entity = entity_dirs[0].name if input_file is not None else entity
    summary = {
        "timestamp": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(
            timespec="seconds"
        ),
        "root": str(root),
        "mode": mode,
        "input_file": str(input_file.resolve()) if input_file is not None else None,
        "passed": overall_passed,
        "entity": resolved_entity,
        "entity_names": [path.name for path in entity_dirs],
        "routes": list(ROUTES),
        "frame_gaps": frame_gaps,
        **totals,
        "files": entity_summaries,
    }
    if debug_snapshots and input_file is not None:
        _debug_snapshot(
            True,
            input_file.resolve(),
            "final run summary",
            summary,
        )
    return summary


# ---------------------------------------------------------------------------
# Logging / output helpers
# ---------------------------------------------------------------------------


def _log_results(summary: Dict[str, Any]) -> None:
    """Write a short human-readable result summary to the logger."""
    frame_gaps = summary.get("frame_gaps", [])
    if frame_gaps:
        LOGGER.info(
            "Missing frame.jsonld for %d entity/entities: %s",
            len(frame_gaps),
            frame_gaps,
        )

    LOGGER.info(
        "%d / %d valid files passed frame round-trip checks",
        summary.get("validation_passed", 0),
        summary.get("total_files", 0),
    )
    if summary["passed"]:
        LOGGER.info("Tests %spassed%s", _BOLD_GREEN, _ANSI_RESET)
    else:
        LOGGER.info("Tests %sfailed%s", _BOLD_RED, _ANSI_RESET)


def write_summary(summary: Dict[str, Any], summary_dir: Path) -> None:
    """Write the machine-readable frame summary JSON file."""
    summary_dir.mkdir(parents=True, exist_ok=True)
    with (summary_dir / SUMMARY_FILENAME).open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def make_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for frame validation."""
    parser = argparse.ArgumentParser(
        prog="validate_jsonld_frames",
        description=(
            "Validate JSON-LD frame round-trips for FEGA valid examples.\n"
            "Requires a running Biovalidator endpoint (see --url)."
        ),
        epilog=(
            "Examples:\n"
            "  validate_jsonld_frames --entity cohort -v\n"
            "  validate_jsonld_frames --file path/to/example.json -vv\n"
            "  validate_jsonld_frames --root schemas/entities "
            "--url http://localhost:3020/validate --summary-dir . -v"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"Entity schema root (default: {DEFAULT_ROOT})",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--entity",
        help="Validate one entity by directory name, e.g. 'cohort'.",
    )
    selection.add_argument(
        "--file",
        type=Path,
        dest="input_file",
        help="Validate one wrapped JSON example and trace it with -vv.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_VALIDATOR_URL,
        help=f"Biovalidator endpoint URL (default: {DEFAULT_VALIDATOR_URL})",
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
    """Parse CLI arguments, run validation, and exit with the suite status."""
    parser = make_arg_parser()
    args = parser.parse_args(argv)
    debug_snapshots = args.input_file is not None and args.verbosity >= 2
    if debug_snapshots and args.print_summary:
        parser.error("--print-summary cannot be combined with --file -vv")

    configure_logging(args.verbosity)
    _suppress_third_party_debug()

    try:
        summary = validate_jsonld_frames(
            args.root,
            args.entity,
            args.url,
            input_file=args.input_file,
            debug_snapshots=debug_snapshots,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
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
