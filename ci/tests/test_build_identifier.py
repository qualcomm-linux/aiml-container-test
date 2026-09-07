# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

REPOSITORY = Path(__file__).parents[2]
WORKFLOW = REPOSITORY / ".github/workflows/docker_build.yml"


def load_build_identifier_script():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["build-oci"]["steps"]
    return next(step["run"] for step in steps if step.get("id") == "build_identifier")


class BuildIdentifierTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_build_identifier_script()
        cls.checkout_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def run_identifier(self, **overrides):
        with tempfile.NamedTemporaryFile() as output:
            environment = os.environ.copy()
            environment.update(
                {
                    "EXPECTED_SHA": self.checkout_sha,
                    "GITHUB_EVENT_NAME": "pull_request",
                    "GITHUB_OUTPUT": output.name,
                    "GITHUB_REF": "refs/pull/50/merge",
                    "GITHUB_REF_NAME": "50/merge",
                    "GITHUB_REF_TYPE": "branch",
                    "GITHUB_REPOSITORY": "qualcomm-linux/aiml-container-test",
                    "GITHUB_RUN_ATTEMPT": "2",
                    "GITHUB_RUN_ID": "123456",
                    "GITHUB_SERVER_URL": "https://github.com",
                    "PR_NUMBER": "50",
                    "SOURCE_REF": "dependabot/github_actions/actions/checkout-7",
                }
            )
            environment.update(overrides)
            result = subprocess.run(
                ["bash", "-c", self.script],
                cwd=REPOSITORY,
                env=environment,
                capture_output=True,
                check=False,
                text=True,
            )
            output.seek(0)
            step_output = output.read().decode()
        return result, step_output

    def assert_identifier(self, expected, **overrides):
        result, step_output = self.run_identifier(**overrides)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(step_output, f"identifier={expected}\n")
        return result

    def assert_rejected(self, message, **overrides):
        result, step_output = self.run_identifier(**overrides)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(step_output, "")
        self.assertIn(message, result.stdout + result.stderr)

    def test_pr_identifier_uses_only_pr_number(self):
        head_refs = (
            "dependabot/github_actions/actions/checkout-7",
            "feature/readable-builds",
            "renovate-docker-buildx-action-4.x",
        )

        for head_ref in head_refs:
            with self.subTest(head_ref=head_ref):
                result = self.assert_identifier("pr-50", SOURCE_REF=head_ref)
                self.assertIn(f"Build source branch: {head_ref}", result.stdout)
                self.assertIn(f"Build commit: {self.checkout_sha}", result.stdout)
                self.assertIn("Workflow run ID: 123456 (attempt 2)", result.stdout)
                self.assertIn(
                    "Workflow run URL: "
                    "https://github.com/qualcomm-linux/aiml-container-test/"
                    "actions/runs/123456",
                    result.stdout,
                )

    def test_branch_identifiers_use_controlled_branch_names(self):
        for event_name, branch_name in (
            ("push", "main"),
            ("push", "ci-staging"),
            ("schedule", "main"),
            ("workflow_dispatch", "ci-staging"),
        ):
            with self.subTest(event_name=event_name, branch_name=branch_name):
                self.assert_identifier(
                    f"branch-{branch_name}",
                    GITHUB_EVENT_NAME=event_name,
                    GITHUB_REF=f"refs/heads/{branch_name}",
                    GITHUB_REF_NAME=branch_name,
                    PR_NUMBER="",
                    SOURCE_REF=branch_name,
                )

    def test_rejects_missing_or_malformed_pr_numbers(self):
        for pr_number in ("", "0", "01", "-1", "not-a-number"):
            with self.subTest(pr_number=pr_number):
                self.assert_rejected(
                    "missing or malformed pull request number",
                    PR_NUMBER=pr_number,
                )

    def test_rejects_malformed_or_mismatched_commits(self):
        malformed_shas = (
            "A" * 40,
            "a" * 39,
            "a" * 39 + "/",
        )
        for expected_sha in malformed_shas:
            with self.subTest(expected_sha=expected_sha):
                self.assert_rejected(
                    "github.sha must be exactly 40 lowercase hexadecimal characters",
                    EXPECTED_SHA=expected_sha,
                )

        mismatched_sha = (
            "0" if self.checkout_sha[0] != "0" else "1"
        ) + self.checkout_sha[1:]
        self.assert_rejected(
            "checked-out HEAD does not match github.sha",
            EXPECTED_SHA=mismatched_sha,
        )

    def test_rejects_unsupported_events_and_refs(self):
        cases = (
            (
                "unsupported workflow event",
                {"GITHUB_EVENT_NAME": "release"},
            ),
            (
                "pull_request event has unsupported ref",
                {"GITHUB_REF": "refs/heads/main"},
            ),
            (
                "push event has unsupported ref",
                {
                    "GITHUB_EVENT_NAME": "push",
                    "GITHUB_REF": "refs/tags/v1",
                    "GITHUB_REF_NAME": "v1",
                    "GITHUB_REF_TYPE": "tag",
                    "PR_NUMBER": "",
                    "SOURCE_REF": "v1",
                },
            ),
            (
                "schedule event must run from branch 'main'",
                {
                    "GITHUB_EVENT_NAME": "schedule",
                    "GITHUB_REF": "refs/heads/ci-staging",
                    "GITHUB_REF_NAME": "ci-staging",
                    "PR_NUMBER": "",
                    "SOURCE_REF": "ci-staging",
                },
            ),
            (
                "workflow_dispatch event uses unsupported branch 'feature'",
                {
                    "GITHUB_EVENT_NAME": "workflow_dispatch",
                    "GITHUB_REF": "refs/heads/feature",
                    "GITHUB_REF_NAME": "feature",
                    "PR_NUMBER": "",
                    "SOURCE_REF": "feature",
                },
            ),
        )

        for message, environment in cases:
            with self.subTest(message=message):
                self.assert_rejected(message, **environment)

    def test_rejects_unsafe_or_oversized_branch_identifiers(self):
        cases = (
            ("not safe as a filename component", "feature/topic"),
            ("not a valid Docker tag", "feature:topic"),
            ("exceeds the 128-character Docker tag limit", "x" * 122),
        )

        for message, branch_name in cases:
            with self.subTest(branch_name=branch_name):
                self.assert_rejected(
                    message,
                    GITHUB_EVENT_NAME="push",
                    GITHUB_REF=f"refs/heads/{branch_name}",
                    GITHUB_REF_NAME=branch_name,
                    PR_NUMBER="",
                    SOURCE_REF=branch_name,
                )

    def test_workflow_uses_one_validated_identifier_for_all_identity_sinks(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        output = "${{ steps.build_identifier.outputs.identifier }}"

        self.assertNotIn("ci/build_reference.py", workflow)
        self.assertNotIn("env.BUILD_REFERENCE", workflow)
        self.assertNotIn("sha-${{", workflow)
        self.assertEqual(workflow.count("id: build_identifier"), 1)
        self.assertEqual(
            workflow.count(
                'printf \'identifier=%s\\n\' "$build_identifier" >>"$GITHUB_OUTPUT"'
            ),
            1,
        )
        self.assertGreaterEqual(workflow.count(output), 9)
        self.assertIn(
            f"url: ${{{{ steps.upload_artifacts_s3.outputs.url }}}}/"
            f"aiml-container-{output}.tar",
            workflow,
        )
        self.assertEqual(workflow.count(f"tags: aiml-container-test:{output}"), 1)
        self.assertEqual(
            workflow.count(
                "tags: ghcr.io/qualcomm-linux/aiml-container-test:" + output
            ),
            1,
        )
        self.assertIn(
            f"outputs: type=docker,dest=${{{{ runner.temp }}}}/"
            f"aiml-container-{output}.tar",
            workflow,
        )
        self.assertIn(
            f"STAGED_IMAGE_TAR: OCI-artifacts/aiml-container-{output}.tar",
            workflow,
        )
        self.assertIn(f"BUILD_IDENTIFIER: {output}", workflow)
        self.assertIn('--source-version "${BUILD_IDENTIFIER}"', workflow)

        sink_lines = [
            line
            for line in workflow.splitlines()
            if "tags:" in line
            or "aiml-container-" in line
            or "--source-version" in line
            or "BUILD_IDENTIFIER:" in line
        ]
        for line in sink_lines:
            self.assertNotIn("github.head_ref", line)
            self.assertNotIn("github.ref_name", line)
            self.assertNotIn("github.sha", line)

    def test_workflow_preserves_source_and_run_provenance(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("EXPECTED_SHA: ${{ github.sha }}", workflow)
        self.assertIn(
            "SOURCE_REF: ${{ github.head_ref || github.ref_name }}",
            workflow,
        )
        self.assertIn("PR_NUMBER: ${{ github.event.pull_request.number }}", workflow)
        self.assertIn("RUN_ID: ${{ github.run_id }}", workflow)
        self.assertIn("RUN_ATTEMPT: ${{ github.run_attempt }}", workflow)
        self.assertIn("RUN_URL: ${{ github.server_url }}/", workflow)
        self.assertIn("org.opencontainers.image.revision=${{ github.sha }}", workflow)
        self.assertIn("org.opencontainers.image.ref.name=${{ github.head_ref", workflow)
        self.assertIn("OCI-artifacts/build-provenance.txt", workflow)

    def test_unrelated_nproc_command_is_unchanged(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("--parallelism `nproc`", workflow)
        self.assertNotIn('--parallelism "$(nproc)"', workflow)


if __name__ == "__main__":
    unittest.main()
