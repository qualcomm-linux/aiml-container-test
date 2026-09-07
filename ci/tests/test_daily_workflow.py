#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

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

    def test_scopes_are_independent_and_share_one_container(self):
        generic = job_block(self.daily, "test-generic")
        arduino = job_block(self.daily, "test-arduino")
        self.assertNotIn("resolve-qcom-image-arduino", generic)
        self.assertNotIn("test-arduino", generic)
        self.assertNotIn("resolve-qcom-image-generic", arduino)
        self.assertNotIn("test-generic", arduino)
        digest = (
            "container_digest: "
            "${{ needs.build-daily.outputs.container_digest }}"
        )
        self.assertIn(digest, generic)
        self.assertIn(digest, arduino)

    def test_scopes_publish_distinct_lava_reports(self):
        self.assertIn(
            "report_scope: generic", job_block(self.daily, "test-generic")
        )
        self.assertIn(
            "report_scope: arduino", job_block(self.daily, "test-arduino")
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
        self.assertIn("needs.test-arduino.result == 'success'", comparison)

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

    def test_push_runs_glymur_on_the_testing_branch(self):
        self.assertIn("branches: [main, ci-staging]", self.push)
        self.assertIn(
            """      boards_include: '["qrb2210-rb1","qcs6490-rb3gen2-vision-kit","glymur-crd"]'""",
            job_block(self.push, "test-generic"),
        )


if __name__ == "__main__":
    unittest.main()
