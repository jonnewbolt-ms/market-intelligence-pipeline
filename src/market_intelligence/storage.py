from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from market_intelligence.configuration import Bundle, load_bundle
from market_intelligence.models import RunConfig


def now() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=True), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS runs "
                "(id TEXT PRIMARY KEY, created_at TEXT, status TEXT, scenario TEXT, mode TEXT)"
            )

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.root / "index.sqlite3", timeout=30)) as connection:
            with connection:
                yield connection

    def path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{16}", run_id):
            raise ValueError("Invalid run ID")
        path = self.root / run_id
        if not path.is_dir():
            raise ValueError(f"Run not found: {run_id}")
        return path

    def create(self, bundle: Bundle, config: RunConfig) -> dict:
        run_id = uuid.uuid4().hex[:16]
        path = self.root / run_id
        path.mkdir()
        snapshot = path / "snapshot"
        for relative, text in bundle.files.items():
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        manifest = {
            "id": run_id,
            "created_at": now(),
            "scenario": bundle.scenario.name,
            "question": bundle.scenario.question,
            "synthetic": bundle.scenario.synthetic,
            "fingerprint": bundle.fingerprint,
            "config": config.model_dump(),
            "status": "pending",
            "completed_phases": [],
            "active_phase": None,
            "error": None,
            "metrics": [],
            "attempts": [],
            "wall_seconds": 0.0,
        }
        self.save(manifest)
        return manifest

    def save(self, manifest: dict) -> None:
        write_json(self.path(manifest["id"]) / "manifest.json", manifest)
        with self.connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?)",
                (
                    manifest["id"],
                    manifest["created_at"],
                    manifest["status"],
                    manifest["scenario"],
                    manifest["config"]["mode"],
                ),
            )

    def load(self, run_id: str) -> dict:
        return read_json(self.path(run_id) / "manifest.json")

    def snapshot(self, manifest: dict) -> Bundle:
        bundle = load_bundle(self.path(manifest["id"]) / "snapshot")
        if bundle.fingerprint != manifest["fingerprint"]:
            raise ValueError(
                "Run snapshot was modified; start a new run rather than mixing evidence"
            )
        return bundle

    def list(self) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute("SELECT id FROM runs ORDER BY created_at DESC").fetchall()
        return [self.load(row[0]) for row in rows]
