#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "compare_performance.py"
SPEC = importlib.util.spec_from_file_location("compare_performance", SCRIPT)
COMPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPARE)


class ComparePerformanceTest(unittest.TestCase):
    def test_combines_scoped_reports_into_svg_and_table(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            output_dir = root / "output"
            self.write_report(input_dir / "generic", "rb1", "RB1", 30.5)
            self.write_report(input_dir / "arduino", "ventuno", "VENTUNO Q", 40)

            suite, container, boards = COMPARE.load_reports(input_dir)
            output_dir.mkdir()
            COMPARE.write_svg(output_dir / "comparison.svg", boards)
            COMPARE.write_summary(
                output_dir / "summary.md", suite, container, boards
            )

            svg = (output_dir / "comparison.svg").read_text(encoding="utf-8")
            summary = (output_dir / "summary.md").read_text(encoding="utf-8")
            self.assertIn("TensorFlow Lite latency by board", svg)
            self.assertIn("30.5 ms", svg)
            self.assertIn("N/A", svg)
            self.assertIn(
                "| Label image | CPU | **30.5 ms** | 40 ms |", summary
            )
            self.assertIn(
                "**Bold** marks the lowest measured latency in each row.",
                summary,
            )
            self.assertIn("`aabbccddeeff`", summary)

    def write_report(self, directory, board_id, board_name, measurement):
        directory.mkdir(parents=True)
        report = {
            "schema_version": 1,
            "suite": "trixie",
            "provenance": {
                "aiml_container": {
                    "sha": "aabbccddeeff00112233445566778899aabbccdd",
                    "digest": f"sha256:{'1' * 64}",
                }
            },
            "boards": [
                {
                    "id": board_id,
                    "name": board_name,
                    "results": [
                        {
                            "workload": "label_image",
                            "accelerator": "cpu",
                            "result": "pass",
                            "measurement": measurement,
                            "unit": "ms",
                        }
                    ],
                }
            ],
        }
        (directory / "results.json").write_text(
            json.dumps(report), encoding="utf-8"
        )


if __name__ == "__main__":
    unittest.main()
