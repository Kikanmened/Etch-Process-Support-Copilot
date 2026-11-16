"""Offline browser smoke, responsive portfolio captures, and download checks.

Start the dashboard on 127.0.0.1:8501 first. Artifacts stay in ignored data/processed.
"""

import json
from urllib.parse import urlparse

from playwright.sync_api import Route, sync_playwright

from etch_copilot.dashboard.artifacts import write_verification_artifact


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1440, "height": 1100}, accept_downloads=True
        )
        external: list[str] = []

        def route_request(route: Route) -> None:
            # Browser test intentionally denies every non-loopback HTTP request.
            request = route.request
            if urlparse(request.url).hostname != "127.0.0.1":
                external.append(urlparse(request.url).hostname or "unknown")
                route.abort()
            else:
                route.continue_()

        context.route("**/*", route_request)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8501")
        page.get_by_role("heading", name="Overview and engineering readiness").wait_for()
        page.get_by_text("Synthetic SPC investigations", exact=True).first.click()
        page.get_by_role("combobox", name="Scenario").click()
        page.get_by_role("option", name="S2", exact=True).click()
        page.get_by_role("button", name="Run candidate investigation").click()
        page.locator(".js-plotly-plot").first.wait_for()
        assert page.locator(".js-plotly-plot").count() == 2
        assert (
            page.locator(".js-plotly-plot").first.evaluate(
                "(plot) => plot.layout.legend.orientation"
            )
            == "h"
        )
        page.locator(".js-plotly-plot").first.scroll_into_view_if_needed()
        write_verification_artifact("synthetic-s2-desktop.png", page.screenshot())
        for width, height in [(768, 1024), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_function("""() => {
                const plot = document.querySelector('.js-plotly-plot');
                return plot && plot._fullLayout.width <= window.innerWidth;
            }""")
            page.wait_for_timeout(500)
            page.locator(".js-plotly-plot").first.scroll_into_view_if_needed()
            write_verification_artifact(f"synthetic-s2-{width}.png", page.screenshot())
        page.set_viewport_size({"width": 1440, "height": 1100})
        page.get_by_text("Provenance & JSON exports", exact=True).first.click()
        with page.expect_download() as pending:
            page.get_by_role("button", name="Download verified JSON").click()
        download = pending.value
        path = download.path()
        payload = json.loads(path.read_bytes())
        assert payload["results"]["qualification"]["status"] == "SUPPORTED"
        assert payload["results"]["qualification"]["operational_control_limits_status"] == "BLOCKED"
        assert "/Users/" not in json.dumps(payload)
        assert "scenario_truth" not in json.dumps(payload)
        with page.expect_download() as repeated:
            page.get_by_role("button", name="Download verified JSON").click()
        assert repeated.value.path().read_bytes() == path.read_bytes()
        page.get_by_text("BOSCH process evidence", exact=True).first.click()
        page.get_by_role("button", name="Discover available evidence").click()
        page.get_by_role("button", name="Analyze recorded evidence").wait_for(timeout=30000)
        page.get_by_role("button", name="Analyze recorded evidence").click()
        page.locator(".js-plotly-plot").first.wait_for(timeout=30000)
        page.locator(".js-plotly-plot").first.scroll_into_view_if_needed()
        write_verification_artifact("bosch-desktop.png", page.screenshot())
        page.get_by_text("PHM equipment evidence", exact=True).first.click()
        page.get_by_role("button", name="Discover available evidence").click()
        page.get_by_role("button", name="Analyze equipment evidence").wait_for(timeout=30000)
        page.get_by_role("button", name="Analyze equipment evidence").click()
        page.get_by_text("Raw observations", exact=True).wait_for(timeout=30000)
        for scenario in ("S1", "S3"):
            page.get_by_text("Synthetic SPC investigations", exact=True).first.click()
            page.get_by_role("combobox", name="Scenario").click()
            page.get_by_role("option", name=scenario, exact=True).click()
            page.get_by_role("button", name="Run candidate investigation").click()
            page.get_by_text("Candidate readiness: BLOCKED", exact=True).wait_for(timeout=30000)
            assert page.locator(".js-plotly-plot").count() == 0
        assert "/Users/" not in page.locator("body").inner_text()
        assert not errors, errors
        assert not external, external
        write_verification_artifact(
            "browser-verification.json",
            (
                json.dumps(
                    {
                        "external_requests": external,
                        "browser_errors": errors,
                        "viewports": [1440, 768, 390],
                        "verified_download": True,
                        "network_policy": "only loopback allowed; external HTTP denied",
                    },
                    indent=2,
                )
                + "\n"
            ).encode(),
        )
        browser.close()


if __name__ == "__main__":
    main()
