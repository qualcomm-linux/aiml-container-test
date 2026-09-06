#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import csv
import importlib.util
import json
import shutil
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
        messages = [
            "AIML_PROVENANCE kernel=7.2.0-test",
            "AIML_PROVENANCE qairt=2.47.0 "
            f"tflite_commit={'f' * 40} configuration_version=3 threads=8 "
            "timeout_seconds=360 op_profiling=1 outer_warmup_runs=1 "
            "outer_sample_count=10 benchmark_warmup_runs=10 "
            "benchmark_warmup_min_secs=1 benchmark_num_runs=100 "
            "benchmark_min_secs=3 benchmark_max_secs=150 "
            "label_image_warmup_runs=10 label_image_count=100",
            "MODEL model_id=mobilenet-quant-v1-224 "
            f"sha256={'a' * 64} path=/model.tflite",
            "INPUT test_case_prefix=tflite-label-image "
            f"sha256={'b' * 64} path=/input.bmp",
        ]
        messages.extend(
            self.diagnostic_messages("tflite-label-image-cpu", 30.5, False)
        )
        messages.extend(
            self.diagnostic_messages(
                "tflite-benchmark-mobilenet-quant-v1-224-cpu",
                100.25,
                True,
            )
        )
        messages.extend(
            [
                "LAVA_RESULT test_case_id=tflite-label-image-cpu "
                "measurement=30.5 units=ms result=pass record_end=1",
                "LAVA_RESULT test_case_id=tflite-label-image-gpu "
                "result=fail record_end=1",
                "LAVA_RESULT "
                "test_case_id=tflite-benchmark-mobilenet-quant-v1-224-cpu "
                "measurement=100.25 units=ms result=pass record_end=1",
            ]
        )
        (self.input_dir / "job-42.yaml").write_text(
            "\n".join(
                f"- {json.dumps({'dt': '2026-09-03T12:00:00', 'lvl': 'target', 'msg': message})}"
                for message in messages
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
        self.assertIn("workflow attempt 2", summary)
        self.assertIn("publication attempt 1", summary)
        self.assertIn("`7.2.0-test`", summary)
        self.assertIn("| GPU | fail | N/A |", summary)

        with (self.output_dir / "results.csv").open(
            newline="", encoding="utf-8"
        ) as source:
            rows = list(csv.DictReader(source))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["model_sha256"], "a" * 64)
        self.assertEqual(rows[0]["sample_count"], "10")
        self.assertEqual(json.loads(rows[0]["samples"]), [30.5] * 10)
        self.assertEqual(rows[0]["trimmed_mean"], "30.5")
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
        self.assertEqual(results["schema_version"], 2)
        self.assertEqual(results["boards"][0]["qairt"], "2.47.0")
        self.assertEqual(results["boards"][0]["kernel"], "7.2.0-test")
        self.assertEqual(
            results["boards"][0]["actual_device"], "test-device-01"
        )
        self.assertEqual(results["boards"][0]["tflite_commit"], "f" * 40)
        self.assertEqual(
            results["boards"][0]["test_configuration"]["version"], 3
        )
        self.assertTrue(
            results["boards"][0]["test_configuration"]["op_profiling"]
        )
        label_result = results["boards"][0]["results"][0]
        self.assertEqual(len(label_result["samples"]), 10)
        self.assertEqual(label_result["statistics"]["trimmed_mean"], 30.5)
        self.assertEqual(label_result["statistics"]["stability"], "stable")
        self.assertEqual(
            label_result["telemetry"]["before"]["cpu_online"], "0-3"
        )
        benchmark_result = results["boards"][0]["results"][2]
        self.assertEqual(benchmark_result["samples"][0]["inner"]["count"], 100)
        self.assertEqual(
            benchmark_result["samples"][0]["inner"]["median_us"], 101.0
        )

    def test_compares_matching_measurements_across_configuration_changes(self):
        boards = REPORT.load_jobs(
            self.input_dir,
            REPORT.load_board_map(self.boards_file),
            "https://lava.example.com",
        )
        previous = {
            "schema_version": 2,
            "suite": "trixie",
            "provenance": self.provenance(),
            "boards": [
                {
                    "id": "test-board",
                    "actual_device": "test-device-01",
                    "test_configuration": {
                        "version": 3,
                        "threads": 4,
                        "timeout_seconds": 120,
                        "op_profiling": False,
                    },
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
        self.assertEqual(
            REPORT.test_configuration_changes(
                boards[0], previous["boards"][0]
            ),
            [
                "threads: `4` -> `8`",
                "timeout: `120 s` -> `360 s`",
                "operator profiling: `disabled` -> `enabled`",
                "outer warm-up runs: `N/A` -> `1`",
                "outer sample count: `N/A` -> `10`",
                "benchmark warm-up runs: `N/A` -> `10`",
                "benchmark warm-up minimum: `N/A` -> `1 s`",
                "benchmark runs: `N/A` -> `100`",
                "benchmark minimum: `N/A` -> `3 s`",
                "benchmark maximum: `N/A` -> `150 s`",
                "label-image warm-up runs: `N/A` -> `10`",
                "label-image count: `N/A` -> `100`",
            ],
        )
        self.assertEqual(
            boards[0]["results"][0]["comparison_scope"], "same-dut"
        )

    def test_old_single_sample_baseline_is_non_comparable(self):
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
                    "actual_device": "test-device-01",
                    "test_configuration": {"version": 3},
                    "results": [
                        {
                            **boards[0]["results"][0],
                            "measurement": 25.0,
                        }
                    ],
                }
            ],
        }

        REPORT.add_comparisons(boards, previous, "trixie")

        result = boards[0]["results"][0]
        self.assertEqual(result["comparison_status"], "method-changed")
        self.assertIsNone(result["previous_measurement"])
        self.assertIsNone(result["change_percent"])

    def test_cross_dut_fallback_is_visibly_labeled(self):
        boards = REPORT.load_jobs(
            self.input_dir,
            REPORT.load_board_map(self.boards_file),
            "https://lava.example.com",
        )
        previous = {
            "schema_version": 2,
            "suite": "trixie",
            "provenance": self.provenance(),
            "boards": [
                {
                    "id": "test-board",
                    "actual_device": "other-device-99",
                    "test_configuration": boards[0]["test_configuration"],
                    "results": [
                        {
                            **boards[0]["results"][0],
                            "measurement": 25.0,
                        }
                    ],
                }
            ],
        }

        previous_boards = REPORT.add_comparisons(boards, previous, "trixie")
        summary = self.root / "cross-dut.md"
        REPORT.write_summary(
            summary,
            boards,
            self.provenance(),
            previous,
            previous_boards,
        )

        result = boards[0]["results"][0]
        self.assertEqual(result["comparison_scope"], "cross-dut")
        self.assertEqual(result["comparison_status"], "compared")
        self.assertIn("**cross-DUT**", summary.read_text(encoding="utf-8"))

    def test_incomplete_samples_and_measurement_mismatch_are_rejected(self):
        log_path = self.input_dir / "job-42.yaml"
        original = log_path.read_text(encoding="utf-8")
        log_path.write_text(
            "\n".join(
                line
                for line in original.splitlines()
                if "index=10 " not in line
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "has 9 samples"):
            REPORT.load_jobs(
                self.input_dir,
                REPORT.load_board_map(self.boards_file),
                "https://lava.example.com",
            )

        log_path.write_text(original, encoding="utf-8")
        tests_path = self.input_dir / "job-42-tests.csv"
        contents = tests_path.read_text(encoding="utf-8")
        tests_path.write_text(
            contents.replace("30.5,ms", "31.5,ms", 1),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "does not match trimmed mean"):
            REPORT.load_jobs(
                self.input_dir,
                REPORT.load_board_map(self.boards_file),
                "https://lava.example.com",
            )

    def test_prefixed_child_diagnostics_cannot_impersonate_records(self):
        log_path = self.input_dir / "job-42.yaml"
        entry = {
            "dt": "2026-09-03T12:00:04",
            "lvl": "target",
            "msg": (
                "TFLITE_OUTPUT AIML_SAMPLE "
                "test_case_id=tflite-label-image-cpu index=11 "
                "measurement=999 units=ms"
            ),
        }
        with log_path.open("a", encoding="utf-8") as destination:
            destination.write(f"\n- {json.dumps(entry)}")

        boards = REPORT.load_jobs(
            self.input_dir,
            REPORT.load_board_map(self.boards_file),
            "https://lava.example.com",
        )

        self.assertEqual(len(boards[0]["results"][0]["samples"]), 10)

    def test_raw_result_parser_accepts_protocol_carriage_return(self):
        results = REPORT.parse_lava_results(
            [
                "LAVA_RESULT test_case_id=tflite-label-image-cpu "
                "measurement=30.5 units=ms result=pass record_end=1\r"
            ]
        )

        self.assertEqual(results["tflite-label-image-cpu"]["result"], "pass")

    def test_reads_old_report_for_context(self):
        previous_path = self.root / "previous.json"
        previous_path.write_text(
            json.dumps({"schema_version": 1, "boards": []}),
            encoding="utf-8",
        )

        self.assertEqual(REPORT.read_previous(previous_path)["schema_version"], 1)

    def test_statistics_use_sample_variance_and_flag_instability(self):
        statistics = REPORT.calculate_statistics(
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        )

        self.assertEqual(statistics["discarded_low"], 1)
        self.assertEqual(statistics["discarded_high"], 10)
        self.assertEqual(statistics["raw_mean"], 5.5)
        self.assertEqual(statistics["trimmed_mean"], 5.5)
        self.assertEqual(statistics["median"], 5.5)
        self.assertEqual(statistics["mad"], 2.5)
        self.assertAlmostEqual(statistics["raw_variance"], 55 / 6)
        self.assertEqual(statistics["trimmed_variance"], 6)

        message = (
            "AIML_STATS test_case_id=case count=10 discarded_low=1 "
            "discarded_high=10 raw_mean=5.5 trimmed_mean=5.5 median=5.5 "
            "mad=2.5 raw_variance=9.166666667 raw_stddev=3.027650354 "
            "raw_cv=0.550481883 trimmed_variance=6 "
            "trimmed_stddev=2.449489743 trimmed_cv=0.445361771 units=ms"
        )
        parsed = REPORT.parse_diagnostics([message])
        self.assertEqual(parsed["case"]["statistics"]["stability"], "unstable")

    def test_reports_when_aiml_tests_did_not_run(self):
        with (self.input_dir / "job-42-tests.csv").open(
            "w", newline="", encoding="utf-8"
        ) as destination:
            writer = csv.DictWriter(
                destination,
                fieldnames=["name", "suite", "result", "measurement", "unit"],
            )
            writer.writeheader()

        with self.assertRaisesRegex(
            ValueError, "missing=.*tflite-label-image-cpu"
        ):
            REPORT.load_jobs(
                self.input_dir,
                REPORT.load_board_map(self.boards_file),
                "https://lava.example.com",
            )

    def test_rejects_lava_api_omissions(self):
        tests_path = self.input_dir / "job-42-tests.csv"
        with tests_path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            rows = list(reader)
            fieldnames = reader.fieldnames
        with tests_path.open("w", newline="", encoding="utf-8") as destination:
            writer = csv.DictWriter(destination, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows[1:])

        with self.assertRaisesRegex(
            ValueError, "missing=.*tflite-label-image-cpu"
        ):
            REPORT.load_jobs(
                self.input_dir,
                REPORT.load_board_map(self.boards_file),
                "https://lava.example.com",
            )

    def test_rejects_missing_current_configuration_version(self):
        log_path = self.input_dir / "job-42.yaml"
        log_path.write_text(
            log_path.read_text(encoding="utf-8").replace(
                " configuration_version=3", ""
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError, "configuration version None; expected 3"
        ):
            REPORT.load_jobs(
                self.input_dir,
                REPORT.load_board_map(self.boards_file),
                "https://lava.example.com",
            )

    def test_uses_only_latest_lava_retry_results(self):
        (self.input_dir / "job-41.json").write_text(
            json.dumps(
                {
                    "id": 41,
                    "requested_device_type": "test-device",
                    "actual_device": "test-device-old",
                }
            ),
            encoding="utf-8",
        )
        (self.input_dir / "job-41.yaml").write_text("", encoding="utf-8")
        with (self.input_dir / "job-41-tests.csv").open(
            "w", newline="", encoding="utf-8"
        ) as destination:
            writer = csv.DictWriter(
                destination,
                fieldnames=["name", "suite", "result", "measurement", "unit"],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "name": "tflite-label-image-cpu",
                    "suite": "2_aiml-container-smoke",
                    "result": "pass",
                    "measurement": "999",
                    "unit": "ms",
                }
            )

        boards = REPORT.load_jobs(
            self.input_dir,
            REPORT.load_board_map(self.boards_file),
            "https://lava.example.com",
        )

        self.assertEqual([job["id"] for job in boards[0]["lava_jobs"]], [41, 42])
        self.assertEqual(boards[0]["actual_device"], "test-device-01")
        self.assertEqual(boards[0]["results"][0]["measurement"], 30.5)

    def test_keeps_monza_and_imola_devices_distinct(self):
        repository_boards = Path(__file__).parents[2] / "ci/boards.json"
        self.boards_file.write_text(
            repository_boards.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (self.input_dir / "job-42.json").write_text(
            json.dumps(
                {
                    "id": 42,
                    "requested_device_type": "monaco-arduino-monza",
                    "actual_device": "monza-01",
                }
            ),
            encoding="utf-8",
        )
        (self.input_dir / "job-43.json").write_text(
            json.dumps(
                {
                    "id": 43,
                    "requested_device_type": "qrb2210-arduino-imola",
                    "actual_device": "unoq-04",
                }
            ),
            encoding="utf-8",
        )
        shutil.copyfile(
            self.input_dir / "job-42.yaml", self.input_dir / "job-43.yaml"
        )
        shutil.copyfile(
            self.input_dir / "job-42-tests.csv",
            self.input_dir / "job-43-tests.csv",
        )

        self.run_report()
        report = json.loads(
            (self.output_dir / "results.json").read_text(encoding="utf-8")
        )
        boards = report["boards"]
        summary = (self.output_dir / "summary.md").read_text(encoding="utf-8")

        self.assertEqual(
            [(board["id"], board["actual_device"]) for board in boards],
            [
                ("qrb2210-arduino-imola", "unoq-04"),
                ("monaco-arduino-monza", "monza-01"),
            ],
        )
        self.assertIn("## Arduino UNO Q", summary)
        self.assertIn("## Arduino VENTUNO Q", summary)
        self.assertIn("`unoq-04`", summary)
        self.assertIn("`monza-01`", summary)

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
                "2",
                "--qcom-publication-attempt",
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
    def diagnostic_messages(test_case_id, measurement, benchmark):
        inner = (
            "inner_count=100 inner_min_us=100 inner_max_us=102 "
            "inner_avg_us=101 inner_stddev_us=1 inner_median_us=101 "
            "inner_p5_us=100 inner_p95_us=102"
            if benchmark
            else "inner_count=100 inner_min_us=na inner_max_us=na "
            "inner_avg_us=na inner_stddev_us=na inner_median_us=na "
            "inner_p5_us=na inner_p95_us=na"
        )
        messages = [
            f"AIML_TELEMETRY test_case_id={test_case_id} phase=before "
            "cpu_online=0-3 scaling_governors=policy0:performance "
            "scaling_current_khz=policy0:1800000 "
            "policy_frequencies_khz=policy0:300000-1800000 "
            "load=0.10,0.20,0.30 thermal_millicelsius=thermal_zone0:cpu:42000",
            f"AIML_WARMUP test_case_id={test_case_id} "
            f"measurement={measurement} units=ms {inner}",
        ]
        messages.extend(
            f"AIML_SAMPLE test_case_id={test_case_id} index={index} "
            f"measurement={measurement} units=ms {inner}"
            for index in range(1, 11)
        )
        messages.extend(
            [
                f"AIML_TELEMETRY test_case_id={test_case_id} phase=after "
                "cpu_online=0-3 scaling_governors=policy0:performance "
                "scaling_current_khz=policy0:1800000 "
                "policy_frequencies_khz=policy0:300000-1800000 "
                "load=0.20,0.20,0.30 "
                "thermal_millicelsius=thermal_zone0:cpu:43000",
                f"AIML_STATS test_case_id={test_case_id} count=10 "
                f"discarded_low={measurement} discarded_high={measurement} "
                f"raw_mean={measurement} trimmed_mean={measurement} "
                f"median={measurement} mad=0 raw_variance=0 raw_stddev=0 "
                "raw_cv=0 trimmed_variance=0 trimmed_stddev=0 trimmed_cv=0 "
                "units=ms",
            ]
        )
        return messages

    @staticmethod
    def provenance():
        return {
            "qcom_deb_images": {
                "workflow": ".github/workflows/build.yml",
                "event": "workflow_run",
                "ref": "main",
                "sha": "c" * 40,
                "run_id": 10,
                "run_attempt": 2,
                "publication_attempt": 1,
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
