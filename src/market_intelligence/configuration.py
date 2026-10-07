from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from market_intelligence.models import ROLES, Guardrails, Scenario, SkillMeta


def safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes scenario directory: {relative}")
    if not path.is_file():
        raise ValueError(f"Missing scenario file: {relative}")
    return path


def frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("Markdown requires YAML frontmatter delimited by ---")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError("Unterminated YAML frontmatter") from exc
    metadata = yaml.safe_load("\n".join(lines[1:end]))
    if not isinstance(metadata, dict):
        raise ValueError("Frontmatter must be a mapping")
    body = "\n".join(lines[end + 1 :]).strip()
    if not body:
        raise ValueError("Markdown instructions must not be empty")
    return metadata, body


@dataclass(frozen=True)
class Skill:
    meta: SkillMeta
    body: str
    path: str


@dataclass(frozen=True)
class Bundle:
    root: Path
    scenario: Scenario
    skills: dict[str, Skill]
    knowledge: dict[str, str]
    guardrails: Guardrails
    files: dict[str, str]

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self.files, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()

    def instructions(self, role: str) -> str:
        skill = self.skills[role]
        documents = "\n\n".join(
            f"## Company knowledge: {name}\n{self.knowledge[name]}" for name in skill.meta.knowledge
        )
        return f"{skill.body}\n\n{documents}"


def load_bundle(root: Path) -> Bundle:
    root = root.resolve()
    config_file = safe_path(root, "scenario.yaml")
    scenario = Scenario.model_validate(yaml.safe_load(config_file.read_text(encoding="utf-8")))
    files = {"scenario.yaml": config_file.read_text(encoding="utf-8")}
    skills: dict[str, Skill] = {}
    knowledge: dict[str, str] = {}
    for path in sorted((root / "skills").rglob("SKILL.md")):
        relative = str(path.relative_to(root))
        text = safe_path(root, relative).read_text(encoding="utf-8")
        meta, body = frontmatter(text)
        parsed = SkillMeta.model_validate(meta)
        if parsed.role not in ROLES or parsed.role in skills:
            raise ValueError(f"Unknown or duplicate skill role: {parsed.role}")
        expected_phase = parsed.role if parsed.role in ("inputs", "outputs") else "business"
        if parsed.phase != expected_phase:
            raise ValueError(f"Wrong phase for skill {parsed.role}: {parsed.phase}")
        skills[parsed.role] = Skill(parsed, body, relative)
        files[relative] = text
        for name in parsed.knowledge:
            document = safe_path(root, f"knowledge/{name}")
            knowledge[name] = document.read_text(encoding="utf-8")
            files[str(document.relative_to(root))] = knowledge[name]
    if set(skills) != set(ROLES):
        raise ValueError(f"Scenario needs exactly these skill roles: {', '.join(ROLES)}")
    guardrail_path = safe_path(root, "knowledge/guardrails.md")
    guardrail_text = guardrail_path.read_text(encoding="utf-8")
    guardrail_data, _ = frontmatter(guardrail_text)
    guardrails = Guardrails.model_validate(guardrail_data)
    if (
        sum(
            (
                guardrails.consumer_weight,
                guardrails.commercial_weight,
                guardrails.feasibility_weight,
            )
        )
        <= 0
    ):
        raise ValueError("At least one decision weight must be positive")
    files[str(guardrail_path.relative_to(root))] = guardrail_text
    for source in scenario.sources:
        path = safe_path(root, source.path)
        if path.stat().st_size > 10_000_000:
            raise ValueError(f"Source exceeds the 10 MB demo limit: {source.path}")
        files[str(path.relative_to(root))] = path.read_text(encoding="utf-8-sig")
    return Bundle(root, scenario, skills, knowledge, guardrails, files)
