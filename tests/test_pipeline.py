import json

import pytest

from market_intelligence.comparison import compare
from market_intelligence.configuration import load_bundle
from market_intelligence.models import Decision, RunConfig, SignalBatch
from market_intelligence.pipeline import Pipeline, rank_decision, validate_signals
from market_intelligence.providers import DemoProvider
from market_intelligence.storage import read_json


async def test_end_to_end_persists_evidence_and_decisions(scenario, store):
    result = await Pipeline(store).run(scenario, RunConfig())
    path = store.path(result["id"])
    assert store.load(result["id"])["status"] == "completed"
    inputs = read_json(path / "inputs.json")
    business = read_json(path / "business.json")
    outputs = read_json(path / "outputs.json")
    assert len(inputs["evidence"]) == len(inputs["signals"]) == 16
    assert len(inputs["historical_margins"]) == 6
    assert inputs["historical_margins"][0]["historical_margin_pct"] == 40
    assert len(business["experts"]) == 3
    assert outputs["recommended"] == "Premium gym concept - specialty bottle"
    assert all(row["authorization"].startswith("Human review") for row in outputs["options"])
    assert len(result["metrics"]) == 7
    assert all(metric["output_tokens"] is None for metric in result["metrics"])
    assert len(list((path / "calls").glob("*.request.json"))) == 7
    assert "DETERMINISTIC DEMO" in (path / "brief.md").read_text()
    assert store.snapshot(result).fingerprint == result["fingerprint"]


async def test_markdown_constraint_changes_recommendation(scenario, store):
    baseline = await Pipeline(store).run(scenario, RunConfig())
    guardrails = scenario / "knowledge" / "guardrails.md"
    guardrails.write_text(
        guardrails.read_text().replace(
            "specialty_packaging_allowed: true", "specialty_packaging_allowed: false"
        )
    )
    candidate = await Pipeline(store).run(scenario, RunConfig())
    outputs = read_json(store.path(candidate["id"]) / "outputs.json")
    assert outputs["recommended"] == "Afternoon lime refreshment - convenience-store can"
    assert outputs["options"][1]["eligible"] is False
    assert baseline["fingerprint"] != candidate["fingerprint"]
    assert store.snapshot(baseline).guardrails.specialty_packaging_allowed is True
    comparison = compare(store, baseline["id"], candidate["id"])
    assert not comparison["controlled_inputs"]
    assert not comparison["speed_comparable"]


async def test_resume_reuses_only_complete_phases_and_frozen_skills(scenario, store):
    partial = await Pipeline(store).run(scenario, RunConfig(), "inputs")
    path = store.path(partial["id"])
    saved_inputs = (path / "inputs.json").read_bytes()
    source = scenario / "inputs" / "market-research.md"
    source.write_text("Changed source, not part of the original run.")
    complete = await Pipeline(store).resume(partial["id"])
    assert complete["status"] == "completed"
    assert saved_inputs == (path / "inputs.json").read_bytes()
    assert len(complete["metrics"]) == 7
    assert len(complete["attempts"]) == 2
    assert not (path / "execution.lock").exists()


async def test_tampered_snapshot_is_refused(scenario, store):
    partial = await Pipeline(store).run(scenario, RunConfig(), "inputs")
    path = store.path(partial["id"])
    (path / "snapshot" / "knowledge" / "brand-strategy.md").write_text("tampered")
    with pytest.raises(ValueError, match="snapshot was modified"):
        await Pipeline(store).resume(partial["id"])
    assert store.load(partial["id"])["status"] == "failed"
    assert not (path / "execution.lock").exists()


class FailingProvider(DemoProvider):
    async def generate(self, call_id, role, instructions, payload, response_type, model, timeout):
        if role == "outputs":
            raise RuntimeError("Deliberate model failure")
        return await super().generate(
            call_id, role, instructions, payload, response_type, model, timeout
        )


async def test_failure_is_persisted_and_resumable(scenario, store):
    with pytest.raises(RuntimeError, match="Deliberate"):
        await Pipeline(store, provider_factory=FailingProvider).run(scenario, RunConfig())
    failed = store.list()[0]
    assert failed["status"] == "failed"
    assert "Deliberate" in failed["error"]
    assert failed["completed_phases"] == ["inputs", "business"]
    assert not (store.path(failed["id"]) / "outputs.json").exists()
    recovered = await Pipeline(store).resume(failed["id"])
    assert recovered["status"] == "completed"


async def test_per_role_models_are_passed_to_sdk_boundary(scenario, store):
    calls = []

    class RecordingProvider(DemoProvider):
        async def generate(
            self, call_id, role, instructions, payload, response_type, model, timeout
        ):
            calls.append((role, model, instructions))
            return await super().generate(
                call_id, role, instructions, payload, response_type, model, timeout
            )

    await Pipeline(store, provider_factory=RecordingProvider).run(
        scenario, RunConfig(mode="live", model="family-a", overrides={"commercial": "family-b"})
    )
    assert [model for role, model, _ in calls if role == "commercial"] == ["family-b"]
    assert all(model == "family-a" for role, model, _ in calls if role != "commercial")
    assert any("Commercial expert" in text for _, _, text in calls)


async def test_unknown_override_fails_before_creating_run(scenario, store):
    with pytest.raises(ValueError, match="Unknown model override"):
        await Pipeline(store).run(scenario, RunConfig(overrides={"typo": "model"}))
    assert store.list() == []


async def test_execution_lock_blocks_parallel_resume(scenario, store):
    partial = await Pipeline(store).run(scenario, RunConfig(), "inputs")
    (store.path(partial["id"]) / "execution.lock").touch()
    with pytest.raises(RuntimeError, match="already executing"):
        await Pipeline(store).resume(partial["id"])


def test_invalid_quotes_and_missing_records_fail(scenario):
    from market_intelligence.ingestion import ingest

    evidence, _ = ingest(load_bundle(scenario))
    one = evidence[:1]
    batch = SignalBatch.model_validate(
        {
            "signals": [
                {
                    "evidence_id": one[0].id,
                    "observation": "Fake",
                    "quote": "This quote was fabricated",
                    "limitations": [],
                }
            ]
        }
    )
    with pytest.raises(ValueError, match="quote"):
        validate_signals(batch, one)
    batch.signals[0].quote = one[0].text[:10]
    with pytest.raises(ValueError, match="exactly one"):
        validate_signals(batch, evidence)


async def test_unknown_finding_reference_rejected(scenario, store):
    completed = await Pipeline(store).run(scenario, RunConfig())
    path = store.path(completed["id"])
    output_request = next((path / "calls").glob("outputs-*.response.json"))
    decision = Decision.model_validate(json.loads(output_request.read_text()))
    decision.options[0].finding_ids = ["fabricated"]
    with pytest.raises(ValueError, match="unknown finding"):
        rank_decision(
            decision,
            read_json(path / "business.json")["synthesis"],
            load_bundle(scenario).guardrails,
        )


async def test_retrieval_limit_is_explicit(scenario, store):
    config = scenario / "scenario.yaml"
    config.write_text(
        config.read_text().replace("expert_evidence_limit: 60", "expert_evidence_limit: 3")
    )
    result = await Pipeline(store).run(scenario, RunConfig())
    business = read_json(store.path(result["id"]) / "business.json")
    assert all(coverage["omitted"] == 13 for coverage in business["coverage"].values())
    assert all(coverage["selected"] == 3 for coverage in business["coverage"].values())


async def test_noop_resume_preserves_measurements(scenario, store):
    result = await Pipeline(store).run(scenario, RunConfig())
    resumed = await Pipeline(store).resume(result["id"])
    assert resumed["wall_seconds"] == result["wall_seconds"]
    assert resumed["attempts"] == result["attempts"]
    assert len(resumed["metrics"]) == 7


async def test_parallel_failure_preserves_underlying_error(scenario, store):
    class BrokenInputProvider(DemoProvider):
        async def generate(self, *args, **kwargs):
            raise RuntimeError("Actionable input failure")

    with pytest.raises(ExceptionGroup):
        await Pipeline(store, provider_factory=BrokenInputProvider).run(scenario, RunConfig())
    manifest = store.list()[0]
    assert "Actionable input failure" in manifest["error"]
    assert list((store.path(manifest["id"]) / "calls").glob("*.error.json"))


async def test_all_options_blocked_does_not_recommend(scenario, store):
    completed = await Pipeline(store).run(scenario, RunConfig())
    path = store.path(completed["id"])
    response_path = next((path / "calls").glob("outputs-*.response.json"))
    decision = Decision.model_validate(read_json(response_path))
    for option in decision.options:
        option.packaging = "specialty_bottle"
    guardrails = load_bundle(scenario).guardrails
    guardrails.specialty_packaging_allowed = False
    result = rank_decision(decision, read_json(path / "business.json")["synthesis"], guardrails)
    assert result["recommended"] is None
    assert result["status"] == "blocked"
