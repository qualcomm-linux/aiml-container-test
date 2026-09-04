#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import argparse
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORY = "qualcomm-linux/qcom-deb-images"
ARTIFACT_HOST = "qli-prod-artifacts.qualcomm.com"
ARTIFACT_ROOT = f"/qcom-prd-gh-artifacts/{REPOSITORY}/"
MAX_AGE = timedelta(days=7)
MAX_POINTER_ARCHIVE_SIZE = 64 * 1024
MAX_POINTER_SIZE = 4096
SOURCE_CONFIG = {
    "generic": {
        "workflow_file": "build.yml",
        "workflow_path": ".github/workflows/build.yml",
        "event": "workflow_run",
    },
    "arduino": {
        "workflow_file": "linux-arduino.yml",
        "workflow_path": ".github/workflows/linux-arduino.yml",
        "event": "schedule",
    },
}


class ResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Resolution:
    build_url: str
    publication_attempt: int
    artifact_id: int
    run: dict
    age_hours: int


class AuthStrippingRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        redirected = super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )
        if (
            redirected is not None
            and urlsplit(request.full_url).hostname
            != urlsplit(redirected.full_url).hostname
        ):
            redirected.remove_header("Authorization")
        return redirected


class GitHubClient:
    def __init__(self, token=None):
        self.token = token or os.environ.get("GH_TOKEN")
        if not self.token:
            raise ResolutionError("GH_TOKEN is required")
        self.opener = build_opener(AuthStrippingRedirectHandler())

    def request(self, endpoint, fields=None):
        query = f"?{urlencode(fields)}" if fields else ""
        request = Request(
            f"https://api.github.com/{endpoint}{query}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "aiml-container-test-qcom-image-resolver",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            return self.opener.open(request, timeout=60)
        except (HTTPError, URLError) as error:
            status = getattr(error, "code", "network error")
            raise ResolutionError(
                f"GitHub API request failed for {endpoint} ({status})"
            ) from error

    def get_json(self, endpoint, fields=None):
        with self.request(endpoint, fields) as response:
            try:
                return json.load(response)
            except json.JSONDecodeError as error:
                raise ResolutionError(
                    f"GitHub API returned invalid JSON for {endpoint}"
                ) from error

    def download_artifact(self, artifact_id):
        endpoint = f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip"
        with self.request(endpoint) as response:
            host = urlsplit(response.geturl()).hostname
            if host is None or not host.endswith(".blob.core.windows.net"):
                raise ResolutionError(
                    f"artifact {artifact_id} download redirected to an invalid host"
                )
            archive = response.read(MAX_POINTER_ARCHIVE_SIZE + 1)
        if len(archive) > MAX_POINTER_ARCHIVE_SIZE:
            raise ResolutionError("pointer artifact archive is unexpectedly large")
        return archive


def parse_timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ResolutionError("run has an invalid created_at timestamp") from error
    if parsed.tzinfo is None:
        raise ResolutionError("run created_at timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def validate_run(run, source, now):
    config = SOURCE_CONFIG[source]
    expected = {
        "repository": REPOSITORY,
        "workflow": config["workflow_path"],
        "event": config["event"],
        "branch": "main",
        "conclusion": "success",
    }
    actual = {
        "repository": (run.get("head_repository") or {}).get("full_name"),
        "workflow": run.get("path"),
        "event": run.get("event"),
        "branch": run.get("head_branch"),
        "conclusion": run.get("conclusion"),
    }
    if actual != expected:
        raise ResolutionError(
            f"run {run.get('id', '<unknown>')} does not match the trusted "
            f"qcom-deb-images {source} workflow"
        )
    if not isinstance(run.get("id"), int) or run["id"] <= 0:
        raise ResolutionError("run has an invalid ID")
    if not isinstance(run.get("run_attempt"), int) or run["run_attempt"] <= 0:
        raise ResolutionError(f"run {run['id']} has an invalid workflow attempt")
    if re.fullmatch(r"[0-9a-f]{40}", run.get("head_sha", "")) is None:
        raise ResolutionError(f"run {run['id']} has an invalid commit SHA")

    age = now - parse_timestamp(run.get("created_at"))
    if age < timedelta(0):
        raise ResolutionError(f"run {run['id']} has a future created_at timestamp")
    if age > MAX_AGE:
        raise ResolutionError(
            f"run {run['id']} is {int(age.total_seconds() // 3600)} hours old"
        )
    return int(age.total_seconds() // 3600)


def pointer_artifacts(artifacts):
    candidates = [
        artifact
        for artifact in artifacts
        if artifact.get("name") == "build_url" and artifact.get("expired") is False
    ]
    return sorted(
        candidates,
        key=lambda artifact: (
            parse_timestamp(artifact.get("created_at")),
            artifact.get("id", 0),
        ),
        reverse=True,
    )


def read_pointer_archive(archive):
    if len(archive) > MAX_POINTER_ARCHIVE_SIZE:
        raise ResolutionError("pointer artifact archive is unexpectedly large")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            members = [member for member in bundle.infolist() if not member.is_dir()]
            if len(members) != 1 or members[0].filename != "build_url":
                raise ResolutionError(
                    "pointer artifact must contain exactly one build_url file"
                )
            member = members[0]
            if member.file_size > MAX_POINTER_SIZE:
                raise ResolutionError("build_url pointer is unexpectedly large")
            return bundle.read(member)
    except zipfile.BadZipFile as error:
        raise ResolutionError("pointer artifact is not a valid ZIP archive") from error


def validate_pointer(content, run_id):
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ResolutionError("build_url pointer is not UTF-8") from error

    lines = text.splitlines()
    if len(lines) != 1 or not lines[0] or lines[0] != lines[0].strip():
        raise ResolutionError("build_url pointer must contain exactly one non-empty URL")
    url = lines[0]
    if any(ord(character) < 0x20 or ord(character) > 0x7E for character in url):
        raise ResolutionError("build_url pointer contains invalid characters")

    parsed = urlsplit(url)
    expected_path = re.fullmatch(
        rf"{re.escape(ARTIFACT_ROOT)}{run_id}-([1-9][0-9]*)/?", parsed.path
    )
    if (
        parsed.scheme != "https"
        or parsed.netloc != ARTIFACT_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or expected_path is None
    ):
        raise ResolutionError(
            "build_url pointer is not an approved qcom-deb-images publication URL"
        )

    publication_attempt = int(expected_path.group(1))
    return f"https://{ARTIFACT_HOST}{parsed.path.rstrip('/')}/", publication_attempt


def probe_image(url, suite):
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*", suite) is None:
        raise ResolutionError("suite must contain only lowercase letters, digits, or '-'")
    image_path = (
        f"{urlsplit(url).path.removeprefix('/qcom-prd-gh-artifacts/')}"
        f"{suite}-flash-emmc.tar.gz"
    )
    try:
        presign = subprocess.run(
            [
                "aws",
                "s3",
                "presign",
                f"s3://qcom-prd-gh-artifacts/{image_path}",
                "--expires-in",
                "300",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise ResolutionError("could not authorize the image probe") from error

    probe_url = presign.stdout.strip()
    parsed_probe = urlsplit(probe_url)
    valid_probe_host = (
        parsed_probe.hostname == "qcom-prd-gh-artifacts.s3.amazonaws.com"
        or (
            parsed_probe.hostname is not None
            and parsed_probe.hostname.startswith("qcom-prd-gh-artifacts.s3.")
            and parsed_probe.hostname.endswith(".amazonaws.com")
        )
    )
    if (
        parsed_probe.scheme != "https"
        or not valid_probe_host
        or parsed_probe.username is not None
        or parsed_probe.password is not None
        or parsed_probe.fragment
        or parsed_probe.path != f"/{image_path}"
        or not parsed_probe.query
    ):
        raise ResolutionError("AWS returned an invalid image probe URL")

    result = subprocess.run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--retry",
            "3",
            "--retry-delay",
            "2",
            "--retry-all-errors",
            "--connect-timeout",
            "15",
            "--max-time",
            "60",
            "--max-filesize",
            "1024",
            "--range",
            "0-0",
            "--output",
            os.devnull,
            probe_url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise ResolutionError(
            f"{suite}-flash-emmc.tar.gz probe failed (curl exit {result.returncode})"
        )


def resolve_run(run, source, suite, client, probe, now):
    age_hours = validate_run(run, source, now)
    run_id = run["id"]
    artifacts = []
    for page in range(1, 11):
        artifacts_response = client.get_json(
            f"repos/{REPOSITORY}/actions/runs/{run_id}/artifacts",
            {"per_page": 100, "page": page},
        )
        page_artifacts = artifacts_response.get("artifacts", [])
        artifacts.extend(page_artifacts)
        if len(page_artifacts) < 100:
            break
    candidates = pointer_artifacts(artifacts)
    if not candidates:
        raise ResolutionError(f"run {run_id} has no live build_url artifact")

    failures = []
    for artifact in candidates:
        artifact_id = artifact.get("id")
        if not isinstance(artifact_id, int) or artifact_id <= 0:
            failures.append("invalid artifact ID")
            continue
        if artifact.get("size_in_bytes", 0) > MAX_POINTER_ARCHIVE_SIZE:
            failures.append(f"artifact {artifact_id}: archive is unexpectedly large")
            continue
        try:
            pointer = read_pointer_archive(client.download_artifact(artifact_id))
            build_url, publication_attempt = validate_pointer(pointer, run_id)
            probe(build_url, suite)
        except (ResolutionError, subprocess.CalledProcessError) as error:
            failures.append(f"artifact {artifact_id}: {error}")
            continue
        return Resolution(
            build_url=build_url,
            publication_attempt=publication_attempt,
            artifact_id=artifact_id,
            run=run,
            age_hours=age_hours,
        )

    raise ResolutionError(
        f"run {run_id} has no valid build_url pointer for suite {suite}: "
        + "; ".join(failures)
    )


def automatic_runs(source, client, now):
    config = SOURCE_CONFIG[source]
    runs = []
    for page in range(1, 11):
        response = client.get_json(
            f"repos/{REPOSITORY}/actions/workflows/{config['workflow_file']}/runs",
            {
                "branch": "main",
                "status": "success",
                "per_page": 100,
                "page": page,
            },
        )
        page_runs = response.get("workflow_runs", [])
        runs.extend(page_runs)
        if len(page_runs) < 100:
            break
        timestamps = [
            parse_timestamp(run.get("created_at"))
            for run in page_runs
            if run.get("created_at")
        ]
        if timestamps and min(timestamps) < now - MAX_AGE:
            break
    return sorted(
        runs,
        key=lambda run: (parse_timestamp(run.get("created_at")), run.get("id", 0)),
        reverse=True,
    )


def resolve(source, suite, requested_run_id, client, probe=probe_image, now=None):
    if source not in SOURCE_CONFIG:
        raise ResolutionError(f"unknown image source: {source}")
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*", suite) is None:
        raise ResolutionError("suite must contain only lowercase letters, digits, or '-'")
    now = now or datetime.now(timezone.utc)

    if requested_run_id:
        if re.fullmatch(r"[0-9]+", requested_run_id) is None:
            raise ResolutionError("run_id must contain only decimal digits")
        run = client.get_json(
            f"repos/{REPOSITORY}/actions/runs/{requested_run_id}"
        )
        return resolve_run(run, source, suite, client, probe, now)

    failures = []
    for run in automatic_runs(source, client, now):
        try:
            resolution = resolve_run(run, source, suite, client, probe, now)
        except (ResolutionError, subprocess.CalledProcessError) as error:
            failures.append(str(error))
            print(f"Skipping producer run {run.get('id')}: {error}", file=sys.stderr)
            continue
        return resolution

    detail = f": {'; '.join(failures)}" if failures else ""
    raise ResolutionError(
        f"no recent trusted qcom-deb-images {source} run has a valid {suite} image"
        f"{detail}"
    )


def write_result(resolution, source, output_path, summary_path):
    run = resolution.run
    outputs = {
        "build_url": resolution.build_url,
        "publication_attempt": resolution.publication_attempt,
        "run_id": run["id"],
        "run_attempt": run["run_attempt"],
        "workflow": run["path"],
        "event": run["event"],
        "ref": run["head_branch"],
        "sha": run["head_sha"],
    }
    with output_path.open("a", encoding="utf-8") as output:
        for key, value in outputs.items():
            output.write(f"{key}={value}\n")

    summary = [
        "qcom-deb-images input:",
        f"  Image source: {source}",
        (
            f"  Run: {run['id']} workflow attempt {run['run_attempt']} "
            f"({run['html_url']})"
        ),
        (
            f"  Created: {run['created_at']} "
            f"({resolution.age_hours} hours old)"
        ),
        f"  Pointer artifact ID: {resolution.artifact_id}",
        f"  Publication attempt: {resolution.publication_attempt}",
        f"  Artifact prefix: {resolution.build_url}",
    ]
    with summary_path.open("a", encoding="utf-8") as summary_file:
        summary_file.write("\n".join(summary) + "\n")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Resolve a trusted qcom-deb-images publication pointer"
    )
    parser.add_argument("--source", choices=sorted(SOURCE_CONFIG), required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--github-output",
        type=Path,
        default=os.environ.get("GITHUB_OUTPUT"),
    )
    parser.add_argument(
        "--github-step-summary",
        type=Path,
        default=os.environ.get("GITHUB_STEP_SUMMARY"),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.github_output is None or args.github_step_summary is None:
        raise ResolutionError(
            "GITHUB_OUTPUT and GITHUB_STEP_SUMMARY must be set or passed explicitly"
        )
    resolution = resolve(
        args.source,
        args.suite,
        args.run_id,
        GitHubClient(),
    )
    write_result(
        resolution,
        args.source,
        args.github_output,
        args.github_step_summary,
    )


if __name__ == "__main__":
    try:
        main()
    except (ResolutionError, subprocess.CalledProcessError) as error:
        print(f"::error::{error}", file=sys.stderr)
        raise SystemExit(1)
