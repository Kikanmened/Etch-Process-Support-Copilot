"""Display-only charts: original observations and backend-computed limits."""

from typing import Any

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from etch_copilot.dashboard.views import select_indices


def trend_chart(trend: dict[str, Any]) -> Any:
    values = [v if isinstance(v, (int, float)) else None for v in trend["sensor_values"]]
    boundaries = set(trend["interval_summary"]["discontinuity_after_indices"])
    required = {i for b in boundaries for i in (b, b + 1) if i < len(values)}
    indices = select_indices(values, required=required)
    x, y = [], []
    for i in indices:
        x.append(trend["elapsed_coordinates"][i])
        y.append(values[i])
        if i in boundaries:
            x.append(trend["elapsed_coordinates"][i])
            y.append(None)
    figure = go.Figure(
        go.Scatter(
            x=x,
            y=y,
            mode="lines",
            connectgaps=False,
            name="Recorded process evidence",
            line_color="#087e8b",
        )
    )
    figure.update_layout(
        title="BOSCH · recorded process trend",
        xaxis_title=f"Elapsed coordinate ({trend.get('coordinate_unit', 's')})",
        yaxis_title=(
            f"{trend['feature']} · "
            + (
                str(trend["engineering_unit"])
                if trend.get("unit_verified") is True and trend.get("engineering_unit")
                else "units unverified"
            )
        ),
        height=430,
    )
    return figure


def phm_sensor_chart(trend: dict[str, Any]) -> Any:
    """Render raw-coordinate PHM fields without implying duration or fault onset."""
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.12,
        subplot_titles=[series["source_name"] for series in trend["series"]],
    )
    boundaries = set(trend["discontinuity_after_indices"])
    coordinates = trend["source_coordinates"]
    for row, series in enumerate(trend["series"], start=1):
        x: list[int] = []
        y: list[float | None] = []
        for index, (coordinate, value) in enumerate(
            zip(coordinates, series["recorded_values"], strict=True)
        ):
            x.append(coordinate)
            y.append(value)
            if index in boundaries:
                x.append(coordinate)
                y.append(None)
        figure.add_trace(
            go.Scattergl(
                x=x,
                y=y,
                mode="lines",
                connectgaps=False,
                name=series["source_name"],
                line={"color": "#087e8b" if row == 1 else "#8056a5", "width": 1.4},
                hovertemplate="source coordinate=%{x}<br>recorded value=%{y}<extra></extra>",
            ),
            row=row,
            col=1,
        )
    for event in trend["events"]:
        coordinate = event.get("source_coordinate")
        if coordinate is not None:
            figure.add_vline(
                x=coordinate,
                line={"color": "#b42318", "dash": "dot", "width": 1},
                row="all",
                col=1,
            )
    figure.update_xaxes(title_text="Raw source coordinate (unit unresolved)", row=2, col=1)
    figure.update_yaxes(title_text="Recorded value<br>(unit unresolved)", row=1, col=1)
    figure.update_yaxes(title_text="Recorded value<br>(unit unresolved)", row=2, col=1)
    figure.update_layout(
        title=(
            "PHM recorded sensor evidence<br>raw source coordinates"
            "<br><span style='font-size:11px;color:#b42318'>"
            "Red dotted markers: recorded events; not verified fault onset</span>"
        ),
        height=680,
        margin={"l": 70, "r": 25, "t": 130, "b": 65},
        showlegend=False,
        hovermode="x unified",
    )
    return figure


def candidate_charts(qualification: dict[str, Any], evaluation: dict[str, Any]) -> list[Any]:
    baseline = qualification["baseline"]
    limits = baseline["limits"]
    observations = baseline["observations"] + evaluation["incident_observations"]
    transitions = qualification["baseline_transitions"] + evaluation["transitions"]
    figures = []
    for label, x, y, lower, center, upper, signals in (
        (
            "Individuals",
            [o["run_id"] for o in observations],
            [o["etch_rate_nm_per_min"] for o in observations],
            limits["individual_lcl"],
            limits["center_line"],
            limits["individual_ucl"],
            evaluation["individual_signals"],
        ),
        (
            "Moving Range",
            [t["current_run_id"] for t in transitions],
            [t["moving_range"] for t in transitions],
            limits["moving_range_lcl"],
            limits["average_moving_range"],
            limits["moving_range_ucl"],
            evaluation["moving_range_signals"],
        ),
    ):
        split = (
            len(baseline["observations"])
            if label == "Individuals"
            else len(qualification["baseline_transitions"])
        )
        figure = go.Figure()
        for start, end, phase, color in (
            (0, split, "Phase I reference", "#087e8b"),
            (split, len(x), "Phase II incident", "#8056a5"),
        ):
            display_x: list[str] = []
            display_y: list[float | None] = []
            boundaries = {
                t["current_run_id"]
                for t in transitions
                if t["disposition"] == "BOUNDARY_REPORTED_NOT_EVALUATED"
            }
            for index in range(start, end):
                if label == "Individuals" and x[index] in boundaries:
                    display_x.append(x[index])
                    display_y.append(None)
                display_x.append(x[index])
                display_y.append(y[index])
            figure.add_trace(
                go.Scatter(
                    x=display_x,
                    y=display_y,
                    mode="lines+markers",
                    connectgaps=False,
                    name=f"Synthetic candidate · {phase}",
                    line_color=color,
                )
            )
        for value, name in ((lower, "LCL"), (center, "center"), (upper, "UCL")):
            figure.add_hline(
                y=value, line_dash="dash", line_color="#667085", annotation_text=f"Candidate {name}"
            )
        figure.add_trace(
            go.Scatter(
                x=[s["run_id"] for s in signals],
                y=[s["value"] for s in signals],
                mode="markers",
                name="Synthetic candidate signals",
                marker={"color": "#b42318", "size": 11, "symbol": "diamond"},
            )
        )
        figure.update_layout(
            title=f"Synthetic candidate SPC<br>{label} · not operational",
            xaxis_title="Ordered synthetic run ID",
            yaxis_title="nm/min",
            height=600,
            margin={"l": 55, "r": 20, "t": 85, "b": 180},
            legend={"orientation": "h", "x": 0, "y": -0.4},
        )
        figures.append(figure)
    return figures
