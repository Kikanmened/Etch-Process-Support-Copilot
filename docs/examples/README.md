# Deterministic demo artifact

From the repository root, run:

```sh
.venv/bin/python scripts/demo_synthetic.py
```

This command uses only the committed `data/synthetic/demo-v1/` fixture. It validates the
input manifest, runs the public S2 candidate-qualification path, and writes
[`synthetic-s2-evidence.json`](synthetic-s2-evidence.json). The output is sorted,
newline-terminated JSON and is deterministic for unchanged fixture contents.

The artifact shows the complete demonstration boundary:

`input_manifest` → `validation` → `allowed_analytics`

The allowed result is synthetic candidate SPC evidence only. It does not establish
operational control limits, metrological traceability, plasma-physics validity or root
cause.
