#!/bin/bash
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.

set -euo pipefail
shopt -s nullglob

MODEL_DIR=${MODEL_DIR:-/root/models}
THREADS=${THREADS:-$(nproc)}
TIMEOUT_SECONDS=${TIMEOUT_SECONDS:-300}
ENABLE_OP_PROFILING=${ENABLE_OP_PROFILING:-0}

LABEL_IMAGE_DIR=/root/tensorflow/lite/examples/label_image
BENCHMARK_BIN=/root/tensorflow/lite/tools/benchmark/benchmark_model
BUILTIN_MODEL="$LABEL_IMAGE_DIR/mobilenet_quant_v1_224.tflite"

failures=0
output_file=

cleanup()
{
	[[ -z "$output_file" ]] || rm -f -- "$output_file"
}

trap cleanup EXIT

# Compatibility links required by some TensorFlow Lite consumers.
ln -sf \
	/usr/lib/aarch64-linux-gnu/libOpenCL.so.1 \
	/usr/lib/aarch64-linux-gnu/libOpenCL.so

ln -sf \
	/usr/lib/aarch64-linux-gnu/libcdsprpc.so.1.0.0 \
	/usr/lib/aarch64-linux-gnu/libcdsprpc.so

gpu_delegate=/root/tensorflow/lite/delegates/gpu/libtensorflowlite_gpu_delegate.so
if [[ -e "$gpu_delegate" ]]; then
	ln -sf \
		"$gpu_delegate" \
		/lib/aarch64-linux-gnu/libtensorflowlite_gpu_delegate.so
fi

has_gpu=false
if compgen -G '/dev/dri/renderD*' >/dev/null ||
   compgen -G '/dev/card/renderD*' >/dev/null; then
	has_gpu=true
fi

has_cdsp=false
if compgen -G '/dev/fastrpc-cdsp*' >/dev/null; then
	has_cdsp=true
fi

sanitize_id()
{
	local value=$1

	value=${value%.tflite}
	value=${value//\//-}

	printf '%s' "$value" |
		tr '[:upper:]' '[:lower:]' |
		tr -cs '[:alnum:]_-' '-'
}

emit_pass()
{
	local test_case_id=$1
	local measurement=$2

	printf \
		'LAVA_RESULT test_case_id=%s result=pass measurement=%s units=ms\n' \
		"$test_case_id" \
		"$measurement"
}

emit_failure()
{
	local test_case_id=$1

	printf 'LAVA_RESULT test_case_id=%s result=fail\n' "$test_case_id"
	failures=$((failures + 1))
}

run_case()
{
	local test_case_id=$1
	local output_kind=$2
	local measurement
	local command_status
	local tee_status
	local -a statuses

	shift 2

	printf '\nRunning %s:' "$test_case_id"
	printf ' %q' "$@"
	printf '\n'

	output_file=$(mktemp)

	set +e
	timeout --foreground "$TIMEOUT_SECONDS" "$@" 2>&1 |
		tee "$output_file"
	statuses=("${PIPESTATUS[@]}")
	set -e

	command_status=${statuses[0]}
	tee_status=${statuses[1]}

	if (( command_status != 0 )); then
		printf 'ERROR: %s exited with status %d\n' \
			"$test_case_id" "$command_status" >&2
		emit_failure "$test_case_id"
		rm -f -- "$output_file"
		output_file=
		return
	fi

	if (( tee_status != 0 )); then
		printf 'ERROR: failed to capture output for %s\n' \
			"$test_case_id" >&2
		emit_failure "$test_case_id"
		rm -f -- "$output_file"
		output_file=
		return
	fi

	case "$output_kind" in
	label-image)
		measurement=$(
			sed -nE \
				's/.*average time: ([0-9]+([.][0-9]+)?) ms.*/\1/p' \
				"$output_file" |
				tail -n1
		)
		;;
	benchmark)
		measurement=$(
			sed -nE \
				's/.*Inference \(avg\): ([0-9]+([.][0-9]+)?).*/\1/p' \
				"$output_file" |
				tail -n1 |
				awk '{ printf "%.6f", $1 / 1000 }'
		)
		;;
	*)
		printf 'ERROR: unknown output kind: %s\n' "$output_kind" >&2
		exit 2
		;;
	esac

	rm -f -- "$output_file"
	output_file=

	if [[ -z "$measurement" ]]; then
		printf 'ERROR: no latency measurement found for %s\n' \
			"$test_case_id" >&2
		emit_failure "$test_case_id"
		return
	fi

	emit_pass "$test_case_id" "$measurement"
}

run_benchmark_model()
{
	local model=$1
	local model_id=$2
	local model_sha256
	local -a common_args

	model_sha256=$(sha256sum "$model" | awk '{ print $1 }')

	printf '\nMODEL model_id=%s sha256=%s path=%q\n' \
		"$model_id" "$model_sha256" "$model"

	common_args=(
		"--graph=$model"
		"--num_threads=$THREADS"
	)

	if [[ "$ENABLE_OP_PROFILING" == 1 ]]; then
		common_args+=(--enable_op_profiling=true)
	fi

	run_case \
		"tflite-benchmark-${model_id}-cpu" \
		benchmark \
		"$BENCHMARK_BIN" \
		"${common_args[@]}" \
		--use_gpu=false \
		--use_xnnpack=true

	if [[ "$has_gpu" == true ]]; then
		run_case \
			"tflite-benchmark-${model_id}-gpu" \
			benchmark \
			"$BENCHMARK_BIN" \
			"${common_args[@]}" \
			--use_gpu=true
	fi

	if [[ "$has_cdsp" == true ]]; then
		run_case \
			"tflite-benchmark-${model_id}-cdsp" \
			benchmark \
			"$BENCHMARK_BIN" \
			"${common_args[@]}" \
			--use_gpu=false \
			--external_delegate_path=/usr/local/lib/libQnnTFLiteDelegate.so \
			--external_delegate_options=backend_type:htp
	fi
}

cd "$LABEL_IMAGE_DIR"

run_case \
	tflite-label-image-cpu \
	label-image \
	./label_image \
	--image=grace_hopper.bmp \
	--use_gpu=false

if [[ "$has_gpu" == true ]]; then
	run_case \
		tflite-label-image-gpu \
		label-image \
		./label_image \
		--image=grace_hopper.bmp \
		--use_gpu=true
fi

if [[ "$has_cdsp" == true ]]; then
	run_case \
		tflite-label-image-cdsp \
		label-image \
		./label_image \
		--image=grace_hopper.bmp \
		--external_delegate_path=/usr/local/lib/libQnnTFLiteDelegate.so \
		--external_delegate_options=backend_type:htp
fi

run_benchmark_model "$BUILTIN_MODEL" mobilenet-quant-v1-224

if [[ -d "$MODEL_DIR" ]]; then
	while IFS= read -r -d '' model; do
		relative_path=${model#"$MODEL_DIR"/}
		model_id=$(sanitize_id "$relative_path")
		run_benchmark_model "$model" "$model_id"
	done < <(find "$MODEL_DIR" -type f -name '*.tflite' -print0)
else
	printf '\nNo external model directory found at %s; skipping corpus.\n' \
		"$MODEL_DIR"
fi

if (( failures > 0 )); then
	printf '\n%d TensorFlow Lite test(s) failed.\n' "$failures" >&2
	exit 1
fi

printf '\nAll TensorFlow Lite tests passed.\n'
