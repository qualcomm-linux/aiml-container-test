#!/bin/bash

# Add symlink for libOpenCL, tflite hardcodes the .so, it doesn't properly dynamically link to .so.X
ln -sf /usr/lib/aarch64-linux-gnu/libOpenCL.so.1 /usr/lib/aarch64-linux-gnu/libOpenCL.so

# For CPUFreq to use performance governer, run outside the container
echo "Run the following outside the container to have the CPUs run at full tilt:"
echo 'for i in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor ; do echo "performance" > $i ; done'

echo

# GPU hangcheck, also run this outside the container
echo "Extend the GPU hangcheck timer to avoid some models timing out:"
echo 'echo 6000 > /sys/kernel/debug/dri/0/hangcheck_period_ms'

echo
echo "Pausing for 30 seconds so you can do the above"
sleep 10

# This expects models to be present, but we can't distribute them inside the container, so bind mount them using e.g.
# docker run --volume /path/to/local/models:/root/models <..>

cd /root/tensorflow/lite/tools/benchmark/

set -x
for model in $(find /root/models -name "*.tflite") ; do
#	./benchmark_model --graph=${model} --enable_op_profiling=true --use_xnnpack=true --num_threads=$(nproc) --max_sec=300 --profiling_output_csv_file=${model}-gpu.csv  --use_gpu=true |& tee ${model}-gpu-log.txt
#	./benchmark_model --graph=${model} --enable_op_profiling=true --use_xnnpack=true --num_threads=$(nproc) --max_sec=300 --profiling_output_csv_file=${model}-cpu.csv  --use_gpu=false |& tee ${model}-cpu-log.txt
	./benchmark_model --graph=${model} --num_threads=$(nproc) --use_gpu=true |& tee ${model}-gpu-log.txt
	echo "Exit code: " $? >> ${model}-gpu-log.txt
	./benchmark_model --graph=${model} --num_threads=$(nproc) --use_gpu=false |& tee ${model}-cpu-log.txt
	echo "Exit code: " $? >> ${model}-cpu-log.txt
done
