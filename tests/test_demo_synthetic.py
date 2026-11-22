from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "docs" / "examples" / "synthetic-s2-evidence.json"
SCRIPT = ROOT / "scripts" / "demo_synthetic.py"


def test_demo_artifact_is_reproducible(tmp_path: Path) -> None:
    generated = tmp_path / "synthetic-s2-evidence.json"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(generated)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert generated.read_bytes() == ARTIFACT.read_bytes()
