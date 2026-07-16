from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = REPO_ROOT / "scripts" / "py"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from validate_jsonld_frames import _select_primary_entity


def test_primary_selection_matches_equivalent_compact_and_absolute_ids() -> None:
    """Framing must compare node identifiers by JSON-LD value, not spelling."""
    # The test gives the frame output the short CURIE form, but tells the selector
    # the original used the full URL. It passes only if the selector expands both 
    # forms and identifies them as the same Dataset.
    context = {"ega": "https://identifiers.org/ega:"}
    framed = {
        "@context": context,
        "@id": "ega:EGAD00000000001",
        "@type": "ega:dataset",
    }

    primary, error = _select_primary_entity(
        framed,
        "https://identifiers.org/ega:EGAD00000000001",
        ["ega:dataset"],
        context,
    )

    assert error is None
    assert primary == {
        "@id": "ega:EGAD00000000001",
        "@type": "ega:dataset",
    }
