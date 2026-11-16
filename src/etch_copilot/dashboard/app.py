"""Read-only Streamlit presentation; all engineering work belongs to public APIs."""

from typing import Any

import streamlit as st

from etch_copilot.analytics.contracts import AnalyticsScopeError
from etch_copilot.dashboard.charts import candidate_charts, trend_chart
from etch_copilot.dashboard.service import DashboardService, Evidence, ResultStore, bosch_selection
from etch_copilot.dashboard.views import safe_text
from etch_copilot.qualification import AnalysisBlockedError, AnalysisLimitedError

PAGES = (
    "Overview & readiness",
    "BOSCH process evidence",
    "Synthetic SPC investigations",
    "PHM equipment evidence",
    "Provenance & JSON exports",
)


def display(result: Evidence) -> None:
    data = result.data()
    results = data["results"]
    st.caption(
        f"Evidence origin: {data['evidence_origin']} · source contents and availability reverified"
    )
    if "qualification" in results:
        q = results["qualification"]
        st.subheader(f"{q['scenario_id']} · synthetic candidate SPC")
        st.text(f"Candidate readiness: {q['status']}")
        st.warning("Synthetic candidate limits only. Operational SPC remains BLOCKED.")
        st.text(q["interpretation_policy"])
        if q["dependence"]:
            st.subheader("Baseline admission · dependence diagnostic")
            st.json(q["dependence"])
        if q["issues"]:
            st.dataframe(q["issues"], hide_index=True)
        if "evaluation" in results:
            e = results["evaluation"]
            st.caption(f"Frozen baseline: {e['baseline_id']}")
            st.caption(f"Method version: {q['method_version']} · synthetic candidate limits")
            for figure in candidate_charts(q, e):
                st.plotly_chart(
                    figure, config={"displaylogo": False, "modeBarButtonsToRemove": ["toImage"]}
                )
            st.subheader("Synthetic candidate SPC · numerical evidence")
            st.dataframe(
                q["baseline"]["observations"] + e["incident_observations"], hide_index=True
            )
            st.dataframe(q["baseline_transitions"] + e["transitions"], hide_index=True)
            limits = q["baseline"]["limits"]
            st.subheader("Synthetic candidate estimator comparison · nm/min")
            st.dataframe(
                [
                    {
                        "estimator": "Moving range / d2 (selected)",
                        "sigma": limits["sigma_moving_range"],
                        "candidate_LCL": limits["individual_lcl"],
                        "candidate_UCL": limits["individual_ucl"],
                    },
                    {
                        "estimator": "Sample standard deviation (comparison only)",
                        "sigma": limits["sample_standard_deviation"],
                        "candidate_LCL": limits["standard_deviation_individual_lcl"],
                        "candidate_UCL": limits["standard_deviation_individual_ucl"],
                    },
                ],
                hide_index=True,
            )
    elif "trend" in results:
        trend = results["trend"]
        st.caption(f"Run: {trend['run_id']} · readiness: {trend['readiness_status']}")
        st.text(trend["coordinate_semantics"])
        if not trend["unit_verified"]:
            st.warning(
                "Engineering units are unverified. Interpret source values descriptively only."
            )
        st.plotly_chart(
            trend_chart(results["trend"]),
            config={"displaylogo": False, "modeBarButtonsToRemove": ["toImage"]},
        )
        st.subheader("Descriptive statistics · recorded process evidence")
        st.caption(f"Statistics readiness: {results['statistics']['readiness_status']}")
        st.dataframe([results["statistics"]["statistics"]], hide_index=True)
        for limitation in trend["limitations"]:
            st.text(limitation)
        st.dataframe(
            {
                "elapsed_coordinate": results["trend"]["elapsed_coordinates"],
                "recorded_value": results["trend"]["sensor_values"],
            }
        )
        if "comparison" in results:
            st.subheader("Compatible runs · descriptive comparison only")
            st.caption(f"Comparison readiness: {results['comparison']['readiness_status']}")
            st.text(results["comparison"]["interpretation_policy"])
            st.dataframe(
                [
                    {"run_id": row["run_id"], **row["statistics"]}
                    for row in results["comparison"]["runs"]
                ],
                hide_index=True,
            )
        if "metrology" in results:
            st.subheader("Wafer metrology · coverage and reconstruction inventory")
            st.caption(f"Coverage readiness: {results['metrology']['readiness_status']}")
            st.dataframe(results["metrology"]["wafers"], hide_index=True)
            for rule in results["metrology"]["reconstruction_policy"]:
                st.text(rule)
    elif "features" in results:
        st.subheader("Equipment evidence · recorded features and events")
        features, events = results["features"], results["events"]
        st.caption(
            f"Feature readiness: {features['readiness_status']} · "
            f"Event readiness: {events['readiness_status']}"
        )
        st.warning("Recorded events do not establish fault onset or diagnostic accuracy.")
        st.text(features["time_semantics"])
        st.text(features["sampling_bias"])
        left, right = st.columns(2)
        left.metric("Raw observations", features["raw_observation_count"])
        right.metric("Exact duplicate observations (retained)", features["exact_duplicate_count"])
        st.dataframe(features["features"], hide_index=True)
        st.dataframe(events["category_counts"], hide_index=True)
        st.dataframe(events["events"], hide_index=True)
        for limitation in features["limitations"] + events["limitations"]:
            st.text(limitation)
    else:
        readiness = results["readiness"]
        st.subheader("Backend engineering readiness")
        st.text(readiness["dataset_id"])
        if "scenarios" in readiness:
            st.caption(
                "Input qualification (Phase 3 contract). Candidate admission is listed separately."
            )
            rows = [
                {"scenario_id": scenario["scenario_id"], **decision}
                for scenario in readiness["scenarios"]
                for decision in scenario["decisions"]
            ]
            st.dataframe(rows, hide_index=True)
            st.subheader("Synthetic candidate SPC · baseline admission")
            st.dataframe(
                [
                    {
                        "scenario_id": q["scenario_id"],
                        "candidate_status": q["status"],
                        "issues": [issue["message"] for issue in q["issues"]],
                        "operational_status": q["operational_control_limits_status"],
                    }
                    for q in results["candidate_admission"]["scenarios"]
                ],
                hide_index=True,
            )
            for limitation in readiness["limitations"]:
                st.text(limitation)
        else:
            st.dataframe(readiness["readiness"], hide_index=True)
    with st.expander("Complete sanitized evidence and scientific limitations"):
        st.json(data)


def main() -> None:
    st.set_page_config(page_title="Etch · Engineering Evidence", page_icon="◈", layout="wide")
    service = DashboardService()
    if "evidence_store" not in st.session_state:
        st.session_state.evidence_store = ResultStore()
    store: ResultStore = st.session_state.evidence_store
    st.title("Etch · Engineering Evidence")
    st.caption("PROCESS SUPPORT WORKSPACE · READ ONLY · LOCAL DATA")
    page = st.sidebar.radio("Engineering workspace", PAGES)
    st.sidebar.info(
        "Research evidence and synthetic method qualification. "
        "No equipment control or root-cause confirmation."
    )
    # Every retained result is freshly verified, including on dataset/page switches.
    for key, evidence in list(store.entries.items()):
        try:
            service.verify(evidence)
        except Exception:
            del store.entries[key]
            st.warning(
                "Retained evidence invalidated. "
                "Sources are unavailable, changed or failed verification."
            )
    try:
        selection: Any = None
        if page == PAGES[0]:
            st.header("Overview and engineering readiness")
            st.caption(
                "Select a dataset to validate readiness. Startup does not load research data."
            )
            for key in ("bosch", "phm", "synthetic"):
                try:
                    available = service.registry.path(key).is_dir()
                except Exception:
                    available = False
                status = (
                    "local directory present — verification required"
                    if available
                    else "unavailable"
                )
                st.text(f"{key.upper()}: {status}")
            selection = st.selectbox("Dataset", ["synthetic", "bosch", "phm"])
            if st.button("Verify engineering readiness"):
                store.put(page, service.readiness(selection))
        elif page == PAGES[2]:
            st.header("Synthetic SPC investigations")
            selection = st.selectbox("Scenario", ["S1", "S2", "S3"])
            if st.button("Run candidate investigation"):
                store.put(page, service.synthetic(selection))
        elif page in (PAGES[1], PAGES[3]):
            key = "bosch" if page == PAGES[1] else "phm"
            st.header(page)
            if st.button("Discover available evidence"):
                st.session_state["catalog_" + key] = (
                    service.registry.fingerprints(key),
                    service.catalog(key),
                )
            saved = st.session_state.get("catalog_" + key)
            if saved:
                if service.registry.fingerprints(key) != saved[0]:
                    del st.session_state["catalog_" + key]
                    st.warning("Source selection expired. Discover evidence again.")
                    return
                catalog = saved[1]
                if key == "bosch":
                    run = st.selectbox("Run", list(catalog["runs"]), format_func=safe_text)
                    feature = st.selectbox(
                        "Recorded feature", catalog["runs"][run], format_func=safe_text
                    )
                    compatible = [
                        r
                        for r, features in catalog["runs"].items()
                        if feature in features and r != run
                    ]
                    additional_runs = tuple(
                        st.multiselect(
                            "Additional compatible runs (compared with selected run)",
                            compatible,
                            max_selections=9,
                            format_func=safe_text,
                        )
                    )
                    comparisons = (run, *additional_runs) if additional_runs else ()
                    wafers = tuple(
                        st.multiselect(
                            "Wafer coverage inventory",
                            catalog["wafers"],
                            max_selections=50,
                            format_func=safe_text,
                        )
                    )
                    selection = bosch_selection(run, feature, comparisons, wafers)
                    if st.button("Analyze recorded evidence"):
                        store.put(page, service.bosch(run, feature, comparisons, wafers))
                else:
                    selection = st.selectbox(
                        "Equipment", catalog["equipment"], format_func=safe_text
                    )
                    if st.button("Analyze equipment evidence"):
                        store.put(page, service.phm(selection))
        else:
            st.header("Engineering provenance and JSON exports")
            if store.entries:
                selected = st.selectbox("Verified evidence", list(store.entries))
                result = store.entries[selected]
                service.verify(result)
                st.json(result.data()["sources"])
                # Deferred generation rechecks fingerprints at the actual download request.
                st.download_button(
                    "Download verified JSON",
                    data=lambda: service.export(result),
                    file_name=f"{result.dataset}-engineering-evidence.json",
                    mime="application/json",
                    on_click="ignore",
                )
            else:
                st.info("Run an investigation to create verified exportable evidence.")
        if page in store.entries:
            result = store.entries[page]
            matches = (
                result.dataset == selection if page == PAGES[0] else result.selection == selection
            )
            if matches:
                service.verify(result)
                display(result)
    except (AnalyticsScopeError, AnalysisBlockedError, AnalysisLimitedError) as exc:
        store.entries.pop(page, None)
        st.error("Analysis refused by the engineering backend.")
        st.text(safe_text(str(exc)))
    except Exception:
        store.entries.pop(page, None)
        st.error(
            "Evidence unavailable: validation, readiness or source-integrity checks failed. "
            "No retained result is displayed."
        )


if __name__ == "__main__":
    main()
