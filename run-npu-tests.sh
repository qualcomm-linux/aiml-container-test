#!/bin/bash
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.

set -euo pipefail
IFS=$' \t\n'
export LC_ALL=C

DEVICE_ROOT=${DEVICE_ROOT:-/dev}
GENIE_ROOT=${GENIE_ROOT:-/opt/genie-bundles/qwen3-0.6b}
QNN_ROOT=${QNN_ROOT:-/opt/qnn-bundles}
GENIE_T2T_RUN=${GENIE_T2T_RUN:-/usr/local/bin/genie-t2t-run}
QNN_NET_RUN=${QNN_NET_RUN:-/usr/local/bin/qnn-net-run}
QNN_HTP_BACKEND=${QNN_HTP_BACKEND:-/usr/local/lib/libQnnHtp.so}
QAIRT_VERSION_FILE=${QAIRT_VERSION_FILE:-/usr/share/aiml-container/qairt-version}
MACHINE_NAME=${MACHINE_NAME:-}
NPU_CHIPSET=${NPU_CHIPSET:-}
OUTER_SAMPLE_COUNT=10
TIMEOUT_SECONDS=${NPU_TIMEOUT_SECONDS:-300}

export LD_LIBRARY_PATH="/usr/local/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export ADSP_LIBRARY_PATH="/usr/lib/dsp/cdsp${ADSP_LIBRARY_PATH:+:$ADSP_LIBRARY_PATH}"

temporary_directory=
failures=0

die()
{
	printf 'ERROR: %s\n' "$*" >&2
	exit 2
}

require_command()
{
	command -v "$1" >/dev/null 2>&1 ||
		die "required command not found: $1"
}

require_file()
{
	[[ -f "$1" && -r "$1" ]] ||
		die "required readable file not found: $1"
}

require_executable()
{
	[[ -f "$1" && -x "$1" ]] ||
		die "required executable not found: $1"
}

print_runner_output()
{
	local test_case_id=$1
	local output_file=$2

	printf 'ERROR: runner output for %s follows:\n' "$test_case_id" >&2
	tail -n 100 -- "$output_file" >&2
}

validate_positive_integer()
{
	[[ "$2" =~ ^[1-9][0-9]*$ ]] ||
		die "$1 must be a positive integer, got: $2"
}

cleanup()
{
	local status=$?

	trap - EXIT
	if [[ -n "$temporary_directory" && -d "$temporary_directory" ]]; then
		rm -rf -- "$temporary_directory"
	fi
	exit "$status"
}

trap cleanup EXIT

emit_failure()
{
	printf 'LAVA_RESULT test_case_id=%s result=fail record_end=1\n' "$1"
	failures=$((failures + 1))
}

summarize()
{
	local test_case_id=$1
	local unit=$2
	local samples_file=$3
	local statistics
	local count
	local discarded_low
	local discarded_high
	local raw_mean
	local trimmed_mean
	local median
	local mad
	local raw_variance
	local raw_stddev
	local raw_cv
	local trimmed_variance
	local trimmed_stddev
	local trimmed_cv

	if ! statistics=$(
		python3 - "$samples_file" "$OUTER_SAMPLE_COUNT" <<'PY'
import math
import sys

path, expected = sys.argv[1], int(sys.argv[2])
with open(path, encoding="utf-8") as source:
    values = [float(line) for line in source if line.strip()]
if len(values) != expected or any(not math.isfinite(value) or value < 0 for value in values):
    raise SystemExit(1)
values.sort()
raw_mean = sum(values) / len(values)
median = (values[4] + values[5]) / 2
deviations = sorted(abs(value - median) for value in values)
mad = (deviations[4] + deviations[5]) / 2
trimmed = values[1:-1]
trimmed_mean = sum(trimmed) / len(trimmed)
raw_variance = sum((value - raw_mean) ** 2 for value in values) / (len(values) - 1)
trimmed_variance = sum((value - trimmed_mean) ** 2 for value in trimmed) / (len(trimmed) - 1)
raw_stddev = math.sqrt(raw_variance)
trimmed_stddev = math.sqrt(trimmed_variance)
print(
    "\t".join(
        str(value)
        for value in (
            len(values), values[0], values[-1], raw_mean, trimmed_mean, median,
            mad, raw_variance, raw_stddev,
            raw_stddev / raw_mean if raw_mean else 0,
            trimmed_variance, trimmed_stddev,
            trimmed_stddev / trimmed_mean if trimmed_mean else 0,
        )
    )
)
PY
	); then
		printf 'ERROR: could not aggregate samples for %s\n' "$test_case_id" >&2
		emit_failure "$test_case_id"
		return
	fi

	IFS=$'\t' read -r \
		count discarded_low discarded_high raw_mean trimmed_mean median mad \
		raw_variance raw_stddev raw_cv trimmed_variance trimmed_stddev \
		trimmed_cv <<<"$statistics"
	printf \
		'AIML_STATS test_case_id=%s count=%s discarded_low=%s discarded_high=%s raw_mean=%s trimmed_mean=%s median=%s mad=%s raw_variance=%s raw_stddev=%s raw_cv=%s trimmed_variance=%s trimmed_stddev=%s trimmed_cv=%s units=%s\n' \
		"$test_case_id" "$count" "$discarded_low" "$discarded_high" \
		"$raw_mean" "$trimmed_mean" "$median" "$mad" \
		"$raw_variance" "$raw_stddev" "$raw_cv" \
		"$trimmed_variance" "$trimmed_stddev" "$trimmed_cv" "$unit"
	printf \
		'LAVA_RESULT test_case_id=%s measurement=%.9f units=%s result=pass record_end=1\n' \
		"$test_case_id" "$trimmed_mean" "$unit"
}

detect_chipset()
{
	local model=

	if [[ -n "$NPU_CHIPSET" ]]; then
		printf '%s' "$NPU_CHIPSET"
		return
	fi
	if [[ -r /sys/firmware/devicetree/base/model ]]; then
		model=$(tr -d '\000' </sys/firmware/devicetree/base/model)
	fi
	case "$MACHINE_NAME $model" in
		*qcs6490*|*QCS6490*|*RB3gen2*|*RB3\ Gen\ 2*)
			printf qcs6490
			;;
		*qcs8275*|*QCS8275*|*qcs8300*|*QCS8300*|*VENTUNO\ Q*|*Monza*)
			printf qcs8275
			;;
		*)
			printf unsupported
			;;
	esac
}

run_qnn_sample()
{
	local bundle=$1
	local output_directory=$2
	local output_file=$3

	(
		cd "$bundle"
		timeout --foreground "$TIMEOUT_SECONDS" \
			"$QNN_NET_RUN" \
			--backend "$QNN_HTP_BACKEND" \
			--retrieve_context pose_detector.bin \
			--input_list input_list.txt \
			--output_dir "$output_directory" \
			--profiling_level basic
	) >"$output_file" 2>&1
}

parse_qnn_measurement()
{
	awk '
		index($0, "Inference (avg):") {
			line = $0
			sub(/^.*Inference \(avg\):[[:space:]]*/, "", line)
			sub(/[^0-9.].*$/, "", line)
			if (line !~ /^[0-9]+([.][0-9]+)?$/) exit 1
			if (found++) exit 1
			value = line
		}
		END {
			if (found != 1 || value !~ /^[0-9]+([.][0-9]+)?$/) exit 1
			print value / 1000
		}
	' "$1"
}

run_qnn_case()
{
	local chipset=$1
	local bundle="$QNN_ROOT/mediapipe-pose-${chipset}"
	local test_case_id=qnn-mediapipe-pose-detector-htp
	local samples_file="$temporary_directory/qnn.samples"
	local output_file="$temporary_directory/qnn.output"
	local sample
	local measurement

	require_executable "$QNN_NET_RUN"
	require_file "$QNN_HTP_BACKEND"
	require_file "$bundle/pose_detector.bin"
	require_file "$bundle/input_list.txt"
	require_file "$bundle/pose_detector_input.raw"

	printf 'MODEL model_id=mediapipe-pose-detector sha256=%s path=%s\n' \
		"$(sha256sum "$bundle/pose_detector.bin" | awk '{print $1}')" \
		"$bundle/pose_detector.bin"

	printf 'Running unmeasured outer warm-up for %s.\n' "$test_case_id"
	if ! run_qnn_sample "$bundle" "$temporary_directory/qnn-warmup" "$output_file" ||
		! measurement=$(parse_qnn_measurement "$output_file"); then
		printf 'ERROR: QNN HTP warm-up failed for %s\n' "$test_case_id" >&2
		print_runner_output "$test_case_id" "$output_file"
		emit_failure "$test_case_id"
		return
	fi
	printf 'AIML_WARMUP test_case_id=%s measurement=%s units=ms\n' \
		"$test_case_id" "$measurement"

	for ((sample = 1; sample <= OUTER_SAMPLE_COUNT; sample++)); do
		if ! run_qnn_sample "$bundle" "$temporary_directory/qnn-$sample" "$output_file" ||
			! measurement=$(parse_qnn_measurement "$output_file"); then
			printf 'ERROR: QNN HTP sample %d failed for %s\n' \
				"$sample" "$test_case_id" >&2
			print_runner_output "$test_case_id" "$output_file"
			emit_failure "$test_case_id"
			return
		fi
		printf '%s\n' "$measurement" >>"$samples_file"
		printf 'AIML_SAMPLE test_case_id=%s index=%d measurement=%s units=ms\n' \
			"$test_case_id" "$sample" "$measurement"
	done
	summarize "$test_case_id" ms "$samples_file"
}

parse_genie_metrics()
{
	python3 - "$1" <<'PY'
import json
import math
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    profile = json.load(source)
events = [
    event
    for component in profile.get("components", [])
    for event in component.get("events", [])
    if event.get("type") == "GenieDialog_query"
]
if len(events) != 1:
    raise SystemExit("expected exactly one GenieDialog_query event")
event = events[0]
metrics = (
    ("time-to-first-token", "us", 0.001),
    ("prompt-processing-rate", "toks/sec", 1),
    ("token-generation-rate", "toks/sec", 1),
)
for name, unit, multiplier in metrics:
    metric = event.get(name)
    if not isinstance(metric, dict) or metric.get("unit") != unit:
        raise SystemExit(f"invalid {name} metric")
    value = metric.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SystemExit(f"invalid {name} value")
    value *= multiplier
    if not math.isfinite(value) or value < 0:
        raise SystemExit(f"invalid {name} value")
    print(f"{value:.9f}", end="\t")
PY
}

run_genie_sample()
{
	local bundle=$1
	local profile=$2
	local output_file=$3

	(
		cd "$bundle"
		timeout --foreground "$TIMEOUT_SECONDS" \
			"$GENIE_T2T_RUN" \
			--config genie_config.json \
			--prompt_file sample_prompt.txt \
			--profile "$profile"
	) >"$output_file" 2>&1
}

run_genie_case()
{
	local bundle="$GENIE_ROOT/qcs8275"
	local ttft_case=genie-qwen3-0.6b-htp-ttft
	local prefill_case=genie-qwen3-0.6b-htp-prompt-tokens-per-second
	local decode_case=genie-qwen3-0.6b-htp-token-generation-per-second
	local ttft_samples="$temporary_directory/genie-ttft.samples"
	local prefill_samples="$temporary_directory/genie-prefill.samples"
	local decode_samples="$temporary_directory/genie-decode.samples"
	local output_file="$temporary_directory/genie.output"
	local profile
	local metrics
	local ttft
	local prefill
	local decode
	local sample

	require_executable "$GENIE_T2T_RUN"
	require_file "$bundle/genie_config.json"
	require_file "$bundle/htp_backend_ext_config.json"
	require_file "$bundle/sample_prompt.txt"
	require_file "$bundle/tokenizer.json"
	require_file "$bundle/part1_of_2.bin"
	require_file "$bundle/part2_of_2.bin"

	if ! grep -q '"type": "QnnHtp"' "$bundle/genie_config.json"; then
		die "Genie configuration does not select QnnHtp"
	fi
	printf 'MODEL model_id=qwen3-0.6b sha256=%s path=%s\n' \
		"$(sha256sum "$bundle/part1_of_2.bin" "$bundle/part2_of_2.bin" |
			sha256sum | awk '{print $1}')" \
		"$bundle"

	profile="$temporary_directory/genie-warmup.json"
	printf 'Running unmeasured outer warm-up for Genie.\n'
	if ! run_genie_sample "$bundle" "$profile" "$output_file" ||
		! metrics=$(parse_genie_metrics "$profile"); then
		printf 'ERROR: Genie warm-up failed\n' >&2
		print_runner_output "$ttft_case" "$output_file"
		emit_failure "$ttft_case"
		emit_failure "$prefill_case"
		emit_failure "$decode_case"
		return
	fi
	IFS=$'\t' read -r ttft prefill decode <<<"$metrics"
	printf 'AIML_WARMUP test_case_id=%s measurement=%s units=ms\n' "$ttft_case" "$ttft"
	printf 'AIML_WARMUP test_case_id=%s measurement=%s units=toks/sec\n' "$prefill_case" "$prefill"
	printf 'AIML_WARMUP test_case_id=%s measurement=%s units=toks/sec\n' "$decode_case" "$decode"

	for ((sample = 1; sample <= OUTER_SAMPLE_COUNT; sample++)); do
		profile="$temporary_directory/genie-$sample.json"
		if ! run_genie_sample "$bundle" "$profile" "$output_file" ||
			! metrics=$(parse_genie_metrics "$profile"); then
			printf 'ERROR: Genie sample %d failed\n' "$sample" >&2
			print_runner_output "$ttft_case" "$output_file"
			emit_failure "$ttft_case"
			emit_failure "$prefill_case"
			emit_failure "$decode_case"
			return
		fi
		IFS=$'\t' read -r ttft prefill decode <<<"$metrics"
		printf '%s\n' "$ttft" >>"$ttft_samples"
		printf '%s\n' "$prefill" >>"$prefill_samples"
		printf '%s\n' "$decode" >>"$decode_samples"
		printf 'AIML_SAMPLE test_case_id=%s index=%d measurement=%s units=ms\n' "$ttft_case" "$sample" "$ttft"
		printf 'AIML_SAMPLE test_case_id=%s index=%d measurement=%s units=toks/sec\n' "$prefill_case" "$sample" "$prefill"
		printf 'AIML_SAMPLE test_case_id=%s index=%d measurement=%s units=toks/sec\n' "$decode_case" "$sample" "$decode"
	done
	summarize "$ttft_case" ms "$ttft_samples"
	summarize "$prefill_case" toks/sec "$prefill_samples"
	summarize "$decode_case" toks/sec "$decode_samples"
}

for command_name in awk grep mktemp python3 rm sha256sum tail timeout tr; do
	require_command "$command_name"
done
validate_positive_integer NPU_TIMEOUT_SECONDS "$TIMEOUT_SECONDS"
require_file "$QAIRT_VERSION_FILE"

if ! compgen -G "$DEVICE_ROOT/fastrpc-cdsp*" >/dev/null; then
	printf 'NPU tests skipped: no FastRPC CDSP device under %s.\n' "$DEVICE_ROOT"
	exit 0
fi

chipset=$(detect_chipset)
if [[ "$chipset" == unsupported ]]; then
	printf 'NPU tests skipped: no supported QAIRT HTP chipset was detected (%s).\n' \
		"${MACHINE_NAME:-unknown}"
	exit 0
fi

temporary_directory=$(mktemp -d "${TMPDIR:-/tmp}/run-npu-tests.XXXXXX") ||
	die "could not create temporary directory"
qairt_version=$(<"$QAIRT_VERSION_FILE")
printf \
	'AIML_NPU_PROVENANCE qairt=%s chipset=%s outer_warmup_runs=1 outer_sample_count=%s trimmed_lowest=1 trimmed_highest=1\n' \
	"$qairt_version" "$chipset" "$OUTER_SAMPLE_COUNT"

run_qnn_case "$chipset"
if [[ "$chipset" == qcs8275 ]]; then
	run_genie_case
fi

if (( failures > 0 )); then
	printf '%d NPU test(s) failed.\n' "$failures" >&2
	exit 1
fi

printf 'All selected NPU tests passed.\n'
