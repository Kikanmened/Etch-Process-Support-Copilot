"""Deterministic JSON and Markdown audit report generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from etch_copilot.loaders import BoschDataset, PhmDataset
from etch_copilot.models import DatasetProvenance, ValidationSummary


def audit_payload(
    provenance: DatasetProvenance,
    validation: ValidationSummary,
) -> dict[str, Any]:
    """Build a stable, machine-readable audit payload."""
    return {
        "dataset": provenance.model_dump(mode="json"),
        "validation": validation.model_dump(mode="json"),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    """Render an audit payload without volatile timestamps."""
    dataset = payload["dataset"]
    validation = payload["validation"]
    lines = [
        f"# Dataset Audit: {dataset['dataset_id']}",
        "",
        f"- Source directory: `{dataset['source_directory']}`",
        f"- Validation status: `{'PASS' if validation['valid'] else 'FAIL'}`",
        "",
        "## Source files",
        "",
    ]
    for filename in dataset["source_files"]:
        lines.append(f"- `{filename}` — SHA-256 `{dataset['sha256'][filename]}`")
    lines.extend(["", "## Record counts", ""])
    for name, count in sorted(validation["record_counts"].items()):
        lines.append(f"- {name}: {count:,}")
    lines.extend(["", "## Available features", ""])
    lines.extend(f"- `{feature}`" for feature in validation["features"])
    lines.extend(["", "## Time ranges", ""])
    for name, values in sorted(validation["timestamp_ranges"].items()):
        lines.append(f"- {name}: `{values[0]}` to `{values[1]}`")
    lines.extend(["", "## Missing values", ""])
    if validation["missing_values"]:
        for name, count in sorted(validation["missing_values"].items()):
            lines.append(f"- {name}: {count:,}")
    else:
        lines.append("- None detected")
    lines.extend(["", "## Duplicate counts", ""])
    for name, count in sorted(validation["duplicate_counts"].items()):
        lines.append(f"- {name}: {count:,}")
    lines.extend(["", "## Identifier relationships", "", "```json"])
    lines.append(json.dumps(validation["identifier_relationships"], indent=2, sort_keys=True))
    lines.extend(["```", "", "## Validation issues", ""])
    if validation["issues"]:
        for issue in validation["issues"]:
            lines.append(f"- **{issue['severity'].upper()} `{issue['code']}`**: {issue['message']}")
    else:
        lines.append("- None")
    lines.extend(["", "## Unsupported engineering assumptions", ""])
    lines.extend(f"- {item}" for item in validation["unsupported_assumptions"])
    return "\n".join(lines) + "\n"


def write_reports(
    dataset: BoschDataset | PhmDataset,
    output_directory: str | Path,
) -> tuple[Path, Path]:
    """Write deterministic JSON and Markdown reports for one source."""
    output_dir = Path(output_directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = audit_payload(dataset.provenance, dataset.validation)
    stem = dataset.provenance.dataset_id
    json_path = output_dir / f"{stem}.audit.json"
    markdown_path = output_dir / f"{stem}.audit.md"
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return json_path, markdown_path
