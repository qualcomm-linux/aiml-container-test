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
        if report.get("schema_version") != 1:
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
        (result["workload"], result["accelerator"]): result["measurement"]
        for result in board["results"]
        if result["result"] == "pass"
        and result["measurement"] is not None
        and result["unit"] == "ms"
    }


def graph_limit(values):
    maximum = max(values, default=1)
    if maximum <= 0:
        return 1
    magnitude = 10 ** math.floor(math.log10(maximum))
    step = magnitude / 5
    return math.ceil((maximum * 1.12) / step) * step


def svg_text(x, y, text, **attributes):
    rendered = " ".join(
        f'{name.replace("_", "-")}="{value}"'
        for name, value in attributes.items()
    )
    return (
        f'<text x="{x}" y="{y}" {rendered}>'
        f"{html.escape(str(text))}</text>"
    )


def write_svg(path, boards):
    width = 1200
    height = 860
    margin_x = 70
    top = 145
    panel_width = 520
    panel_height = 185
    column_gap = 70
    row_gap = 55
    indexes = {board["id"]: result_index(board) for board in boards}
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
            "Lower is better. Each panel uses a linear scale starting at zero.",
            text_anchor="middle",
            font_family="sans-serif",
            font_size="14",
            fill="#59636e",
        ),
    ]

    legend_width = 150
    legend_start = (width - (legend_width * len(boards))) / 2
    for index, board in enumerate(boards):
        x = legend_start + index * legend_width
        color = COLORS[index % len(COLORS)]
        elements.append(
            f'<rect x="{x}" y="92" width="16" height="16" rx="2" fill="{color}"/>'
        )
        elements.append(
            svg_text(
                x + 24,
                105,
                board["name"],
                font_family="sans-serif",
                font_size="13",
                fill="#1f2328",
            )
        )

    for row, accelerator in enumerate(ACCELERATORS):
        for column, (workload, workload_name) in enumerate(WORKLOADS):
            x = margin_x + column * (panel_width + column_gap)
            y = top + row * (panel_height + row_gap)
            values = [
                indexes[board["id"]].get((workload, accelerator))
                for board in boards
            ]
            limit = graph_limit([value for value in values if value is not None])
            chart_top = y + 36
            chart_bottom = y + panel_height - 28
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
                        f'y2="{chart_bottom}" stroke="#8c959f" stroke-width="1"/>'
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

            slot_width = panel_width / max(len(boards), 1)
            bar_width = min(70, slot_width * 0.55)
            for index, (board, value) in enumerate(zip(boards, values)):
                center = x + slot_width * (index + 0.5)
                color = COLORS[index % len(COLORS)]
                if value is None:
                    elements.append(
                        svg_text(
                            center,
                            chart_bottom - 8,
                            "N/A",
                            text_anchor="middle",
                            font_family="sans-serif",
                            font_size="12",
                            fill="#8c959f",
                        )
                    )
                    continue
                bar_height = chart_height * value / limit
                bar_y = chart_bottom - bar_height
                elements.extend(
                    [
                        (
                            f'<rect x="{center - bar_width / 2:.2f}" '
                            f'y="{bar_y:.2f}" width="{bar_width:.2f}" '
                            f'height="{bar_height:.2f}" rx="3" fill="{color}"/>'
                        ),
                        svg_text(
                            center,
                            f"{max(chart_top + 12, bar_y - 6):.2f}",
                            f"{value:g} ms",
                            text_anchor="middle",
                            font_family="sans-serif",
                            font_size="11",
                            fill="#1f2328",
                        ),
                    ]
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
