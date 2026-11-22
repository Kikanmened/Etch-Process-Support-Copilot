# Continuous integration

The portable GitHub Actions workflow runs for pull requests targeting `dev` or
`main`. It uses Python 3.12, frozen `uv.lock` dependencies, and read-only GitHub
permissions. The workflow installs the optional dashboard dependencies because
the portable dashboard tests and strict type check import the presentation code.

It runs:

```sh
uv sync --frozen --extra dashboard
uv run --frozen --no-sync pytest -q -m "not integration"
uv run --frozen --no-sync ruff format --check .
uv run --frozen --no-sync ruff check .
uv run --frozen --no-sync mypy src
```

## Portable versus provisioned verification

The portable suite selects tests with `-m "not integration"`. Test count is deliberately
not treated as a CI contract: it can change as coverage is added, and the authoritative
result is the completed check for the exact commit under review. The excluded integration
tests intentionally require separately approved local BOSCH and PHM research datasets.
CI does not download, cache, upload or redistribute those datasets, the BOSCH research
reference, or the four standards PDFs.

The **172-test provisioned suite** is run only in an authorized local environment
where those datasets are already available. It additionally verifies real
dataset counts, qualification reports and deterministic engineering analytics.
Generated reports and screenshots remain local Git-ignored artifacts.

The workflow does not run browser capture or performance scripts. They require
an installed browser and local external datasets, and are documented as local
release verification in [the dashboard guide](ENGINEERING_DASHBOARD.md).

## Security properties

- No secrets, tokens, artifact uploads, write permissions or `pull_request_target`
  trigger are used.
- Third-party actions are pinned to immutable commit SHAs.
- `actions/checkout` does not persist credentials.
- Dependency resolution is frozen; CI fails when `pyproject.toml` and `uv.lock`
  disagree.

The workflow validates portable code quality. It does not change any scientific
readiness decision or substitute for the provisioned release checks. A workflow file in
the repository is not evidence of a passing run; use the pull request's exact-commit check
conclusion as the public CI result.

## Current local verification

On 2026-11-22, the current local checkout completed the portable command
`.venv/bin/pytest -q -m "not integration"` with **166 passed, 6 deselected** in 13.51
seconds. This is local evidence only; it is not a GitHub Actions result and does not
replace checking the exact commit's public workflow conclusion.
