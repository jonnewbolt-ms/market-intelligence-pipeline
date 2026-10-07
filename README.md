# Northstar: signal to decision

A beverage-manufacturer demonstrator built with a **uv Python harness and the GitHub
Copilot SDK**. Three stages turn source evidence into expert interpretations, then
human-reviewable pilot decisions. Each stage is controlled by Markdown skills and
company knowledge.

## Start

From this folder in PowerShell:

```powershell
# This workspace has a local uv installation. If uv is already on PATH, skip this.
$env:Path = "$PWD\.tools\uv;$env:Path"
uv sync --locked
uv run streamlit run src\market_intelligence\app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Open http://localhost:8501. No cloud deployment or database server is required.

Dependencies resolve through the approved Microsoft proxy, configured in
`pyproject.toml`: `https://packagefeedproxy.microsoft.io/pypi/simple/`.
The SDK is pinned to **1.0.15**, a stable version available through that feed.
Do not replace the feed with a public fallback on managed devices. `uv.lock` is generated
from the approved feed and included for reproducible installs.

For a new checkout without uv, install uv through your approved software provisioning
process. Python 3.12 is selected by `.python-version`; uv can provision it.

## Two clearly separated execution modes

**Offline walkthrough** runs scripted Northstar narratives and genuine Python validation,
scoring, persistence, and policy gates. It makes no model calls and cannot measure model
speed or capability. Free-form instruction edits are not interpreted in this mode;
validated guardrail frontmatter still changes rankings and eligibility.

**Live Copilot SDK** creates isolated SDK sessions for signal extraction, three experts,
synthesis, and decision generation. All selected Markdown skill instructions and referenced
company knowledge are supplied to those sessions. Existing saved runs can be viewed again
without new model calls: this is replaying artifacts, not rerunning inference.

The supplied research, CSV sales, and social JSON are all **synthetic**. They describe a
fictional manufacturer and must not be presented as actual market research.

## Live authentication and models

Live runs require a Copilot-enabled account and model access. The SDK uses existing Copilot
authentication or a securely supplied `COPILOT_GITHUB_TOKEN` environment variable. Do not put
tokens in scenario files, source code, commands saved in documentation, or the UI.
Use your normal Copilot CLI sign-in flow if `mip models` reports an authentication problem.

The SDK provisions its matching runtime on first use. For a provisioned compatible runtime,
the SDK also supports `COPILOT_CLI_PATH`. Do not assume an arbitrary older CLI is compatible.

```powershell
uv run mip models
uv run mip run --mode live --model gpt-5-mini
uv run mip run --mode live --model "<MODEL_A>" --agent-model commercial="<MODEL_B>"
```

Use **Discover available models** in the sidebar, or `mip models`, to get exact model IDs,
policy availability, limits, and reasoning metadata for the signed-in account.
No model is silently substituted. The model used by this coding conversation does not select
the application's model.

The default run model can be edited in `scenario.yaml`. Overrides support
`inputs`, `consumer`, `commercial`, `product`, `synthesis`, and `outputs`.
Unspecified roles inherit the selected run model. The live UI requires an explicit
acknowledgment before sending scenario data to Copilot.

## CLI

```powershell
uv run mip run --mode demo
uv run mip run --scenario scenarios\functional-beverage --mode demo --phase inputs
uv run mip resume --run-id "<RUN_ID>"
uv run mip list
uv run mip compare --baseline "<BASELINE_ID>" --candidate "<CANDIDATE_ID>"

# Real live calls: consumes Copilot usage. Model IDs come from mip models.
uv run mip benchmark --model "<MODEL_A>" --model "<MODEL_B>" --repeat 3
```

`--phase` includes prerequisite stages and stops at the requested stage. Resume uses
the run's saved model configuration and **frozen** scenario, not edits made since the run.
Resume skips completed phases; it reruns an incomplete phase from the beginning, potentially
incurring additional usage. Start a new run to apply new skills, inputs, or models.

Concurrency defaults to three SDK sessions. Override it with `--concurrency`.
`--timeout` is a per-call limit in seconds, including session creation; runtime startup has
a separate 90-second limit. Errors and malformed model outputs fail the stage explicitly.
There is no automatic fallback from live mode to demo mode.

## Walkthrough for a customer conversation

1. Select **Offline walkthrough**, run all stages, and open the **Decision brief**.
2. Trace a recommendation back through synthesis, expert findings, and verbatim evidence.
3. Open **Skills & knowledge**, select `knowledge\guardrails.md`, and change
   `specialty_packaging_allowed: true` to `false`. Validate and save.
4. Create a new offline run. The specialty-bottle option is now blocked; the standard-can
   pilot becomes the eligible recommendation. Compare the two saved runs.
5. Switch to live mode, discover models, and run the same scenario with two different models.
   Compare latency and the quality of their reasoning. Live conclusions can differ from
   the scripted walkthrough; the manufacturing rule cannot be bypassed.

The three specialists are **consumer/market**, **commercial**, and **product/brand**.
Synthesis preserves disagreements rather than forcing agreement. The decision stage
proposes options; Python applies weighted scoring and hard manufacturing constraints.
All outputs require human review. Unknown new-product margin remains an unresolved gate.

## Scenario configuration

```text
scenarios\
  functional-beverage\
    scenario.yaml
    inputs\
      market-research.md
      sales.csv
      social.json
    skills\
      inputs\signal-extraction\SKILL.md
      business\consumer\SKILL.md
      business\commercial\SKILL.md
      business\product\SKILL.md
      business\synthesis\SKILL.md
      outputs\decision-brief\SKILL.md
    knowledge\
      guardrails.md
      brand-strategy.md
      launch-lessons.md
```

Copy the scenario directory to create a new scenario. Update `scenario.yaml` with its
question, synthetic-data flag, model, sources, and processing limits. The UI discovers
folders containing `scenario.yaml`. Use live mode for new business scenarios: demo mode
contains Northstar-specific scripted interpretations.

Each `SKILL.md` requires YAML frontmatter: `name`, `phase`, `role`, `version`, `knowledge`,
and optional `query_terms`. Exactly one skill must exist for each supported role.
The body describes how to reason. Referenced knowledge files resolve under `knowledge`.
The harness deliberately injects these instructions rather than enabling ambient CLI skills,
plugins, or repository instructions.

`guardrails.md` is both readable policy and validated data. Python enforces its
packaging eligibility, positive score weights, and margin-floor range. Historical gross
margins are calculated from CSV revenue and cost; they are **not** forecasts for new products.
Subjective option scores are not probabilities or empirically measured demand.

## Data handling and scale boundaries

Supported inputs: Markdown/plain-text paragraphs, CSV rows, and JSON arrays of objects.
Every record has a stable content/source/location-based evidence ID. Exact duplicates within
one source are removed; independent sources are retained. Quotes must be exact substrings of
their cited source. Signal extraction must cover every supplied record exactly once.
Findings and recommendations must reference IDs from their actual preceding stage.

Sources are limited to 10 MB each and 6,000 characters per record, with a configurable record
limit (10,000 by default). Extraction is batched with bounded active calls. Expert context
is selected deterministically using the skill's query terms, with a configured record limit
and a 40,000-character combined evidence/signal budget per expert. Every expert exposes its
selected IDs and omitted count. Truncation is not presented as exhaustive review.

This is a local batch demonstrator, not an internet-scale ingestion service. It has no
social-platform credentials, live connectors, PDF/OCR ingestion, distributed queue, or
cross-run extraction cache. No source is fetched automatically from the internet.

## Saved artifacts and comparisons

`runs\<RUN_ID>\` contains:

- `manifest.json`: model settings, status, fingerprint, timing, usage, and attempts.
- `snapshot\`: exact scenario inputs, knowledge, and skills used.
- `inputs.json`, `business.json`, `outputs.json`: typed stage results.
- `calls\`: each request, schema, response, raw final answer, and call error when applicable.
- `brief.md`: a portable decision brief with evidence references.

SQLite indexes the runs; the JSON artifacts remain readable without the UI. A modified
snapshot is rejected on resume. Only one process may execute a given run at a time.
If a process is forcibly killed, its `execution.lock` can remain. Confirm the process has
stopped before removing that specific lock and resuming.

Per-call telemetry records the requested model, effective model when reported, SDK session
ID, elapsed time, first visible output latency, and input/output tokens when provided.
Missing usage stays unknown. First visible output latency includes session setup; it is not
pure provider time-to-first-token. Summed concurrent call times are not pipeline wall time.

Benchmark trials use fresh sessions on a frozen scenario, run sequentially by model, and
reverse order every repetition. Reports persist under `runs\benchmark-*.json`.
Comparisons warn when data, instructions, concurrency, timeouts, execution mode, completeness,
or resume history make speed comparisons invalid. Provider cache state and load remain
uncontrolled. Use repeated trials, not one timing, for claims about speed.

Assess capability by inspecting grounding, handling of contradictions, feasibility, and
usefulness of the next action. More output or more findings is not a quality score.
Evidence-ID and quote validation establishes provenance, **not semantic truth**.

## Operational boundaries

SDK sessions have no tools, ambient configuration discovery, cross-session search, or
filesystem access. Permission requests are denied. Input documents cannot authorize actions.
No recommendation posts, purchases, launches, or changes manufacturing operations.

The UI is intended for a trusted local operator and has no multi-user authentication.
Bind it to loopback; do not expose it publicly. Local run artifacts and SDK runtime storage
may contain supplied business data and are excluded by `.gitignore`. Apply your organization's
data-handling policy before using real customer material or sharing artifacts.

## Development

```powershell
uv sync --locked --group dev
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

Tests exercise phase contracts, evidence validation, policy-driven decision changes,
snapshot integrity, resume/failure paths, model overrides, SDK session options, and UI
interaction. They use deterministic or stubbed providers and make no paid model calls.

## License

Copyright (c) 2026 Jon Newbolt and Microsoft Corporation.
Released under the [MIT License](LICENSE), including its warranty disclaimer and
limitation of liability. This demonstration is provided as-is, without support or
business, financial, medical, or regulatory advice. No Microsoft endorsement or
trademark rights are granted by the license. Third-party dependencies remain under
their respective licenses.
