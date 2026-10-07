from __future__ import annotations

from statistics import median

from market_intelligence.storage import Store, read_json


def summarize(store: Store, run_id: str) -> dict:
    manifest = store.load(run_id)
    outputs_path = store.path(run_id) / "outputs.json"
    business_path = store.path(run_id) / "business.json"
    outputs = read_json(outputs_path) if outputs_path.exists() else None
    business = read_json(business_path) if business_path.exists() else None
    metrics = manifest["metrics"]
    tokens = [metric["output_tokens"] for metric in metrics]
    return {
        "run_id": run_id,
        "mode": manifest["config"]["mode"],
        "model": manifest["config"]["model"],
        "overrides": manifest["config"]["overrides"],
        "status": manifest["status"],
        "fingerprint": manifest["fingerprint"],
        "wall_seconds": round(manifest["wall_seconds"], 3),
        "call_seconds": round(sum(metric["elapsed_seconds"] for metric in metrics), 3),
        "output_tokens": sum(tokens) if tokens and all(t is not None for t in tokens) else None,
        "recommendation": outputs["recommended"] if outputs else None,
        "finding_count": len(business["synthesis"]) if business else 0,
        "conflicts": len(business["conflicts"]) if business else 0,
        "evidence_coverage": business["coverage"] if business else {},
        "error": manifest["error"],
    }


def compare(store: Store, baseline: str, candidate: str) -> dict:
    left, right = summarize(store, baseline), summarize(store, candidate)
    manifests = [store.load(run_id) for run_id in (baseline, candidate)]
    reasons = []
    if left["fingerprint"] != right["fingerprint"]:
        reasons.append(
            "Inputs, skills, or knowledge changed; this is not a controlled model comparison."
        )
    if any(row["mode"] != "live" for row in (left, right)):
        reasons.append("Deterministic demo timings do not measure model performance.")
    if any(row["status"] != "completed" for row in (left, right)):
        reasons.append("At least one run is incomplete or failed.")
    if any(len(manifest["attempts"]) != 1 for manifest in manifests):
        reasons.append("Resumed runs include different work and are not comparable for speed.")
    for key in ("concurrency", "timeout"):
        if manifests[0]["config"][key] != manifests[1]["config"][key]:
            reasons.append(f"{key} differs between runs.")
    return {
        "baseline": left,
        "candidate": right,
        "controlled_inputs": left["fingerprint"] == right["fingerprint"],
        "speed_comparable": not reasons,
        "cautions": reasons
        + [
            "Latency includes SDK session setup; backend load and cache state are uncontrolled.",
            "More findings or longer output is not evidence of higher capability. "
            "Judge grounding, contradiction handling, feasibility, and usefulness side by side.",
        ],
    }


def benchmark_summary(rows: list[dict]) -> list[dict]:
    models = sorted({row["model"] for row in rows})
    return [
        {
            "model": model,
            "successful_runs": len(
                successes := [
                    row for row in rows if row["model"] == model and row["status"] == "completed"
                ]
            ),
            "failed_runs": sum(
                row["model"] == model and row["status"] != "completed" for row in rows
            ),
            "median_wall_seconds": median(row["wall_seconds"] for row in successes)
            if successes
            else None,
        }
        for model in models
    ]
