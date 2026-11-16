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

The portable suite is expected to run **166 tests**. It excludes the six tests
marked `integration`, which intentionally require the separately approved local
BOSCH and PHM research datasets. CI does not download, cache, upload or
redistribute those datasets, the BOSCH research reference, or the four standards
PDFs.

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
readiness decision or substitute for the provisioned release checks.
