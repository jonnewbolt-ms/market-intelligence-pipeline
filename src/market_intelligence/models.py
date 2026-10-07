from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Phase = Literal["inputs", "business", "outputs"]
Mode = Literal["live", "demo"]
ROLES = ("inputs", "consumer", "commercial", "product", "synthesis", "outputs")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Evidence(Contract):
    id: str
    source: str
    kind: Literal["research", "internal", "social"]
    location: str
    text: str


class Signal(Contract):
    evidence_id: str
    observation: str = Field(min_length=1, max_length=1800)
    quote: str = Field(min_length=1, max_length=600)
    limitations: list[str]


class SignalBatch(Contract):
    signals: list[Signal] = Field(min_length=1)


class Finding(Contract):
    title: str = Field(min_length=1)
    interpretation: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    uncertainties: list[str]


class Findings(Contract):
    findings: list[Finding] = Field(min_length=1)
    conflicts: list[str]
    missing_data: list[str]


class Option(Contract):
    name: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    finding_ids: list[str] = Field(min_length=1)
    packaging: Literal["standard_can", "specialty_bottle"]
    consumer_fit: int = Field(ge=1, le=5)
    commercial_fit: int = Field(ge=1, le=5)
    feasibility: int = Field(ge=1, le=5)
    risks: list[str]
    next_action: str
    success_criteria: list[str] = Field(min_length=1)
    stop_criteria: list[str] = Field(min_length=1)


class Decision(Contract):
    headline: str
    options: list[Option] = Field(min_length=2, max_length=5)
    open_questions: list[str]


class Guardrails(Contract):
    specialty_packaging_allowed: bool
    minimum_margin_pct: float = Field(ge=0, le=100)
    consumer_weight: float = Field(ge=0)
    commercial_weight: float = Field(ge=0)
    feasibility_weight: float = Field(ge=0)


class Source(Contract):
    path: str
    kind: Literal["research", "internal", "social"]


class Scenario(Contract):
    name: str
    question: str
    synthetic: bool
    default_model: str
    sources: list[Source] = Field(min_length=1)
    batch_size: int = Field(default=8, ge=1, le=30)
    max_records: int = Field(default=10000, ge=1, le=100000)
    expert_evidence_limit: int = Field(default=60, ge=1, le=200)


class SkillMeta(Contract):
    name: str
    phase: Phase
    role: str
    version: int = Field(ge=1)
    knowledge: list[str]
    query_terms: list[str] = Field(default_factory=list)


class RunConfig(Contract):
    mode: Mode = "demo"
    model: str = "gpt-5-mini"
    overrides: dict[str, str] = Field(default_factory=dict)
    concurrency: int = Field(default=3, ge=1, le=8)
    timeout: int = Field(default=180, ge=10, le=1800)

    def model_for(self, role: str) -> str:
        return self.overrides.get(role, self.model)


class CallMetric(Contract):
    call_id: str | None = None
    role: str
    model: str
    effective_models: list[str] = Field(default_factory=list)
    session_id: str | None = None
    elapsed_seconds: float
    first_token_seconds: float | None = None
    input_tokens: float | None = None
    output_tokens: float | None = None
    error: str | None = None
