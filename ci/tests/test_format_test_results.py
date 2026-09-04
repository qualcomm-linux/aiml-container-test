#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "format_test_results.py"
SPEC = importlib.util.spec_from_file_location("format_test_results", SCRIPT)
FORMATTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FORMATTER)


class FormatTestResultsTest(unittest.TestCase):
    def test_formats_table_legend_and_performance_graph(self):
        document = {
            "title": "All 28 tests pass in 14m 16s",
            "stats": {
                "files": 2,
                "suites": 8,
                "duration": 856,
                "tests": 28,
                "tests_succ": 28,
                "tests_skip": 0,
                "tests_fail": 0,
                "tests_error": 0,
                "runs": 70,
                "runs_succ": 69,
                "runs_skip": 1,
                "runs_fail": 0,
                "runs_error": 0,
            },
        }
        performance = "\n".join(
            [
                "# TensorFlow Lite performance",
                "",
                "## Test Board",
                "",
                "```mermaid",
                "xychart-beta",
                "    bar [1, 2]",
                "```",
            ]
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            results_path = Path(temporary_directory) / "results.json"
            results_path.write_text(json.dumps(document), encoding="utf-8")
            results = FORMATTER.load_results(results_path)

        summary = FORMATTER.format_summary(results, performance)

        self.assertIn(
            "| Metric | Total | Passed | Skipped | Failed | Errors |", summary
        )
        self.assertIn("| Unique tests | 28 | 28 | 0 | 0 | 0 |", summary)
        self.assertIn("| Test runs | 70 | 69 | 1 | 0 | 0 |", summary)
        self.assertIn("**Duration:** 14m 16s", summary)
        self.assertIn("**Legend:** Passed =", summary)
        self.assertIn("## TensorFlow Lite performance", summary)
        self.assertIn("### Test Board", summary)
        self.assertIn("```mermaid", summary)
        self.assertNotRegex(summary, "[✅❌💤🔥⏱]")


if __name__ == "__main__":
    unittest.main()
