from __future__ import annotations

import asyncio
import json
from pathlib import Path

import streamlit as st

from market_intelligence.comparison import compare, summarize
from market_intelligence.configuration import load_bundle
from market_intelligence.editing import save_markdown
from market_intelligence.models import ROLES, RunConfig
from market_intelligence.pipeline import Pipeline
from market_intelligence.providers import CopilotProvider
from market_intelligence.storage import Store, read_json

ROOT = Path(__file__).resolve().parents[2]


def show_evidence(ids: list[str], records: dict, signals: dict) -> None:
    for evidence_id in ids:
        record = records[evidence_id]
        with st.expander(f"{evidence_id} | {record['source']} | {record['location']}"):
            st.caption(record["kind"].upper())
            st.text(record["text"])
            signal = signals[evidence_id]
            st.markdown("**Extracted observation**")
            st.write(signal["observation"])
            st.markdown("**Verified exact quote**")
            st.text(signal["quote"])
            st.write("Limitations:", signal["limitations"])


def show_run(store: Store, manifest: dict) -> None:
    run_path = store.path(manifest["id"])
    st.subheader(manifest["scenario"])
    st.caption(f"Run {manifest['id']} | {manifest['status']} | {manifest['created_at']}")
    if manifest["config"]["mode"] == "demo":
        st.warning(
            "DETERMINISTIC DEMO: scripted synthetic reasoning, not an AI result. "
            "No model was called. Timings must not be used to compare model families."
        )
    elif manifest["synthetic"]:
        st.info("LIVE COPILOT SDK / SYNTHETIC DATA: genuine model responses to fictional evidence.")
    else:
        st.info("LIVE COPILOT SDK / USER-SUPPLIED DATA")
    if manifest["error"]:
        st.error(manifest["error"])
    st.write(manifest["question"])
    columns = st.columns(3)
    for column, title, phase in zip(
        columns,
        ("01 / INPUTS", "02 / EXPERT LOGIC", "03 / DECISIONS"),
        ("inputs", "business", "outputs"),
        strict=True,
    ):
        with column:
            with st.container(border=True):
                st.markdown(f"**{title}**")
                st.write("Complete" if phase in manifest["completed_phases"] else "Pending")

    inputs = read_json(run_path / "inputs.json") if (run_path / "inputs.json").exists() else None
    business = (
        read_json(run_path / "business.json") if (run_path / "business.json").exists() else None
    )
    outputs = read_json(run_path / "outputs.json") if (run_path / "outputs.json").exists() else None
    records = {row["id"]: row for row in inputs["evidence"]} if inputs else {}
    signals = {row["evidence_id"]: row for row in inputs["signals"]} if inputs else {}
    tabs = st.tabs(["Inputs", "Expert logic", "Decision brief", "Run telemetry"])
    with tabs[0]:
        if inputs:
            left, right = st.columns(2)
            left.metric("Evidence records", len(records))
            right.metric("Traceable signals", len(signals))
            for warning in inputs["warnings"]:
                st.info(warning)
            st.dataframe(
                [
                    {
                        "id": row["id"],
                        "source": row["source"],
                        "kind": row["kind"],
                        "location": row["location"],
                    }
                    for row in records.values()
                ],
                hide_index=True,
                width="stretch",
            )
            if inputs["historical_margins"]:
                with st.expander("Python-calculated historical margins (not forecasts)"):
                    st.dataframe(inputs["historical_margins"], hide_index=True)
            evidence_id = st.selectbox("Inspect a signal and its original source", list(records))
            show_evidence([evidence_id], records, signals)
        else:
            st.info("Run the inputs phase to see source records and extracted signals.")
    with tabs[1]:
        if business:
            for role, report in business["experts"].items():
                with st.expander(f"{role.title()} expert", expanded=False):
                    coverage = business["coverage"][role]
                    st.caption(
                        f"Reviewed {coverage['selected']} of {coverage['total']} evidence records."
                    )
                    if coverage["omitted"]:
                        st.warning(
                            f"{coverage['omitted']} records omitted by relevance/context limits. "
                            "Findings do not represent exhaustive review."
                        )
                    for finding in report["findings"]:
                        st.markdown(f"**{finding['title']}**")
                        st.write(finding["interpretation"])
                        st.write("Uncertainties:", finding["uncertainties"])
                        show_evidence(finding["evidence_ids"], records, signals)
                    st.write("Conflicts:", report["conflicts"])
                    st.write("Missing data:", report["missing_data"])
            st.markdown("### Where the experts disagree")
            for conflict in business["conflicts"]:
                st.warning(conflict)
            st.markdown("### Synthesis")
            for finding in business["synthesis"]:
                with st.expander(f"{finding['id']} | {finding['title']}"):
                    st.write(finding["interpretation"])
                    show_evidence(finding["evidence_ids"], records, signals)
        else:
            st.info("Run the business phase to see expert interpretations.")
    with tabs[2]:
        if outputs:
            st.markdown(f"### {outputs['headline']}")
            if outputs["recommended"]:
                st.success(f"Recommended for review: {outputs['recommended']}")
            else:
                st.error("No option passes the manufacturing gate.")
            st.warning(
                "Decision support only. Human approval and verified unit costs are required."
            )
            st.caption(outputs["score_note"])
            st.dataframe(
                [
                    {
                        "Option": option["name"],
                        "Score / 5": option["weighted_score"],
                        "Eligible": option["eligible"],
                        "Manufacturing gate": option["blocked_reason"] or "Passed",
                        "Margin gate": "Unknown - review required",
                    }
                    for option in outputs["options"]
                ],
                hide_index=True,
                width="stretch",
            )
            by_id = {finding["id"]: finding for finding in business["synthesis"]}
            for option in outputs["options"]:
                with st.expander(option["name"], expanded=option["name"] == outputs["recommended"]):
                    st.write(option["rationale"])
                    st.markdown("**Proposed next action**")
                    st.write(option["next_action"])
                    st.write("Success criteria:", option["success_criteria"])
                    st.write("Stop criteria:", option["stop_criteria"])
                    st.write("Risks:", option["risks"])
                    if option["blocked_reason"]:
                        st.error(option["blocked_reason"])
                    st.markdown("**Trace recommendation to synthesis and original evidence**")
                    for finding_id in option["finding_ids"]:
                        finding = by_id[finding_id]
                        st.write(f"{finding_id}: {finding['title']}")
                        show_evidence(finding["evidence_ids"], records, signals)
            st.write("Open questions:", outputs["open_questions"])
            st.download_button(
                "Download decision brief",
                (run_path / "brief.md").read_text(encoding="utf-8"),
                file_name=f"northstar-{manifest['id']}.md",
                mime="text/markdown",
            )
            st.download_button(
                "Download decision JSON",
                json.dumps(outputs, indent=2),
                file_name=f"decision-{manifest['id']}.json",
                mime="application/json",
            )
        else:
            st.info("Complete the pipeline to see ranked options and the decision brief.")
    with tabs[3]:
        st.metric("Pipeline wall time", f"{manifest['wall_seconds']:.2f} s")
        st.caption(
            "Call durations include session setup. Calls run concurrently, so summed durations "
            "are not wall time. Blank token counts mean unavailable, not zero."
        )
        if manifest["metrics"]:
            st.dataframe(manifest["metrics"], hide_index=True, width="stretch")
        st.write("Model configuration:", manifest["config"])
        st.code(manifest["fingerprint"], language=None)
        with st.expander("Immutable skills and knowledge used by this run"):
            bundle = store.snapshot(manifest)
            for relative, text in bundle.files.items():
                if relative.endswith(".md") and not relative.startswith("inputs"):
                    st.markdown(f"**{relative}**")
                    st.code(text, language="markdown")
        st.caption(f"Persistent artifacts: {run_path}")


def main() -> None:
    st.set_page_config(page_title="Northstar | Signal to decision", page_icon="N", layout="wide")
    st.markdown(
        "<style>.block-container{padding-top:2rem;max-width:1440px}"
        "[data-testid=stSidebar]{background:#f4f5f7}"
        "h1{letter-spacing:-.04em}h3{letter-spacing:-.02em}</style>",
        unsafe_allow_html=True,
    )
    store = Store(ROOT / "runs")
    scenarios = sorted(path.parent for path in (ROOT / "scenarios").glob("*/scenario.yaml"))
    st.title("Northstar")
    st.markdown(
        "**SIGNAL TO DECISION** &nbsp; / &nbsp; Beverage market intelligence",
        unsafe_allow_html=True,
    )
    st.caption("Source evidence + company wisdom + expert judgment. Every decision has a trail.")
    with st.sidebar:
        st.header("Demo control room")
        scenario_path = st.selectbox("Scenario", scenarios, format_func=lambda path: path.name)
        bundle = load_bundle(scenario_path)
        mode_label = st.radio("Execution", ["Offline walkthrough", "Live Copilot SDK"])
        mode = "demo" if mode_label == "Offline walkthrough" else "live"
        model = bundle.scenario.default_model
        selected_overrides = {}
        if mode == "live":
            st.caption(
                "Live execution sends selected scenario data to GitHub Copilot and consumes usage."
            )
            if st.button("Discover available models"):

                async def discover():
                    async with CopilotProvider(store.root / ".copilot-runtime") as provider:
                        async with asyncio.timeout(90):
                            return await provider.models()

                try:
                    with st.spinner("Querying the Copilot SDK..."):
                        st.session_state["catalog"] = asyncio.run(discover())
                except Exception as exc:
                    st.error(f"Model discovery failed: {exc}")
            catalog = st.session_state.get("catalog", [])
            available = [
                row["id"]
                for row in catalog
                if row.get("policy", {}).get("state", "enabled") == "enabled"
            ]
            if available:
                default = available.index(model) if model in available else 0
                model = st.selectbox("Run model", available, index=default)
            else:
                model = st.text_input("Run model ID", model)
            with st.expander("Per-expert model overrides"):
                for role in ROLES:
                    override = st.text_input(
                        f"{role} model (blank inherits)", key=f"override-{role}"
                    )
                    if override.strip():
                        selected_overrides[role] = override.strip()
            consent = st.checkbox("Use Copilot for this scenario's data")
        else:
            consent = True
            st.caption(
                "No network or model calls. Scripted Northstar narrative plus real policy gates. "
                "Free-form skill edits affect live runs; policy frontmatter affects both modes."
            )
        with st.expander("Execution settings"):
            concurrency = st.slider("Concurrent sessions", 1, 8, 3)
            timeout = st.number_input("Timeout per call (seconds)", 10, 1800, 180, step=10)
            until = st.selectbox("Run through phase", ["outputs", "business", "inputs"])
        config = RunConfig(
            mode=mode,
            model=model,
            overrides=selected_overrides,
            concurrency=concurrency,
            timeout=int(timeout),
        )
        if st.button("Run pipeline", type="primary", disabled=not consent, width="stretch"):
            with st.status("Running pipeline", expanded=True) as status:
                try:
                    result = asyncio.run(
                        Pipeline(store, st.write).run(scenario_path, config, until)
                    )
                    st.session_state["selected_run"] = result["id"]
                    status.update(label="Run saved", state="complete")
                except Exception as exc:
                    status.update(label="Run failed - see saved error", state="error")
                    st.exception(exc)
        st.divider()
        st.caption("No automatic launch, purchasing, social posting, or production changes.")

    workspace, skills, comparison = st.tabs(
        ["Pipeline explorer", "Skills & knowledge", "Compare runs"]
    )
    manifests = store.list()
    with workspace:
        if not manifests:
            st.info("Start with an offline walkthrough using Run pipeline in the sidebar.")
        else:
            by_id = {manifest["id"]: manifest for manifest in manifests}
            if st.session_state.get("selected_run") not in by_id:
                st.session_state["selected_run"] = manifests[0]["id"]
            selected = st.selectbox(
                "Saved run",
                list(by_id),
                key="selected_run",
                format_func=lambda run_id: (
                    f"{run_id} | {by_id[run_id]['config']['mode']} | "
                    f"{by_id[run_id]['config']['model']} | {by_id[run_id]['status']}"
                ),
            )
            manifest = by_id[selected]
            if manifest["status"] != "completed":
                st.caption("Resume uses the saved snapshot and model settings, not the sidebar.")
                approved = manifest["config"]["mode"] == "demo" or st.checkbox(
                    "Authorize live resume with this run's saved data and models"
                )
                if st.button("Resume saved run", disabled=not approved):
                    try:
                        with st.spinner("Resuming saved run..."):
                            asyncio.run(Pipeline(store).resume(selected))
                        st.rerun()
                    except Exception as exc:
                        st.exception(exc)
            show_run(store, manifest)
    with skills:
        st.subheader("Make company wisdom executable")
        st.write(
            "Edit the scenario, save, then create a new run. Existing runs retain their snapshots. "
            "For the demo moment, change specialty_packaging_allowed to false in guardrails.md."
        )
        editable = sorted(
            {skill.path for skill in bundle.skills.values()}
            | {name for name in bundle.files if Path(name).parts[0] == "knowledge"}
        )
        relative = st.selectbox("Skill or company knowledge", editable)
        original = bundle.files[relative]
        with st.form(f"editor-{scenario_path.name}-{relative}-{bundle.fingerprint}"):
            replacement = st.text_area("Markdown", original, height=440)
            save = st.form_submit_button("Validate and save")
        if save:
            try:
                save_markdown(scenario_path, relative, original, replacement)
                st.success("Saved. Start a new run to apply this version.")
            except Exception as exc:
                st.error(f"Not saved: {exc}")
    with comparison:
        st.subheader("Compare speed and judgment")
        st.caption(
            "Run each model on the same scenario, then compare here. Use the CLI benchmark "
            "command for repeated live trials. No invented capability score or cost estimates."
        )
        if len(manifests) < 2:
            st.info("Create at least two runs to compare their decisions.")
        else:
            ids = [manifest["id"] for manifest in manifests]
            left, right = st.columns(2)
            baseline = left.selectbox("Baseline", ids, index=1)
            candidate = right.selectbox("Candidate", ids, index=0)
            if baseline == candidate:
                st.info("Select two different runs.")
            else:
                result = compare(store, baseline, candidate)
                for caution in result["cautions"]:
                    st.warning(caution)
                st.dataframe(
                    [
                        {
                            key: value
                            for key, value in summarize(store, run_id).items()
                            if key not in ("evidence_coverage", "fingerprint")
                        }
                        for run_id in (baseline, candidate)
                    ],
                    hide_index=True,
                    width="stretch",
                )
                if result["speed_comparable"]:
                    st.bar_chart(
                        {
                            "Run": [baseline, candidate],
                            "Wall time (s)": [
                                result["baseline"]["wall_seconds"],
                                result["candidate"]["wall_seconds"],
                            ],
                        },
                        x="Run",
                        y="Wall time (s)",
                    )
                st.markdown(
                    "**Human review:** grounding / contradictions / feasibility / useful next step"
                )
                for column, run_id in zip(st.columns(2), (baseline, candidate), strict=True):
                    with column:
                        st.markdown(f"**{run_id}**")
                        brief = store.path(run_id) / "brief.md"
                        if brief.exists():
                            st.markdown(brief.read_text(encoding="utf-8"))
                        else:
                            st.info("No decision brief: run incomplete.")


if __name__ == "__main__":
    main()
