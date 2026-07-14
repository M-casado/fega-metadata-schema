from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = REPO_ROOT / "scripts" / "py"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from validate_rdf_shacl import root_has_required_type


CONTEXT = {
    "dcat": "http://www.w3.org/ns/dcat#",
    "sameAs": {"@id": "http://www.w3.org/2002/07/owl#sameAs", "@type": "@id"},
    "related": {"@id": "http://example.org/related", "@type": "@id"},
}


def test_root_type_survives_self_reference() -> None:
    document = {
        "@context": CONTEXT,
        "@id": "http://example.org/dataset/1",
        "@type": "dcat:Dataset",
        "sameAs": {"@id": "http://example.org/dataset/1", "@type": "ega:Dataset"},
    }

    assert root_has_required_type(document, "http://www.w3.org/ns/dcat#Dataset")


def test_nested_type_does_not_satisfy_root_requirement() -> None:
    document = {
        "@context": CONTEXT,
        "@id": "http://example.org/dataset/1",
        "@type": "http://example.org/OtherRootType",
        "related": {
            "@id": "http://example.org/dataset/2",
            "@type": "dcat:Dataset",
        },
    }

    assert not root_has_required_type(document, "http://www.w3.org/ns/dcat#Dataset")


def test_invalid_jsonld_context_is_reported() -> None:
    with pytest.raises(ValueError, match="Failed to expand JSON-LD"):
        root_has_required_type({"@context": "not a valid context reference"}, "dcat:Dataset")
