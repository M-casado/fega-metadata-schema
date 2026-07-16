"""Shared JSON-LD utilities for FEGA validation scripts.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Set, Tuple
from urllib.parse import urlparse

GITHUB_RAW_PREFIX = "https://raw.githubusercontent.com/M-casado/fega-metadata-schema/main/"

JSONLD_KEYWORDS = {
    "@base",
    "@container",
    "@context",
    "@direction",
    "@embed",
    "@explicit",
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
    "@omitDefault",
    "@prefix",
    "@propagate",
    "@protected",
    "@reverse",
    "@requireAll",
    "@set",
    "@type",
    "@value",
    "@version",
    "@vocab",
}


# ---------------------------------------------------------------------------
# Repo root discovery
# ---------------------------------------------------------------------------

def find_repo_root(start: Path) -> Path:
    """Walk up from *start* to find the directory containing pyproject.toml or .git."""
    current = start.resolve()
    while current != current.parent:
        if (current / "pyproject.toml").exists() or (current / ".git").exists():
            return current
        current = current.parent
    return start.resolve()


# ---------------------------------------------------------------------------
# $id → local-path map
# ---------------------------------------------------------------------------

def build_id_to_path_map(repo_root: Path) -> Dict[str, Path]:
    """Return a dict mapping GitHub raw URLs (and schema $ids) to local Paths.

    Covers every ``schema.json`` and every ``context.jsonld`` found under
    *repo_root*.
    """
    id_map: Dict[str, Path] = {}

    for schema_file in sorted(repo_root.rglob("schema.json")):
        try:
            with schema_file.open("r", encoding="utf-8") as fh:
                schema = json.load(fh)
            schema_id = schema.get("$id", "")
            if schema_id:
                id_map[schema_id] = schema_file
        except (json.JSONDecodeError, OSError):
            pass
        # Register via inferred raw-GitHub URL as well.
        try:
            rel = schema_file.relative_to(repo_root)
            url = GITHUB_RAW_PREFIX + str(rel).replace("\\", "/")
            id_map.setdefault(url, schema_file)
        except ValueError:
            pass

    for context_file in sorted(repo_root.rglob("context.jsonld")):
        try:
            rel = context_file.relative_to(repo_root)
            url = GITHUB_RAW_PREFIX + str(rel).replace("\\", "/")
            id_map[url] = context_file
        except ValueError:
            pass

    return id_map


# ---------------------------------------------------------------------------
# Context materialization
# ---------------------------------------------------------------------------

def resolve_ref(ref: str, current_file: Path, id_to_path_map: Dict[str, Path]) -> Path:
    """Resolve a context string reference to a local Path.

    Checks the URL map first, then falls back to relative-path resolution.
    """
    if ref in id_to_path_map:
        return id_to_path_map[ref]

    if not ref.startswith(("http://", "https://")):
        resolved = (current_file.parent / ref).resolve()
        if resolved.exists():
            return resolved
        raise FileNotFoundError(
            f"Cannot resolve relative reference '{ref}' from '{current_file}'"
        )

    raise FileNotFoundError(
        f"Cannot map URL '{ref}' to a local file. "
        "Add the file to the repository or update GITHUB_RAW_PREFIX."
    )


def materialize_context(
    ctx_value: Any,
    current_file: Path,
    id_to_path_map: Dict[str, Path],
    seen: FrozenSet[Path] = frozenset(),
) -> Any:
    """Recursively resolve all string references in *ctx_value* to inline objects.

    Returns a context value (dict or list of dicts) that can be passed directly
    to rdflib or PyLD without network requests.
    """
    if isinstance(ctx_value, str):
        local_path = resolve_ref(ctx_value, current_file, id_to_path_map)

        if local_path in seen:
            raise ValueError(f"Circular context reference detected: '{local_path}'")

        with local_path.open("r", encoding="utf-8") as fh:
            loaded = json.load(fh)

        if "@context" not in loaded:
            raise ValueError(f"No '@context' key found in '{local_path}'")

        return materialize_context(
            loaded["@context"],
            local_path,
            id_to_path_map,
            seen | {local_path},
        )

    if isinstance(ctx_value, list):
        result: List[Any] = []
        for item in ctx_value:
            materialized = materialize_context(item, current_file, id_to_path_map, seen)
            if isinstance(materialized, list):
                result.extend(materialized)
            else:
                result.append(materialized)
        return result

    # dict or scalar – return as-is
    return ctx_value


# ---------------------------------------------------------------------------
# Context inspection
# ---------------------------------------------------------------------------

def context_terms_and_prefixes(context: Any) -> Tuple[Set[str], Set[str]]:
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


def validate_context_term_mappings(
    context: Any,
    terms: Set[str],
) -> List[str]:
    """Check that schema-facing context terms expand to absolute IRIs.

    A term being present in a context is not sufficient: JSON-LD silently
    drops terms mapped to null and rejects or leaves malformed compact IRIs
    unresolved.  Expand each maintained term independently so coverage checks
    verify the mapping that downstream RDF consumers will actually use.
    """
    try:
        from pyld import jsonld
    except ImportError as exc:  # pragma: no cover - runtime dependency guard
        raise ValueError("pyld is required to validate JSON-LD term mappings") from exc

    def term_definition(term: str) -> Any:
        """Return the effective definition of a term in a materialized context."""
        contexts = context if isinstance(context, list) else [context]
        definition = None
        for context_item in contexts:
            if isinstance(context_item, dict) and term in context_item:
                definition = context_item[term]
        return definition

    errors: List[str] = []
    for term in sorted(terms):
        definition = term_definition(term)
        keyword_alias = None
        if isinstance(definition, str) and definition in JSONLD_KEYWORDS:
            keyword_alias = definition
        elif isinstance(definition, dict):
            candidate = definition.get("@id")
            if isinstance(candidate, str) and candidate in JSONLD_KEYWORDS:
                keyword_alias = candidate
        if keyword_alias is not None:
            errors.append(
                f"Term '{term}' aliases JSON-LD keyword '{keyword_alias}' "
                "and cannot represent a schema property"
            )
            continue
        probe_value: Any = "value"
        if isinstance(definition, dict) and "@reverse" in definition:
            probe_value = {"@id": "https://example.org/jsonld-coverage-probe"}
        try:
            expanded = jsonld.expand({"@context": context, term: probe_value})
        except Exception as exc:  # pyld exposes several exception types
            errors.append(f"Term '{term}' cannot be expanded: {exc}")
            continue

        properties = {
            key
            for node in expanded
            if isinstance(node, dict)
            for key in node
            if not key.startswith("@")
        }
        properties.update(
            key
            for node in expanded
            if isinstance(node, dict)
            for reverse in [node.get("@reverse", {})]
            if isinstance(reverse, dict)
            for key in reverse
        )
        if not properties or not all(urlparse(key).scheme for key in properties):
            errors.append(f"Term '{term}' does not expand to an absolute IRI")
    return errors


def walk_object_keys(value: Any, path: str = "") -> List[Tuple[str, str]]:
    """Return all object key paths from a JSON value."""
    keys: List[Tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}/{key}" if path else key
            keys.append((child_path, key))
            keys.extend(walk_object_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            keys.extend(walk_object_keys(child, f"{path}[{index}]"))
    return keys


def is_known_jsonld_key(key: str, terms: Set[str], prefixes: Set[str]) -> bool:
    """Return whether a JSON key is defined by JSON-LD terms or prefixes."""
    if key in JSONLD_KEYWORDS or key in terms:
        return True
    if key.startswith(("http://", "https://")):
        return True
    if ":" in key:
        return key.split(":", 1)[0] in prefixes
    return False


def find_undefined_terms(data: Dict[str, Any], context: Any) -> List[str]:
    """Return JSON key paths that JSON-LD would ignore as undefined terms."""
    terms, prefixes = context_terms_and_prefixes(context)
    return [
        path
        for path, key in walk_object_keys(data)
        if not is_known_jsonld_key(key, terms, prefixes)
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


# ---------------------------------------------------------------------------
# PyLD document loader
# ---------------------------------------------------------------------------

def make_local_document_loader(
    id_to_path_map: Dict[str, Path],
) -> Any:
    """Return a PyLD-compatible document loader that resolves URLs via local files.

    The loader maps known GitHub raw URLs to local paths so that PyLD never
    makes network requests during frame processing.
    """
    def loader(url: str, options: Dict[str, Any] = {}) -> Dict[str, Any]:  # noqa: B006
        if url in id_to_path_map:
            local_path = id_to_path_map[url]
            with local_path.open("r", encoding="utf-8") as fh:
                document = json.load(fh)
            return {
                "contentType": "application/ld+json",
                "contextUrl": None,
                "documentUrl": url,
                "document": document,
            }
        # If not found, raise so no silent fallback to the network.
        raise Exception(  # PyLD catches generic exceptions from loaders
            f"Cannot load URL locally (not in id_to_path_map): {url}"
        )

    return loader
