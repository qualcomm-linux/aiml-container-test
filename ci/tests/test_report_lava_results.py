#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "report_lava_results.py"
SPEC = importlib.util.spec_from_file_location("report_lava_results", SCRIPT)
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


class ReportLavaResultsTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.input_dir = self.root / "input"
        self.output_dir = self.root / "output"
        self.input_dir.mkdir()

        self.boards_file = self.root / "boards.json"
        self.boards_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "boards": {
                        "test-board": {
                            "display_name": "Test Board",
                            "device_types": ["test-device"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        (self.input_dir / "job-42.json").write_text(
            json.dumps(
                {
                    "id": 42,
                    "requested_device_type": "test-device",
                    "actual_device": "test-device-01",
                }
            ),
            encoding="utf-8",
        )
        (self.input_dir / "job-42.yaml").write_text(
            "\n".join(
                [
                    '- {"dt": "2026-09-03T12:00:00", "lvl": "target", '
                    '"msg": "AIML_PROVENANCE kernel=7.2.0-test"}',
                    '- {"dt": "2026-09-03T12:00:01", "lvl": "target", '
                    '"msg": "AIML_PROVENANCE qairt=2.47.0 '
                    f"tflite_commit={'f' * 40} configuration_version=1 threads=8 "
                    'timeout_seconds=300 op_profiling=1"}',
                    '- {"dt": "2026-09-03T12:00:02", "lvl": "target", '
                    '"msg": "MODEL model_id=mobilenet-quant-v1-224 '
                    f"sha256={'a' * 64} path=/model.tflite"
                    '"}',
                    '- {"dt": "2026-09-03T12:00:03", "lvl": "target", '
                    '"msg": "INPUT test_case_prefix=tflite-label-image '
                    f"sha256={'b' * 64} path=/input.bmp"
                    '"}',
                ]
            ),
            encoding="utf-8",
        )
        with (self.input_dir / "job-42-tests.csv").open(
            "w", newline="", encoding="utf-8"
        ) as destination:
            writer = csv.DictWriter(
                destination,
                fieldnames=[
                    "name",
                    "suite",
                    "result",
                    "measurement",
                    "unit",
                ],
            )
            writer.writeheader()
            writer.writerows(
                [
                    {
                        "name": "tflite-label-image-cpu",
                        "suite": "2_aiml-container-smoke",
                        "result": "pass",
                        "measurement": "30.5",
                        "unit": "ms",
                    },
                    {
                        "name": "tflite-label-image-gpu",
                        "suite": "2_aiml-container-smoke",
                        "result": "fail",
                        "measurement": "None",
                        "unit": "",
                    },
                    {
                        "name": "tflite-benchmark-mobilenet-quant-v1-224-cpu",
                        "suite": "2_aiml-container-smoke",
                        "result": "pass",
                        "measurement": "100.25",
                        "unit": "ms",
                    },
                ]
            )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_generates_graph_and_machine_readable_results(self):
        self.run_report()

        summary = (self.output_dir / "summary.md").read_text(encoding="utf-8")
        self.assertIn('x-axis ["LI CPU", "BM CPU"]', summary)
        self.assertIn("bar [30.5, 100.25]", summary)
        self.assertNotIn("bar [30.5, 0", summary)
        self.assertIn("`main@cccccccccccc`", summary)
        self.assertIn("`7.2.0-test`", summary)
        self.assertIn("| GPU | fail | N/A |", summary)

        with (self.output_dir / "results.csv").open(
            newline="", encoding="utf-8"
        ) as source:
            rows = list(csv.DictReader(source))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["model_sha256"], "a" * 64)
        self.assertTrue(
            (self.output_dir / "raw-logs/test-board-42.yaml").is_file()
        )
        self.assertEqual(
            {path.name for path in self.output_dir.iterdir()},
            {"results.json", "results.csv", "raw-logs", "summary.md"},
        )
        results = json.loads(
            (self.output_dir / "results.json").read_text(encoding="utf-8")
        )
        self.assertEqual(results["schema_version"], 1)
        self.assertEqual(results["boards"][0]["qairt"], "2.47.0")
        self.assertEqual(results["boards"][0]["kernel"], "7.2.0-test")
        self.assertEqual(results["boards"][0]["tflite_commit"], "f" * 40)
        self.assertEqual(
            results["boards"][0]["test_configuration"]["version"], 1
        )
        self.assertTrue(
            results["boards"][0]["test_configuration"]["op_profiling"]
        )

    def test_compares_only_compatible_measurements(self):
        boards = REPORT.load_jobs(
            self.input_dir,
            REPORT.load_board_map(self.boards_file),
            "https://lava.example.com",
        )
        previous = {
            "schema_version": 1,
            "suite": "trixie",
            "provenance": self.provenance(),
            "boards": [
                {
                    "id": "test-board",
                    "test_configuration": boards[0]["test_configuration"],
                    "results": [
                        {
                            **boards[0]["results"][0],
                            "measurement": 25.0,
                        },
                        {
                            **boards[0]["results"][2],
                            "measurement": 80.0,
                            "model_sha256": "different",
                        },
                    ],
                }
            ],
        }

        REPORT.add_comparisons(boards, previous, "trixie")

        self.assertEqual(boards[0]["results"][0]["previous_measurement"], 25.0)
        self.assertEqual(boards[0]["results"][0]["change_percent"], 22.0)
        self.assertIsNone(boards[0]["results"][2]["previous_measurement"])

    def run_report(self):
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--input-dir",
                str(self.input_dir),
                "--output-dir",
                str(self.output_dir),
                "--boards",
                str(self.boards_file),
                "--suite",
                "trixie",
                "--lava-url",
                "https://lava.example.com",
                "--qcom-run-id",
                "10",
                "--qcom-run-attempt",
                "1",
                "--qcom-workflow",
                ".github/workflows/build.yml",
                "--qcom-event",
                "workflow_run",
                "--qcom-ref",
                "main",
                "--qcom-sha",
                "c" * 40,
                "--aiml-repository",
                "qualcomm-linux/aiml-container-test",
                "--aiml-ref",
                "feature",
                "--aiml-sha",
                "d" * 40,
                "--aiml-run-id",
                "20",
                "--aiml-run-attempt",
                "1",
                "--container-digest",
                f"sha256:{'e' * 64}",
            ],
            check=True,
        )

    @staticmethod
    def provenance():
        return {
            "qcom_deb_images": {
                "workflow": ".github/workflows/build.yml",
                "event": "workflow_run",
                "ref": "main",
                "sha": "c" * 40,
                "run_id": 10,
            },
            "aiml_container": {
                "repository": "qualcomm-linux/aiml-container-test",
                "ref": "feature",
                "sha": "d" * 40,
                "run_id": 20,
                "digest": f"sha256:{'e' * 64}",
            },
        }


if __name__ == "__main__":
    unittest.main()
