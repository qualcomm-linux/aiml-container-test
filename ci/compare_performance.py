#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import argparse
import html
import json
import math
from pathlib import Path


COLORS = ("#0969da", "#1a7f37", "#8250df", "#bf8700")
WORKLOADS = (
    ("label_image", "Label image"),
    ("benchmark_model", "Benchmark model"),
)
ACCELERATORS = ("cpu", "gpu", "cdsp")
SCHEMA_VERSION = 2
ERROR_CAP_HALF_WIDTH = 10
BOARD_CENTER_SPACING = 104
PANEL_GAP = 46
SIDE_MARGIN = 55
MINIMUM_SVG_WIDTH = 900


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a cross-board TensorFlow Lite performance comparison"
    )
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def load_reports(input_dir):
    report_files = sorted(input_dir.glob("**/results.json"))
    if not report_files:
        raise ValueError(f"no performance reports found in {input_dir}")

    boards = []
    board_ids = set()
    suite = None
    container = None
    for report_file in report_files:
        report = json.loads(report_file.read_text(encoding="utf-8"))
        if report.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported report schema in {report_file}")
        if suite is None:
            suite = report["suite"]
            container = report["provenance"]["aiml_container"]
        elif report["suite"] != suite:
            raise ValueError("cannot compare reports from different suites")
        elif (
            report["provenance"]["aiml_container"]["sha"] != container["sha"]
            or report["provenance"]["aiml_container"]["digest"] != container["digest"]
        ):
            raise ValueError("cannot compare reports from different AIML containers")

        for board in report["boards"]:
            if board["id"] in board_ids:
                raise ValueError(
                    f"duplicate board in performance reports: {board['id']}"
                )
            board_ids.add(board["id"])
            boards.append(board)

    return suite, container, sorted(boards, key=lambda board: board["name"])


def result_index(board):
    return {
        key: result["measurement"]
        for key, result in chart_result_index(board).items()
    }


def chart_result_index(board):
    indexed = {}
    for result in board["results"]:
        if (
            result["result"] != "pass"
            or result["measurement"] is None
            or result["unit"] != "ms"
        ):
            continue
        standard_deviation = None
        statistics = result.get("statistics")
        if isinstance(statistics, dict):
            candidate = statistics.get("trimmed_stddev")
            if (
                isinstance(candidate, (int, float))
                and not isinstance(candidate, bool)
                and math.isfinite(candidate)
                and candidate >= 0
            ):
                standard_deviation = candidate
        indexed[(result["workload"], result["accelerator"])] = {
            "measurement": result["measurement"],
            "standard_deviation": standard_deviation,
        }
    return indexed


def graph_limit(values):
    maximum = max(values, default=1)
    if maximum <= 0:
        return 1
    magnitude = 10 ** math.floor(math.log10(maximum))
    step = magnitude / 5
    return math.ceil((maximum * 1.12) / step) * step


def svg_text(x, y, text, **attributes):
    rendered = " ".join(
        f'{name.replace("_", "-")}="{html.escape(str(value), quote=True)}"'
        for name, value in attributes.items()
    )
    return (
        f'<text x="{x}" y="{y}" {rendered}>'
        f"{html.escape(str(text))}</text>"
    )


def format_chart_measurement(value, standard_deviation):
    precision = 1 if value >= 1 else 2
    formatted_value = f"{value:.{precision}f}"
    if standard_deviation is None:
        return f"{formatted_value} ms"
    return (
        f"{formatted_value} \N{PLUS-MINUS SIGN} "
        f"{standard_deviation:.{precision}f} ms"
    )


def write_svg(path, boards):
    panel_width = BOARD_CENTER_SPACING * max(len(boards), 1)
    content_width = panel_width * len(WORKLOADS) + PANEL_GAP
    width = max(MINIMUM_SVG_WIDTH, content_width + SIDE_MARGIN * 2)
    height = 880
    margin_x = (width - content_width) / 2
    top = 145
    panel_height = 200
    row_gap = 45
    indexes = {board["id"]: chart_result_index(board) for board in boards}
    elements = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}" role="img">'
        ),
        "<title>TensorFlow Lite latency by board</title>",
        (
            "<desc>Grouped latency comparisons for each workload and "
            "accelerator. Lower is better.</desc>"
        ),
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        svg_text(
            width / 2,
            42,
            "TensorFlow Lite latency by board",
            text_anchor="middle",
            font_family="sans-serif",
            font_size="26",
            font_weight="600",
            fill="#1f2328",
        ),
        svg_text(
            width / 2,
            70,
            (
                "Lower is better. Linear axes start at zero. Bars: trimmed "
                "mean; whiskers: \N{PLUS-MINUS SIGN}1\u03c3 "
                "(n=8 after trimming)."
            ),
            text_anchor="middle",
            font_family="sans-serif",
            font_size="14",
            fill="#59636e",
        ),
    ]

    legend = [
        (
            f'<text x="{width / 2:g}" y="105" text-anchor="middle" '
            'font-family="sans-serif" font-size="13" fill="#1f2328" '
            'data-role="legend">'
        )
    ]
    for index, board in enumerate(boards):
        color = COLORS[index % len(COLORS)]
        item_gap = ' dx="28"' if index else ""
        legend.append(
            f'<tspan{item_gap} fill="{color}" font-size="16" '
            'aria-hidden="true" data-role="legend-swatch">&#9632;</tspan>'
        )
        legend.append(
            '<tspan dx="8" fill="#1f2328" data-role="legend-label">'
            f'{html.escape(str(board["name"]))}</tspan>'
        )
    legend.append("</text>")
    elements.append("".join(legend))

    for row, accelerator in enumerate(ACCELERATORS):
        for column, (workload, workload_name) in enumerate(WORKLOADS):
            x = margin_x + column * (panel_width + PANEL_GAP)
            y = top + row * (panel_height + row_gap)
            results = [
                indexes[board["id"]].get((workload, accelerator))
                for board in boards
            ]
            values = [
                result["measurement"] if result is not None else None
                for result in results
            ]
            extents = [
                result["measurement"]
                + (result["standard_deviation"] or 0)
                for result in results
                if result is not None
            ]
            limit = graph_limit(extents)
            measured = [value for value in values if value is not None]
            best = min(measured) if measured else None
            chart_top = y + 36
            chart_bottom = y + panel_height - 40
            chart_height = chart_bottom - chart_top
            elements.extend(
                [
                    svg_text(
                        x,
                        y + 17,
                        f"{workload_name} / {accelerator.upper()}",
                        font_family="sans-serif",
                        font_size="16",
                        font_weight="600",
                        fill="#1f2328",
                    ),
                    (
                        f'<line x1="{x}" y1="{chart_bottom}" x2="{x + panel_width}" '
                        f'y2="{chart_bottom}" stroke="#8c959f" stroke-width="1" '
                        'data-role="axis"/>'
                    ),
                ]
            )
            for tick in range(1, 5):
                tick_y = chart_bottom - (chart_height * tick / 4)
                tick_value = limit * tick / 4
                elements.extend(
                    [
                        (
                            f'<line x1="{x}" y1="{tick_y:.2f}" '
                            f'x2="{x + panel_width}" y2="{tick_y:.2f}" '
                            'stroke="#d8dee4" stroke-width="1"/>'
                        ),
                        svg_text(
                            x - 8,
                            f"{tick_y + 4:.2f}",
                            f"{tick_value:g}",
                            text_anchor="end",
                            font_family="sans-serif",
                            font_size="11",
                            fill="#59636e",
                        ),
                    ]
                )

            bar_width = ERROR_CAP_HALF_WIDTH * 2
            board_group_width = BOARD_CENTER_SPACING * max(
                len(boards) - 1, 0
            )
            first_board_x = x + (panel_width - board_group_width) / 2
            for index, (board, result) in enumerate(zip(boards, results)):
                center = first_board_x + BOARD_CENTER_SPACING * index
                color = COLORS[index % len(COLORS)]
                if result is None:
                    elements.append(
                        svg_text(
                            center,
                            chart_bottom - 8,
                            "N/A",
                            text_anchor="middle",
                            font_family="sans-serif",
                            font_size="12",
                            fill="#8c959f",
                            data_role="na-label",
                        )
                    )
                else:
                    value = result["measurement"]
                    standard_deviation = result["standard_deviation"]
                    bar_height = chart_height * value / limit
                    bar_y = chart_bottom - bar_height
                    upper_y = bar_y
                    whisker_stem = []
                    whisker_caps = []
                    board_id = html.escape(str(board["id"]), quote=True)
                    if standard_deviation is not None and standard_deviation > 0:
                        upper_value = value + standard_deviation
                        lower_value = max(0, value - standard_deviation)
                        upper_y = chart_bottom - chart_height * upper_value / limit
                        lower_y = chart_bottom - chart_height * lower_value / limit
                        whisker_stem = [
                            (
                                f'<line x1="{center:.2f}" y1="{upper_y:.2f}" '
                                f'x2="{center:.2f}" y2="{lower_y:.2f}" '
                                'stroke="#24292f" stroke-width="1" '
                                'stroke-linecap="round" '
                                f'data-board="{board_id}" '
                                'data-role="error-whisker"/>'
                            )
                        ]
                        whisker_caps = [
                            (
                                f'<line x1="{center - ERROR_CAP_HALF_WIDTH:.2f}" '
                                f'y1="{upper_y:.2f}" '
                                f'x2="{center + ERROR_CAP_HALF_WIDTH:.2f}" '
                                f'y2="{upper_y:.2f}" stroke="#24292f" '
                                'stroke-width="1" stroke-linecap="round" '
                                f'data-board="{board_id}" '
                                'data-role="error-cap"/>'
                            ),
                            (
                                f'<line x1="{center - ERROR_CAP_HALF_WIDTH:.2f}" '
                                f'y1="{lower_y:.2f}" '
                                f'x2="{center + ERROR_CAP_HALF_WIDTH:.2f}" '
                                f'y2="{lower_y:.2f}" stroke="#24292f" '
                                'stroke-width="1" stroke-linecap="round" '
                                f'data-board="{board_id}" '
                                'data-role="error-cap"/>'
                            ),
                        ]
                    value_attributes = {
                        "text_anchor": "middle",
                        "font_family": "sans-serif",
                        "font_size": "11",
                        "fill": "#1f2328",
                        "data_role": "value-label",
                    }
                    if value == best:
                        value_attributes["font_weight"] = "700"
                    elements.extend(
                        [
                            (
                                f'<rect x="{center - bar_width / 2:.2f}" '
                                f'y="{bar_y:.2f}" width="{bar_width:.2f}" '
                                f'height="{bar_height:.2f}" fill="{color}" '
                                f'data-board="{board_id}" '
                                'data-role="measurement-bar"/>'
                            ),
                            *whisker_stem,
                            *whisker_caps,
                            svg_text(
                                center,
                                f"{max(chart_top + 12, upper_y - 6):.2f}",
                                format_chart_measurement(
                                    value, standard_deviation
                                ),
                                **value_attributes,
                            ),
                        ]
                    )
                elements.append(
                    svg_text(
                        center,
                        chart_bottom + 18,
                        board["name"],
                        text_anchor="middle",
                        font_family="sans-serif",
                        font_size="11",
                        fill="#59636e",
                        data_role="bar-label",
                    )
                )

    elements.extend(
        [
            svg_text(
                width / 2,
                height - 20,
                (
                    "N/A means the accelerator was unavailable or no valid "
                    "millisecond measurement was recorded."
                ),
                text_anchor="middle",
                font_family="sans-serif",
                font_size="12",
                fill="#59636e",
            ),
            "</svg>",
            "",
        ]
    )
    path.write_text("\n".join(elements), encoding="utf-8")


def format_measurement(value):
    return f"{value:g} ms" if value is not None else "N/A"


def write_summary(path, suite, container, boards):
    indexes = {board["id"]: result_index(board) for board in boards}
    board_headers = " | ".join(board["name"] for board in boards)
    lines = [
        "# Cross-board TensorFlow Lite performance",
        "",
        (
            "Lower latency is better. Download `comparison.svg` from the board "
            "comparison artifact for the expanded six-panel chart."
        ),
        "",
        f"| Workload | Accelerator | {board_headers} |",
        f"|:---|:---|{'---:|' * len(boards)}",
    ]
    for workload, workload_name in WORKLOADS:
        for accelerator in ACCELERATORS:
            measurements = [
                indexes[board["id"]].get((workload, accelerator))
                for board in boards
            ]
            measured = [value for value in measurements if value is not None]
            best = min(measured) if measured else None
            values = " | ".join(
                (
                    f"**{format_measurement(value)}**"
                    if value is not None and value == best
                    else format_measurement(value)
                )
                for value in measurements
            )
            lines.append(
                f"| {workload_name} | {accelerator.upper()} | {values} |"
            )
    lines.extend(
        [
            "",
            (
                f"Suite: `{suite}`. AIML container: "
                f"`{container['sha'][:12]}` (`{container['digest']}`)."
            ),
            "",
            "**Bold** marks the lowest measured latency in each row.",
            "",
            "N/A means no valid millisecond measurement was recorded.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    args = parse_args()
    suite, container, boards = load_reports(args.input_dir)
    if len(boards) < 2:
        raise ValueError("at least two boards are required for comparison")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_svg(args.output_dir / "comparison.svg", boards)
    write_summary(
        args.output_dir / "summary.md",
        suite,
        container,
        boards,
    )


if __name__ == "__main__":
    main()
