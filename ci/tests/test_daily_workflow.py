#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def load_workflow(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def job_block(workflow, job_name):
    marker = f"  {job_name}:\n"
    start = workflow.index(marker)
    end = len(workflow)
    for line in workflow[start + len(marker) :].splitlines(keepends=True):
        if line.startswith("  ") and not line.startswith("    "):
            end = workflow.index(line, start + len(marker))
            break
    return workflow[start:end]


class DailyWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daily = load_workflow("build-daily.yml")
        cls.compare = load_workflow("compare-performance.yml")
        cls.push = load_workflow("build-on-push.yml")
        cls.lava = load_workflow("lava-test.yml")

    def test_schedule_routes_as_all_and_dispatch_preserves_each_family(self):
        self.assertIn(
            """      image_source:
        description: qcom-deb-images workflow family
        required: true
        default: all
        type: choice
        options:
          - all
          - generic
          - arduino
""",
            self.daily,
        )
        self.assertIn(
            "IMAGE_SOURCE: ${{ inputs.image_source || 'all' }}",
            job_block(self.daily, "configure"),
        )

    def test_invalid_all_inputs_are_rejected_before_trusted_jobs(self):
        configure = job_block(self.daily, "configure")
        self.assertIn("needs: validate-ref", configure)
        self.assertIn('--run-id "$QCOM_BUILD_RUN_ID"', configure)
        for job_name in (
            "resolve-qcom-image-generic",
            "resolve-qcom-image-arduino",
            "build-daily",
            "schema-check",
        ):
            self.assertIn("needs: configure", job_block(self.daily, job_name))
        self.assertIn(
            "run_id: ${{ needs.configure.outputs.generic_run_id }}",
            job_block(self.daily, "resolve-qcom-image-generic"),
        )
        self.assertIn(
            "run_id: ${{ needs.configure.outputs.arduino_run_id }}",
            job_block(self.daily, "resolve-qcom-image-arduino"),
        )

    def test_generic_invocation_aggregates_all_family_scopes(self):
        generic = job_block(self.daily, "test-generic")
        arduino = job_block(self.daily, "test-arduino")
        self.assertIn("name: Test AIML container with generic images", generic)
        self.assertNotIn("test-arduino", generic)
        self.assertNotIn("test-generic", arduino)
        self.assertIn("resolve-qcom-image-arduino", generic)
        self.assertIn("additional_report_scope:", generic)
        self.assertIn("&& 'arduino' || ''", generic)
        self.assertIn(
            "needs.configure.outputs.arduino_enabled == 'true'",
            generic,
        )
        self.assertIn(
            "needs.configure.outputs.generic_enabled != 'true'", arduino
        )
        digest = (
            "container_digest: "
            "${{ needs.build-daily.outputs.container_digest }}"
        )
        self.assertIn(digest, generic)
        self.assertIn(digest, arduino)

    def test_canonical_generic_summary_aggregates_all_four_board_reports(self):
        publish = job_block(self.lava, "publish-test-results")
        self.assertIn("name: Publish Tests Results", publish)
        self.assertIn("needs: submit-job", publish)
        self.assertIn("Report scope: ${scope}", publish)
        self.assertIn(
            'cat "performance-results/$scope/summary.md" '
            '>>"$GITHUB_STEP_SUMMARY"',
            publish,
        )
        self.assertIn("LAVA results (generic)", publish)
        self.assertIn("LAVA results (arduino)", publish)
        self.assertIn("performance-results/generic", publish)
        self.assertIn("performance-results/arduino", publish)
        boards = json.loads(
            (ROOT / "ci" / "boards.json").read_text(encoding="utf-8")
        )["boards"]
        self.assertEqual(
            set(boards),
            {
                "qrb2210-rb1",
                "qcs6490-rb3gen2-vision-kit",
                "monaco-arduino-monza",
                "qrb2210-arduino-imola",
            },
        )
        self.assertIn("scope-matrix.json", job_block(self.lava, "prepare-job-list"))
        submit = job_block(self.lava, "submit-job")
        self.assertIn("matrix.scope", submit)
        self.assertIn(
            "matrix: ${{ fromJson(needs.prepare-job-list.outputs.jobmatrix) }}",
            submit,
        )
        self.assertNotIn("publish-test-results", submit)
        prepare = job_block(self.lava, "prepare-job-list")
        self.assertIn('[[ "$scope" =~ ^(generic|arduino)$ ]]', prepare)
        self.assertIn(
            "only a generic report can aggregate the arduino scope",
            prepare,
        )

    def test_scheduled_comparison_requires_both_successful_scopes(self):
        comparison = job_block(self.daily, "compare-performance")
        self.assertEqual(
            comparison.count(
                "uses: ./.github/workflows/compare-performance.yml"
            ),
            1,
        )
        self.assertIn("always()", comparison)
        self.assertIn("generic_enabled == 'true'", comparison)
        self.assertIn("arduino_enabled == 'true'", comparison)
        self.assertIn("needs.test-generic.result == 'success'", comparison)
        self.assertNotIn("test-arduino", comparison)

    def test_comparison_consumes_both_scoped_artifacts(self):
        self.assertIn(
            """          path: performance-reports/generic
          pattern: tflite-performance-${{ inputs.suite }}-generic-*
""",
            self.compare,
        )
        self.assertIn(
            """          path: performance-reports/arduino
          pattern: tflite-performance-${{ inputs.suite }}-arduino-*
""",
            self.compare,
        )

    def test_push_and_daily_share_comparison_workflow(self):
        expected = "uses: ./.github/workflows/compare-performance.yml"
        self.assertIn(expected, job_block(self.push, "compare-performance"))
        self.assertIn(expected, job_block(self.daily, "compare-performance"))
        push_generic = job_block(self.push, "test-generic")
        self.assertIn("additional_report_scope: arduino", push_generic)
        self.assertNotIn("  test-arduino:\n", self.push)


if __name__ == "__main__":
    unittest.main()
