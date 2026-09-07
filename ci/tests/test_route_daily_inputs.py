#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import importlib.util
import json
import sys
import unittest
from pathlib import Path

CI_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(CI_DIR))
SCRIPT = CI_DIR / "route_daily_inputs.py"
SPEC = importlib.util.spec_from_file_location("route_daily_inputs", SCRIPT)
ROUTE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROUTE)
BOARDS = ROUTE.load_boards(CI_DIR / "boards.json")


class RouteDailyInputsTest(unittest.TestCase):
    def test_schedule_defaults_to_both_image_families(self):
        outputs = ROUTE.route_inputs(BOARDS, "all", "", "")

        self.assertEqual(outputs["generic_enabled"], "true")
        self.assertEqual(outputs["arduino_enabled"], "true")
        self.assertEqual(
            json.loads(outputs["generic_boards"]),
            ["qrb2210-rb1", "qcs6490-rb3gen2-vision-kit"],
        )
        self.assertEqual(
            json.loads(outputs["arduino_boards"]),
            ["monaco-arduino-monza", "qrb2210-arduino-imola"],
        )

    def test_manual_generic_selects_only_generic(self):
        outputs = ROUTE.route_inputs(BOARDS, "generic", "1234", "")

        self.assertEqual(outputs["generic_enabled"], "true")
        self.assertEqual(outputs["arduino_enabled"], "false")
        self.assertEqual(outputs["generic_run_id"], "1234")
        self.assertEqual(outputs["arduino_run_id"], "")
        self.assertEqual(json.loads(outputs["arduino_boards"]), [])

    def test_manual_arduino_selects_only_arduino(self):
        outputs = ROUTE.route_inputs(BOARDS, "arduino", "1234", "")

        self.assertEqual(outputs["generic_enabled"], "false")
        self.assertEqual(outputs["arduino_enabled"], "true")
        self.assertEqual(outputs["generic_run_id"], "")
        self.assertEqual(outputs["arduino_run_id"], "1234")
        self.assertEqual(json.loads(outputs["generic_boards"]), [])

    def test_all_partitions_cross_family_board_filter(self):
        outputs = ROUTE.route_inputs(
            BOARDS,
            "all",
            "",
            '["qrb2210-rb1","qrb2210-arduino-imola"]',
        )

        self.assertEqual(
            json.loads(outputs["generic_boards"]), ["qrb2210-rb1"]
        )
        self.assertEqual(
            json.loads(outputs["arduino_boards"]),
            ["qrb2210-arduino-imola"],
        )

    def test_rejects_all_with_one_explicit_producer_run(self):
        with self.assertRaisesRegex(
            ValueError,
            "qcom_build_run_id cannot be used with image_source=all",
        ):
            ROUTE.route_inputs(BOARDS, "all", "1234", "")

    def test_rejects_run_id_output_injection(self):
        with self.assertRaisesRegex(
            ValueError,
            "qcom_build_run_id must be a positive decimal run ID",
        ):
            ROUTE.route_inputs(
                BOARDS,
                "arduino",
                "456\ngeneric_enabled=true\ngeneric_run_id=123",
                "",
            )

    def test_rejects_cross_family_board_for_single_source(self):
        with self.assertRaisesRegex(
            ValueError,
            "boards do not use the generic image source",
        ):
            ROUTE.route_inputs(
                BOARDS,
                "generic",
                "",
                '["qrb2210-arduino-imola"]',
            )

    def test_rejects_board_with_unsupported_image_source(self):
        boards = {
            **BOARDS,
            "unsupported-board": {
                "display_name": "Unsupported",
                "image_source": "unsupported",
                "device_types": ["unsupported-board"],
            },
        }
        with self.assertRaisesRegex(
            ValueError,
            "boards use an unsupported image source: unsupported-board",
        ):
            ROUTE.route_inputs(
                boards,
                "all",
                "",
                '["unsupported-board"]',
            )


if __name__ == "__main__":
    unittest.main()
