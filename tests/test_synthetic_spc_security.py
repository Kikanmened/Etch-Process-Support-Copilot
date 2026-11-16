from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from etch_copilot.models import DatasetLoadError
from etch_copilot.provenance import sha256_file
from etch_copilot.synthetic import (
    SyntheticGeneratorConfig,
    generate_synthetic_dataset,
    load_synthetic_dataset,
)
from etch_copilot.synthetic.spc import (
    evaluate_synthetic_candidate_spc,
    qualify_synthetic_candidate_baseline,
)


def _refresh_hash(directory: Path, filename: str) -> None:
    manifest_path = directory / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][filename] = sha256_file(directory / filename)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_spc_rejects_phase_labels_that_contradict_trusted_order_contract(
    tmp_path: Path,
) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=1))
    runs = pd.read_csv(output / "runs.csv")
    runs.loc[runs["run_id"] == "S2-R030", "phase"] = "incident"
    runs.loc[runs["run_id"] == "S2-R031", "phase"] = "baseline"
    runs.to_csv(output / "runs.csv", index=False, lineterminator="\n", float_format="%.6f")
    _refresh_hash(output, "runs.csv")

    dataset = load_synthetic_dataset(output)
    with pytest.raises(DatasetLoadError, match="trusted synthetic membership"):
        qualify_synthetic_candidate_baseline(dataset, "S2")


def test_mutated_in_memory_dataset_cannot_bypass_spc_readiness(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=1))
    dataset = load_synthetic_dataset(output)
    dataset.runs.loc[dataset.runs["scenario_id"] == "S1", "phase"] = "baseline"

    with pytest.raises(DatasetLoadError, match="content changed"):
        qualify_synthetic_candidate_baseline(dataset, "S1")


def test_unqualified_sampling_gap_blocks_baseline_admission(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=1))
    runs = pd.read_csv(output / "runs.csv")
    telemetry = pd.read_csv(output / "telemetry.csv")
    run_mask = runs["run_id"] == "S2-R010"
    telemetry_mask = telemetry["run_id"] == "S2-R010"
    for column in ("start_ts_utc", "end_ts_utc"):
        shifted = pd.to_datetime(runs.loc[run_mask, column], utc=True) + pd.Timedelta(seconds=60)
        runs.loc[run_mask, column] = shifted.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    shifted_telemetry = pd.to_datetime(
        telemetry.loc[telemetry_mask, "timestamp_utc"], utc=True
    ) + pd.Timedelta(seconds=60)
    telemetry.loc[telemetry_mask, "timestamp_utc"] = shifted_telemetry.dt.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    runs.to_csv(output / "runs.csv", index=False, lineterminator="\n", float_format="%.6f")
    telemetry.to_csv(
        output / "telemetry.csv", index=False, lineterminator="\n", float_format="%.6f"
    )
    _refresh_hash(output, "runs.csv")
    _refresh_hash(output, "telemetry.csv")

    qualification = qualify_synthetic_candidate_baseline(load_synthetic_dataset(output), "S2")

    assert qualification.status.value == "BLOCKED"
    assert "UNQUALIFIED_BASELINE_BOUNDARY" in {issue.code for issue in qualification.issues}


def test_consistently_manipulated_cadence_cannot_define_its_own_contract(
    tmp_path: Path,
) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=1))
    runs = pd.read_csv(output / "runs.csv")
    telemetry = pd.read_csv(output / "telemetry.csv")
    s2_indices = runs.index[runs["scenario_id"] == "S2"].tolist()
    base_start = pd.Timestamp(runs.loc[s2_indices[0], "start_ts_utc"])
    for sequence_index, row_index in enumerate(s2_indices):
        run_id = str(runs.loc[row_index, "run_id"])
        old_start = pd.Timestamp(runs.loc[row_index, "start_ts_utc"])
        new_start = base_start + pd.Timedelta(seconds=960 * sequence_index)
        delta = new_start - old_start
        runs.loc[row_index, "start_ts_utc"] = new_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        runs.loc[row_index, "end_ts_utc"] = (
            pd.Timestamp(runs.loc[row_index, "end_ts_utc"]) + delta
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        telemetry_mask = telemetry["run_id"] == run_id
        telemetry.loc[telemetry_mask, "timestamp_utc"] = (
            pd.to_datetime(telemetry.loc[telemetry_mask, "timestamp_utc"], utc=True) + delta
        ).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    runs.to_csv(output / "runs.csv", index=False, lineterminator="\n", float_format="%.6f")
    telemetry.to_csv(
        output / "telemetry.csv", index=False, lineterminator="\n", float_format="%.6f"
    )
    _refresh_hash(output, "runs.csv")
    _refresh_hash(output, "telemetry.csv")

    qualification = qualify_synthetic_candidate_baseline(load_synthetic_dataset(output), "S2")

    assert qualification.status.value == "BLOCKED"
    assert "UNQUALIFIED_BASELINE_BOUNDARY" in {issue.code for issue in qualification.issues}


def test_phase_one_moving_range_signal_blocks_baseline(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=1))
    metrology = pd.read_csv(output / "metrology.csv")
    deviations = (
        0.09470803828730423,
        1.2500243810835503,
        -0.931378367720707,
        0.9923772805192402,
        -0.25915453769343405,
        -0.26151098398117395,
        1.8997252784647571,
        0.1575370716337192,
        -0.042924253792244314,
        0.7294984864356091,
        1.1268539623838552,
        -0.030843275034930208,
        0.5879937451803643,
        -0.9737243574656975,
        -0.3667904699805292,
        2.561874965597218,
        -1.3322831645911484,
        -1.5085141271610722,
        -1.6269127299570283,
        -0.23865285544380352,
        -0.17242544785211128,
        -0.3203377073792124,
        0.06912764471505721,
        -1.3355855015706948,
        -0.07946503129535401,
        0.2380985047634084,
        0.7510424068935218,
        -0.8462226452665478,
        -0.39987080697555927,
        -2.0151776559190417,
    )
    for index, deviation in enumerate(deviations, start=1):
        run_id = f"S2-R{index:03d}"
        mask = metrology["run_id"] == run_id
        metrology.loc[mask, "post_thickness_nm"] = (
            metrology.loc[mask, "pre_thickness_nm"] - (100.0 + deviation) * 2.0
        )
    metrology.to_csv(
        output / "metrology.csv", index=False, lineterminator="\n", float_format="%.6f"
    )
    _refresh_hash(output, "metrology.csv")

    qualification = qualify_synthetic_candidate_baseline(load_synthetic_dataset(output), "S2")

    assert qualification.dependence is not None
    assert qualification.dependence.outcome.value == "PASS"
    assert qualification.status.value == "BLOCKED"
    assert "UNRESOLVED_PHASE_ONE_MR_SIGNAL" in {issue.code for issue in qualification.issues}


def test_extreme_finite_incidents_are_evaluated_without_sum_overflow(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=1))
    metrology = pd.read_csv(output / "metrology.csv")
    incident_mask = (metrology["scenario_id"] == "S2") & metrology["run_id"].str.match(
        r"S2-R03[1-8]"
    )
    metrology.loc[incident_mask, "pre_thickness_nm"] = 1e308
    metrology.loc[incident_mask, "post_thickness_nm"] = 0.0
    metrology.to_csv(
        output / "metrology.csv", index=False, lineterminator="\n", float_format="%.6f"
    )
    _refresh_hash(output, "metrology.csv")
    dataset = load_synthetic_dataset(output)
    qualification = qualify_synthetic_candidate_baseline(dataset, "S2")
    assert qualification.baseline is not None

    evaluation = evaluate_synthetic_candidate_spc(dataset, qualification.baseline)

    assert evaluation.incident_mean == pytest.approx(5e307)
    assert len(evaluation.individual_signals) == 8
