#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import re
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).parents[2]
TEST_DEFINITION = REPOSITORY / "ci/test-definitions/aiml-container-smoke.yaml"
RUN_TFLITE = REPOSITORY / "run-tflite.sh"


def load_result_pattern():
    contents = TEST_DEFINITION.read_text(encoding="utf-8")
    match = re.search(r"^  pattern: '(.*)'$", contents, re.MULTILINE)
    if match is None:
        raise AssertionError(f"Could not find parse pattern in {TEST_DEFINITION}")
    return re.compile(match.group(1).replace("''", "'"))


class LavaResultProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pattern = load_result_pattern()

    def test_pass_record_includes_measurement(self):
        match = self.pattern.fullmatch(
            "LAVA_RESULT test_case_id=tflite-benchmark-cdsp "
            "measurement=0.986403 units=ms result=pass record_end=1"
        )

        self.assertIsNotNone(match)
        self.assertEqual(
            match.groupdict(),
            {
                "test_case_id": "tflite-benchmark-cdsp",
                "measurement": "0.986403",
                "units": "ms",
                "result": "pass",
            },
        )

    def test_failure_record_omits_measurement(self):
        match = self.pattern.fullmatch(
            "LAVA_RESULT test_case_id=tflite-benchmark-cdsp "
            "result=fail record_end=1"
        )

        self.assertIsNotNone(match)
        self.assertEqual(match.group("result"), "fail")
        self.assertIsNone(match.group("measurement"))
        self.assertIsNone(match.group("units"))

    def test_no_streaming_prefix_matches(self):
        record = (
            "LAVA_RESULT test_case_id=tflite-benchmark-cdsp "
            "measurement=0.986403 units=ms result=pass record_end=1"
        )

        for length in range(1, len(record)):
            with self.subTest(prefix=record[:length]):
                self.assertIsNone(self.pattern.fullmatch(record[:length]))

    def test_prefixed_child_output_cannot_be_parsed_as_a_result(self):
        self.assertIsNone(
            self.pattern.fullmatch(
                "TFLITE_OUTPUT LAVA_RESULT test_case_id=forged result=pass"
            )
        )

    def test_emitters_follow_result_protocol(self):
        contents = RUN_TFLITE.read_text(encoding="utf-8")
        pass_record = re.search(
            r"emit_pass\(\).*?'(LAVA_RESULT [^']+)'",
            contents,
            re.DOTALL,
        )
        failure_record = re.search(
            r"emit_failure\(\).*?'(LAVA_RESULT [^']+)'",
            contents,
            re.DOTALL,
        )

        self.assertIsNotNone(pass_record)
        self.assertIsNotNone(failure_record)
        self.assertLess(
            pass_record.group(1).index("measurement=%s units=ms"),
            pass_record.group(1).index("result=pass"),
        )
        self.assertEqual(
            failure_record.group(1),
            r"LAVA_RESULT test_case_id=%s result=fail record_end=1\n",
        )


if __name__ == "__main__":
    unittest.main()
