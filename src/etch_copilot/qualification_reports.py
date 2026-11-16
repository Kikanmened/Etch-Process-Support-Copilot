"""Deterministic engineering-qualification report serialization."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from etch_copilot.qualification import BoschQualification, PhmQualification


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _markdown_json(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    return serialized.replace("```", "\\u0060\\u0060\\u0060")


def _readiness_markdown(readiness: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Analysis | Status | Missing requirements | Blocking issues | Limitations |",
        "|---|---|---|---|---|",
    ]
    for decision in readiness:
        missing = "; ".join(decision["missing_requirements"]) or "—"
        blocking = "; ".join(decision["blocking_issues"]) or "—"
        limitations = "; ".join(decision["limitations"]) or "—"
        lines.append(
            f"| `{decision['analysis_id']}` | **{decision['status']}** | "
            f"{missing} | {blocking} | {limitations} |"
        )
    return lines


def _qualification_markdown(payload: dict[str, Any], title: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"- Dataset: `{payload['dataset_id']}`",
        f"- Qualification engine: `{payload['engine_version']}`",
        "- Method: deterministic inspection of source data, metadata, documentation, and checksums",
        "",
        "## Qualification contract",
        "",
        "```json",
    ]
    contract = {key: value for key, value in payload.items() if key != "readiness"}
    lines.extend([_markdown_json(contract), "```", ""])
    lines.extend(["## Analysis readiness", ""])
    lines.extend(_readiness_markdown(payload["readiness"]))
    lines.extend(
        [
            "",
            "## Phase 2 requirements",
            "",
            "- Call the readiness engine before every scientific calculation.",
            "- Refuse BLOCKED analyses programmatically.",
            "- Require explicit acceptance and display of limitations for LIMITED analyses.",
            "- Preserve raw source coordinates, identifiers, and missing values.",
        ]
    )
    return "\n".join(lines) + "\n"


def _matrix_payload(bosch: BoschQualification, phm: PhmQualification) -> dict[str, Any]:
    return {
        "engine_version": bosch.engine_version,
        "datasets": [bosch.dataset_id, phm.dataset_id],
        "decisions": [item.model_dump(mode="json") for item in (*bosch.readiness, *phm.readiness)],
    }


def _matrix_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Analysis Readiness Matrix",
        "",
        f"Qualification engine: `{payload['engine_version']}`",
        "",
    ]
    lines.extend(_readiness_markdown(payload["decisions"]))
    return "\n".join(lines) + "\n"


def write_qualification_reports(
    bosch: BoschQualification,
    phm: PhmQualification,
    output_directory: str | Path,
) -> tuple[Path, ...]:
    """Write deterministic source contracts and the combined readiness matrix."""
    output = Path(output_directory)
    if output.is_symlink():
        raise ValueError(f"unsafe report output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    bosch_payload = bosch.model_dump(mode="json")
    phm_payload = phm.model_dump(mode="json")
    matrix_payload = _matrix_payload(bosch, phm)
    files_and_text = (
        ("bosch_engineering_qualification.json", _json_text(bosch_payload)),
        (
            "bosch_engineering_qualification.md",
            _qualification_markdown(bosch_payload, "BOSCH Engineering Qualification"),
        ),
        ("phm_engineering_qualification.json", _json_text(phm_payload)),
        (
            "phm_engineering_qualification.md",
            _qualification_markdown(phm_payload, "PHM Engineering Qualification"),
        ),
        ("analysis_readiness_matrix.json", _json_text(matrix_payload)),
        ("analysis_readiness_matrix.md", _matrix_markdown(matrix_payload)),
    )
    paths: list[Path] = []
    for filename, content in files_and_text:
        path = output / filename
        _atomic_write_text(path, content)
        paths.append(path)
    return tuple(paths)


def _atomic_write_text(path: Path, content: str) -> None:
    if path.is_symlink():
        raise ValueError(f"unsafe report target: {path}")
    if path.exists() and not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
        raise ValueError(f"unsafe report target: {path}")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
