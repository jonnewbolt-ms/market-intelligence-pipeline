from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import perf_counter
from typing import TypeVar

from pydantic import BaseModel

from market_intelligence.configuration import load_bundle
from market_intelligence.ingestion import ingest
from market_intelligence.models import (
    ROLES,
    Decision,
    Evidence,
    Findings,
    Guardrails,
    Phase,
    RunConfig,
    Signal,
    SignalBatch,
)
from market_intelligence.providers import CopilotProvider, DemoProvider
from market_intelligence.storage import Store, now, read_json, write_json

T = TypeVar("T", bound=BaseModel)
PHASES = ("inputs", "business", "outputs")


def describe_error(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(describe_error(nested) for nested in error.exceptions)
    return f"{type(error).__name__}: {error}"


def validate_signals(batch: SignalBatch, evidence: list[Evidence]) -> None:
    by_id = {record.id: record for record in evidence}
    ids = [signal.evidence_id for signal in batch.signals]
    if len(ids) != len(set(ids)) or set(ids) != set(by_id):
        raise ValueError("Extraction must return exactly one signal for each supplied evidence ID")
    for signal in batch.signals:
        if signal.quote not in by_id[signal.evidence_id].text:
            raise ValueError(f"Unverifiable verbatim quote for {signal.evidence_id}")


def validate_findings(report: Findings, allowed: set[str]) -> None:
    for finding in report.findings:
        if not set(finding.evidence_ids) <= allowed:
            raise ValueError(f"Finding cites unknown evidence: {finding.title}")


def historical_margins(evidence: list[Evidence]) -> list[dict]:
    margins = []
    for record in evidence:
        if record.kind != "internal" or not record.source.endswith(".csv"):
            continue
        row = json.loads(record.text)
        if not {"revenue_usd", "cost_usd"} <= row.keys():
            continue
        try:
            revenue, cost = Decimal(row["revenue_usd"]), Decimal(row["cost_usd"])
        except InvalidOperation as exc:
            raise ValueError(f"Invalid monetary value in {record.id}") from exc
        if not revenue.is_finite() or not cost.is_finite() or revenue <= 0 or cost < 0:
            raise ValueError(f"Revenue must be positive and cost nonnegative in {record.id}")
        margins.append(
            {
                "evidence_id": record.id,
                "sku": row.get("sku"),
                "period": row.get("period"),
                "historical_margin_pct": float((revenue - cost) / revenue * 100),
                "new_product_forecast": False,
            }
        )
    return margins


def select_evidence(
    evidence: list[Evidence],
    signals: list[Signal],
    terms: list[str],
    limit: int,
) -> list[Evidence]:
    signal_sizes = {signal.evidence_id: len(signal.model_dump_json()) for signal in signals}
    ordered = sorted(
        evidence,
        key=lambda record: -sum(record.text.lower().count(term.lower()) for term in terms),
    )
    selected = []
    size = 0
    for record in ordered:
        record_size = len(record.model_dump_json()) + signal_sizes[record.id]
        if size + record_size > 40000:
            continue
        selected.append(record)
        size += record_size
        if len(selected) >= limit:
            break
    if not selected:
        raise ValueError("No evidence fits the expert context budget")
    return selected


def rank_decision(decision: Decision, synthesis: list[dict], guardrails: Guardrails) -> dict:
    ids = {finding["id"] for finding in synthesis}
    if len({option.name for option in decision.options}) != len(decision.options):
        raise ValueError("Decision alternatives must have distinct names")
    rows = []
    denominator = sum(
        (guardrails.consumer_weight, guardrails.commercial_weight, guardrails.feasibility_weight)
    )
    if denominator <= 0:
        raise ValueError("Decision weights must have a positive total")
    for option in decision.options:
        if not set(option.finding_ids) <= ids:
            raise ValueError(f"Option cites unknown finding IDs: {option.name}")
        eligible = guardrails.specialty_packaging_allowed or option.packaging == "standard_can"
        score = (
            option.consumer_fit * guardrails.consumer_weight
            + option.commercial_fit * guardrails.commercial_weight
            + option.feasibility * guardrails.feasibility_weight
        ) / denominator
        rows.append(
            {
                **option.model_dump(),
                "weighted_score": round(score, 3),
                "eligible": eligible,
                "blocked_reason": None
                if eligible
                else "Specialty packaging is prohibited by policy.",
                "authorization": "Human review required; proposed-product margin is unknown.",
                "minimum_margin_pct": guardrails.minimum_margin_pct,
            }
        )
    rows.sort(key=lambda row: (not row["eligible"], -row["weighted_score"], row["name"]))
    eligible = [row for row in rows if row["eligible"]]
    return {
        "headline": decision.headline,
        "recommended": eligible[0]["name"] if eligible else None,
        "status": "review_required" if eligible else "blocked",
        "options": rows,
        "open_questions": decision.open_questions,
        "guardrails": guardrails.model_dump(),
        "score_note": "Subjective 1-5 fit scores, weighted by policy; not probabilities.",
    }


def brief_markdown(manifest: dict, outputs: dict, business: dict) -> str:
    mode = (
        "DETERMINISTIC DEMO - not AI"
        if manifest["config"]["mode"] == "demo"
        else "LIVE COPILOT SDK"
    )
    lines = [
        f"# {manifest['scenario']}",
        "",
        f"**{mode}**",
        f"**Data:** {'Synthetic' if manifest['synthetic'] else 'User-supplied'}",
        f"**Question:** {manifest['question']}",
        "",
        f"## {outputs['headline']}",
        "",
        f"**Recommended for review:** {outputs['recommended'] or 'None - all options blocked'}",
        "**Authorization:** No spending or launch is authorized by this brief.",
        "",
    ]
    for option in outputs["options"]:
        lines.extend(
            [
                f"### {option['name']}",
                f"Score: {option['weighted_score']}/5 | Eligible: {option['eligible']}",
                option["rationale"],
                f"Policy: {option['blocked_reason'] or option['authorization']}",
                f"Finding references: {', '.join(option['finding_ids'])}",
                f"Next action: {option['next_action']}",
                "Success criteria: " + "; ".join(option["success_criteria"]),
                "Stop criteria: " + "; ".join(option["stop_criteria"]),
                "Risks: " + "; ".join(option["risks"]),
                "",
            ]
        )
    lines.extend(["## Evidence-backed synthesis", ""])
    for finding in business["synthesis"]:
        lines.extend(
            [
                f"### {finding['id']}: {finding['title']}",
                finding["interpretation"],
                f"Evidence: {', '.join(finding['evidence_ids'])}",
                "",
            ]
        )
    lines.extend(
        [
            "## Unresolved questions",
            *[f"- {question}" for question in outputs["open_questions"]],
            "",
            "## Disagreements",
            *[f"- {conflict}" for conflict in business["conflicts"]],
            "",
            "## Limitations",
            "Reference and quote validation checks provenance, not the truth of an interpretation.",
            "See inputs.json for original source records and exact quotes.",
        ]
    )
    return "\n".join(lines) + "\n"


class Pipeline:
    def __init__(
        self,
        store: Store,
        progress: Callable[[str], None] | None = None,
        provider_factory=None,
    ):
        self.store = store
        self.progress = progress or (lambda _message: None)
        self.provider_factory = provider_factory

    async def run(
        self,
        scenario: Path,
        config: RunConfig,
        until: Phase = "outputs",
    ) -> dict:
        unknown = set(config.overrides) - set(ROLES)
        if unknown:
            raise ValueError(f"Unknown model override roles: {sorted(unknown)}")
        if not config.model.strip() or any(
            not model.strip() for model in config.overrides.values()
        ):
            raise ValueError("Model IDs must not be empty")
        bundle = load_bundle(scenario)
        if config.mode == "demo" and not bundle.scenario.synthetic:
            raise ValueError("Deterministic demo mode only accepts explicitly synthetic scenarios")
        manifest = self.store.create(bundle, config)
        return await self.resume(manifest["id"], until)

    async def resume(self, run_id: str, until: Phase = "outputs") -> dict:
        path = self.store.path(run_id)
        lock = path / "execution.lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(
                f"Run {run_id} is already executing. If its process crashed, verify it is "
                "stopped before removing that run's execution.lock."
            ) from exc
        os.close(descriptor)
        manifest = self.store.load(run_id)
        started = perf_counter()
        attempt = {"started_at": now(), "until": until}
        provider = None
        attempted = False
        try:
            bundle = self.store.snapshot(manifest)
            config = RunConfig.model_validate(manifest["config"])
            remaining = [
                phase
                for phase in PHASES[: PHASES.index(until) + 1]
                if phase not in manifest["completed_phases"]
            ]
            if not remaining:
                return manifest
            manifest.update(status="running", error=None)
            manifest["attempts"].append(attempt)
            attempted = True
            self.store.save(manifest)
            if self.provider_factory:
                provider = self.provider_factory()
            elif config.mode == "demo":
                provider = DemoProvider()
            else:
                provider = CopilotProvider(self.store.root / ".copilot-runtime")
            semaphore = asyncio.Semaphore(config.concurrency)
            async with provider:
                async with asyncio.timeout(config.timeout):
                    await provider.validate_models({config.model, *config.overrides.values()})

                async def call(role: str, payload: dict, response_type: type[T]) -> T:
                    call_id = f"{role}-{uuid.uuid4().hex[:10]}"
                    request = {
                        "role": role,
                        "requested_model": config.model_for(role),
                        "instructions": bundle.instructions(role),
                        "payload": payload,
                        "response_schema": response_type.model_json_schema(),
                    }
                    write_json(path / "calls" / f"{call_id}.request.json", request)
                    async with semaphore:
                        label = config.model_for(role) if config.mode == "live" else "demo rules"
                        self.progress(f"Running {role} ({label})")
                        try:
                            async with asyncio.timeout(config.timeout):
                                response = await provider.generate(
                                    call_id,
                                    role,
                                    request["instructions"],
                                    payload,
                                    response_type,
                                    config.model_for(role),
                                    config.timeout,
                                )
                            write_json(
                                path / "calls" / f"{call_id}.response.json", response.model_dump()
                            )
                            return response
                        except Exception as exc:
                            write_json(
                                path / "calls" / f"{call_id}.error.json",
                                {"error": describe_error(exc), "role": role},
                            )
                            raise
                        finally:
                            if call_id in provider.last_responses:
                                write_json(
                                    path / "calls" / f"{call_id}.raw.json",
                                    {"content": provider.last_responses[call_id]},
                                )

                for phase in remaining:
                    manifest["active_phase"] = phase
                    self.store.save(manifest)
                    self.progress(f"Phase: {phase}")
                    if phase == "inputs":
                        evidence, warnings = ingest(bundle)
                        tasks = []
                        async with asyncio.TaskGroup() as group:
                            for offset in range(0, len(evidence), bundle.scenario.batch_size):
                                batch = evidence[offset : offset + bundle.scenario.batch_size]
                                tasks.append(
                                    (
                                        batch,
                                        group.create_task(
                                            call(
                                                "inputs",
                                                {
                                                    "question": bundle.scenario.question,
                                                    "evidence": [
                                                        record.model_dump() for record in batch
                                                    ],
                                                },
                                                SignalBatch,
                                            )
                                        ),
                                    )
                                )
                        signals = []
                        for batch, task in tasks:
                            result = task.result()
                            validate_signals(result, batch)
                            signals.extend(signal.model_dump() for signal in result.signals)
                        result = {
                            "evidence": [record.model_dump() for record in evidence],
                            "signals": signals,
                            "warnings": warnings,
                            "historical_margins": historical_margins(evidence),
                        }
                    elif phase == "business":
                        inputs = read_json(path / "inputs.json")
                        evidence = [Evidence.model_validate(row) for row in inputs["evidence"]]
                        signals = [Signal.model_validate(row) for row in inputs["signals"]]
                        tasks = {}
                        coverage = {}
                        async with asyncio.TaskGroup() as group:
                            for role in ("consumer", "commercial", "product"):
                                selected = select_evidence(
                                    evidence,
                                    signals,
                                    bundle.skills[role].meta.query_terms,
                                    bundle.scenario.expert_evidence_limit,
                                )
                                selected_ids = {record.id for record in selected}
                                coverage[role] = {
                                    "selected_ids": sorted(selected_ids),
                                    "selected": len(selected),
                                    "total": len(evidence),
                                    "omitted": len(evidence) - len(selected),
                                }
                                tasks[role] = group.create_task(
                                    call(
                                        role,
                                        {
                                            "question": bundle.scenario.question,
                                            "evidence": [
                                                record.model_dump() for record in selected
                                            ],
                                            "signals": [
                                                signal.model_dump()
                                                for signal in signals
                                                if signal.evidence_id in selected_ids
                                            ],
                                            "historical_margins": [
                                                row
                                                for row in inputs["historical_margins"]
                                                if row["evidence_id"] in selected_ids
                                            ],
                                            "coverage": coverage[role],
                                        },
                                        Findings,
                                    )
                                )
                        reports = {}
                        cited: set[str] = set()
                        for role, task in tasks.items():
                            report = task.result()
                            validate_findings(report, set(coverage[role]["selected_ids"]))
                            reports[role] = report.model_dump()
                            cited.update(
                                eid for finding in report.findings for eid in finding.evidence_ids
                            )
                        synthesis = await call(
                            "synthesis",
                            {
                                "question": bundle.scenario.question,
                                "reports": reports,
                            },
                            Findings,
                        )
                        validate_findings(synthesis, cited)
                        result = {
                            "experts": reports,
                            "coverage": coverage,
                            "synthesis": [
                                {"id": f"finding-{index}", **finding.model_dump()}
                                for index, finding in enumerate(synthesis.findings, 1)
                            ],
                            "conflicts": synthesis.conflicts,
                            "missing_data": synthesis.missing_data,
                        }
                    else:
                        business = read_json(path / "business.json")
                        decision = await call(
                            "outputs",
                            {
                                "question": bundle.scenario.question,
                                "findings": business["synthesis"],
                                "conflicts": business["conflicts"],
                                "missing_data": business["missing_data"],
                                "guardrails": bundle.guardrails.model_dump(),
                            },
                            Decision,
                        )
                        result = rank_decision(decision, business["synthesis"], bundle.guardrails)
                        (path / "brief.md").write_text(
                            brief_markdown(manifest, result, business), encoding="utf-8"
                        )
                    write_json(path / f"{phase}.json", result)
                    manifest["completed_phases"].append(phase)
                    self.store.save(manifest)
            manifest["status"] = (
                "completed" if "outputs" in manifest["completed_phases"] else "partial"
            )
            manifest["active_phase"] = None
            return manifest
        except Exception as exc:
            manifest["status"] = "failed"
            manifest["error"] = describe_error(exc)
            raise
        finally:
            if manifest["status"] == "running":
                manifest["status"] = "interrupted"
                manifest["error"] = "Execution interrupted; completed phases can be resumed."
            if provider is not None:
                manifest["metrics"].extend(metric.model_dump() for metric in provider.metrics)
            if attempted:
                elapsed = perf_counter() - started
                manifest["wall_seconds"] += elapsed
                attempt.update(
                    finished_at=now(), elapsed_seconds=elapsed, status=manifest["status"]
                )
            try:
                self.store.save(manifest)
            finally:
                lock.unlink()
