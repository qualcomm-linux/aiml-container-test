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

SCHEMA_VERSION = 2
MEASUREMENT_METHOD_VERSION = 3
EXPECTED_SAMPLE_COUNT = 10
UNSTABLE_CV_THRESHOLD = 0.05
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
    "warmup_measurement",
    "sample_count",
    "samples",
    "discarded_low",
    "discarded_high",
    "raw_mean",
    "trimmed_mean",
    "median",
    "mad",
    "raw_variance",
    "raw_stddev",
    "raw_cv",
    "trimmed_variance",
    "trimmed_stddev",
    "trimmed_cv",
    "stability",
    "telemetry_before",
    "telemetry_after",
    "previous_measurement",
    "change",
    "change_percent",
    "comparison_scope",
    "comparison_status",
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
    if previous.get("schema_version") not in (1, SCHEMA_VERSION):
        return None
    return previous


def match_value(pattern, text):
    match = re.search(pattern, text)
    return match.group(1) if match else None


def extract_log_messages(text):
    messages = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            try:
                entry = json.loads(stripped[2:])
            except json.JSONDecodeError:
                continue
            message = entry.get("msg") if isinstance(entry, dict) else None
            if isinstance(message, list):
                messages.extend(str(value) for value in message)
            elif message is not None:
                messages.append(str(message))
        elif stripped.startswith(("AIML_", "MODEL ", "INPUT ")):
            messages.append(stripped)
    return messages


def parse_log_provenance(messages):
    text = "\n".join(messages)
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
        "outer_warmup_runs": match_value(
            r"AIML_PROVENANCE [^\n]*outer_warmup_runs=(\d+)", text
        ),
        "outer_sample_count": match_value(
            r"AIML_PROVENANCE [^\n]*outer_sample_count=(\d+)", text
        ),
        "benchmark_warmup_runs": match_value(
            r"AIML_PROVENANCE [^\n]*benchmark_warmup_runs=(\d+)", text
        ),
        "benchmark_warmup_min_secs": match_value(
            r"AIML_PROVENANCE [^\n]*benchmark_warmup_min_secs=([0-9.]+)",
            text,
        ),
        "benchmark_num_runs": match_value(
            r"AIML_PROVENANCE [^\n]*benchmark_num_runs=(\d+)", text
        ),
        "benchmark_min_secs": match_value(
            r"AIML_PROVENANCE [^\n]*benchmark_min_secs=([0-9.]+)", text
        ),
        "benchmark_max_secs": match_value(
            r"AIML_PROVENANCE [^\n]*benchmark_max_secs=([0-9.]+)", text
        ),
        "label_image_warmup_runs": match_value(
            r"AIML_PROVENANCE [^\n]*label_image_warmup_runs=(\d+)", text
        ),
        "label_image_count": match_value(
            r"AIML_PROVENANCE [^\n]*label_image_count=(\d+)", text
        ),
        "label_input_sha256": match_value(
            r"INPUT test_case_prefix=tflite-label-image sha256=([0-9a-f]{64})",
            text,
        ),
        "models": models,
    }


def parse_record(message, prefix):
    if not message.startswith(f"{prefix} "):
        return None
    fields = {}
    for token in message.split()[1:]:
        if "=" not in token:
            raise ValueError(f"malformed {prefix} token: {token}")
        key, value = token.split("=", 1)
        if not key or key in fields:
            raise ValueError(f"malformed {prefix} field: {token}")
        fields[key] = value
    return fields


def parse_optional_number(value):
    if value in (None, "na", "unavailable"):
        return None
    return parse_measurement(value)


def parse_required_measurement(value, field):
    measurement = parse_measurement(value)
    if measurement is None:
        raise ValueError(f"missing measurement field: {field}")
    return measurement


def parse_inner_statistics(fields):
    count = fields.get("inner_count")
    if count not in (None, "na") and (not count.isdigit() or int(count) < 1):
        raise ValueError(f"invalid inner_count: {count}")
    return {
        "count": int(count) if count not in (None, "na") else None,
        "min_us": parse_optional_number(fields.get("inner_min_us")),
        "max_us": parse_optional_number(fields.get("inner_max_us")),
        "avg_us": parse_optional_number(fields.get("inner_avg_us")),
        "stddev_us": parse_optional_number(fields.get("inner_stddev_us")),
        "median_us": parse_optional_number(fields.get("inner_median_us")),
        "p5_us": parse_optional_number(fields.get("inner_p5_us")),
        "p95_us": parse_optional_number(fields.get("inner_p95_us")),
    }


def parse_diagnostics(messages):
    diagnostics = {}
    for message in messages:
        if message.startswith("AIML_WARMUP "):
            kind = "warmup"
        elif message.startswith("AIML_SAMPLE "):
            kind = "sample"
        elif message.startswith("AIML_STATS "):
            kind = "statistics"
        elif message.startswith("AIML_TELEMETRY "):
            kind = "telemetry"
        else:
            continue
        record_prefix = {
            "warmup": "AIML_WARMUP",
            "sample": "AIML_SAMPLE",
            "statistics": "AIML_STATS",
            "telemetry": "AIML_TELEMETRY",
        }[kind]
        fields = parse_record(message, record_prefix)
        test_case_id = fields.pop("test_case_id", None)
        if not test_case_id:
            raise ValueError(f"{kind} record is missing test_case_id")
        case = diagnostics.setdefault(
            test_case_id,
            {
                "warmup": None,
                "samples": {},
                "statistics": None,
                "telemetry": {"before": None, "after": None},
            },
        )

        if kind == "telemetry":
            phase = fields.pop("phase", None)
            if phase not in case["telemetry"]:
                raise ValueError(f"invalid telemetry phase for {test_case_id}")
            if case["telemetry"][phase] is not None:
                raise ValueError(f"duplicate {phase} telemetry for {test_case_id}")
            case["telemetry"][phase] = fields
            continue

        if kind == "statistics":
            if case["statistics"] is not None:
                raise ValueError(f"duplicate statistics for {test_case_id}")
            units = fields.pop("units", None)
            if units != "ms":
                raise ValueError(f"invalid statistics units for {test_case_id}")
            count_value = fields.pop("count", None)
            if count_value is None or not count_value.isdigit():
                raise ValueError(f"invalid statistics count for {test_case_id}")
            count = int(count_value)
            statistics = {"count": count, "unit": units}
            for name in (
                "discarded_low",
                "discarded_high",
                "raw_mean",
                "trimmed_mean",
                "median",
                "mad",
                "raw_variance",
                "raw_stddev",
                "raw_cv",
                "trimmed_variance",
                "trimmed_stddev",
                "trimmed_cv",
            ):
                statistics[name] = parse_required_measurement(
                    fields.pop(name, None), name
                )
            if fields:
                raise ValueError(
                    f"unknown statistics fields for {test_case_id}: {fields}"
                )
            statistics["stability"] = (
                "unstable"
                if statistics["trimmed_cv"] >= UNSTABLE_CV_THRESHOLD
                else "stable"
            )
            case["statistics"] = statistics
            continue

        units = fields.pop("units", None)
        if units != "ms":
            raise ValueError(f"invalid {kind} units for {test_case_id}")
        measurement = parse_required_measurement(
            fields.pop("measurement", None), "measurement"
        )
        index = fields.pop("index", None)
        inner = parse_inner_statistics(fields)
        known_inner_fields = {
            "inner_count",
            "inner_min_us",
            "inner_max_us",
            "inner_avg_us",
            "inner_stddev_us",
            "inner_median_us",
            "inner_p5_us",
            "inner_p95_us",
        }
        unknown = set(fields) - known_inner_fields
        if unknown:
            raise ValueError(
                f"unknown {kind} fields for {test_case_id}: {sorted(unknown)}"
            )
        record = {"measurement": measurement, "unit": units, "inner": inner}
        if kind == "warmup":
            if case["warmup"] is not None:
                raise ValueError(f"duplicate warmup for {test_case_id}")
            case["warmup"] = record
        else:
            if index is None:
                raise ValueError(f"sample is missing index for {test_case_id}")
            if not index.isdigit() or int(index) < 1:
                raise ValueError(f"invalid sample index for {test_case_id}")
            index = int(index)
            if index in case["samples"]:
                raise ValueError(f"duplicate sample {index} for {test_case_id}")
            record["index"] = index
            case["samples"][index] = record

    for case in diagnostics.values():
        case["samples"] = [
            case["samples"][index] for index in sorted(case["samples"])
        ]
    return diagnostics


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


def calculate_statistics(samples):
    ordered = sorted(samples)
    count = len(ordered)
    raw_mean = sum(ordered) / count
    median = (ordered[count // 2 - 1] + ordered[count // 2]) / 2
    deviations = sorted(abs(value - median) for value in ordered)
    mad = (deviations[count // 2 - 1] + deviations[count // 2]) / 2
    trimmed = ordered[1:-1]
    trimmed_mean = sum(trimmed) / len(trimmed)

    def sample_variance(values, mean):
        return sum((value - mean) ** 2 for value in values) / (len(values) - 1)

    raw_variance = sample_variance(ordered, raw_mean)
    trimmed_variance = sample_variance(trimmed, trimmed_mean)
    raw_stddev = math.sqrt(raw_variance)
    trimmed_stddev = math.sqrt(trimmed_variance)
    return {
        "count": count,
        "discarded_low": ordered[0],
        "discarded_high": ordered[-1],
        "raw_mean": raw_mean,
        "trimmed_mean": trimmed_mean,
        "median": median,
        "mad": mad,
        "raw_variance": raw_variance,
        "raw_stddev": raw_stddev,
        "raw_cv": raw_stddev / raw_mean if raw_mean else 0,
        "trimmed_variance": trimmed_variance,
        "trimmed_stddev": trimmed_stddev,
        "trimmed_cv": trimmed_stddev / trimmed_mean if trimmed_mean else 0,
    }


def validate_case_diagnostics(
    test_case_id,
    result,
    measurement,
    unit,
    diagnostics,
    configuration_version,
):
    case = diagnostics.get(
        test_case_id,
        {
            "warmup": None,
            "samples": [],
            "statistics": None,
            "telemetry": {"before": None, "after": None},
        },
    )
    if result != "pass":
        if measurement is not None:
            raise ValueError(f"failed test has a measurement: {test_case_id}")
        return case
    if configuration_version != MEASUREMENT_METHOD_VERSION:
        return case

    if unit != "ms":
        raise ValueError(f"passing test has invalid units: {test_case_id}")
    if case["warmup"] is None:
        raise ValueError(f"missing outer warmup for passing test {test_case_id}")
    samples = case["samples"]
    if len(samples) != EXPECTED_SAMPLE_COUNT:
        raise ValueError(
            f"passing test {test_case_id} has {len(samples)} samples; "
            f"expected {EXPECTED_SAMPLE_COUNT}"
        )
    if [sample["index"] for sample in samples] != list(
        range(1, EXPECTED_SAMPLE_COUNT + 1)
    ):
        raise ValueError(f"non-contiguous sample indices for {test_case_id}")
    statistics = case["statistics"]
    if statistics is None or statistics["count"] != EXPECTED_SAMPLE_COUNT:
        raise ValueError(f"missing complete statistics for {test_case_id}")
    calculated = calculate_statistics(
        [sample["measurement"] for sample in samples]
    )
    for name, expected in calculated.items():
        actual = statistics[name]
        if isinstance(expected, int):
            matches = actual == expected
        else:
            matches = math.isclose(
                actual, expected, rel_tol=1e-8, abs_tol=1e-8
            )
        if not matches:
            raise ValueError(
                f"invalid {name} statistic for {test_case_id}: "
                f"{actual} != {expected}"
            )
    if measurement is None or not math.isclose(
        measurement,
        statistics["trimmed_mean"],
        rel_tol=0,
        abs_tol=1e-6,
    ):
        raise ValueError(
            f"LAVA measurement does not match trimmed mean for {test_case_id}"
        )
    return case


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

        messages = extract_log_messages(log_file.read_text(encoding="utf-8"))
        provenance = parse_log_provenance(messages)
        diagnostics = parse_diagnostics(messages)
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
            "outer_warmup_runs": (
                int(provenance["outer_warmup_runs"])
                if provenance["outer_warmup_runs"]
                else None
            ),
            "outer_sample_count": (
                int(provenance["outer_sample_count"])
                if provenance["outer_sample_count"]
                else None
            ),
            "benchmark_warmup_runs": (
                int(provenance["benchmark_warmup_runs"])
                if provenance["benchmark_warmup_runs"]
                else None
            ),
            "benchmark_warmup_min_secs": (
                float(provenance["benchmark_warmup_min_secs"])
                if provenance["benchmark_warmup_min_secs"]
                else None
            ),
            "benchmark_num_runs": (
                int(provenance["benchmark_num_runs"])
                if provenance["benchmark_num_runs"]
                else None
            ),
            "benchmark_min_secs": (
                float(provenance["benchmark_min_secs"])
                if provenance["benchmark_min_secs"]
                else None
            ),
            "benchmark_max_secs": (
                float(provenance["benchmark_max_secs"])
                if provenance["benchmark_max_secs"]
                else None
            ),
            "label_image_warmup_runs": (
                int(provenance["label_image_warmup_runs"])
                if provenance["label_image_warmup_runs"]
                else None
            ),
            "label_image_count": (
                int(provenance["label_image_count"])
                if provenance["label_image_count"]
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
                measurement = parse_measurement(row["measurement"])
                case_diagnostics = validate_case_diagnostics(
                    test_case_id,
                    row["result"],
                    measurement,
                    row["unit"] or None,
                    diagnostics,
                    board["test_configuration"]["version"],
                )
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
                        "measurement": measurement,
                        "unit": row["unit"] or None,
                        "warmup": case_diagnostics["warmup"],
                        "samples": case_diagnostics["samples"],
                        "statistics": case_diagnostics["statistics"],
                        "telemetry": case_diagnostics["telemetry"],
                        "previous_measurement": None,
                        "change": None,
                        "change_percent": None,
                        "comparison_scope": None,
                        "comparison_status": "no-baseline",
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

        method_changed = (
            previous.get("schema_version") != SCHEMA_VERSION
            or previous_board.get("test_configuration", {}).get("version")
            != board.get("test_configuration", {}).get("version")
            or board.get("test_configuration", {}).get("version")
            != MEASUREMENT_METHOD_VERSION
        )
        comparison_scope = (
            "same-dut"
            if board.get("actual_device")
            and board.get("actual_device") == previous_board.get("actual_device")
            else "cross-dut"
        )
        previous_results = {
            result["test_case_id"]: result
            for result in previous_board.get("results", [])
        }
        for result in board["results"]:
            old = previous_results.get(result["test_case_id"])
            if old is None:
                continue
            result["comparison_scope"] = comparison_scope
            if method_changed:
                result["comparison_status"] = "method-changed"
                continue
            if result["result"] != "pass" or old.get("result") != "pass":
                result["comparison_status"] = "result-not-pass"
                continue
            if result["unit"] != old.get("unit"):
                result["comparison_status"] = "unit-changed"
                continue
            if result["model_sha256"] is None:
                result["comparison_status"] = "missing-model-identity"
                continue
            if result["model_sha256"] != old.get("model_sha256"):
                result["comparison_status"] = "model-changed"
                continue
            if (
                result["workload"] == "label_image"
                and result["input_sha256"] is None
            ):
                result["comparison_status"] = "missing-input-identity"
                continue
            if result["input_sha256"] != old.get("input_sha256"):
                result["comparison_status"] = "input-changed"
                continue

            current_value = result["measurement"]
            previous_value = old.get("measurement")
            if current_value is None or previous_value is None:
                result["comparison_status"] = "missing-measurement"
                continue
            result["previous_measurement"] = previous_value
            result["change"] = current_value - previous_value
            result["comparison_status"] = "compared"
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
        ("outer_warmup_runs", "outer warm-up runs", lambda value: str(value)),
        ("outer_sample_count", "outer sample count", lambda value: str(value)),
        (
            "benchmark_warmup_runs",
            "benchmark warm-up runs",
            lambda value: str(value),
        ),
        (
            "benchmark_warmup_min_secs",
            "benchmark warm-up minimum",
            lambda value: f"{value:g} s",
        ),
        ("benchmark_num_runs", "benchmark runs", lambda value: str(value)),
        (
            "benchmark_min_secs",
            "benchmark minimum",
            lambda value: f"{value:g} s",
        ),
        (
            "benchmark_max_secs",
            "benchmark maximum",
            lambda value: f"{value:g} s",
        ),
        (
            "label_image_warmup_runs",
            "label-image warm-up runs",
            lambda value: str(value),
        ),
        ("label_image_count", "label-image count", lambda value: str(value)),
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
        writer = csv.DictWriter(
            destination, fieldnames=RESULT_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        for board in boards:
            job_ids = ",".join(str(job["id"]) for job in board["lava_jobs"])
            for result in board["results"]:
                statistics = result.get("statistics") or {}
                warmup = result.get("warmup") or {}
                telemetry = result.get("telemetry") or {}
                samples = result.get("samples") or []
                writer.writerow(
                    {
                        "board_id": board["id"],
                        "board_name": board["name"],
                        "device_type": board["device_type"],
                        "actual_device": board["actual_device"] or "",
                        "lava_job_id": job_ids,
                        **result,
                        "warmup_measurement": warmup.get("measurement"),
                        "sample_count": len(samples),
                        "samples": json.dumps(
                            [sample["measurement"] for sample in samples],
                            separators=(",", ":"),
                        ),
                        **{
                            field: statistics.get(field)
                            for field in (
                                "discarded_low",
                                "discarded_high",
                                "raw_mean",
                                "trimmed_mean",
                                "median",
                                "mad",
                                "raw_variance",
                                "raw_stddev",
                                "raw_cv",
                                "trimmed_variance",
                                "trimmed_stddev",
                                "trimmed_cv",
                                "stability",
                            )
                        },
                        "telemetry_before": json.dumps(
                            telemetry.get("before"),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        "telemetry_after": json.dumps(
                            telemetry.get("after"),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
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
        "Each latency is the mean after discarding exactly one lowest and one "
        "highest value from 10 measured outer runs. Benchmark values are "
        "converted from microseconds to milliseconds.",
        "",
        "A trimmed coefficient of variation (CV) of 5% or more is marked "
        "**unstable** as a diagnostic only; it does not change the test result.",
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
                "| Test | Model | Accelerator | Result | Latency | Samples | Stability | Previous | Change |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for result in board["results"]:
            statistics = result.get("statistics")
            latency = (
                f"{format_number(result['measurement'])} {result['unit']}"
                if result["measurement"] is not None and result["unit"]
                else "N/A"
            )
            if result["previous_measurement"] is not None:
                scope = (
                    "same DUT"
                    if result["comparison_scope"] == "same-dut"
                    else "**cross-DUT**"
                )
                previous_value = (
                    f"{format_number(result['previous_measurement'])} "
                    f"{result['unit']} ({scope})"
                )
            elif result["comparison_status"] == "method-changed":
                previous_value = "Non-comparable (method changed)"
            else:
                previous_value = "N/A"
            change = (
                f"{result['change']:+.6f} {result['unit']} "
                f"({result['change_percent']:+.2f}%)"
                if result["change"] is not None
                and result["change_percent"] is not None
                else "N/A"
            )
            sample_count = len(result.get("samples") or [])
            sample_summary = (
                f"{sample_count} (trim 1 low/1 high)"
                if sample_count
                else "N/A"
            )
            stability = (
                f"{statistics['stability']}; "
                f"CV {statistics['trimmed_cv'] * 100:.2f}%; "
                f"MAD {format_number(statistics['mad'])} ms"
                if statistics
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
                        sample_summary,
                        stability,
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
        "measurement_method": {
            "version": MEASUREMENT_METHOD_VERSION,
            "outer_warmup_runs": 1,
            "outer_sample_count": EXPECTED_SAMPLE_COUNT,
            "trim_lowest": 1,
            "trim_highest": 1,
            "aggregate": "arithmetic_mean",
        },
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
