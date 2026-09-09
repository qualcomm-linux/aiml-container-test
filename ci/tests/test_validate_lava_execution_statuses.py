# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "validate_lava_execution_statuses.py"
SPEC = importlib.util.spec_from_file_location(
    "validate_lava_execution_statuses", SCRIPT
)
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class ValidateLavaExecutionStatusesTest(unittest.TestCase):
    def artifacts_dir(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        return Path(temporary_directory.name) / "artifacts"

    def scope_spec(self, scope, statuses):
        return {
            "scope": scope,
            "boards": [status["board"] for status in statuses],
            "expected_statuses": statuses,
        }

    def write_status(self, artifacts_dir, scope, slug, payload, parent=None):
        artifact_dir = (
            artifacts_dir
            / (parent or "")
            / f"lava-execution-status-trixie-{scope}-{slug}"
        )
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / "lava-execution-status.json"
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        else:
            path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    @staticmethod
    def payload(scope, board, slug, status="success"):
        return {
            "scope": scope,
            "board": board,
            "slug": slug,
            "status": status,
        }

    def assert_incomplete_with(self, result, diagnostic):
        self.assertFalse(result["complete"])
        self.assertTrue(
            any(diagnostic in message for message in result["diagnostics"]),
            result["diagnostics"],
        )

    def test_discovers_downloaded_payloads_for_generic_and_arduino(self):
        artifacts_dir = self.artifacts_dir()
        generic = {
            "board": "qrb2210-rb1",
            "slug": "qrb2210-rb1-boot",
        }
        arduino = {
            "board": "qrb2210-arduino-imola",
            "slug": "qrb2210-arduino-imola-boot",
        }
        self.write_status(
            artifacts_dir,
            "generic",
            generic["slug"],
            self.payload("generic", generic["board"], generic["slug"]),
        )
        self.write_status(
            artifacts_dir,
            "arduino",
            arduino["slug"],
            self.payload("arduino", arduino["board"], arduino["slug"]),
        )

        generic_result = VALIDATOR.validate_status_artifacts(
            artifacts_dir,
            "trixie",
            self.scope_spec("generic", [generic]),
        )
        arduino_result = VALIDATOR.validate_status_artifacts(
            artifacts_dir,
            "trixie",
            self.scope_spec("arduino", [arduino]),
        )

        self.assertTrue(generic_result["complete"], generic_result["diagnostics"])
        self.assertEqual(generic_result["status_count"], 1)
        self.assertEqual(generic_result["expected_status_count"], 1)
        self.assertTrue(arduino_result["complete"], arduino_result["diagnostics"])
        self.assertEqual(arduino_result["status_count"], 1)
        self.assertEqual(arduino_result["expected_status_count"], 1)

    def test_reports_missing_selected_status(self):
        board = {"board": "qrb2210-rb1", "slug": "qrb2210-rb1-boot"}
        result = VALIDATOR.validate_status_artifacts(
            self.artifacts_dir(),
            "trixie",
            self.scope_spec("generic", [board]),
        )

        self.assertEqual(result["status_count"], 0)
        self.assert_incomplete_with(result, "missing execution status")

    def test_does_not_count_arbitrary_payload_named_files(self):
        artifacts_dir = self.artifacts_dir()
        board = {"board": "qrb2210-rb1", "slug": "qrb2210-rb1-boot"}
        ignored = artifacts_dir / "unrelated" / "lava-execution-status.json"
        ignored.parent.mkdir(parents=True)
        ignored.write_text(
            json.dumps(self.payload("generic", board["board"], board["slug"])),
            encoding="utf-8",
        )

        result = VALIDATOR.validate_status_artifacts(
            artifacts_dir,
            "trixie",
            self.scope_spec("generic", [board]),
        )

        self.assertEqual(result["status_count"], 0)
        self.assert_incomplete_with(result, "missing execution status")

    def test_rejects_duplicate_status_mapping(self):
        artifacts_dir = self.artifacts_dir()
        board = {"board": "qrb2210-rb1", "slug": "qrb2210-rb1-boot"}
        payload = self.payload("generic", board["board"], board["slug"])
        self.write_status(
            artifacts_dir, "generic", board["slug"], payload
        )
        self.write_status(
            artifacts_dir, "generic", board["slug"], payload, parent="retry"
        )

        result = VALIDATOR.validate_status_artifacts(
            artifacts_dir,
            "trixie",
            self.scope_spec("generic", [board]),
        )

        self.assertEqual(result["status_count"], 1)
        self.assert_incomplete_with(result, "duplicate status mapping")

    def test_rejects_wrong_scope(self):
        artifacts_dir = self.artifacts_dir()
        board = {"board": "qrb2210-rb1", "slug": "qrb2210-rb1-boot"}
        self.write_status(
            artifacts_dir,
            "generic",
            board["slug"],
            self.payload("arduino", board["board"], board["slug"]),
        )

        result = VALIDATOR.validate_status_artifacts(
            artifacts_dir,
            "trixie",
            self.scope_spec("generic", [board]),
        )

        self.assert_incomplete_with(result, "wrong scope")

    def test_rejects_wrong_board(self):
        artifacts_dir = self.artifacts_dir()
        board = {"board": "qrb2210-rb1", "slug": "qrb2210-rb1-boot"}
        self.write_status(
            artifacts_dir,
            "generic",
            board["slug"],
            self.payload(
                "generic",
                "qcs6490-rb3gen2-vision-kit",
                board["slug"],
            ),
        )

        result = VALIDATOR.validate_status_artifacts(
            artifacts_dir,
            "trixie",
            self.scope_spec("generic", [board]),
        )

        self.assert_incomplete_with(result, "wrong board")

    def test_rejects_wrong_slug(self):
        artifacts_dir = self.artifacts_dir()
        board = {"board": "qrb2210-rb1", "slug": "qrb2210-rb1-boot"}
        self.write_status(
            artifacts_dir,
            "generic",
            board["slug"],
            self.payload("generic", board["board"], "unexpected-boot"),
        )

        result = VALIDATOR.validate_status_artifacts(
            artifacts_dir,
            "trixie",
            self.scope_spec("generic", [board]),
        )

        self.assert_incomplete_with(result, "wrong slug")

    def test_rejects_malformed_payload(self):
        artifacts_dir = self.artifacts_dir()
        board = {"board": "qrb2210-rb1", "slug": "qrb2210-rb1-boot"}
        self.write_status(
            artifacts_dir, "generic", board["slug"], "{not JSON"
        )

        result = VALIDATOR.validate_status_artifacts(
            artifacts_dir,
            "trixie",
            self.scope_spec("generic", [board]),
        )

        self.assert_incomplete_with(result, "cannot read JSON payload")

    def test_rejects_failed_status(self):
        artifacts_dir = self.artifacts_dir()
        board = {"board": "qrb2210-rb1", "slug": "qrb2210-rb1-boot"}
        self.write_status(
            artifacts_dir,
            "generic",
            board["slug"],
            self.payload(
                "generic", board["board"], board["slug"], status="failed"
            ),
        )

        result = VALIDATOR.validate_status_artifacts(
            artifacts_dir,
            "trixie",
            self.scope_spec("generic", [board]),
        )

        self.assertEqual(result["status_count"], 1)
        self.assert_incomplete_with(result, "reported status 'failed'")
