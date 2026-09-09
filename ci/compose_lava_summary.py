#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import argparse
import json
import re
import sys
from pathlib import Path

PERFORMANCE_TITLE = "# TensorFlow Lite performance"
DIAGNOSTICS_TITLE = re.compile(r"# LAVA report diagnostics: .+")


def load_scope_names(path):
    document = json.loads(path.read_text(encoding="utf-8"))
    entries = document.get("include")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"invalid or empty scope matrix in {path}")
    scopes = []
    for entry in entries:
        scope = entry.get("scope") if isinstance(entry, dict) else None
        if not isinstance(scope, str) or not scope:
            raise ValueError(f"scope matrix contains an invalid entry in {path}")
        if scope in scopes:
            raise ValueError(f"scope matrix contains duplicate scope {scope!r}")
        scopes.append(scope)
    return scopes


def load_report_status(path, scopes):
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError(f"invalid report status in {path}")
    for scope in scopes:
        status = document.get(scope)
        if not isinstance(status, dict) or not isinstance(
            status.get("incomplete"), bool
        ):
            raise TypeError(f"invalid report status for {scope!r} in {path}")
    return document


def shift_headings(markdown, levels):
    shifted = []
    for line in markdown.splitlines():
        match = re.fullmatch(r"(#{1,6}) (.+)", line)
        if match:
            level = min(len(match.group(1)) + levels, 6)
            line = f"{'#' * level} {match.group(2)}"
        shifted.append(line)
    return "\n".join(shifted).strip()


def split_performance_summary(markdown, path):
    lines = markdown.splitlines()
    if not lines or lines[0] != PERFORMANCE_TITLE:
        raise ValueError(f"unexpected performance summary title in {path}")
    body_start = next(
        (index for index, line in enumerate(lines[1:], 1) if line.startswith("## ")),
        None,
    )
    if body_start is None:
        raise ValueError(f"performance summary has no board sections in {path}")
    introduction = "\n".join(lines[1:body_start]).strip()
    body = "\n".join(lines[body_start:]).strip()
    return introduction, body


def split_provenance(body, path):
    lines = body.splitlines()
    markers = [index for index, line in enumerate(lines) if line == "## Provenance"]
    if len(markers) != 1:
        raise ValueError(
            f"performance summary must contain exactly one provenance section in {path}"
        )
    marker = markers[0]
    board_sections = "\n".join(lines[:marker]).strip()
    provenance = [line for line in lines[marker + 1 :] if line.strip()]
    if (
        len(provenance) < 3
        or not provenance[0].startswith("|")
        or not provenance[1].startswith("|---")
        or not all(line.startswith("|") for line in provenance[2:])
    ):
        raise ValueError(f"invalid provenance table in {path}")
    return board_sections, (provenance[0], provenance[1], provenance[2:])


def diagnostics_body(markdown, path):
    lines = markdown.splitlines()
    if not lines or DIAGNOSTICS_TITLE.fullmatch(lines[0]) is None:
        raise ValueError(f"unexpected diagnostics title in {path}")
    return "\n".join(lines[1:]).strip()


def compose_summary(results_root, scopes, report_status):
    reports = []
    introductions = []
    provenance_header = None
    provenance_rows = []
    for scope in scopes:
        scope_root = results_root / scope
        summary_path = scope_root / "summary.md"
        diagnostics_path = scope_root / "diagnostics.md"
        introduction = ""
        body = ""
        diagnostics = ""
        if summary_path.is_file() and summary_path.stat().st_size:
            introduction, body = split_performance_summary(
                summary_path.read_text(encoding="utf-8"), summary_path
            )
            body, provenance = split_provenance(body, summary_path)
            header = provenance[:2]
            if provenance_header is None:
                provenance_header = header
            elif provenance_header != header:
                raise ValueError(
                    f"provenance table headings disagree in {summary_path}"
                )
            for row in provenance[2]:
                if row not in provenance_rows:
                    provenance_rows.append(row)
            if introduction and introduction not in introductions:
                introductions.append(introduction)
        if diagnostics_path.is_file() and diagnostics_path.stat().st_size:
            diagnostics = diagnostics_body(
                diagnostics_path.read_text(encoding="utf-8"), diagnostics_path
            )
        reports.append((scope, body, diagnostics))

    lines = ["# TensorFlow Lite test results", ""]
    for introduction in introductions:
        lines.extend([introduction, ""])

    for scope, body, diagnostics in reports:
        lines.extend([f"## Report scope: {scope}", ""])
        if report_status[scope]["incomplete"]:
            lines.extend(
                [
                    (
                        "> **INCOMPLETE / UNAVAILABLE:** Some LAVA diagnostics "
                        "or results are missing; available details follow."
                    ),
                    "",
                ]
            )
        if body:
            lines.extend([shift_headings(body, 1), ""])
        else:
            lines.extend(
                [
                    (
                        "> **UNAVAILABLE:** A complete performance report could "
                        "not be generated for this scope."
                    ),
                    "",
                ]
            )
    if provenance_header is not None:
        lines.extend(
            [
                "## Provenance",
                "",
                provenance_header[0],
                provenance_header[1],
                *provenance_rows,
                "",
            ]
        )

    diagnostics_reports = [
        (scope, diagnostics) for scope, _, diagnostics in reports if diagnostics
    ]
    if diagnostics_reports:
        lines.extend(["## Diagnostics", ""])
        for scope, diagnostics in diagnostics_reports:
            lines.extend(
                [f"### Report scope: {scope}", "", shift_headings(diagnostics, 1), ""]
            )

    return "\n".join(lines).rstrip() + "\n"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compose the canonical all-board LAVA job summary"
    )
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--scope-matrix", type=Path, required=True)
    parser.add_argument("--report-status", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        scopes = load_scope_names(args.scope_matrix)
        report_status = load_report_status(args.report_status, scopes)
        summary = compose_summary(args.results_root, scopes, report_status)
        args.output.write_text(summary, encoding="utf-8")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
