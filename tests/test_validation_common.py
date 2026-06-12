from __future__ import annotations

import json

from fega_tools.validation_common import (
    BASIC_COUNT_KEYS,
    add_counts,
    coverage_gaps_for_entity_category,
    empty_counts,
    find_entity_dirs,
    find_example_coverage_gaps,
    load_wrapped_example,
)


def test_count_helpers_create_and_update_counters() -> None:
    """Check that the counter helpers create and accumulate totals correctly."""
    counts = empty_counts(BASIC_COUNT_KEYS)
    add_counts(counts, {"total_files": 2, "script_errors": 1}, BASIC_COUNT_KEYS)

    assert counts["total_files"] == 2
    assert counts["script_errors"] == 1
    assert counts["validation_passed"] == 0


def test_find_example_coverage_gaps_reports_missing_and_empty_dirs(tmp_path) -> None:
    """Check that missing and empty example directories are reported."""
    entity = tmp_path / "cohort"
    (entity / "schema.json").parent.mkdir(parents=True)
    (entity / "schema.json").write_text("{}", encoding="utf-8")
    (entity / "examples" / "valid").mkdir(parents=True)

    gaps = find_example_coverage_gaps([entity], ("valid", "invalid"))

    assert gaps == [{"entity": "cohort", "missing": ["invalid"], "empty": ["valid"]}]
    assert coverage_gaps_for_entity_category(gaps, "cohort", "valid") == gaps
    assert coverage_gaps_for_entity_category(gaps, "cohort", "invalid") == gaps
    assert coverage_gaps_for_entity_category(gaps, "cohort", "other") == []


def test_find_entity_dirs_and_load_wrapped_example(tmp_path) -> None:
    """Check entity discovery and loading of wrapped example documents."""
    entity = tmp_path / "dataset"
    entity.mkdir()
    (entity / "schema.json").write_text("{}", encoding="utf-8")
    example = tmp_path / "example.json"
    example.write_text(
        json.dumps({"schema": {"$ref": "schema.json"}, "data": {"@type": "x"}}),
        encoding="utf-8",
    )

    assert find_entity_dirs(tmp_path, None) == [entity]
    assert find_entity_dirs(tmp_path, "dataset", require_schema=True) == [entity]
    assert load_wrapped_example(example)["data"] == {"@type": "x"}
