from __future__ import annotations

import pytest

from fega_tools.json_pointer import _validate_replacements, patch_json_tree


def test_patch_json_tree_updates_raw_github_uri_segments() -> None:
    """Check that matching raw GitHub URLs are rewritten in JSON-LD keys."""
    uri = "https://raw.githubusercontent.com/M-casado/fega-metadata-schema/main/schemas/entities/cohort/schema.json"
    document = {
        "$id": uri,
        "nested": {
            "$ref": uri,
            "unchanged": uri,
            "@context": "./context.jsonld",
        },
    }
    mappings: dict[str, str] = {}

    patched = patch_json_tree(
        document,
        replacements={"branch": ("main", "dev")},
        uri_mappings=mappings,
    )

    expected = uri.replace("/main/", "/dev/")
    assert patched["$id"] == expected
    assert patched["nested"]["$ref"] == expected
    assert patched["nested"]["unchanged"] == uri
    assert patched["nested"]["@context"] == "./context.jsonld"
    assert mappings == {uri: expected}


def test_patch_json_tree_requires_all_segments_to_match_by_default() -> None:
    """Check that partial matches are ignored when all segments must match."""
    uri = "https://raw.githubusercontent.com/M-casado/fega-metadata-schema/main/schema.json"

    patched = patch_json_tree(
        {"$ref": uri},
        replacements={
            "owner": ("other-owner", "new-owner"),
            "branch": ("main", "dev"),
        },
    )

    assert patched == {"$ref": uri}


def test_validate_replacements_rejects_unknown_segment() -> None:
    """Check that unsupported replacement segment names are rejected."""
    with pytest.raises(ValueError, match="Invalid segment"):
        _validate_replacements({"tag": ("main", "dev")})
