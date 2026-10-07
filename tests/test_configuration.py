import pytest

from market_intelligence.configuration import frontmatter, load_bundle, safe_path
from market_intelligence.editing import save_markdown
from market_intelligence.ingestion import ingest


def test_path_traversal_is_refused(scenario):
    with pytest.raises(ValueError, match="escapes"):
        safe_path(scenario, "../outside.txt")


def test_frontmatter_errors_are_explicit():
    with pytest.raises(ValueError, match="requires YAML"):
        frontmatter("# no metadata")
    with pytest.raises(ValueError, match="Unterminated"):
        frontmatter("---\nname: bad")


def test_edit_validates_entire_scenario_before_save(scenario):
    relative = str(
        next((scenario / "skills" / "business" / "consumer").glob("SKILL.md")).relative_to(scenario)
    )
    target = scenario / relative
    original = target.read_text()
    with pytest.raises(ValueError, match="Missing scenario file"):
        save_markdown(
            scenario, relative, original, original.replace("brand-strategy.md", "absent.md")
        )
    assert target.read_text() == original


def test_edit_detects_conflict(scenario):
    relative = str(
        next((scenario / "skills" / "business" / "consumer").glob("SKILL.md")).relative_to(scenario)
    )
    target = scenario / relative
    original = target.read_text()
    target.write_text(original + "\nConcurrent edit.")
    with pytest.raises(ValueError, match="changed since"):
        save_markdown(scenario, relative, original, original + "\nMy edit.")


def test_guardrail_weights_must_be_positive(scenario):
    target = scenario / "knowledge" / "guardrails.md"
    original = target.read_text()
    replacement = original.replace("0.45", "0").replace("0.30", "0").replace("0.25", "0")
    with pytest.raises(ValueError, match="positive"):
        save_markdown(scenario, str(target.relative_to(scenario)), original, replacement)
    assert target.read_text() == original


def test_invalid_csv_and_record_limits(scenario):
    target = scenario / "inputs" / "sales.csv"
    target.write_text("a,b\n1,2,3\n")
    with pytest.raises(ValueError, match="Malformed CSV"):
        ingest(load_bundle(scenario))


def test_identical_social_records_are_deduplicated(scenario):
    target = scenario / "inputs" / "social.json"
    target.write_text('[{"text":"same"},{"text":"same"}]')
    evidence, warnings = ingest(load_bundle(scenario))
    assert len([record for record in evidence if record.kind == "social"]) == 1
    assert any("duplicate" in warning for warning in warnings)
