#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import argparse
import csv
import json
import math
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
ACCELERATOR_ORDER = {"cpu": 0, "gpu": 1, "cdsp": 2}
RESULT_FIELDS = [
    "board_id",
    "board_name",
    "device_type",
    "actual_device",
    "lava_job_id",
    "test_case_id",
    "workload",
    "model_id",
    "model_sha256",
    "input_sha256",
    "accelerator",
    "result",
    "measurement",
    "unit",
    "previous_measurement",
    "change",
    "change_percent",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate TensorFlow Lite reports from LAVA API exports"
    )
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--boards", type=Path, required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--lava-url", required=True)
    parser.add_argument("--qcom-run-id", required=True)
    parser.add_argument("--qcom-run-attempt", required=True)
    parser.add_argument("--qcom-publication-attempt", required=True)
    parser.add_argument("--qcom-workflow", required=True)
    parser.add_argument("--qcom-event", required=True)
    parser.add_argument("--qcom-ref", required=True)
    parser.add_argument("--qcom-sha", required=True)
    parser.add_argument("--aiml-repository", required=True)
    parser.add_argument("--aiml-ref", required=True)
    parser.add_argument("--aiml-sha", required=True)
    parser.add_argument("--aiml-run-id", required=True)
    parser.add_argument("--aiml-run-attempt", required=True)
    parser.add_argument("--container-digest", required=True)
    parser.add_argument("--previous-results", type=Path)
    return parser.parse_args()


def load_board_map(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported boards schema in {path}")

    device_types = {}
    for board_id, board in data["boards"].items():
        for device_type in board["device_types"]:
            if device_type in device_types:
                raise ValueError(f"duplicate device type in {path}: {device_type}")
            device_types[device_type] = {
                "id": board_id,
                "display_name": board["display_name"],
            }
    return device_types


def read_previous(path):
    if path is None or not path.is_file():
        return None
    previous = json.loads(path.read_text(encoding="utf-8"))
    if previous.get("schema_version") != SCHEMA_VERSION:
        return None
    return previous


def match_value(pattern, text):
    match = re.search(pattern, text)
    return match.group(1) if match else None


def parse_log_provenance(text):
    models = {
        model_id: checksum
        for model_id, checksum in re.findall(
            r"MODEL model_id=(\S+) sha256=([0-9a-f]{64})", text
        )
    }
    return {
        "kernel": match_value(r'AIML_PROVENANCE kernel=([^\s"\'}]+)', text),
        "qairt": match_value(r'AIML_PROVENANCE qairt=([^\s"\'}]+)', text),
        "tflite_commit": match_value(
            r"AIML_PROVENANCE [^\n]*tflite_commit=([0-9a-f]{40})", text
        ),
        "configuration_version": match_value(
            r"AIML_PROVENANCE [^\n]*configuration_version=(\d+)", text
        ),
        "threads": match_value(r"AIML_PROVENANCE [^\n]*threads=(\d+)", text),
        "timeout_seconds": match_value(
            r"AIML_PROVENANCE [^\n]*timeout_seconds=(\d+)", text
        ),
        "op_profiling": match_value(
            r"AIML_PROVENANCE [^\n]*op_profiling=([01])", text
        ),
        "label_input_sha256": match_value(
            r"INPUT test_case_prefix=tflite-label-image sha256=([0-9a-f]{64})",
            text,
        ),
        "models": models,
    }


def parse_test_case(test_case_id):
    if test_case_id.startswith("tflite-label-image-"):
        accelerator = test_case_id.removeprefix("tflite-label-image-")
        return {
            "workload": "label_image",
            "model_id": "mobilenet-quant-v1-224",
            "accelerator": accelerator,
        }

    prefix = "tflite-benchmark-"
    if test_case_id.startswith(prefix):
        for accelerator in ACCELERATOR_ORDER:
            suffix = f"-{accelerator}"
            if test_case_id.endswith(suffix):
                return {
                    "workload": "benchmark_model",
                    "model_id": test_case_id[len(prefix) : -len(suffix)],
                    "accelerator": accelerator,
                }
    raise ValueError(f"unrecognised TensorFlow Lite test case: {test_case_id}")


def parse_measurement(value):
    if value in ("", "None", None):
        return None
    measurement = float(value)
    if not math.isfinite(measurement) or measurement < 0:
        raise ValueError(f"invalid measurement: {value}")
    return measurement


def result_sort_key(result):
    return (
        0 if result["workload"] == "label_image" else 1,
        result["model_id"],
        ACCELERATOR_ORDER.get(result["accelerator"], 99),
        result["test_case_id"],
    )


def graph_label(result):
    accelerator = result["accelerator"].upper()
    if result["workload"] == "label_image":
        return f"LI {accelerator}"
    if result["model_id"] == "mobilenet-quant-v1-224":
        return f"BM {accelerator}"
    return f"BM {result['model_id']} {accelerator}"


def format_number(value):
    if value is None:
        return "N/A"
    return f"{value:.6f}".rstrip("0").rstrip(".")


def graph_limit(values):
    maximum = max(values)
    if maximum == 0:
        return 1
    step = 10 ** (math.floor(math.log10(maximum)) - 1)
    limit = math.ceil((maximum * 1.05) / step) * step
    if limit <= maximum:
        limit += step
    return format_number(limit)


def markdown_escape(value):
    return str(value).replace("|", "\\|")


def load_jobs(input_dir, board_map, lava_url):
    boards = {}
    job_files = sorted(input_dir.glob("job-*.json"))
    if not job_files:
        raise ValueError(f"no LAVA job details found in {input_dir}")

    jobs = []
    for job_file in job_files:
        job = json.loads(job_file.read_text(encoding="utf-8"))
        job_id = str(job["id"])
        device_type = job["requested_device_type"]
        if device_type not in board_map:
            raise ValueError(f"no board metadata for LAVA device type {device_type}")
        jobs.append((int(job_id), job, board_map[device_type]))

    latest_job_ids = {}
    for job_id, _, board_metadata in jobs:
        latest_job_ids[board_metadata["id"]] = max(
            job_id, latest_job_ids.get(board_metadata["id"], 0)
        )

    for numeric_job_id, job, board_metadata in sorted(jobs):
        job_id = str(numeric_job_id)
        device_type = job["requested_device_type"]
        board = boards.setdefault(
            board_metadata["id"],
            {
                "id": board_metadata["id"],
                "name": board_metadata["display_name"],
                "device_type": device_type,
                "actual_device": None,
                "kernel": None,
                "qairt": None,
                "tflite_commit": None,
                "test_configuration": {},
                "lava_jobs": [],
                "results": [],
            },
        )
        board["lava_jobs"].append(
            {
                "id": int(job_id),
                "url": f"{lava_url.rstrip('/')}/scheduler/job/{job_id}",
            }
        )
        if numeric_job_id != latest_job_ids[board_metadata["id"]]:
            continue
        board["device_type"] = device_type
        board["actual_device"] = job.get("actual_device")

        log_file = input_dir / f"job-{job_id}.yaml"
        tests_file = input_dir / f"job-{job_id}-tests.csv"
        if not log_file.is_file() or not tests_file.is_file():
            raise ValueError(f"incomplete LAVA API export for job {job_id}")

        provenance = parse_log_provenance(log_file.read_text(encoding="utf-8"))
        board["kernel"] = provenance["kernel"] or board["kernel"]
        board["qairt"] = provenance["qairt"] or board["qairt"]
        board["tflite_commit"] = (
            provenance["tflite_commit"] or board["tflite_commit"]
        )
        board["test_configuration"] = {
            "version": (
                int(provenance["configuration_version"])
                if provenance["configuration_version"]
                else None
            ),
            "threads": (
                int(provenance["threads"]) if provenance["threads"] else None
            ),
            "timeout_seconds": (
                int(provenance["timeout_seconds"])
                if provenance["timeout_seconds"]
                else None
            ),
            "op_profiling": (
                provenance["op_profiling"] == "1"
                if provenance["op_profiling"] is not None
                else None
            ),
        }

        with tests_file.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                test_case_id = row["name"]
                if not row["suite"].endswith("aiml-container-smoke"):
                    continue
                if not test_case_id.startswith("tflite-"):
                    continue

                parsed = parse_test_case(test_case_id)
                model_sha256 = provenance["models"].get(parsed["model_id"])
                board["results"].append(
                    {
                        "test_case_id": test_case_id,
                        **parsed,
                        "model_sha256": model_sha256,
                        "input_sha256": (
                            provenance["label_input_sha256"]
                            if parsed["workload"] == "label_image"
                            else None
                        ),
                        "result": row["result"],
                        "measurement": parse_measurement(row["measurement"]),
                        "unit": row["unit"] or None,
                        "previous_measurement": None,
                        "change": None,
                        "change_percent": None,
                    }
                )

    for board in boards.values():
        board["lava_jobs"].sort(key=lambda job: job["id"])
        board["results"].sort(key=result_sort_key)
    return sorted(boards.values(), key=lambda board: board["name"])


def previous_board_index(previous):
    if previous is None:
        return {}
    return {board["id"]: board for board in previous.get("boards", [])}


def add_comparisons(boards, previous, suite):
    previous_boards = previous_board_index(previous)
    if previous is None or previous.get("suite") != suite:
        return {}

    for board in boards:
        previous_board = previous_boards.get(board["id"])
        if previous_board is None:
            continue

        previous_results = {
            result["test_case_id"]: result
            for result in previous_board.get("results", [])
        }
        for result in board["results"]:
            old = previous_results.get(result["test_case_id"])
            if old is None:
                continue
            if result["result"] != "pass" or old.get("result") != "pass":
                continue
            if result["unit"] != old.get("unit"):
                continue
            if result["model_sha256"] is None:
                continue
            if result["model_sha256"] != old.get("model_sha256"):
                continue
            if (
                result["workload"] == "label_image"
                and result["input_sha256"] is None
            ):
                continue
            if result["input_sha256"] != old.get("input_sha256"):
                continue

            current_value = result["measurement"]
            previous_value = old.get("measurement")
            if current_value is None or previous_value is None:
                continue
            result["previous_measurement"] = previous_value
            result["change"] = current_value - previous_value
            if previous_value != 0:
                result["change_percent"] = (
                    (current_value - previous_value) / previous_value
                ) * 100
    return previous_boards


def environment_changes(board, previous_board, provenance, previous_provenance):
    if previous_board is None:
        return []

    values = [
        (
            "qcom-deb-images SHA",
            previous_provenance.get("qcom_deb_images", {}).get("sha"),
            provenance["qcom_deb_images"]["sha"],
        ),
        (
            "kernel",
            previous_board.get("kernel"),
            board.get("kernel"),
        ),
        (
            "QAIRT",
            previous_board.get("qairt"),
            board.get("qairt"),
        ),
        (
            "TensorFlow Lite commit",
            previous_board.get("tflite_commit"),
            board.get("tflite_commit"),
        ),
        (
            "AIML container SHA",
            previous_provenance.get("aiml_container", {}).get("sha"),
            provenance["aiml_container"]["sha"],
        ),
        (
            "container digest",
            previous_provenance.get("aiml_container", {}).get("digest"),
            provenance["aiml_container"]["digest"],
        ),
    ]
    return [
        f"{name}: `{old or 'N/A'}` -> `{new or 'N/A'}`"
        for name, old, new in values
        if old != new
    ]


def test_configuration_changes(board, previous_board):
    if previous_board is None:
        return []

    previous = previous_board.get("test_configuration", {})
    current = board.get("test_configuration", {})
    fields = [
        ("version", "version", lambda value: str(value)),
        ("threads", "threads", lambda value: str(value)),
        (
            "timeout_seconds",
            "timeout",
            lambda value: f"{value} s",
        ),
        (
            "op_profiling",
            "operator profiling",
            lambda value: "enabled" if value else "disabled",
        ),
    ]
    changes = []
    for key, label, formatter in fields:
        old = previous.get(key)
        new = current.get(key)
        if old == new:
            continue
        old_display = "N/A" if old is None else formatter(old)
        new_display = "N/A" if new is None else formatter(new)
        changes.append(f"{label}: `{old_display}` -> `{new_display}`")
    return changes


def write_csv(path, boards):
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        for board in boards:
            job_ids = ",".join(str(job["id"]) for job in board["lava_jobs"])
            for result in board["results"]:
                writer.writerow(
                    {
                        "board_id": board["id"],
                        "board_name": board["name"],
                        "device_type": board["device_type"],
                        "actual_device": board["actual_device"] or "",
                        "lava_job_id": job_ids,
                        **result,
                    }
                )


def provenance_table(lines, boards, provenance):
    qcom = provenance["qcom_deb_images"]
    aiml = provenance["aiml_container"]
    qcom_run_url = (
        "https://github.com/qualcomm-linux/qcom-deb-images/actions/runs/"
        f"{qcom['run_id']}"
    )
    qcom_commit_url = (
        "https://github.com/qualcomm-linux/qcom-deb-images/commit/" f"{qcom['sha']}"
    )
    aiml_run_url = (
        f"https://github.com/{aiml['repository']}/actions/runs/{aiml['run_id']}"
    )
    aiml_commit_url = (
        f"https://github.com/{aiml['repository']}/commit/{aiml['sha']}"
    )

    lines.extend(
        [
            "## Provenance",
            "",
            "| Board | qcom-deb-images | Kernel | AIML container | TensorFlow Lite | QAIRT | Container digest | LAVA |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for board in boards:
        lava_links = ", ".join(
            f"[{job['id']}]({job['url']}) on "
            f"`{board['actual_device'] or board['device_type']}`"
            for job in board["lava_jobs"]
        )
        qcom_link = (
            f"[`{qcom['ref']}@{qcom['sha'][:12]}`]({qcom_commit_url}) "
            f"via [`{qcom['workflow']}` ({qcom['event']}) "
            f"run {qcom['run_id']}, workflow attempt {qcom['run_attempt']}]"
            f"({qcom_run_url}); publication attempt "
            f"{qcom['publication_attempt']}"
        )
        aiml_link = (
            f"[`{aiml['ref']}@{aiml['sha'][:12]}`]({aiml_commit_url}) "
            f"via [run {aiml['run_id']}]({aiml_run_url})"
        )
        lines.append(
            "| "
            + " | ".join(
                markdown_escape(value)
                for value in (
                    board["name"],
                    qcom_link,
                    f"`{board['kernel'] or 'N/A'}`",
                    aiml_link,
                    f"`{board['tflite_commit'] or 'N/A'}`",
                    f"`{board['qairt'] or 'N/A'}`",
                    f"`{aiml['digest']}`",
                    lava_links,
                )
            )
            + " |"
        )
    lines.append("")


def write_summary(path, boards, provenance, previous, previous_boards):
    lines = [
        "# TensorFlow Lite performance",
        "",
        "Lower latency is better. Every graph uses a linear Y axis starting at zero. "
        "Benchmark values are converted from microseconds to milliseconds.",
        "",
    ]
    previous_provenance = previous.get("provenance", {}) if previous else {}

    for board in boards:
        lines.extend([f"## {board['name']}", ""])
        if not board["results"]:
            lines.extend(
                [
                    "**Tests did not run.** No TensorFlow Lite test cases were "
                    "recorded for this board.",
                    "",
                ]
            )
            continue

        measured = [
            result
            for result in board["results"]
            if result["result"] == "pass"
            and result["measurement"] is not None
            and result["unit"] == "ms"
        ]
        if measured:
            labels = ", ".join(
                json.dumps(graph_label(result)) for result in measured
            )
            values = ", ".join(
                format_number(result["measurement"]) for result in measured
            )
            lines.extend(
                [
                    "```mermaid",
                    "xychart-beta",
                    f'    title "{board["name"]} TensorFlow Lite latency"',
                    f"    x-axis [{labels}]",
                    f'    y-axis "Latency (ms)" 0 --> {graph_limit([result["measurement"] for result in measured])}',
                    f"    bar [{values}]",
                    "```",
                    "",
                ]
            )
        else:
            lines.extend(["No latency measurements were recorded.", ""])

        lines.extend(
            [
                "| Test | Model | Accelerator | Result | Latency | Previous | Change |",
                "|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for result in board["results"]:
            latency = (
                f"{format_number(result['measurement'])} {result['unit']}"
                if result["measurement"] is not None and result["unit"]
                else "N/A"
            )
            previous_value = (
                f"{format_number(result['previous_measurement'])} {result['unit']}"
                if result["previous_measurement"] is not None
                else "N/A"
            )
            change = (
                f"{result['change']:+.6f} {result['unit']} "
                f"({result['change_percent']:+.2f}%)"
                if result["change"] is not None
                and result["change_percent"] is not None
                else "N/A"
            )
            lines.append(
                "| "
                + " | ".join(
                    markdown_escape(value)
                    for value in (
                        f"`{result['test_case_id']}`",
                        f"`{result['model_id']}`",
                        result["accelerator"].upper(),
                        result["result"],
                        latency,
                        previous_value,
                        change,
                    )
                )
                + " |"
            )
        lines.append("")

        changes = environment_changes(
            board,
            previous_boards.get(board["id"]),
            provenance,
            previous_provenance,
        )
        if changes:
            lines.append("Environment changes since the previous report:")
            lines.extend(f"- {change}" for change in changes)
            lines.append("")
        previous_board = previous_boards.get(board["id"])
        configuration_changes = test_configuration_changes(board, previous_board)
        if configuration_changes:
            lines.append("Test configuration changes since the previous report:")
            lines.extend(f"- {change}" for change in configuration_changes)
            lines.append("")

    provenance_table(lines, boards, provenance)
    path.write_text("\n".join(lines), encoding="utf-8")


def prepare_output(output_dir, input_dir, boards):
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in ("results.json", "results.csv", "summary.md"):
        path = output_dir / filename
        if path.exists():
            path.unlink()

    raw_logs = output_dir / "raw-logs"
    if raw_logs.exists():
        shutil.rmtree(raw_logs)
    raw_logs.mkdir()

    for board in boards:
        for job in board["lava_jobs"]:
            source = input_dir / f"job-{job['id']}.yaml"
            destination = raw_logs / f"{board['id']}-{job['id']}.yaml"
            shutil.copyfile(source, destination)


def main():
    args = parse_args()
    board_map = load_board_map(args.boards)
    boards = load_jobs(args.input_dir, board_map, args.lava_url)
    previous = read_previous(args.previous_results)

    provenance = {
        "qcom_deb_images": {
            "repository": "qualcomm-linux/qcom-deb-images",
            "workflow": args.qcom_workflow,
            "event": args.qcom_event,
            "ref": args.qcom_ref,
            "sha": args.qcom_sha,
            "run_id": int(args.qcom_run_id),
            "run_attempt": int(args.qcom_run_attempt),
            "publication_attempt": int(args.qcom_publication_attempt),
        },
        "aiml_container": {
            "repository": args.aiml_repository,
            "ref": args.aiml_ref,
            "sha": args.aiml_sha,
            "run_id": int(args.aiml_run_id),
            "run_attempt": int(args.aiml_run_attempt),
            "digest": args.container_digest,
        },
    }
    previous_boards = add_comparisons(boards, previous, args.suite)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suite": args.suite,
        "provenance": provenance,
        "boards": boards,
    }

    prepare_output(args.output_dir, args.input_dir, boards)
    (args.output_dir / "results.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_csv(args.output_dir / "results.csv", boards)
    write_summary(
        args.output_dir / "summary.md",
        boards,
        provenance,
        previous,
        previous_boards,
    )


if __name__ == "__main__":
    main()
