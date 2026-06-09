"""Shared JSON-LD utilities for FEGA validation scripts.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, FrozenSet, List

GITHUB_RAW_PREFIX = "https://raw.githubusercontent.com/M-casado/fega-metadata-schema/main/"


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
