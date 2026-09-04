#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "check_lava_execution.py"
SPEC = importlib.util.spec_from_file_location("check_lava_execution", SCRIPT)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class CheckLavaExecutionTest(unittest.TestCase):
    def write_junit(self, contents):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        path = Path(temporary_directory.name) / "results.xml"
        path.write_text(contents, encoding="utf-8")
        return path

    def test_counts_tflite_cases_in_aiml_suite(self):
        path = self.write_junit(
            """
            <testsuites>
              <testsuite name="2_aiml-container-smoke">
                <testcase name="tflite-label-image-cpu"/>
                <testcase name="tflite-benchmark-model-cpu"/>
              </testsuite>
            </testsuites>
            """
        )

        self.assertEqual(CHECK.count_aiml_tests(path), 2)

    def test_ignores_lava_infrastructure_cases(self):
        path = self.write_junit(
            """
            <testsuites>
              <testsuite name="lava">
                <testcase name="login-action"/>
                <testcase name="job"/>
              </testsuite>
            </testsuites>
            """
        )

        self.assertEqual(CHECK.count_aiml_tests(path), 0)

    def test_rejects_entity_declarations(self):
        path = self.write_junit(
            """
            <!DOCTYPE testsuites [
              <!ENTITY payload SYSTEM "file:///etc/passwd">
            ]>
            <testsuites>
              <testsuite name="2_aiml-container-smoke">
                <testcase name="tflite-label-image-cpu">&payload;</testcase>
              </testsuite>
            </testsuites>
            """
        )

        with self.assertRaisesRegex(CHECK.UnsafeJUnitError, "not allowed"):
            CHECK.count_aiml_tests(path)
