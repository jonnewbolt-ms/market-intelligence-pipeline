from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

from market_intelligence.configuration import Bundle, safe_path
from market_intelligence.models import Evidence


def source_records(path: Path):
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError(f"Invalid CSV header: {path.name}")
            for row_number, row in enumerate(reader, 2):
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"Malformed CSV row: {path.name}:{row_number}")
                yield f"row {row_number}", json.dumps(row, ensure_ascii=True, sort_keys=True)
    elif path.suffix.lower() == ".json":
        rows = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(rows, list):
            raise ValueError(f"JSON source must be an array: {path.name}")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"JSON record must be an object: {path.name}[{index}]")
            yield f"item {index + 1}", json.dumps(row, ensure_ascii=True, sort_keys=True)
    elif path.suffix.lower() in (".md", ".txt"):
        text = path.read_text(encoding="utf-8-sig")
        for index, block in enumerate(re.split(r"\n\s*\n", text)):
            if block.strip():
                yield f"paragraph {index + 1}", block.strip()
    else:
        raise ValueError(f"Unsupported source format: {path.suffix}")


def ingest(bundle: Bundle) -> tuple[list[Evidence], list[str]]:
    records: list[Evidence] = []
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    total = 0
    duplicates = 0
    for source in bundle.scenario.sources:
        source_count = 0
        for location, text in source_records(safe_path(bundle.root, source.path)):
            source_count += 1
            total += 1
            if total > bundle.scenario.max_records:
                raise ValueError(
                    "Source record limit exceeded; split the scenario into smaller runs"
                )
            if len(text) > 6000:
                raise ValueError(f"Record exceeds 6000 characters: {source.path}, {location}")
            # Deduplicate within a source, retaining independent corroboration across sources.
            key = (source.path, text)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            digest = hashlib.sha256(f"{source.path}|{location}|{text}".encode()).hexdigest()[:16]
            records.append(
                Evidence(
                    id=f"ev-{digest}",
                    source=source.path,
                    kind=source.kind,
                    location=location,
                    text=text,
                )
            )
        if source_count == 0:
            raise ValueError(f"Source contains no records: {source.path}")
    if not records:
        raise ValueError("No input evidence found")
    if duplicates:
        warnings.append(f"Removed {duplicates} exact duplicate records within their source.")
    if any(record.kind == "social" for record in records):
        warnings.append("Social exports are a selected sample, not representative purchase intent.")
    if bundle.scenario.synthetic:
        warnings.append("All scenario data is synthetic; no real market conclusions may be drawn.")
    return records, warnings
