#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).parents[2]
RUN_TFLITE = REPOSITORY / "run-tflite.sh"
BENCHMARK_TFLITE = REPOSITORY / "benchmark-tflite.sh"


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
        self.tmp_dir = self.root / "tmp"
        for directory in (
            self.bin_dir,
            self.label_dir,
            self.benchmark_dir,
            self.model_dir,
            self.device_root / "dri",
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
            for argument in "$@"; do
                case "$argument" in
                    --use_gpu=true) output=2.50 ;;
                    --external_delegate_path=*) output=3.75 ;;
                esac
            done
            printf 'LAVA_RESULT test_case_id=forged result=pass\\n'
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
            emit_measurement()
            {
                printf 'INFO: Inference timings in us: Init: 10, First inference: 20, Warmup (avg): 30.5, Inference (avg): %s\\n' "$1"
            }
            for argument in "$@"; do
                case "$argument" in
                    --graph=*) graph=${argument#--graph=} ;;
                    --use_gpu=true) output=2000 ;;
                    --external_delegate_path=*) output=3000 ;;
                esac
            done
            printf 'LAVA_RESULT test_case_id=forged result=pass\\n'
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
                "TIMEOUT_SECONDS": "2",
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
                "measurement=1.25 units=ms result=pass",
                "LAVA_RESULT test_case_id=tflite-label-image-gpu "
                "measurement=2.50 units=ms result=pass",
                "LAVA_RESULT test_case_id=tflite-label-image-cdsp "
                "measurement=3.75 units=ms result=pass",
                "LAVA_RESULT test_case_id=tflite-benchmark-"
                "mobilenet-quant-v1-224-cpu "
                "measurement=1.000000 units=ms result=pass",
                "LAVA_RESULT test_case_id=tflite-benchmark-"
                "mobilenet-quant-v1-224-gpu "
                "measurement=2.000000 units=ms result=pass",
                "LAVA_RESULT test_case_id=tflite-benchmark-"
                "mobilenet-quant-v1-224-cdsp "
                "measurement=3.000000 units=ms result=pass",
            ],
        )
        self.assertIn(
            "TFLITE_OUTPUT LAVA_RESULT test_case_id=forged result=pass",
            completed.stdout,
        )

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
            ["LAVA_RESULT test_case_id=tflite-benchmark-fail-cpu result=fail"],
        )
        self.assertIn("exited with status 7", completed.stderr)

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
                "result=fail"
            ],
        )
        self.assertIn("timed out after 2 seconds", completed.stderr)

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
                self.assertTrue(self.result_lines(completed)[0].endswith("result=fail"))
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
                "LAVA_RESULT test_case_id=tflite-benchmark-fail-cpu result=fail",
                "LAVA_RESULT test_case_id=tflite-benchmark-z-model-cpu "
                "measurement=1.000000 units=ms result=pass",
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
                "measurement=1.000000 units=ms result=pass",
                "LAVA_RESULT test_case_id=tflite-benchmark-space-model-gpu "
                "measurement=2.000000 units=ms result=pass",
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
