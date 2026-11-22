"""Deployment and optional-installation contracts for the local-only dashboard."""

import ast
import tomllib

from etch_copilot.dashboard.service import ROOT


def test_local_security_configuration() -> None:
    config = tomllib.loads((ROOT / ".streamlit/config.toml").read_text())
    assert config["server"]["address"] == "127.0.0.1"
    assert config["server"]["enableCORS"] is True
    assert config["server"]["enableXsrfProtection"] is True
    assert config["browser"]["gatherUsageStats"] is False
    assert config["client"]["showErrorDetails"] == "none"
    assert config["client"]["disableDataExport"] is True


def test_light_and_dark_themes_have_independent_palettes() -> None:
    config = tomllib.loads((ROOT / ".streamlit/config.toml").read_text())
    theme = config["theme"]
    assert theme["base"] == "light"
    assert theme["light"]["backgroundColor"] == "#ffffff"
    assert theme["light"]["textColor"] == "#172b4d"
    assert theme["dark"]["backgroundColor"] == "#0e1117"
    assert theme["dark"]["textColor"] == "#f2f5f8"


def test_backend_installation_has_no_required_dashboard_dependencies() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    for dependency in project["dependencies"]:
        assert not dependency.startswith(("streamlit", "plotly", "playwright"))
    for path in (ROOT / "src/etch_copilot").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("etch_copilot.dashboard")
