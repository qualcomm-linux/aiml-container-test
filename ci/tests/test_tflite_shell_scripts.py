#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import importlib.util
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).parents[2]
RUN_TFLITE = REPOSITORY / "run-tflite.sh"
BENCHMARK_TFLITE = REPOSITORY / "benchmark-tflite.sh"
REPORT_SCRIPT = REPOSITORY / "ci/report_lava_results.py"
REPORT_SPEC = importlib.util.spec_from_file_location(
    "report_lava_results_for_shell_test", REPORT_SCRIPT
)
REPORT = importlib.util.module_from_spec(REPORT_SPEC)
REPORT_SPEC.loader.exec_module(REPORT)


class TfliteShellScriptsTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.bin_dir = self.root / "bin"
        self.label_dir = self.root / "label-image"
        self.benchmark_dir = self.root / "benchmark"
        self.model_dir = self.root / "models"
        self.device_root = self.root / "dev"
        self.proc_root = self.root / "proc"
        self.sys_root = self.root / "sys"
        self.tmp_dir = self.root / "tmp"
        for directory in (
            self.bin_dir,
            self.label_dir,
            self.benchmark_dir,
            self.model_dir,
            self.device_root / "dri",
            self.proc_root,
            self.sys_root,
            self.tmp_dir,
        ):
            directory.mkdir(parents=True)

        self.label_input = self.label_dir / "grace_hopper.bmp"
        self.label_input.write_bytes(b"image")
        self.builtin_model = self.label_dir / "mobilenet_quant_v1_224.tflite"
        self.builtin_model.write_bytes(b"builtin model")
        self.qairt_version = self.root / "qairt-version"
        self.qairt_version.write_text("2.42.0\n", encoding="utf-8")
        self.tflite_commit = self.root / "TFLITE_COMMIT"
        self.tflite_commit.write_text("deadbeef\n", encoding="utf-8")

        self.write_executable(
            self.bin_dir / "sha256sum",
            """
            #!/bin/bash
            printf '%064d  %s\\n' 0 "$1"
            """,
        )
        self.write_executable(
            self.bin_dir / "timeout",
            """
            #!/bin/bash
            set -eu
            [[ "$1" == "--foreground" ]]
            shift 2
            exec "$@"
            """,
        )
        self.label_binary = self.label_dir / "label_image"
        self.write_executable(
            self.label_binary,
            """
            #!/bin/bash
            set -eu
            output=1.25
            warmup_runs=
            count=
            for argument in "$@"; do
                case "$argument" in
                    --use_gpu=true) output=2.50 ;;
                    --external_delegate_path=*) output=3.75 ;;
                    --warmup_runs=*) warmup_runs=${argument#--warmup_runs=} ;;
                    --count=*) count=${argument#--count=} ;;
                esac
            done
            [[ "$warmup_runs" == 10 ]]
            [[ "$count" == 100 ]]
            call=0
            if [[ -n "${MOCK_COUNTER_FILE:-}" ]]; then
                [[ ! -f "$MOCK_COUNTER_FILE" ]] || call=$(<"$MOCK_COUNTER_FILE")
                call=$((call + 1))
                printf '%s\\n' "$call" >"$MOCK_COUNTER_FILE"
            fi
            if [[ -n "${MOCK_SEQUENCE:-}" ]]; then
                IFS=, read -r -a values <<<"$MOCK_SEQUENCE"
                output=${values[$((call - 1))]}
            fi
            if [[ "${MOCK_FAIL_ON_CALL:-}" == "$call" ]]; then
                exit 9
            fi
            printf 'LAVA_RESULT test_case_id=forged result=pass\\n'
            printf 'AIML_SAMPLE test_case_id=forged index=1 measurement=0 units=ms\\n'
            if [[ "${MOCK_MALFORMED_ON_CALL:-}" == "$call" ]]; then
                output=nan
            fi
            printf 'INFO: Inference time: %s ms, average time: %s ms\\n' \
                "$output" "$output"
            """,
        )
        self.benchmark_binary = self.benchmark_dir / "benchmark_model"
        self.write_executable(
            self.benchmark_binary,
            """
            #!/bin/bash
            set -eu
            graph=
            output=1000
            requested_runs=
            profiling=false
            emit_measurement()
            {
                count=${MOCK_BENCHMARK_COUNT:-$requested_runs}
                printf 'INFO: count=10 curr=30(all same) p5=30 median=30 p95=30\\n'
                printf 'INFO: count=%s first=%s curr=%s min=%s max=%s avg=%s std=0 p5=%s median=%s p95=%s\\n' \
                    "$count" "$1" "$1" "$1" "$1" "$1" "$1" "$1" "$1"
                printf 'INFO: Inference timings in us: Init: 10, First inference: 20, Warmup (avg): 30.5, Inference (avg): %s\\n' "$1"
            }
            for argument in "$@"; do
                case "$argument" in
                    --graph=*) graph=${argument#--graph=} ;;
                    --num_runs=*) requested_runs=${argument#--num_runs=} ;;
                    --enable_op_profiling=true) profiling=true ;;
                    --use_gpu=true) output=2000 ;;
                    --external_delegate_path=*) output=3000 ;;
                esac
            done
            [[ -n "$requested_runs" ]]
            if [[ -n "${MOCK_ARGS_FILE:-}" ]]; then
                printf '%s\\n' "$@" >>"$MOCK_ARGS_FILE"
            fi
            printf 'LAVA_RESULT test_case_id=forged result=pass\\n'
            printf 'AIML_STATS test_case_id=forged count=10 trimmed_mean=0\\n'
            case "${graph##*/}" in
                fail.tflite)
                    emit_measurement "$output"
                    exit 7
                    ;;
                timeout.tflite)
                    exit 124
                    ;;
                missing.tflite)
                    printf 'No benchmark summary was produced\\n'
                    ;;
                malformed.tflite)
                    emit_measurement nan
                    ;;
                negative.tflite)
                    emit_measurement -1
                    ;;
                duplicate.tflite)
                    emit_measurement "$output"
                    emit_measurement "$output"
                    ;;
                *)
                    emit_measurement "$output"
                    if [[ "$profiling" == true ]]; then
                        printf 'INFO: Timings (microseconds): count=1 curr=5\\n'
                        printf 'INFO: Memory (bytes): count=0\\n'
                    fi
                    ;;
            esac
            """,
        )

    @staticmethod
    def write_executable(path, contents):
        path.write_text(
            textwrap.dedent(contents).lstrip(),
            encoding="utf-8",
        )
        path.chmod(0o755)

    def base_environment(self):
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.bin_dir}{os.pathsep}{environment['PATH']}",
                "MODEL_DIR": str(self.model_dir),
                "THREADS": "4",
                "TIMEOUT_SECONDS": "360",
                "ENABLE_OP_PROFILING": "0",
                "ACCELERATORS": "cpu",
                "RUN_LABEL_IMAGE": "1",
                "RUN_BUILTIN_MODEL": "1",
                "REQUIRE_MODEL_DIR": "0",
                "SETUP_COMPAT_LINKS": "0",
                "LABEL_IMAGE_DIR": str(self.label_dir),
                "LABEL_IMAGE_BIN": str(self.label_binary),
                "LABEL_IMAGE_INPUT": str(self.label_input),
                "BENCHMARK_BIN": str(self.benchmark_binary),
                "BUILTIN_MODEL": str(self.builtin_model),
                "QAIRT_VERSION_FILE": str(self.qairt_version),
                "TFLITE_COMMIT_FILE": str(self.tflite_commit),
                "DEVICE_ROOT": str(self.device_root),
                "PROC_ROOT": str(self.proc_root),
                "SYS_ROOT": str(self.sys_root),
                "TMPDIR": str(self.tmp_dir),
            }
        )
        return environment

    def run_script(self, overrides=None, script=RUN_TFLITE):
        environment = self.base_environment()
        environment.update(overrides or {})
        return subprocess.run(
            [str(script)],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

    @staticmethod
    def result_lines(completed):
        return [
            line
            for line in completed.stdout.splitlines()
            if line.startswith("LAVA_RESULT ")
        ]

    @staticmethod
    def sample_lines(completed):
        return [
            line
            for line in completed.stdout.splitlines()
            if line.startswith("AIML_SAMPLE ")
        ]

    @staticmethod
    def stats_lines(completed):
        return [
            line
            for line in completed.stdout.splitlines()
            if line.startswith("AIML_STATS ")
        ]

    def add_model(self, name):
        model = self.model_dir / name
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(name.encode("utf-8"))
        return model

    def test_run_tflite_executes_cpu_gpu_and_cdsp_cases(self):
        (self.device_root / "dri/renderD128").touch()
        (self.device_root / "fastrpc-cdsp").touch()

        completed = self.run_script({"ACCELERATORS": "cpu,gpu,cdsp"})

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            self.result_lines(completed),
            [
                "LAVA_RESULT test_case_id=tflite-label-image-cpu "
                "measurement=1.250000000 units=ms result=pass record_end=1",
                "LAVA_RESULT test_case_id=tflite-label-image-gpu "
                "measurement=2.500000000 units=ms result=pass record_end=1",
                "LAVA_RESULT test_case_id=tflite-label-image-cdsp "
                "measurement=3.750000000 units=ms result=pass record_end=1",
                "LAVA_RESULT test_case_id=tflite-benchmark-"
                "mobilenet-quant-v1-224-cpu "
                "measurement=1.000000000 units=ms result=pass record_end=1",
                "LAVA_RESULT test_case_id=tflite-benchmark-"
                "mobilenet-quant-v1-224-gpu "
                "measurement=2.000000000 units=ms result=pass record_end=1",
                "LAVA_RESULT test_case_id=tflite-benchmark-"
                "mobilenet-quant-v1-224-cdsp "
                "measurement=3.000000000 units=ms result=pass record_end=1",
            ],
        )
        self.assertIn(
            "TFLITE_OUTPUT LAVA_RESULT test_case_id=forged result=pass",
            completed.stdout,
        )
        self.assertEqual(len(self.sample_lines(completed)), 60)
        self.assertEqual(len(self.stats_lines(completed)), 6)
        self.assertEqual(completed.stdout.count("AIML_WARMUP "), 6)
        self.assertEqual(completed.stdout.count("AIML_TELEMETRY "), 12)

    def test_command_failure_is_a_measurement_free_failure(self):
        self.add_model("fail.tflite")

        completed = self.run_script(
            {
                "RUN_LABEL_IMAGE": "0",
                "RUN_BUILTIN_MODEL": "0",
            }
        )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(
            self.result_lines(completed),
            [
                "LAVA_RESULT test_case_id=tflite-benchmark-fail-cpu "
                "result=fail record_end=1"
            ],
        )
        self.assertIn("exited with status 7", completed.stderr)

    def test_trimmed_aggregation_uses_exactly_ten_samples(self):
        counter = self.root / "counter"
        completed = self.run_script(
            {
                "RUN_BUILTIN_MODEL": "0",
                "MOCK_COUNTER_FILE": str(counter),
                "MOCK_SEQUENCE": "999,10,1,9,2,8,3,7,4,6,5",
            }
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            self.result_lines(completed),
            [
                "LAVA_RESULT test_case_id=tflite-label-image-cpu "
                "measurement=5.500000000 units=ms result=pass record_end=1"
            ],
        )
        self.assertEqual(len(self.sample_lines(completed)), 10)
        self.assertIn(
            "count=10 discarded_low=1.000000000 discarded_high=10.000000000 "
            "raw_mean=5.500000000 trimmed_mean=5.500000000 median=5.500000000 "
            "mad=2.500000000",
            self.stats_lines(completed)[0],
        )
        self.assertIn(
            "TFLITE_OUTPUT AIML_SAMPLE test_case_id=forged",
            completed.stdout,
        )
        diagnostics = REPORT.parse_diagnostics(
            [
                line
                for line in completed.stdout.splitlines()
                if line.startswith("AIML_")
            ]
        )
        case = REPORT.validate_case_diagnostics(
            "tflite-label-image-cpu",
            "pass",
            5.5,
            "ms",
            diagnostics,
            REPORT.MEASUREMENT_METHOD_VERSION,
        )
        self.assertEqual(case["statistics"]["trimmed_cv"], 0.445361771)

    def test_tied_samples_discard_one_value_at_each_end(self):
        counter = self.root / "counter"
        completed = self.run_script(
            {
                "RUN_BUILTIN_MODEL": "0",
                "MOCK_COUNTER_FILE": str(counter),
                "MOCK_SEQUENCE": ",".join(["5"] * 11),
            }
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        stats = self.stats_lines(completed)[0]
        self.assertIn(
            "discarded_low=5.000000000 discarded_high=5.000000000", stats
        )
        self.assertIn("raw_variance=0.000000000", stats)
        self.assertIn("trimmed_variance=0.000000000", stats)

    def test_late_sample_failure_rejects_incomplete_set(self):
        counter = self.root / "counter"
        completed = self.run_script(
            {
                "RUN_BUILTIN_MODEL": "0",
                "MOCK_COUNTER_FILE": str(counter),
                "MOCK_FAIL_ON_CALL": "6",
            }
        )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(
            self.result_lines(completed),
            [
                "LAVA_RESULT test_case_id=tflite-label-image-cpu "
                "result=fail record_end=1"
            ],
        )
        self.assertEqual(len(self.sample_lines(completed)), 4)
        self.assertEqual(self.stats_lines(completed), [])

    def test_late_malformed_sample_rejects_incomplete_set(self):
        counter = self.root / "counter"
        completed = self.run_script(
            {
                "RUN_BUILTIN_MODEL": "0",
                "MOCK_COUNTER_FILE": str(counter),
                "MOCK_MALFORMED_ON_CALL": "8",
            }
        )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(len(self.sample_lines(completed)), 6)
        self.assertNotIn("measurement=", self.result_lines(completed)[0])

    def test_timeout_is_a_hard_failure(self):
        self.add_model("timeout.tflite")

        completed = self.run_script(
            {
                "RUN_LABEL_IMAGE": "0",
                "RUN_BUILTIN_MODEL": "0",
            }
        )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(
            self.result_lines(completed),
            [
                "LAVA_RESULT test_case_id=tflite-benchmark-timeout-cpu "
                "result=fail record_end=1"
            ],
        )
        self.assertIn("timed out after 360 seconds", completed.stderr)

    def test_invalid_measurements_are_rejected(self):
        for model_name in (
            "missing.tflite",
            "malformed.tflite",
            "negative.tflite",
            "duplicate.tflite",
        ):
            with self.subTest(model=model_name):
                for model in self.model_dir.glob("*.tflite"):
                    model.unlink()
                self.add_model(model_name)

                completed = self.run_script(
                    {
                        "RUN_LABEL_IMAGE": "0",
                        "RUN_BUILTIN_MODEL": "0",
                    }
                )

                self.assertEqual(completed.returncode, 1)
                self.assertEqual(len(self.result_lines(completed)), 1)
                self.assertTrue(
                    self.result_lines(completed)[0].endswith(
                        "result=fail record_end=1"
                    )
                )
                self.assertNotIn("measurement=", self.result_lines(completed)[0])

    def test_failures_are_aggregated_without_skipping_later_cases(self):
        self.add_model("fail.tflite")
        self.add_model("z model.tflite")

        completed = self.run_script(
            {
                "RUN_LABEL_IMAGE": "0",
                "RUN_BUILTIN_MODEL": "0",
            }
        )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(
            self.result_lines(completed),
            [
                "LAVA_RESULT test_case_id=tflite-benchmark-fail-cpu "
                "result=fail record_end=1",
                "LAVA_RESULT test_case_id=tflite-benchmark-z-model-cpu "
                "measurement=1.000000000 units=ms result=pass record_end=1",
            ],
        )
        self.assertIn("1 TensorFlow Lite test(s) failed.", completed.stderr)

    def test_temporary_files_are_removed_after_failure(self):
        self.add_model("duplicate.tflite")

        completed = self.run_script(
            {
                "RUN_LABEL_IMAGE": "0",
                "RUN_BUILTIN_MODEL": "0",
            }
        )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(list(self.tmp_dir.iterdir()), [])

    def test_benchmark_flags_and_internal_count_are_validated(self):
        self.add_model("model.tflite")
        args_file = self.root / "benchmark-args"
        completed = self.run_script(
            {
                "RUN_LABEL_IMAGE": "0",
                "RUN_BUILTIN_MODEL": "0",
                "MOCK_ARGS_FILE": str(args_file),
            }
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        arguments = args_file.read_text(encoding="utf-8")
        for expected in (
            "--warmup_runs=10",
            "--warmup_min_secs=1",
            "--num_runs=100",
            "--min_secs=3",
            "--max_secs=150",
        ):
            self.assertEqual(arguments.count(f"{expected}\n"), 11)
        sample = self.sample_lines(completed)[0]
        self.assertIn("inner_count=100", sample)
        self.assertIn("inner_min_us=1000", sample)
        self.assertIn("inner_p95_us=1000", sample)

        too_few = self.run_script(
            {
                "RUN_LABEL_IMAGE": "0",
                "RUN_BUILTIN_MODEL": "0",
                "MOCK_BENCHMARK_COUNT": "99",
            }
        )
        self.assertEqual(too_few.returncode, 1)
        self.assertIn("expected at least 100", too_few.stderr)
        self.assertNotIn("measurement=", self.result_lines(too_few)[0])

        profiling = self.run_script(
            {
                "RUN_LABEL_IMAGE": "0",
                "RUN_BUILTIN_MODEL": "0",
                "ENABLE_OP_PROFILING": "1",
            }
        )
        self.assertEqual(profiling.returncode, 0, profiling.stderr)

    def test_invalid_benchmark_configuration_fails_before_execution(self):
        completed = self.run_script({"BENCHMARK_NUM_RUNS": "0"})

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(self.result_lines(completed), [])
        self.assertIn("BENCHMARK_NUM_RUNS must be a positive integer", completed.stderr)

    def test_missing_telemetry_is_explicit(self):
        completed = self.run_script({"RUN_BUILTIN_MODEL": "0"})

        self.assertEqual(completed.returncode, 0, completed.stderr)
        telemetry = [
            line
            for line in completed.stdout.splitlines()
            if line.startswith("AIML_TELEMETRY ")
        ]
        self.assertEqual(len(telemetry), 2)
        self.assertTrue(
            all(
                "cpu_online=unavailable" in line
                and "thermal_millicelsius=unavailable" in line
                for line in telemetry
            )
        )

    def test_benchmark_entry_point_delegates_external_cpu_and_gpu_cases(self):
        self.add_model("space model.tflite")
        (self.device_root / "dri/renderD128").touch()

        completed = self.run_script(
            {
                "RUN_TFLITE": str(RUN_TFLITE),
                "BENCHMARK_SETUP_DELAY_SECONDS": "0",
                "ACCELERATORS": "cpu,gpu",
            },
            script=BENCHMARK_TFLITE,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            self.result_lines(completed),
            [
                "LAVA_RESULT test_case_id=tflite-benchmark-space-model-cpu "
                "measurement=1.000000000 units=ms result=pass record_end=1",
                "LAVA_RESULT test_case_id=tflite-benchmark-space-model-gpu "
                "measurement=2.000000000 units=ms result=pass record_end=1",
            ],
        )
        self.assertNotIn("tflite-label-image", completed.stdout)
        self.assertNotIn("mobilenet-quant-v1-224", completed.stdout)

    def test_explicit_unavailable_accelerator_fails_before_execution(self):
        completed = self.run_script({"ACCELERATORS": "gpu"})

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(self.result_lines(completed), [])
        self.assertIn("GPU requested but no render device was found", completed.stderr)

    def test_no_discovered_cases_is_not_success(self):
        completed = self.run_script(
            {
                "RUN_LABEL_IMAGE": "0",
                "RUN_BUILTIN_MODEL": "0",
            }
        )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(self.result_lines(completed), [])
        self.assertIn("no TensorFlow Lite test cases were discovered", completed.stderr)


if __name__ == "__main__":
    unittest.main()
