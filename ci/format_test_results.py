#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import argparse
import json
from pathlib import Path


RESULT_KEYS = (
    "files",
    "suites",
    "duration",
    "tests",
    "tests_succ",
    "tests_skip",
    "tests_fail",
    "tests_error",
    "runs",
    "runs_succ",
    "runs_skip",
    "runs_fail",
    "runs_error",
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Format LAVA test and performance results for a GitHub check"
    )
    parser.add_argument("--test-results", type=Path, required=True)
    parser.add_argument("--performance-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_results(path):
    document = json.loads(path.read_text(encoding="utf-8"))
    results = document.get("stats")
    if not isinstance(results, dict):
        raise ValueError(f"invalid or missing stats in {path}")
    for key in RESULT_KEYS:
        value = results.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"invalid or missing {key} in {path}")
    return results


def format_duration(seconds):
    total = round(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def demote_headings(markdown):
    lines = []
    for line in markdown.splitlines():
        heading = len(line) - len(line.lstrip("#"))
        if 0 < heading < 6 and line[heading : heading + 1] == " ":
            line = f"#{line}"
        lines.append(line)
    return "\n".join(lines)


def format_summary(results, performance_summary):
    duration = format_duration(results["duration"])
    lines = [
        "## LAVA test results",
        "",
        "| Metric | Total | Passed | Skipped | Failed | Errors |",
        "|:---|---:|---:|---:|---:|---:|",
        (
            f"| Unique tests | {results['tests']} | {results['tests_succ']} | "
            f"{results['tests_skip']} | {results['tests_fail']} | "
            f"{results['tests_error']} |"
        ),
        (
            f"| Test runs | {results['runs']} | {results['runs_succ']} | "
            f"{results['runs_skip']} | {results['runs_fail']} | "
            f"{results['runs_error']} |"
        ),
        "",
        (
            f"**Duration:** {duration} across {results['files']} result files and "
            f"{results['suites']} test suites."
        ),
        "",
        (
            "**Legend:** Passed = completed successfully; Skipped = intentionally "
            "not run; Failed = a test assertion failed; Errors = the test could not "
            "complete. Test runs include repeated tests across boards."
        ),
        "",
        "---",
        "",
        demote_headings(performance_summary).rstrip(),
        "",
    ]
    return "\n".join(lines)


def main():
    args = parse_args()
    results = load_results(args.test_results)
    performance_summary = args.performance_summary.read_text(encoding="utf-8")
    args.output.write_text(
        format_summary(results, performance_summary),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
