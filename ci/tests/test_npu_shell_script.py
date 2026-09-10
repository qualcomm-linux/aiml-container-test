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
RUN_NPU_TESTS = REPOSITORY / "run-npu-tests.sh"


class NpuShellScriptTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.bin_dir = self.root / "bin"
        self.device_root = self.root / "dev"
        self.genie_root = self.root / "genie"
        self.qnn_root = self.root / "qnn"
        self.tmp_dir = self.root / "tmp"
        for directory in (
            self.bin_dir,
            self.device_root,
            self.genie_root / "qcs8275",
            self.qnn_root / "mediapipe-pose-qcs6490",
            self.qnn_root / "mediapipe-pose-qcs8275",
            self.tmp_dir,
        ):
            directory.mkdir(parents=True)

        self.qairt_version = self.root / "qairt-version"
        self.qairt_version.write_text("2.47.0\n", encoding="utf-8")
        self.backend = self.root / "libQnnHtp.so"
        self.backend.touch()
        for chipset in ("qcs6490", "qcs8275"):
            bundle = self.qnn_root / f"mediapipe-pose-{chipset}"
            (bundle / "pose_detector.bin").write_bytes(b"context")
            (bundle / "pose_detector_input.raw").write_bytes(b"input")
            (bundle / "input_list.txt").write_text(
                "image:=pose_detector_input.raw\n", encoding="utf-8"
            )
        genie_bundle = self.genie_root / "qcs8275"
        for filename in (
            "htp_backend_ext_config.json",
            "sample_prompt.txt",
            "tokenizer.json",
            "part1_of_2.bin",
            "part2_of_2.bin",
        ):
            (genie_bundle / filename).write_bytes(b"asset")
        (genie_bundle / "genie_config.json").write_text(
            '{"dialog":{"engine":{"backend":{"type": "QnnHtp"}}}}\n',
            encoding="utf-8",
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
        self.write_executable(
            self.bin_dir / "sha256sum",
            """
            #!/bin/bash
            for path in "$@"; do
                printf '%064d  %s\\n' 0 "$path"
            done
            """,
        )
        self.qnn_runner = self.bin_dir / "qnn-net-run"
        self.write_executable(
            self.qnn_runner,
            """
            #!/bin/bash
            set -eu
            counter=${MOCK_QNN_COUNTER:?}
            call=0
            [[ ! -f "$counter" ]] || call=$(<"$counter")
            call=$((call + 1))
            printf '%s\\n' "$call" >"$counter"
            printf 'Inference (avg): %d us\\n' "$((call * 1000))"
            """,
        )
        self.genie_runner = self.bin_dir / "genie-t2t-run"
        self.write_executable(
            self.genie_runner,
            """
            #!/bin/bash
            set -eu
            counter=${MOCK_GENIE_COUNTER:?}
            profile=
            while (($#)); do
                case "$1" in
                    --profile) profile=$2; shift 2 ;;
                    *) shift ;;
                esac
            done
            [[ -n "$profile" ]]
            call=0
            [[ ! -f "$counter" ]] || call=$(<"$counter")
            call=$((call + 1))
            printf '%s\\n' "$call" >"$counter"
            cat >"$profile" <<JSON
            {"components":[{"events":[{"type":"GenieDialog_query","time-to-first-token":{"value":$((call * 1000)),"unit":"us"},"prompt-processing-rate":{"value":$call,"unit":"toks/sec"},"token-generation-rate":{"value":$((call * 2)),"unit":"toks/sec"}}]}]}
            JSON
            """,
        )

    @staticmethod
    def write_executable(path, contents):
        path.write_text(
            textwrap.dedent(contents).lstrip(), encoding="utf-8"
        )
        path.chmod(0o755)

    def environment(self, machine_name):
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.bin_dir}{os.pathsep}{environment['PATH']}",
                "DEVICE_ROOT": str(self.device_root),
                "GENIE_ROOT": str(self.genie_root),
                "QNN_ROOT": str(self.qnn_root),
                "GENIE_T2T_RUN": str(self.genie_runner),
                "QNN_NET_RUN": str(self.qnn_runner),
                "QNN_HTP_BACKEND": str(self.backend),
                "QAIRT_VERSION_FILE": str(self.qairt_version),
                "MACHINE_NAME": machine_name,
                "MOCK_QNN_COUNTER": str(self.root / "qnn-counter"),
                "MOCK_GENIE_COUNTER": str(self.root / "genie-counter"),
                "TMPDIR": str(self.tmp_dir),
            }
        )
        return environment

    def run_script(self, machine_name):
        return subprocess.run(
            [str(RUN_NPU_TESTS)],
            env=self.environment(machine_name),
            check=False,
            capture_output=True,
            text=True,
        )

    @staticmethod
    def lines(completed, prefix):
        return [
            line
            for line in completed.stdout.splitlines()
            if line.startswith(prefix)
        ]

    def test_skips_when_cdsp_is_missing(self):
        completed = self.run_script("Arduino VENTUNO Q")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("NPU tests skipped", completed.stdout)
        self.assertEqual(self.lines(completed, "LAVA_RESULT "), [])

    def test_qcs6490_runs_only_the_qnn_context(self):
        (self.device_root / "fastrpc-cdsp").touch()
        completed = self.run_script("Qualcomm Technologies, Inc. Robotics RB3gen2")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            self.lines(completed, "LAVA_RESULT "),
            [
                "LAVA_RESULT test_case_id=qnn-mediapipe-pose-detector-htp "
                "measurement=6.500000000 units=ms result=pass record_end=1"
            ],
        )
        self.assertEqual(len(self.lines(completed, "AIML_SAMPLE ")), 10)
        self.assertIn(
            "AIML_STATS test_case_id=qnn-mediapipe-pose-detector-htp "
            "count=10 discarded_low=2.0 discarded_high=11.0",
            completed.stdout,
        )

    def test_qcs8275_runs_qnn_and_all_genie_metrics(self):
        (self.device_root / "fastrpc-cdsp").touch()
        completed = self.run_script("Arduino VENTUNO Q")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result_lines = self.lines(completed, "LAVA_RESULT ")
        self.assertEqual(len(result_lines), 4)
        self.assertIn(
            "test_case_id=qnn-mediapipe-pose-detector-htp "
            "measurement=6.500000000 units=ms result=pass",
            result_lines[0],
        )
        self.assertIn(
            "test_case_id=genie-qwen3-0.6b-htp-ttft "
            "measurement=6.500000000 units=ms result=pass",
            result_lines[1],
        )
        self.assertIn(
            "test_case_id=genie-qwen3-0.6b-htp-prompt-tokens-per-second "
            "measurement=6.500000000 units=toks/sec result=pass",
            result_lines[2],
        )
        self.assertIn(
            "test_case_id=genie-qwen3-0.6b-htp-token-generation-per-second "
            "measurement=13.000000000 units=toks/sec result=pass",
            result_lines[3],
        )
        self.assertEqual(len(self.lines(completed, "AIML_SAMPLE ")), 40)

    def test_qnn_failure_includes_runner_output(self):
        (self.device_root / "fastrpc-cdsp").touch()
        self.write_executable(
            self.qnn_runner,
            """
            #!/bin/bash
            printf 'QNN backend initialization failed\\n' >&2
            exit 1
            """,
        )

        completed = self.run_script("Qualcomm Technologies, Inc. Robotics RB3gen2")

        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "ERROR: QNN HTP warm-up failed for "
            "qnn-mediapipe-pose-detector-htp",
            completed.stderr,
        )
        self.assertIn(
            "ERROR: runner output for qnn-mediapipe-pose-detector-htp follows:",
            completed.stderr,
        )
        self.assertIn("QNN backend initialization failed", completed.stderr)


if __name__ == "__main__":
    unittest.main()
