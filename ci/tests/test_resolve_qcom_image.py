#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import importlib.util
import io
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "resolve_qcom_image.py"
SPEC = importlib.util.spec_from_file_location("resolve_qcom_image", SCRIPT)
RESOLVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESOLVER)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def run_fixture(run_id, attempt=1, created_at="2026-09-04T06:50:42Z"):
    return {
        "id": run_id,
        "run_attempt": attempt,
        "created_at": created_at,
        "html_url": f"https://github.com/example/actions/runs/{run_id}",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "event": "schedule",
        "conclusion": "success",
        "path": ".github/workflows/linux-arduino.yml",
        "head_repository": {"full_name": "qualcomm-linux/qcom-deb-images"},
    }


def pointer_zip(pointer):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("build_url", pointer)
    return archive.getvalue()


def artifact_fixture(artifact_id, created_at):
    return {
        "id": artifact_id,
        "name": "build_url",
        "expired": False,
        "created_at": created_at,
        "size_in_bytes": 220,
    }


class FakeClient:
    def __init__(self, runs, artifacts, archives):
        self.runs = runs
        self.artifacts = artifacts
        self.archives = archives
        self.downloads = []

    def get_json(self, endpoint, fields=None):
        if "/workflows/" in endpoint:
            page = int(fields["page"])
            return {"workflow_runs": self.runs if page == 1 else []}
        if endpoint.endswith("/artifacts"):
            run_id = int(endpoint.split("/")[-2])
            page = int(fields["page"])
            return {
                "artifacts": self.artifacts.get(run_id, []) if page == 1 else []
            }
        run_id = int(endpoint.rsplit("/", 1)[1])
        return next(run for run in self.runs if run["id"] == run_id)

    def download_artifact(self, artifact_id):
        self.downloads.append(artifact_id)
        return self.archives[artifact_id]


class ResolveQcomImageTest(unittest.TestCase):
    def test_accepts_runs_within_and_exactly_at_fourteen_day_boundary(self):
        for age in (timedelta(days=14), timedelta(days=14) - timedelta(seconds=1)):
            with self.subTest(age=age):
                run = run_fixture(
                    123,
                    created_at=(NOW - age).isoformat().replace("+00:00", "Z"),
                )

                self.assertEqual(
                    RESOLVER.validate_run(run, "arduino", NOW),
                    int(age.total_seconds() // 3600),
                )

    def test_rejects_run_older_than_fourteen_days(self):
        run = run_fixture(
            123,
            created_at=(
                NOW - timedelta(days=14) - timedelta(seconds=1)
            ).isoformat().replace("+00:00", "Z"),
        )

        with self.assertRaisesRegex(RESOLVER.ResolutionError, "336 hours old"):
            RESOLVER.validate_run(run, "arduino", NOW)

    def test_age_extension_preserves_trusted_run_requirements(self):
        invalid_values = {
            "head_repository": {"full_name": "example/qcom-deb-images"},
            "path": ".github/workflows/build.yml",
            "event": "workflow_dispatch",
            "head_branch": "feature",
            "conclusion": "failure",
        }
        for field, value in invalid_values.items():
            with self.subTest(field=field):
                run = run_fixture(123)
                run[field] = value
                with self.assertRaisesRegex(
                    RESOLVER.ResolutionError, "does not match the trusted"
                ):
                    RESOLVER.validate_run(run, "arduino", NOW)

    def test_rerun_uses_publication_attempt_from_pointer(self):
        run = run_fixture(33846066976, attempt=2)
        artifact = artifact_fixture(9928371450, "2026-09-04T07:57:55Z")
        pointer = (
            "https://qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
            "qualcomm-linux/qcom-deb-images/33846066976-1/\n"
        )
        client = FakeClient([run], {run["id"]: [artifact]}, {artifact["id"]: pointer_zip(pointer)})
        probed = []

        result = RESOLVER.resolve(
            "arduino",
            "trixie",
            str(run["id"]),
            client,
            probe=lambda url, suite: probed.append((url, suite)),
            now=NOW,
        )

        self.assertEqual(result.run["run_attempt"], 2)
        self.assertEqual(result.publication_attempt, 1)
        self.assertTrue(result.build_url.endswith("/33846066976-1/"))
        self.assertEqual(probed, [(result.build_url, "trixie")])

    def test_duplicate_pointers_try_newest_first_and_use_older_valid(self):
        run = run_fixture(33846066976, attempt=2)
        newer = artifact_fixture(20, "2026-09-04T08:00:00Z")
        older = artifact_fixture(10, "2026-09-04T07:00:00Z")
        valid = (
            "https://qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
            "qualcomm-linux/qcom-deb-images/33846066976-1/\n"
        )
        client = FakeClient(
            [run],
            {run["id"]: [older, newer]},
            {
                newer["id"]: pointer_zip("https://attacker.example/image/\n"),
                older["id"]: pointer_zip(valid),
            },
        )

        result = RESOLVER.resolve(
            "arduino",
            "trixie",
            str(run["id"]),
            client,
            probe=lambda _url, _suite: None,
            now=NOW,
        )

        self.assertEqual(client.downloads, [20, 10])
        self.assertEqual(result.artifact_id, 10)

    def test_rejects_malformed_wrong_host_and_wrong_run_pointers(self):
        invalid_pointers = [
            "",
            "https://qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
            "qualcomm-linux/qcom-deb-images/123-1/\nextra\n",
            "http://qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
            "qualcomm-linux/qcom-deb-images/123-1/\n",
            "https://user@qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
            "qualcomm-linux/qcom-deb-images/123-1/\n",
            "https://qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
            "qualcomm-linux/qcom-deb-images/123-1/?token=x\n",
            "https://qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
            "qualcomm-linux/qcom-deb-images/123-1/#fragment\n",
            "https://qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
            "qualcomm-linux/qcom-deb-images/123-1/../2/\n",
            "https://qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
            "qualcomm-linux/qcom-deb-images/123-0/\n",
            "https://qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
            "qualcomm-linux/qcom-deb-images/999-1/\n",
            "https://evil.example/qcom-prd-gh-artifacts/"
            "qualcomm-linux/qcom-deb-images/123-1/\n",
        ]
        for pointer in invalid_pointers:
            with self.subTest(pointer=pointer):
                with self.assertRaises(RESOLVER.ResolutionError):
                    RESOLVER.validate_pointer(pointer.encode(), 123)

    def test_missing_suite_payload_falls_back_to_older_run(self):
        newest = run_fixture(200, created_at="2026-09-04T10:00:00Z")
        older = run_fixture(100, created_at="2026-09-04T09:00:00Z")
        artifacts = {
            200: [artifact_fixture(20, "2026-09-04T10:10:00Z")],
            100: [artifact_fixture(10, "2026-09-04T09:10:00Z")],
        }
        archives = {
            20: pointer_zip(
                "https://qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
                "qualcomm-linux/qcom-deb-images/200-1/\n"
            ),
            10: pointer_zip(
                "https://qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
                "qualcomm-linux/qcom-deb-images/100-1/\n"
            ),
        }
        client = FakeClient([older, newest], artifacts, archives)

        def probe(url, _suite):
            if "/200-1/" in url:
                raise RESOLVER.ResolutionError("suite image missing")

        result = RESOLVER.resolve(
            "arduino", "trixie", "", client, probe=probe, now=NOW
        )

        self.assertEqual(result.run["id"], 100)
        self.assertEqual(client.downloads, [20, 10])

    def test_explicit_run_never_falls_back(self):
        requested = run_fixture(200, created_at="2026-09-04T10:00:00Z")
        older = run_fixture(100, created_at="2026-09-04T09:00:00Z")
        artifacts = {
            200: [artifact_fixture(20, "2026-09-04T10:10:00Z")],
            100: [artifact_fixture(10, "2026-09-04T09:10:00Z")],
        }
        archives = {
            20: pointer_zip(
                "https://qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
                "qualcomm-linux/qcom-deb-images/200-1/\n"
            ),
            10: pointer_zip(
                "https://qli-prod-artifacts.qualcomm.com/qcom-prd-gh-artifacts/"
                "qualcomm-linux/qcom-deb-images/100-1/\n"
            ),
        }
        client = FakeClient([older, requested], artifacts, archives)

        with self.assertRaisesRegex(
            RESOLVER.ResolutionError, "run 200 has no valid build_url"
        ):
            RESOLVER.resolve(
                "arduino",
                "trixie",
                "200",
                client,
                probe=lambda _url, _suite: (_ for _ in ()).throw(
                    RESOLVER.ResolutionError("suite image missing")
                ),
                now=NOW,
            )

        self.assertEqual(client.downloads, [20])


if __name__ == "__main__":
    unittest.main()
