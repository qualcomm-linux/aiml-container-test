#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "select_lava_boards.py"
SPEC = importlib.util.spec_from_file_location("select_lava_boards", SCRIPT)
SELECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTOR)


class SelectLavaBoardsTest(unittest.TestCase):
    def setUp(self):
        self.boards = {
            "generic-board": {
                "display_name": "Generic",
                "image_source": "generic",
                "device_types": ["generic-device"],
            },
            "monza": {
                "display_name": "Arduino VENTUNO Q",
                "image_source": "arduino",
                "device_types": ["monza-device"],
            },
            "imola": {
                "display_name": "Arduino UNO Q",
                "image_source": "arduino",
                "device_types": ["imola-device"],
            },
        }

    def test_empty_include_selects_all_boards_for_source(self):
        self.assertEqual(
            SELECTOR.select_boards(self.boards, "arduino", ""),
            ["monza", "imola"],
        )

    def test_rejects_board_from_another_image_source(self):
        with self.assertRaisesRegex(
            ValueError, "do not use the arduino image source: generic-board"
        ):
            SELECTOR.select_boards(
                self.boards, "arduino", '["imola","generic-board"]'
            )

    def test_rejects_unknown_and_duplicate_boards(self):
        with self.assertRaisesRegex(ValueError, "unknown boards requested"):
            SELECTOR.select_boards(self.boards, "arduino", '["unknown"]')
        with self.assertRaisesRegex(ValueError, "must not contain duplicate"):
            SELECTOR.select_boards(self.boards, "arduino", '["imola","imola"]')

    def test_repository_templates_match_board_metadata(self):
        root = Path(__file__).parents[2]
        boards = SELECTOR.load_boards(root / "ci/boards.json")
        SELECTOR.validate_templates(boards, root / "ci/lava")

        self.assertEqual(
            SELECTOR.select_boards(boards, "arduino", ""),
            ["monaco-arduino-monza", "qrb2210-arduino-imola"],
        )

    def test_rejects_template_device_type_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            lava_dir = Path(temporary_directory)
            for board_id in self.boards:
                template_dir = lava_dir / board_id
                template_dir.mkdir()
                device_type = self.boards[board_id]["device_types"][0]
                (template_dir / "boot.yaml").write_text(
                    f"device_type: {device_type}\n", encoding="utf-8"
                )
            (lava_dir / "imola/boot.yaml").write_text(
                "device_type: wrong-device\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(
                ValueError, "templates use unconfigured device types"
            ):
                SELECTOR.validate_templates(self.boards, lava_dir)

    def test_load_boards_rejects_duplicate_device_types(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "boards.json"
            duplicate = dict(self.boards)
            duplicate["imola"] = {
                **duplicate["imola"],
                "device_types": ["monza-device"],
            }
            path.write_text(
                json.dumps({"schema_version": 1, "boards": duplicate}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicate LAVA device type"):
                SELECTOR.load_boards(path)


if __name__ == "__main__":
    unittest.main()
