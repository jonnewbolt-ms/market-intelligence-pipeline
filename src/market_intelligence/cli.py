from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import typer

from market_intelligence.comparison import benchmark_summary, compare, summarize
from market_intelligence.configuration import load_bundle
from market_intelligence.models import Mode, Phase, RunConfig
from market_intelligence.pipeline import Pipeline
from market_intelligence.providers import CopilotProvider
from market_intelligence.storage import Store, write_json

app = typer.Typer(
    no_args_is_help=True, help="Northstar: evidence to decisions with the Copilot SDK."
)
DEFAULT_SCENARIO = Path("scenarios") / "functional-beverage"


def emit(value) -> None:
    typer.echo(json.dumps(value, indent=2, ensure_ascii=True))


def execute(awaitable):
    try:
        return asyncio.run(awaitable)
    except Exception as exc:
        typer.echo(f"ERROR: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from exc


def overrides(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        role, separator, model = value.partition("=")
        if not separator or not role or not model:
            raise typer.BadParameter("Overrides must be ROLE=MODEL")
        if role in result:
            raise typer.BadParameter(f"Duplicate override for {role}")
        result[role] = model
    return result


@app.command()
def run(
    scenario: Path = typer.Option(DEFAULT_SCENARIO, exists=True, file_okay=False),
    mode: Mode = typer.Option("demo", help="demo is deterministic; live calls Copilot."),
    model: str | None = typer.Option(None, help="Exact ID from mip models."),
    agent_model: list[str] = typer.Option([], help="Repeat ROLE=MODEL for expert overrides."),
    phase: Phase = typer.Option("outputs", help="Stop after this phase, including prerequisites."),
    concurrency: int = typer.Option(3, min=1, max=8),
    timeout: int = typer.Option(180, min=10, max=1800),
    runs: Path = typer.Option(Path("runs")),
):
    """Run a scenario and persist all intermediate evidence and decisions."""
    bundle = load_bundle(scenario)
    config = RunConfig(
        mode=mode,
        model=model or bundle.scenario.default_model,
        overrides=overrides(agent_model),
        concurrency=concurrency,
        timeout=timeout,
    )
    store = Store(runs)
    result = execute(
        Pipeline(store, lambda text: typer.echo(text, err=True)).run(scenario, config, phase)
    )
    emit(summarize(store, result["id"]))
    typer.echo(f"Artifacts: {store.path(result['id'])}", err=True)


@app.command()
def resume(
    run_id: str = typer.Option(...),
    phase: Phase = typer.Option("outputs"),
    runs: Path = typer.Option(Path("runs")),
):
    """Resume from completed phase boundaries using immutable run snapshots."""
    store = Store(runs)
    result = execute(Pipeline(store, lambda text: typer.echo(text, err=True)).resume(run_id, phase))
    emit(summarize(store, result["id"]))


@app.command("models")
def models_command(runs: Path = typer.Option(Path("runs"))):
    """Discover model IDs and policy/capability metadata for this Copilot account."""

    async def discover():
        async with CopilotProvider(runs / ".copilot-runtime") as provider:
            async with asyncio.timeout(90):
                return await provider.models()

    emit(execute(discover()))


@app.command("list")
def list_command(runs: Path = typer.Option(Path("runs"))):
    """List persisted runs, including failed attempts."""
    store = Store(runs)
    emit([summarize(store, run["id"]) for run in store.list()])


@app.command("compare")
def compare_command(
    baseline: str = typer.Option(...),
    candidate: str = typer.Option(...),
    runs: Path = typer.Option(Path("runs")),
):
    """Compare results and expose differences that invalidate speed comparisons."""
    emit(compare(Store(runs), baseline, candidate))


@app.command()
def benchmark(
    models: list[str] = typer.Option(..., "--model", help="Repeat for each exact model ID."),
    repeat: int = typer.Option(1, min=1, max=10),
    scenario: Path = typer.Option(DEFAULT_SCENARIO, exists=True, file_okay=False),
    concurrency: int = typer.Option(3, min=1, max=8),
    timeout: int = typer.Option(180, min=10, max=1800),
    runs: Path = typer.Option(Path("runs")),
):
    """Run fresh LIVE trials on one frozen scenario. Consumes Copilot usage."""
    if len(set(models)) < 2 or len(models) != len(set(models)):
        raise typer.BadParameter("Supply at least two distinct --model IDs, without duplicates.")
    store = Store(runs)
    bundle = load_bundle(scenario)
    report_path = store.root / f"benchmark-{uuid.uuid4().hex[:12]}.json"

    async def trials():
        rows = []
        frozen_scenario = None
        for repetition in range(repeat):
            order = models if repetition % 2 == 0 else list(reversed(models))
            for model in order:
                frozen = load_bundle(frozen_scenario) if frozen_scenario else bundle
                config = RunConfig(
                    mode="live", model=model, concurrency=concurrency, timeout=timeout
                )
                manifest = store.create(frozen, config)
                frozen_scenario = store.path(manifest["id"]) / "snapshot"
                typer.echo(f"Trial {repetition + 1}: {model}, run {manifest['id']}", err=True)
                try:
                    await Pipeline(store).resume(manifest["id"])
                except Exception as exc:
                    typer.echo(f"Trial failed: {type(exc).__name__}: {exc}", err=True)
                rows.append(summarize(store, manifest["id"]))
                write_json(
                    report_path,
                    {
                        "trials": rows,
                        "summary": benchmark_summary(rows),
                        "note": "Fresh sequential trials; order reversed every repetition. "
                        "Network/cache conditions uncontrolled. Capability requires human review.",
                    },
                )
        return rows

    rows = execute(trials())
    emit(benchmark_summary(rows))
    typer.echo(f"Benchmark saved: {report_path}", err=True)
    if any(row["status"] != "completed" for row in rows):
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
