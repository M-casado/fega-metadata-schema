from __future__ import annotations

import json
from pathlib import Path

from fega_tools.jsonld_coverage import (
    collect_schema_property_paths,
    validate_jsonld_coverage,
)
from fega_tools.jsonld_utils import (
    build_id_to_path_map,
    validate_context_term_mappings,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_entity(
    repo: Path,
    entity: str,
    schema: dict,
    context_terms: dict,
    frame: dict,
) -> Path:
    entity_dir = repo / "schemas" / "entities" / entity
    schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
    schema.setdefault("$id", f"https://example.org/schemas/entities/{entity}/schema.json")
    schema.setdefault("@context", "./context.jsonld")
    _write_json(entity_dir / "schema.json", schema)
    _write_json(entity_dir / "context.jsonld", {"@context": context_terms})
    _write_json(entity_dir / "frame.jsonld", frame)
    return entity_dir


def test_collect_schema_property_paths_follows_local_defs_and_skips_standards(
    tmp_path: Path,
) -> None:
    """Check local $defs are traversed but external/standards refs stop."""
    repo = tmp_path
    entity_dir = repo / "schemas" / "entities" / "biomaterial"
    schema = {
        "$id": "https://example.org/schemas/entities/biomaterial/schema.json",
        "allOf": [{"$ref": "#/$defs/checklist"}],
        "$defs": {
            "checklist": {
                "properties": {
                    "biomaterialType": {
                        "properties": {
                            "label": {"type": "string"},
                        }
                    },
                    "externalCarrier": {
                        "$ref": "../../../standards/json-schema/vendor/schema.json#/properties/vendorOnly"
                    },
                }
            }
        },
    }
    _write_json(entity_dir / "schema.json", schema)
    id_to_path_map = build_id_to_path_map(repo)

    paths = collect_schema_property_paths(
        schema,
        entity_dir / "schema.json",
        id_to_path_map,
        repo,
    )

    assert paths["biomaterialType"] == {"biomaterialType"}
    assert paths["label"] == {"biomaterialType.label"}
    assert paths["externalCarrier"] == {"externalCarrier"}
    assert "vendorOnly" not in paths


def test_nested_context_terms_are_required_but_nested_frame_keys_are_not(
    tmp_path: Path,
) -> None:
    """Check nested terms need context coverage but not top-level frame entries."""
    repo = tmp_path
    _write_entity(
        repo,
        "sample",
        {
            "type": "object",
            "properties": {
                "rootNode": {
                    "type": "object",
                    "properties": {
                        "nestedValue": {"type": "string"},
                    },
                }
            },
        },
        {"rootNode": "https://example.org/rootNode"},
        {
            "@context": "https://example.org/schemas/entities/sample/schema.json",
            "@type": "ega:sample",
            "@embed": "@always",
            "@explicit": False,
            "rootNode": {},
        },
    )

    summary = validate_jsonld_coverage(
        repo / "schemas" / "entities",
        "sample",
        repo_root=repo,
    )
    result = summary["files"][0]

    assert result["missing_context_terms"] == ["nestedValue"]
    assert result["missing_context_term_paths"] == {
        "nestedValue": ["rootNode.nestedValue"]
    }
    assert result["missing_frame_keys"] == []


def test_missing_root_frame_key_fails_frame_coverage(tmp_path: Path) -> None:
    """Check direct root-surface properties must be represented in frames."""
    repo = tmp_path
    _write_entity(
        repo,
        "sample",
        {
            "type": "object",
            "properties": {
                "rootNode": {"type": "string"},
            },
        },
        {"rootNode": "https://example.org/rootNode"},
        {
            "@context": "https://example.org/schemas/entities/sample/schema.json",
            "@type": "ega:sample",
            "@embed": "@always",
            "@explicit": False,
        },
    )

    summary = validate_jsonld_coverage(
        repo / "schemas" / "entities",
        "sample",
        repo_root=repo,
    )
    result = summary["files"][0]

    assert result["missing_context_terms"] == []
    assert result["missing_frame_keys"] == ["rootNode"]
    assert result["missing_frame_key_paths"] == {"rootNode": ["rootNode"]}


def test_known_external_frame_keys_are_allowed(tmp_path: Path) -> None:
    """Check extra frame keys are allowed when materialized context defines them."""
    repo = tmp_path
    _write_entity(
        repo,
        "sample",
        {
            "type": "object",
            "properties": {
                "rootNode": {"type": "string"},
            },
        },
        {
            "rootNode": "https://example.org/rootNode",
            "externalKnown": "https://example.org/externalKnown",
        },
        {
            "@context": "https://example.org/schemas/entities/sample/schema.json",
            "@type": "ega:sample",
            "@embed": "@always",
            "@explicit": False,
            "rootNode": {},
            "externalKnown": {},
        },
    )

    summary = validate_jsonld_coverage(
        repo / "schemas" / "entities",
        "sample",
        repo_root=repo,
    )
    result = summary["files"][0]

    assert result["missing_context_terms"] == []
    assert result["missing_frame_keys"] == []
    assert result["unknown_frame_keys"] == []


def test_reverse_context_terms_expand_as_relationships() -> None:
    """Reverse properties must be probed with node values, not literals."""
    context = {
        "used": "http://www.w3.org/ns/prov#used",
        "wasUsedBy": {"@reverse": "used", "@container": "@set"},
        "wasInformedBy": "http://www.w3.org/ns/prov#wasInformedBy",
        "informs": {"@reverse": "wasInformedBy", "@container": "@set"},
    }

    assert validate_context_term_mappings(
        context,
        {"used", "wasUsedBy", "wasInformedBy", "informs"},
    ) == []


def test_keyword_alias_cannot_cover_a_schema_property() -> None:
    """A schema property needs an RDF predicate, not an alias for a keyword."""
    assert validate_context_term_mappings(
        {"id": "@id"},
        {"id"},
    ) == [
        "Term 'id' aliases JSON-LD keyword '@id' and cannot represent a schema property"
    ]
