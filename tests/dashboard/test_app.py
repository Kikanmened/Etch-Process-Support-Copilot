"""Optional dashboard interaction and display-contract tests."""

import shutil
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("plotly")

from streamlit.testing.v1 import AppTest

from etch_copilot.dashboard.charts import candidate_charts, trend_chart
from etch_copilot.dashboard.service import ROOT, DashboardService


def test_scenario_switching_and_exports() -> None:
    app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    app.sidebar.radio[0].set_value("Synthetic SPC investigations").run()
    app.button[0].click().run()
    assert not app.error
    assert any("BLOCKED" in item.value for item in app.text)
    app.selectbox[0].set_value("S2").run()
    assert not app.get("plotly_chart")
    app.button[0].click().run()
    assert not app.error
    assert len(app.get("plotly_chart")) == 2
    app.selectbox[0].set_value("S3").run()
    app.button[0].click().run()
    assert not app.error
    assert not app.get("plotly_chart")
    app.sidebar.radio[0].set_value("Provenance & JSON exports").run()
    assert not app.exception
    assert len(app.get("download_button")) == 1


def test_candidate_plots_match_backend() -> None:
    result = DashboardService().synthetic("S2").data()["results"]
    q, e = result["qualification"], result["evaluation"]
    figures = candidate_charts(q, e)
    assert [v for trace in figures[0].data[:2] for v in trace.y if v is not None] == [
        o["etch_rate_nm_per_min"]
        for o in q["baseline"]["observations"] + e["incident_observations"]
    ]
    assert list(figures[0].data[2].y) == [s["value"] for s in e["individual_signals"]]
    assert figures[0].layout.shapes[0].y0 == q["baseline"]["limits"]["individual_lcl"]


def test_trend_keeps_transition_break() -> None:
    figure = trend_chart(
        {
            "sensor_values": [1.0, 2.0, None, 4.0],
            "elapsed_coordinates": [0.0, 1.0, 2.0, 30.0],
            "interval_summary": {"discontinuity_after_indices": [2]},
            "feature": "pressure",
            "engineering_unit": None,
        }
    )
    assert list(figure.data[0].y) == [1.0, 2.0, None, None, 4.0]
    assert figure.data[0].connectgaps is False


def test_unverified_units_and_candidate_boundaries() -> None:
    trend = {
        "sensor_values": [1.0, 2.0],
        "elapsed_coordinates": [0.0, 1.0],
        "interval_summary": {"discontinuity_after_indices": []},
        "feature": "pressure",
        "engineering_unit": "Pa",
        "unit_verified": False,
    }
    assert "units unverified" in trend_chart(trend).layout.yaxis.title.text
    trend["unit_verified"] = True
    assert "Pa" in trend_chart(trend).layout.yaxis.title.text
    result = DashboardService().synthetic("S2").data()["results"]
    q, e = result["qualification"], result["evaluation"]
    e["transitions"][1]["disposition"] = "BOUNDARY_REPORTED_NOT_EVALUATED"
    e["transitions"][1]["moving_range"] = None
    figures = candidate_charts(q, e)
    assert figures[0].data[1].y[1] is None
    assert figures[1].data[1].y[1] is None


def test_missing_dataset_and_session_isolation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    from pathlib import Path

    import etch_copilot.dashboard.app as module
    from etch_copilot.dashboard.service import Registry

    monkeypatch.setattr(
        module, "DashboardService", lambda: DashboardService(Registry(Path(str(tmp_path))))
    )
    app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30).run()
    app.button[0].click().run()
    assert len(app.error) == 1
    assert not app.exception
    assert not app.session_state["evidence_store"].entries
    second = AppTest.from_file(ROOT / "streamlit_app.py").run()
    assert not second.session_state["evidence_store"].entries


def test_external_pages_and_freshness(
    tmp_path: Path,
    bosch_fixture: Path,
    phm_fixture: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import h5py

    import etch_copilot.dashboard.app as module
    from etch_copilot.dashboard.service import Registry

    shutil.copytree(bosch_fixture, tmp_path / "data/external/bosch")
    shutil.copytree(phm_fixture, tmp_path / "data/external/phm_ion_mill_2018/compact")
    shutil.copytree(ROOT / "data/synthetic/demo-v1", tmp_path / "data/synthetic/demo-v1")
    source = tmp_path / "data/external/bosch/Process_data.nc"
    with h5py.File(source, "a") as handle:
        handle.copy("Day_2024_07_02_Wafer_01", "Day_2024_07_02_Wafer_02")
    service = DashboardService(Registry(tmp_path))
    monkeypatch.setattr(module, "DashboardService", lambda: service)
    app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30).run()
    app.button[0].click().run()
    assert not app.error
    assert len(app.dataframe) == 2
    app.selectbox[0].set_value("bosch").run()
    app.button[0].click().run()
    assert not app.error
    app.sidebar.radio[0].set_value("BOSCH process evidence").run()
    app.button[0].click().run()
    assert "Day_2024_07_02_Wafer_01" not in app.multiselect[0].options
    app.multiselect[0].set_value(["Day_2024_07_02_Wafer_02"]).run()
    app.multiselect[1].set_value(service.catalog("bosch")["wafers"]).run()
    app.button[1].click().run()
    assert not app.error
    assert len(app.get("plotly_chart")) == 1
    assert len(app.dataframe) == 4
    app.sidebar.radio[0].set_value("PHM equipment evidence").run()
    app.button[0].click().run()
    app.button[1].click().run()
    assert not app.error
    assert len(app.metric) == 2
    assert len(app.dataframe) == 3
    source.write_bytes(source.read_bytes() + b"\n")
    app.sidebar.radio[0].set_value("BOSCH process evidence").run()
    assert app.warning
    assert not app.get("plotly_chart")
    assert "BOSCH process evidence" not in app.session_state["evidence_store"].entries
