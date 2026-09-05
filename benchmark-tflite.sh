#!/bin/bash
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.

set -euo pipefail
IFS=$' \t\n'
export LC_ALL=C

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
RUN_TFLITE=${RUN_TFLITE:-"$SCRIPT_DIR/run-tflite.sh"}
BENCHMARK_SETUP_DELAY_SECONDS=${BENCHMARK_SETUP_DELAY_SECONDS:-10}

[[ "$BENCHMARK_SETUP_DELAY_SECONDS" =~ ^[0-9]+$ ]] || {
	printf 'ERROR: BENCHMARK_SETUP_DELAY_SECONDS must be a non-negative integer, got: %s\n' \
		"$BENCHMARK_SETUP_DELAY_SECONDS" >&2
	exit 2
}
[[ -f "$RUN_TFLITE" && -x "$RUN_TFLITE" ]] || {
	printf 'ERROR: run-tflite entry point is not executable: %s\n' \
		"$RUN_TFLITE" >&2
	exit 2
}

printf '%s\n' \
	'Run the following outside the container to have the CPUs run at full tilt:' \
	"for i in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo \"performance\" > \"\$i\"; done" \
	'' \
	'Extend the GPU hangcheck timer to avoid some models timing out:' \
	'echo 6000 > /sys/kernel/debug/dri/0/hangcheck_period_ms'

if (( BENCHMARK_SETUP_DELAY_SECONDS > 0 )); then
	printf '\nPausing for %s seconds so you can apply the host settings.\n' \
		"$BENCHMARK_SETUP_DELAY_SECONDS"
	sleep "$BENCHMARK_SETUP_DELAY_SECONDS"
fi

# This entry point intentionally runs only externally mounted models on CPU and
# GPU. run-tflite.sh owns command execution, measurement parsing, and results.
export RUN_LABEL_IMAGE=0
export RUN_BUILTIN_MODEL=0
export REQUIRE_MODEL_DIR=1
export ACCELERATORS=${ACCELERATORS:-cpu,gpu}

exec "$RUN_TFLITE"
