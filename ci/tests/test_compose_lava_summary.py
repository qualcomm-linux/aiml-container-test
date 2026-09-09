#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "compose_lava_summary.py"
SPEC = importlib.util.spec_from_file_location("compose_lava_summary", SCRIPT)
COMPOSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPOSER)

INTRODUCTION = (
    "Lower latency is better. Every graph uses a linear Y axis starting at zero.\n\n"
    "A trimmed coefficient of variation (CV) of 5% or more is marked **unstable**."
)


class ComposeLavaSummaryTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.results_root = Path(self.temporary_directory.name)
        self.scopes = ("generic", "arduino")
        for scope in self.scopes:
            (self.results_root / scope).mkdir()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_scope(self, scope, boards, provenance):
        lines = ["# TensorFlow Lite performance", "", INTRODUCTION, ""]
        for board in boards:
            lines.extend(
                [
                    f"## {board}",
                    "",
                    "**Test results:** 14 passed, 0 failed, 14 total.",
                    "",
                    "```mermaid",
                    "xychart-beta",
                    f'    title "{board} TensorFlow Lite latency"',
                    "    bar [1, 2]",
                    "```",
                    "",
                    "| Test | Result |",
                    "|---|---:|",
                    "| `label-image` | pass |",
                    "",
                ]
            )
        lines.extend(
            [
                "## Provenance",
                "",
                "| Board | LAVA job |",
                "|---|---|",
                f"| {', '.join(boards)} | {provenance} |",
                "",
            ]
        )
        (self.results_root / scope / "summary.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )
        (self.results_root / scope / "diagnostics.md").write_text(
            f"# LAVA report diagnostics: {scope}\n\n"
            f"- Expected boards: `{'+'.join(boards)}`\n"
            "- Execution statuses validated: 2 of 2 expected\n",
            encoding="utf-8",
        )

    def test_renders_one_clean_all_board_report(self):
        self.write_scope("generic", ("RB1", "RB3Gen2"), "406437, 406434")
        self.write_scope(
            "arduino",
            ("Arduino UNO Q", "Arduino VENTUNO Q"),
            "406435, 406436",
        )
        report_status = {
            "generic": {"incomplete": False},
            "arduino": {"incomplete": False},
        }

        summary = COMPOSER.compose_summary(
            self.results_root, self.scopes, report_status
        )

        self.assertEqual(summary.count("# TensorFlow Lite test results"), 1)
        self.assertNotIn("# TensorFlow Lite performance", summary)
        self.assertEqual(summary.count(INTRODUCTION), 1)
        self.assertEqual(summary.count("```mermaid"), 4)
        self.assertEqual(summary.count("**Test results:**"), 4)
        self.assertEqual(summary.count("## Provenance"), 1)
        self.assertEqual(summary.count("| Board | LAVA job |"), 1)
        self.assertEqual(summary.count("## Diagnostics"), 1)
        self.assertNotIn("## LAVA test results", summary)
        self.assertNotIn("check-summary", summary)
        summary_lines = summary.splitlines()
        for scope in self.scopes:
            self.assertEqual(summary_lines.count(f"## Report scope: {scope}"), 1)
            self.assertEqual(summary_lines.count(f"### Report scope: {scope}"), 1)
            self.assertEqual(
                summary.count(f"# LAVA report diagnostics: {scope}"), 0
            )
        for board in ("RB1", "RB3Gen2", "Arduino UNO Q", "Arduino VENTUNO Q"):
            self.assertEqual(summary.count(f"### {board}\n"), 1)
        for job_id in ("406437", "406434", "406435", "406436"):
            self.assertEqual(summary.count(job_id), 1)

    def test_marks_incomplete_scope_without_repeating_diagnostics_title(self):
        self.write_scope("generic", ("RB1", "RB3Gen2"), "406437, 406434")
        report_status = {"generic": {"incomplete": True}}

        summary = COMPOSER.compose_summary(
            self.results_root, ("generic",), report_status
        )

        self.assertEqual(summary.count("INCOMPLETE / UNAVAILABLE"), 1)
        self.assertEqual(summary.count("## Diagnostics"), 1)


if __name__ == "__main__":
    unittest.main()
