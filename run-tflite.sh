#!/bin/bash
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.

set -euo pipefail
IFS=$' \t\n'
export LC_ALL=C

MODEL_DIR=${MODEL_DIR:-/root/models}
THREADS=${THREADS:-}
TIMEOUT_SECONDS=${TIMEOUT_SECONDS:-360}
ENABLE_OP_PROFILING=${ENABLE_OP_PROFILING:-0}
ACCELERATORS=${ACCELERATORS:-auto}
RUN_LABEL_IMAGE=${RUN_LABEL_IMAGE:-1}
RUN_BUILTIN_MODEL=${RUN_BUILTIN_MODEL:-1}
REQUIRE_MODEL_DIR=${REQUIRE_MODEL_DIR:-0}
SETUP_COMPAT_LINKS=${SETUP_COMPAT_LINKS:-1}
BENCHMARK_WARMUP_RUNS=${BENCHMARK_WARMUP_RUNS:-10}
BENCHMARK_WARMUP_MIN_SECS=${BENCHMARK_WARMUP_MIN_SECS:-1}
BENCHMARK_NUM_RUNS=${BENCHMARK_NUM_RUNS:-100}
BENCHMARK_MIN_SECS=${BENCHMARK_MIN_SECS:-3}
BENCHMARK_MAX_SECS=${BENCHMARK_MAX_SECS:-150}
LABEL_IMAGE_WARMUP_RUNS=${LABEL_IMAGE_WARMUP_RUNS:-10}
LABEL_IMAGE_COUNT=${LABEL_IMAGE_COUNT:-100}
OUTER_SAMPLE_COUNT=10
TIMEOUT_HEADROOM_SECONDS=30
TEST_CONFIGURATION_VERSION=3
PROC_ROOT=${PROC_ROOT:-/proc}
SYS_ROOT=${SYS_ROOT:-/sys}

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

validate_nonnegative_number()
{
	local name=$1
	local value=$2

	if [[ "$value" =~ ^[0-9]+([.][0-9]+)?$ ]] &&
		awk -v value="$value" \
			'BEGIN { exit !(value == value && value >= 0 && value < 1e308) }'; then
		return
	fi
	die "$name must be a finite non-negative number, got: $value"
}

validate_positive_number()
{
	local name=$1
	local value=$2

	validate_nonnegative_number "$name" "$value"
	awk -v value="$value" 'BEGIN { exit !(value > 0) }' ||
		die "$name must be greater than zero, got: $value"
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

join_array()
{
	local delimiter=$1
	shift
	local joined=
	local value

	for value in "$@"; do
		if [[ -n "$joined" ]]; then
			joined+=$delimiter
		fi
		joined+=$value
	done
	printf '%s' "$joined"
}

telemetry_value()
{
	local path=$1
	local value

	if [[ ! -r "$path" ]] || ! IFS= read -r value <"$path"; then
		printf unavailable
		return
	fi
	value=${value//[[:space:]]/_}
	[[ -n "$value" ]] || value=unavailable
	printf '%s' "$value"
}

emit_telemetry()
{
	local test_case_id=$1
	local phase=$2
	local cpu_online
	local load=unavailable
	local governor_entries=()
	local current_entries=()
	local frequency_entries=()
	local thermal_entries=()
	local policy
	local policy_name
	local minimum
	local maximum
	local zone
	local zone_name
	local zone_type
	local zone_temp
	local load_1
	local load_5
	local load_15
	local _

	cpu_online=$(telemetry_value "$SYS_ROOT/devices/system/cpu/online")
	if [[ -r "$PROC_ROOT/loadavg" ]] &&
		read -r load_1 load_5 load_15 _ <"$PROC_ROOT/loadavg"; then
		load="${load_1},${load_5},${load_15}"
	fi

	for policy in "$SYS_ROOT"/devices/system/cpu/cpufreq/policy*; do
		[[ -d "$policy" ]] || continue
		policy_name=${policy##*/}
		governor_entries+=(
			"${policy_name}:$(telemetry_value "$policy/scaling_governor")"
		)
		current_entries+=(
			"${policy_name}:$(telemetry_value "$policy/scaling_cur_freq")"
		)
		minimum=$(telemetry_value "$policy/scaling_min_freq")
		maximum=$(telemetry_value "$policy/scaling_max_freq")
		frequency_entries+=("${policy_name}:${minimum}-${maximum}")
	done
	for zone in "$SYS_ROOT"/class/thermal/thermal_zone*; do
		[[ -d "$zone" ]] || continue
		zone_name=${zone##*/}
		zone_type=$(telemetry_value "$zone/type")
		zone_temp=$(telemetry_value "$zone/temp")
		thermal_entries+=("${zone_name}:${zone_type}:${zone_temp}")
	done

	printf \
		'AIML_TELEMETRY test_case_id=%s phase=%s cpu_online=%s scaling_governors=%s scaling_current_khz=%s policy_frequencies_khz=%s load=%s thermal_millicelsius=%s\n' \
		"$test_case_id" \
		"$phase" \
		"$cpu_online" \
		"$(join_array , "${governor_entries[@]:-unavailable}")" \
		"$(join_array , "${current_entries[@]:-unavailable}")" \
		"$(join_array , "${frequency_entries[@]:-unavailable}")" \
		"$load" \
		"$(join_array , "${thermal_entries[@]:-unavailable}")"
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

parse_benchmark_output()
{
	local output_file=$1

	awk '
		function valid_number(value) {
			return value ~ /^[0-9]+([.][0-9]+)?$/
		}
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
		index($0, "count=") && index($0, "p5=") &&
				index($0, "median=") && index($0, "p95=") {
			stats_blocks++
			stats_found = 0
			delete values
			for (field = 1; field <= NF; field++) {
				if ($field ~ /^[a-z0-9_]+=/) {
					key = $field
					sub(/=.*/, "", key)
					value = $field
					sub(/^[^=]+=/, "", value)
					values[key] = value
				}
			}
			if (values["count"] ~ /^[0-9]+$/ &&
					valid_number(values["p5"]) &&
					valid_number(values["median"]) &&
					valid_number(values["p95"])) {
				count = values["count"]
				minimum = valid_number(values["min"]) ? values["min"] : "na"
				maximum = valid_number(values["max"]) ? values["max"] : "na"
				average = valid_number(values["avg"]) ? values["avg"] : "na"
				stddev = valid_number(values["std"]) ? values["std"] : "na"
				p5 = values["p5"]
				median = values["median"]
				p95 = values["p95"]
				stats_found = 1
			} else {
				invalid_stats = 1
			}
		}
		END {
			if (markers != 1 || invalid || stats_blocks < 2 ||
					invalid_stats || !stats_found) {
				exit 1
			}
			printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n", measurement,
				count, minimum, maximum, average, stddev, median, p5, p95
		}
	' "$output_file"
}

calculate_statistics()
{
	local samples_file=$1

	awk -v expected="$OUTER_SAMPLE_COUNT" '
		function sort(values, count,    i, j, candidate) {
			for (i = 2; i <= count; i++) {
				candidate = values[i]
				j = i - 1
				while (j >= 1 && values[j] > candidate) {
					values[j + 1] = values[j]
					j--
				}
				values[j + 1] = candidate
			}
		}
		function sample_variance(values, first, last, mean,
				count, position, delta, total) {
			count = last - first + 1
			if (count < 2) {
				return 0
			}
			total = 0
			for (position = first; position <= last; position++) {
				delta = values[position] - mean
				total += delta * delta
			}
			return total / (count - 1)
		}
		{
			if ($0 !~ /^[0-9]+([.][0-9]+)?$/) {
				exit 2
			}
			values[++count] = $0 + 0
			raw_total += $0
		}
		END {
			if (count != expected) {
				exit 1
			}
			sort(values, count)
			raw_mean = raw_total / count
			median = (values[count / 2] + values[count / 2 + 1]) / 2
			for (position = 1; position <= count; position++) {
				deviations[position] = values[position] > median \
					? values[position] - median : median - values[position]
			}
			sort(deviations, count)
			mad = (deviations[count / 2] + deviations[count / 2 + 1]) / 2
			trimmed_total = 0
			for (position = 2; position < count; position++) {
				trimmed_total += values[position]
			}
			trimmed_count = count - 2
			trimmed_mean = trimmed_total / trimmed_count
			raw_variance = sample_variance(values, 1, count, raw_mean)
			trimmed_variance = sample_variance(values, 2, count - 1, trimmed_mean)
			raw_stddev = sqrt(raw_variance)
			trimmed_stddev = sqrt(trimmed_variance)
			raw_cv = raw_mean == 0 ? 0 : raw_stddev / raw_mean
			trimmed_cv = trimmed_mean == 0 ? 0 : trimmed_stddev / trimmed_mean
			printf "%d\t%.9f\t%.9f\t%.9f\t%.9f\t%.9f\t%.9f\t%.9f\t%.9f\t%.9f\t%.9f\t%.9f\t%.9f\n",
				count, values[1], values[count], raw_mean, trimmed_mean,
				median, mad, raw_variance, raw_stddev, raw_cv,
				trimmed_variance, trimmed_stddev, trimmed_cv
		}
	' "$samples_file"
}

execution_measurement=
execution_inner_count=na
execution_inner_min_us=na
execution_inner_max_us=na
execution_inner_avg_us=na
execution_inner_stddev_us=na
execution_inner_median_us=na
execution_inner_p5_us=na
execution_inner_p95_us=na

execute_sample()
{
	local test_case_id=$1
	local output_kind=$2
	local working_directory=$3
	local output_file
	local raw_measurement
	local parsed
	local command_status
	local tee_status
	local prefix_status
	local metric
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
	printf '\n'
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
		return 1
	fi

	if (( tee_status != 0 || prefix_status != 0 )); then
		printf 'ERROR: failed to capture output for %s (tee=%d, prefix=%d)\n' \
			"$test_case_id" "$tee_status" "$prefix_status" >&2
		return 1
	fi

	execution_inner_count=na
	execution_inner_min_us=na
	execution_inner_max_us=na
	execution_inner_avg_us=na
	execution_inner_stddev_us=na
	execution_inner_median_us=na
	execution_inner_p5_us=na
	execution_inner_p95_us=na
	case "$output_kind" in
	label-image)
		if ! execution_measurement=$(parse_label_image_measurement "$output_file"); then
			printf 'ERROR: expected exactly one valid average-time measurement for %s\n' \
				"$test_case_id" >&2
			return 1
		fi
		execution_inner_count=$LABEL_IMAGE_COUNT
		;;
	benchmark)
		if ! parsed=$(parse_benchmark_output "$output_file"); then
			printf 'ERROR: expected one inference average and valid internal statistics for %s\n' \
				"$test_case_id" >&2
			return 1
		fi
		IFS=$'\t' read -r \
			raw_measurement \
			execution_inner_count \
			execution_inner_min_us \
			execution_inner_max_us \
			execution_inner_avg_us \
			execution_inner_stddev_us \
			execution_inner_median_us \
			execution_inner_p5_us \
			execution_inner_p95_us <<<"$parsed"
		if [[ ! "$execution_inner_count" =~ ^[0-9]+$ ]] ||
			(( execution_inner_count < BENCHMARK_NUM_RUNS )); then
			printf \
				'ERROR: benchmark inference count for %s was %s; expected at least %s\n' \
				"$test_case_id" "$execution_inner_count" "$BENCHMARK_NUM_RUNS" >&2
			return 1
		fi
		for metric in \
			"$execution_inner_min_us" \
			"$execution_inner_max_us" \
			"$execution_inner_avg_us" \
			"$execution_inner_stddev_us" \
			"$execution_inner_median_us" \
			"$execution_inner_p5_us" \
			"$execution_inner_p95_us"; do
			if [[ "$metric" != na ]] && ! validate_measurement "$metric"; then
				printf 'ERROR: invalid benchmark internal statistic for %s: %s\n' \
					"$test_case_id" "$metric" >&2
				return 1
			fi
		done
		if ! validate_measurement "$raw_measurement"; then
			printf 'ERROR: invalid microsecond measurement for %s: %s\n' \
				"$test_case_id" "$raw_measurement" >&2
			return 1
		fi
		if ! execution_measurement=$(
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
			return 1
		fi
		;;
	esac

	if ! validate_measurement "$execution_measurement"; then
		printf 'ERROR: invalid millisecond measurement for %s: %s\n' \
			"$test_case_id" "$execution_measurement" >&2
		return 1
	fi
}

run_case()
{
	local test_case_id=$1
	local output_kind=$2
	local working_directory=$3
	local samples_file
	local warmup_measurement
	local sample_index
	local aggregate
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

	shift 3

	samples_file=$(mktemp "$temp_dir/samples.XXXXXX") ||
		die "could not create samples file in $temp_dir"
	temporary_files[temporary_file_count]=$samples_file
	temporary_file_count=$((temporary_file_count + 1))

	emit_telemetry "$test_case_id" before
	printf '\nRunning unmeasured outer warm-up for %s.\n' "$test_case_id"
	if ! execute_sample \
		"$test_case_id" "$output_kind" "$working_directory" "$@"; then
		emit_telemetry "$test_case_id" after
		emit_failure "$test_case_id"
		return
	fi
	warmup_measurement=$execution_measurement
	printf \
		'AIML_WARMUP test_case_id=%s measurement=%s units=ms inner_count=%s inner_min_us=%s inner_max_us=%s inner_avg_us=%s inner_stddev_us=%s inner_median_us=%s inner_p5_us=%s inner_p95_us=%s\n' \
		"$test_case_id" "$warmup_measurement" \
		"$execution_inner_count" "$execution_inner_min_us" \
		"$execution_inner_max_us" "$execution_inner_avg_us" \
		"$execution_inner_stddev_us" "$execution_inner_median_us" \
		"$execution_inner_p5_us" "$execution_inner_p95_us"

	for ((sample_index = 1;
		sample_index <= OUTER_SAMPLE_COUNT;
		sample_index++)); do
		printf '\nRunning measured sample %d/%d for %s.\n' \
			"$sample_index" "$OUTER_SAMPLE_COUNT" "$test_case_id"
		if ! execute_sample \
			"$test_case_id" "$output_kind" "$working_directory" "$@"; then
			emit_telemetry "$test_case_id" after
			emit_failure "$test_case_id"
			return
		fi
		printf '%s\n' "$execution_measurement" >>"$samples_file" ||
			die "could not record sample for $test_case_id"
		printf \
			'AIML_SAMPLE test_case_id=%s index=%d measurement=%s units=ms inner_count=%s inner_min_us=%s inner_max_us=%s inner_avg_us=%s inner_stddev_us=%s inner_median_us=%s inner_p5_us=%s inner_p95_us=%s\n' \
			"$test_case_id" "$sample_index" "$execution_measurement" \
			"$execution_inner_count" "$execution_inner_min_us" \
			"$execution_inner_max_us" "$execution_inner_avg_us" \
			"$execution_inner_stddev_us" "$execution_inner_median_us" \
			"$execution_inner_p5_us" "$execution_inner_p95_us"
	done

	if ! aggregate=$(calculate_statistics "$samples_file"); then
		printf 'ERROR: could not aggregate exactly %d samples for %s\n' \
			"$OUTER_SAMPLE_COUNT" "$test_case_id" >&2
		emit_telemetry "$test_case_id" after
		emit_failure "$test_case_id"
		return
	fi
	IFS=$'\t' read -r \
		count discarded_low discarded_high raw_mean trimmed_mean median mad \
		raw_variance raw_stddev raw_cv trimmed_variance trimmed_stddev \
		trimmed_cv <<<"$aggregate"
	for metric in \
		"$count" "$discarded_low" "$discarded_high" "$raw_mean" \
		"$trimmed_mean" "$median" "$mad" "$raw_variance" "$raw_stddev" \
		"$raw_cv" "$trimmed_variance" "$trimmed_stddev" "$trimmed_cv"; do
		[[ -n "$metric" ]] ||
			die "aggregate output is incomplete for $test_case_id"
	done

	emit_telemetry "$test_case_id" after
	printf \
		'AIML_STATS test_case_id=%s count=%s discarded_low=%s discarded_high=%s raw_mean=%s trimmed_mean=%s median=%s mad=%s raw_variance=%s raw_stddev=%s raw_cv=%s trimmed_variance=%s trimmed_stddev=%s trimmed_cv=%s units=ms\n' \
		"$test_case_id" "$count" "$discarded_low" "$discarded_high" \
		"$raw_mean" "$trimmed_mean" "$median" "$mad" \
		"$raw_variance" "$raw_stddev" "$raw_cv" \
		"$trimmed_variance" "$trimmed_stddev" "$trimmed_cv"

	emit_pass "$test_case_id" "$trimmed_mean"
}

run_label_image()
{
	local accelerator=$1
	local -a args

	args=("--image=$LABEL_IMAGE_INPUT")
	args+=(
		"--warmup_runs=$LABEL_IMAGE_WARMUP_RUNS"
		"--count=$LABEL_IMAGE_COUNT"
	)
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
		"--warmup_runs=$BENCHMARK_WARMUP_RUNS"
		"--warmup_min_secs=$BENCHMARK_WARMUP_MIN_SECS"
		"--num_runs=$BENCHMARK_NUM_RUNS"
		"--min_secs=$BENCHMARK_MIN_SECS"
		"--max_secs=$BENCHMARK_MAX_SECS"
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
validate_positive_integer BENCHMARK_WARMUP_RUNS "$BENCHMARK_WARMUP_RUNS"
validate_nonnegative_number BENCHMARK_WARMUP_MIN_SECS "$BENCHMARK_WARMUP_MIN_SECS"
validate_positive_integer BENCHMARK_NUM_RUNS "$BENCHMARK_NUM_RUNS"
validate_nonnegative_number BENCHMARK_MIN_SECS "$BENCHMARK_MIN_SECS"
validate_positive_number BENCHMARK_MAX_SECS "$BENCHMARK_MAX_SECS"
validate_positive_integer LABEL_IMAGE_WARMUP_RUNS "$LABEL_IMAGE_WARMUP_RUNS"
validate_positive_integer LABEL_IMAGE_COUNT "$LABEL_IMAGE_COUNT"
awk \
	-v warmup_min="$BENCHMARK_WARMUP_MIN_SECS" \
	-v minimum="$BENCHMARK_MIN_SECS" \
	-v maximum="$BENCHMARK_MAX_SECS" \
	'BEGIN { exit !(maximum >= warmup_min && maximum >= minimum) }' ||
	die "BENCHMARK_MAX_SECS must be at least both benchmark minimum durations"
awk \
	-v timeout="$TIMEOUT_SECONDS" \
	-v maximum="$BENCHMARK_MAX_SECS" \
	-v headroom="$TIMEOUT_HEADROOM_SECONDS" \
	'BEGIN { exit !(timeout >= (2 * maximum) + headroom) }' ||
	die "TIMEOUT_SECONDS must be at least twice BENCHMARK_MAX_SECS plus ${TIMEOUT_HEADROOM_SECONDS} seconds"
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
	'AIML_PROVENANCE qairt=%s tflite_commit=%s configuration_version=%s threads=%s timeout_seconds=%s op_profiling=%s accelerators=%s outer_warmup_runs=1 outer_sample_count=%s benchmark_warmup_runs=%s benchmark_warmup_min_secs=%s benchmark_num_runs=%s benchmark_min_secs=%s benchmark_max_secs=%s label_image_warmup_runs=%s label_image_count=%s\n' \
	"$qairt_version" \
	"$tflite_commit" \
	"$TEST_CONFIGURATION_VERSION" \
	"$THREADS" \
	"$TIMEOUT_SECONDS" \
	"$ENABLE_OP_PROFILING" \
	"$accelerator_csv" \
	"$OUTER_SAMPLE_COUNT" \
	"$BENCHMARK_WARMUP_RUNS" \
	"$BENCHMARK_WARMUP_MIN_SECS" \
	"$BENCHMARK_NUM_RUNS" \
	"$BENCHMARK_MIN_SECS" \
	"$BENCHMARK_MAX_SECS" \
	"$LABEL_IMAGE_WARMUP_RUNS" \
	"$LABEL_IMAGE_COUNT"

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
