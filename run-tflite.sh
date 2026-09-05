#!/bin/bash
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.

set -euo pipefail
IFS=$' \t\n'
export LC_ALL=C

MODEL_DIR=${MODEL_DIR:-/root/models}
THREADS=${THREADS:-}
TIMEOUT_SECONDS=${TIMEOUT_SECONDS:-300}
ENABLE_OP_PROFILING=${ENABLE_OP_PROFILING:-0}
ACCELERATORS=${ACCELERATORS:-auto}
RUN_LABEL_IMAGE=${RUN_LABEL_IMAGE:-1}
RUN_BUILTIN_MODEL=${RUN_BUILTIN_MODEL:-1}
REQUIRE_MODEL_DIR=${REQUIRE_MODEL_DIR:-0}
SETUP_COMPAT_LINKS=${SETUP_COMPAT_LINKS:-1}
TEST_CONFIGURATION_VERSION=2

LABEL_IMAGE_DIR=${LABEL_IMAGE_DIR:-/root/tensorflow/lite/examples/label_image}
LABEL_IMAGE_BIN=${LABEL_IMAGE_BIN:-"$LABEL_IMAGE_DIR/label_image"}
LABEL_IMAGE_INPUT=${LABEL_IMAGE_INPUT:-"$LABEL_IMAGE_DIR/grace_hopper.bmp"}
BENCHMARK_BIN=${BENCHMARK_BIN:-/root/tensorflow/lite/tools/benchmark/benchmark_model}
BUILTIN_MODEL=${BUILTIN_MODEL:-"$LABEL_IMAGE_DIR/mobilenet_quant_v1_224.tflite"}
QAIRT_VERSION_FILE=${QAIRT_VERSION_FILE:-/usr/share/aiml-container/qairt-version}
TFLITE_COMMIT_FILE=${TFLITE_COMMIT_FILE:-/root/tensorflow/TFLITE_COMMIT}
DEVICE_ROOT=${DEVICE_ROOT:-/dev}

OPENCL_LIBRARY=${OPENCL_LIBRARY:-/usr/lib/aarch64-linux-gnu/libOpenCL.so.1}
OPENCL_LINK=${OPENCL_LINK:-/usr/lib/aarch64-linux-gnu/libOpenCL.so}
CDSPRPC_LIBRARY=${CDSPRPC_LIBRARY:-/usr/lib/aarch64-linux-gnu/libcdsprpc.so.1.0.0}
CDSPRPC_LINK=${CDSPRPC_LINK:-/usr/lib/aarch64-linux-gnu/libcdsprpc.so}
GPU_DELEGATE=${GPU_DELEGATE:-/root/tensorflow/lite/delegates/gpu/libtensorflowlite_gpu_delegate.so}
GPU_DELEGATE_LINK=${GPU_DELEGATE_LINK:-/lib/aarch64-linux-gnu/libtensorflowlite_gpu_delegate.so}

failures=0
temp_dir=
temporary_files=()
temporary_file_count=0
model_paths=()
model_ids=()
model_hashes=()
model_count=0

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

require_readable_file()
{
	[[ -f "$1" && -r "$1" ]] ||
		die "required readable file not found: $1"
}

require_executable()
{
	[[ -f "$1" && -x "$1" ]] ||
		die "required executable not found: $1"
}

validate_boolean()
{
	local name=$1
	local value=$2

	[[ "$value" == 0 || "$value" == 1 ]] ||
		die "$name must be 0 or 1, got: $value"
}

validate_positive_integer()
{
	local name=$1
	local value=$2

	[[ "$value" =~ ^[1-9][0-9]*$ ]] ||
		die "$name must be a positive integer, got: $value"
}

validate_token()
{
	local name=$1
	local value=$2

	[[ -n "$value" && "$value" =~ ^[[:graph:]]+$ ]] ||
		die "$name must be a non-empty value without whitespace"
}

cleanup()
{
	local status=$?
	local file
	local file_index

	trap - EXIT
	set +e
	set +u
	for ((file_index = 0; file_index < temporary_file_count; file_index++)); do
		file=${temporary_files[$file_index]}
		if [[ -e "$file" || -L "$file" ]]; then
			rm -f -- "$file" ||
				printf 'WARNING: could not remove temporary file %q\n' \
					"$file" >&2
		fi
	done
	if [[ -n "$temp_dir" && -d "$temp_dir" ]]; then
		rmdir -- "$temp_dir" ||
			printf 'WARNING: could not remove temporary directory %q\n' \
				"$temp_dir" >&2
	fi
	exit "$status"
}

trap cleanup EXIT

sanitize_id()
{
	local value=$1

	value=${value%.tflite}
	value=${value//\//-}

	printf '%s' "$value" |
		tr '[:upper:]' '[:lower:]' |
		tr -cs '[:alnum:]_-' '-' |
		sed -E 's/^-+//; s/-+$//'
}

hash_file()
{
	local file=$1
	local digest

	digest=$(sha256sum "$file") ||
		die "could not hash file: $file"
	digest=${digest%%[[:space:]]*}
	[[ "$digest" =~ ^[0-9a-f]{64}$ ]] ||
		die "sha256sum returned an invalid digest for $file"
	printf '%s' "$digest"
}

ensure_symlink()
{
	local source=$1
	local destination=$2
	local current_target

	require_readable_file "$source"
	[[ -d "${destination%/*}" ]] ||
		die "symlink parent directory not found: ${destination%/*}"

	if [[ -L "$destination" ]]; then
		current_target=$(readlink "$destination") ||
			die "could not read existing symlink: $destination"
		[[ "$current_target" == "$source" ]] ||
			die "refusing to replace existing symlink $destination -> $current_target"
		return
	fi
	[[ ! -e "$destination" ]] ||
		die "refusing to replace existing path: $destination"
	ln -s -- "$source" "$destination" ||
		die "could not create symlink: $destination"
}

emit_pass()
{
	local test_case_id=$1
	local measurement=$2

	printf \
		'LAVA_RESULT test_case_id=%s measurement=%s units=ms result=pass record_end=1\n' \
		"$test_case_id" \
		"$measurement"
}

emit_failure()
{
	local test_case_id=$1

	printf 'LAVA_RESULT test_case_id=%s result=fail record_end=1\n' "$test_case_id"
	failures=$((failures + 1))
}

validate_measurement()
{
	local measurement=$1

	[[ "$measurement" =~ ^[0-9]+([.][0-9]+)?$ ]] &&
		awk -v value="$measurement" \
			'BEGIN { exit !(value == value && value >= 0 && value < 1e308) }'
}

parse_label_image_measurement()
{
	local output_file=$1

	awk '
		index($0, "average time:") {
			line = $0
			probe = $0
			occurrences = 0
			while (sub(/average time:/, "", probe)) {
				occurrences++
			}
			markers += occurrences
			if (occurrences != 1 || line !~ /average time:[[:space:]]+[0-9]+([.][0-9]+)?[[:space:]]+ms[[:space:]]*$/) {
				invalid = 1
				next
			}
			sub(/^.*average time:[[:space:]]+/, "", line)
			sub(/[[:space:]]+ms[[:space:]]*$/, "", line)
			measurement = line
		}
		END {
			if (markers != 1 || invalid) {
				exit 1
			}
			print measurement
		}
	' "$output_file"
}

parse_benchmark_measurement()
{
	local output_file=$1

	awk '
		index($0, "Inference (avg):") {
			line = $0
			probe = $0
			occurrences = 0
			while (sub(/Inference \(avg\):/, "", probe)) {
				occurrences++
			}
			markers += occurrences
			if (occurrences != 1 || line !~ /Inference \(avg\):[[:space:]]+[0-9]+([.][0-9]+)?[[:space:]]*$/) {
				invalid = 1
				next
			}
			sub(/^.*Inference \(avg\):[[:space:]]+/, "", line)
			sub(/[[:space:]]*$/, "", line)
			measurement = line
		}
		END {
			if (markers != 1 || invalid) {
				exit 1
			}
			print measurement
		}
	' "$output_file"
}

run_case()
{
	local test_case_id=$1
	local output_kind=$2
	local working_directory=$3
	local output_file
	local measurement
	local raw_measurement
	local command_status
	local tee_status
	local prefix_status
	local -a statuses

	shift 3

	case "$output_kind" in
	label-image|benchmark)
		;;
	*)
		die "unsupported output kind: $output_kind"
		;;
	esac

	printf '\nRunning %s:' "$test_case_id"
	printf ' %q' "$@"
	printf '\n'

	output_file=$(mktemp "$temp_dir/output.XXXXXX") ||
		die "could not create output file in $temp_dir"
	temporary_files[temporary_file_count]=$output_file
	temporary_file_count=$((temporary_file_count + 1))

	set +e
	(
		cd "$working_directory" || exit 125
		exec timeout --foreground "$TIMEOUT_SECONDS" "$@"
	) 2>&1 |
		tee "$output_file" |
		sed 's/^/TFLITE_OUTPUT /'
	statuses=("${PIPESTATUS[@]}")
	set -e

	(( ${#statuses[@]} == 3 )) ||
		die "could not capture pipeline statuses for $test_case_id"
	command_status=${statuses[0]}
	tee_status=${statuses[1]}
	prefix_status=${statuses[2]}

	if (( command_status != 0 )); then
		if (( command_status == 124 )); then
			printf 'ERROR: %s timed out after %s seconds\n' \
				"$test_case_id" "$TIMEOUT_SECONDS" >&2
		else
			printf 'ERROR: %s exited with status %d\n' \
				"$test_case_id" "$command_status" >&2
		fi
		emit_failure "$test_case_id"
		return
	fi

	if (( tee_status != 0 || prefix_status != 0 )); then
		printf 'ERROR: failed to capture output for %s (tee=%d, prefix=%d)\n' \
			"$test_case_id" "$tee_status" "$prefix_status" >&2
		emit_failure "$test_case_id"
		return
	fi

	case "$output_kind" in
	label-image)
		if ! measurement=$(parse_label_image_measurement "$output_file"); then
			printf 'ERROR: expected exactly one valid average-time measurement for %s\n' \
				"$test_case_id" >&2
			emit_failure "$test_case_id"
			return
		fi
		;;
	benchmark)
		if ! raw_measurement=$(parse_benchmark_measurement "$output_file"); then
			printf 'ERROR: expected exactly one valid inference-average measurement for %s\n' \
				"$test_case_id" >&2
			emit_failure "$test_case_id"
			return
		fi
		if ! validate_measurement "$raw_measurement"; then
			printf 'ERROR: invalid microsecond measurement for %s: %s\n' \
				"$test_case_id" "$raw_measurement" >&2
			emit_failure "$test_case_id"
			return
		fi
		if ! measurement=$(
			awk -v value="$raw_measurement" \
				'BEGIN {
					milliseconds = value / 1000
					if (milliseconds != milliseconds || milliseconds < 0 || milliseconds >= 1e308) {
						exit 1
					}
					printf "%.6f", milliseconds
				}'
		); then
			printf 'ERROR: could not convert measurement for %s\n' \
				"$test_case_id" >&2
			emit_failure "$test_case_id"
			return
		fi
		;;
	esac

	if ! validate_measurement "$measurement"; then
		printf 'ERROR: invalid millisecond measurement for %s: %s\n' \
			"$test_case_id" "$measurement" >&2
		emit_failure "$test_case_id"
		return
	fi

	emit_pass "$test_case_id" "$measurement"
}

run_label_image()
{
	local accelerator=$1
	local -a args

	args=("--image=$LABEL_IMAGE_INPUT")
	case "$accelerator" in
	cpu)
		args+=(--use_gpu=false)
		;;
	gpu)
		args+=(--use_gpu=true)
		;;
	cdsp)
		args+=(
			--use_gpu=false
			--external_delegate_path=/usr/local/lib/libQnnTFLiteDelegate.so
			--external_delegate_options=backend_type:htp
		)
		;;
	*)
		die "unsupported accelerator: $accelerator"
		;;
	esac

	run_case \
		"tflite-label-image-${accelerator}" \
		label-image \
		"$LABEL_IMAGE_DIR" \
		"$LABEL_IMAGE_BIN" \
		"${args[@]}"
}

run_benchmark_model()
{
	local model=$1
	local model_id=$2
	local accelerator=$3
	local -a args

	args=(
		"--graph=$model"
		"--num_threads=$THREADS"
	)
	if [[ "$ENABLE_OP_PROFILING" == 1 ]]; then
		args+=(--enable_op_profiling=true)
	fi

	case "$accelerator" in
	cpu)
		args+=(--use_gpu=false --use_xnnpack=true)
		;;
	gpu)
		args+=(--use_gpu=true)
		;;
	cdsp)
		args+=(
			--use_gpu=false
			--external_delegate_path=/usr/local/lib/libQnnTFLiteDelegate.so
			--external_delegate_options=backend_type:htp
		)
		;;
	*)
		die "unsupported accelerator: $accelerator"
		;;
	esac

	run_case \
		"tflite-benchmark-${model_id}-${accelerator}" \
		benchmark \
		"${BENCHMARK_BIN%/*}" \
		"$BENCHMARK_BIN" \
		"${args[@]}"
}

for command_name in awk find mktemp rm rmdir sed sha256sum tee timeout tr; do
	require_command "$command_name"
done

if [[ -z "$THREADS" ]]; then
	require_command nproc
	THREADS=$(nproc)
fi

validate_positive_integer THREADS "$THREADS"
validate_positive_integer TIMEOUT_SECONDS "$TIMEOUT_SECONDS"
validate_boolean ENABLE_OP_PROFILING "$ENABLE_OP_PROFILING"
validate_boolean RUN_LABEL_IMAGE "$RUN_LABEL_IMAGE"
validate_boolean RUN_BUILTIN_MODEL "$RUN_BUILTIN_MODEL"
validate_boolean REQUIRE_MODEL_DIR "$REQUIRE_MODEL_DIR"
validate_boolean SETUP_COMPAT_LINKS "$SETUP_COMPAT_LINKS"

require_readable_file "$QAIRT_VERSION_FILE"
require_readable_file "$TFLITE_COMMIT_FILE"
qairt_version=$(<"$QAIRT_VERSION_FILE")
tflite_commit=$(<"$TFLITE_COMMIT_FILE")
validate_token qairt-version "$qairt_version"
validate_token tflite-commit "$tflite_commit"

has_gpu=false
if compgen -G "$DEVICE_ROOT/dri/renderD*" >/dev/null ||
	compgen -G "$DEVICE_ROOT/card/renderD*" >/dev/null; then
	has_gpu=true
fi

has_cdsp=false
if compgen -G "$DEVICE_ROOT/fastrpc-cdsp*" >/dev/null; then
	has_cdsp=true
fi

use_cpu=false
use_gpu=false
use_cdsp=false
if [[ "$ACCELERATORS" == auto ]]; then
	use_cpu=true
	[[ "$has_gpu" == false ]] || use_gpu=true
	[[ "$has_cdsp" == false ]] || use_cdsp=true
else
	[[ -n "$ACCELERATORS" ]] ||
		die "ACCELERATORS must not be empty"
	IFS=, read -r -a requested_accelerators <<<"$ACCELERATORS"
	for accelerator in "${requested_accelerators[@]}"; do
		case "$accelerator" in
		cpu)
			[[ "$use_cpu" == false ]] ||
				die "duplicate accelerator: cpu"
			use_cpu=true
			;;
		gpu)
			[[ "$use_gpu" == false ]] ||
				die "duplicate accelerator: gpu"
			[[ "$has_gpu" == true ]] ||
				die "GPU requested but no render device was found under $DEVICE_ROOT"
			use_gpu=true
			;;
		cdsp)
			[[ "$use_cdsp" == false ]] ||
				die "duplicate accelerator: cdsp"
			[[ "$has_cdsp" == true ]] ||
				die "CDSP requested but no FastRPC device was found under $DEVICE_ROOT"
			use_cdsp=true
			;;
		*)
			die "unsupported accelerator: $accelerator"
			;;
		esac
	done
fi

accelerators=()
accelerator_count=0
if [[ "$use_cpu" == true ]]; then
	accelerators[accelerator_count]=cpu
	accelerator_count=$((accelerator_count + 1))
fi
if [[ "$use_gpu" == true ]]; then
	accelerators[accelerator_count]=gpu
	accelerator_count=$((accelerator_count + 1))
fi
if [[ "$use_cdsp" == true ]]; then
	accelerators[accelerator_count]=cdsp
	accelerator_count=$((accelerator_count + 1))
fi
(( accelerator_count > 0 )) ||
	die "no accelerators selected"
accelerator_csv=$(
	IFS=,
	printf '%s' "${accelerators[*]}"
)

if [[ "$RUN_LABEL_IMAGE" == 1 ]]; then
	require_executable "$LABEL_IMAGE_BIN"
	require_readable_file "$LABEL_IMAGE_INPUT"
	label_image_sha256=$(hash_file "$LABEL_IMAGE_INPUT")
fi

temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/run-tflite.XXXXXX") ||
	die "could not create temporary directory"

if [[ "$RUN_BUILTIN_MODEL" == 1 ]]; then
	require_readable_file "$BUILTIN_MODEL"
	model_paths[model_count]=$BUILTIN_MODEL
	model_ids[model_count]=mobilenet-quant-v1-224
	model_hashes[model_count]=$(hash_file "$BUILTIN_MODEL")
	model_count=$((model_count + 1))
fi

external_models=()
external_model_count=0
if [[ -d "$MODEL_DIR" ]]; then
	model_list_file=$(mktemp "$temp_dir/models.XXXXXX") ||
		die "could not create model list in $temp_dir"
	temporary_files[temporary_file_count]=$model_list_file
	temporary_file_count=$((temporary_file_count + 1))
	if ! find "$MODEL_DIR" -type f -name '*.tflite' -print0 >"$model_list_file"; then
		die "could not enumerate models under $MODEL_DIR"
	fi
	while IFS= read -r -d '' model; do
		external_models[external_model_count]=$model
		external_model_count=$((external_model_count + 1))
	done <"$model_list_file"

	for ((i = 1; i < external_model_count; i++)); do
		model=${external_models[$i]}
		j=$((i - 1))
		while (( j >= 0 )) && [[ "${external_models[$j]}" > "$model" ]]; do
			external_models[j + 1]=${external_models[$j]}
			j=$((j - 1))
		done
		external_models[j + 1]=$model
	done

	for ((external_model_index = 0;
		external_model_index < external_model_count;
		external_model_index++)); do
		model=${external_models[$external_model_index]}
		require_readable_file "$model"
		relative_path=${model#"$MODEL_DIR"/}
		model_id=$(sanitize_id "$relative_path")
		[[ -n "$model_id" ]] ||
			die "could not derive a test ID from model path: $model"
		for ((existing_index = 0;
			existing_index < model_count;
			existing_index++)); do
			existing_id=${model_ids[$existing_index]}
			[[ "$existing_id" != "$model_id" ]] ||
				die "duplicate model ID $model_id from $model"
		done
		model_paths[model_count]=$model
		model_ids[model_count]=$model_id
		model_hashes[model_count]=$(hash_file "$model")
		model_count=$((model_count + 1))
	done
elif [[ "$REQUIRE_MODEL_DIR" == 1 ]]; then
	die "required model directory not found: $MODEL_DIR"
else
	printf 'No external model directory found at %s; skipping corpus.\n' \
		"$MODEL_DIR"
fi

if [[ "$RUN_LABEL_IMAGE" == 0 && $model_count -eq 0 ]]; then
	die "no TensorFlow Lite test cases were discovered"
fi

if (( model_count > 0 )); then
	require_executable "$BENCHMARK_BIN"
fi

if [[ "$SETUP_COMPAT_LINKS" == 1 ]]; then
	require_command ln
	require_command readlink
	ensure_symlink "$OPENCL_LIBRARY" "$OPENCL_LINK"
	ensure_symlink "$CDSPRPC_LIBRARY" "$CDSPRPC_LINK"
	if [[ -e "$GPU_DELEGATE" ]]; then
		ensure_symlink "$GPU_DELEGATE" "$GPU_DELEGATE_LINK"
	fi
fi

printf \
	'AIML_PROVENANCE qairt=%s tflite_commit=%s configuration_version=%s threads=%s timeout_seconds=%s op_profiling=%s accelerators=%s\n' \
	"$qairt_version" \
	"$tflite_commit" \
	"$TEST_CONFIGURATION_VERSION" \
	"$THREADS" \
	"$TIMEOUT_SECONDS" \
	"$ENABLE_OP_PROFILING" \
	"$accelerator_csv"

if [[ "$RUN_LABEL_IMAGE" == 1 ]]; then
	printf 'INPUT test_case_prefix=tflite-label-image sha256=%s path=%q\n' \
		"$label_image_sha256" "$LABEL_IMAGE_INPUT"
	for ((accelerator_index = 0;
		accelerator_index < accelerator_count;
		accelerator_index++)); do
		accelerator=${accelerators[$accelerator_index]}
		run_label_image "$accelerator"
	done
fi

for ((model_index = 0; model_index < model_count; model_index++)); do
	printf 'MODEL model_id=%s sha256=%s path=%q\n' \
		"${model_ids[$model_index]}" \
		"${model_hashes[$model_index]}" \
		"${model_paths[$model_index]}"
	for ((accelerator_index = 0;
		accelerator_index < accelerator_count;
		accelerator_index++)); do
		accelerator=${accelerators[$accelerator_index]}
		run_benchmark_model \
			"${model_paths[$model_index]}" \
			"${model_ids[$model_index]}" \
			"$accelerator"
	done
done

if (( failures > 0 )); then
	printf '\n%d TensorFlow Lite test(s) failed.\n' "$failures" >&2
	exit 1
fi

printf '\nAll TensorFlow Lite tests passed.\n'
