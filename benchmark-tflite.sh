#!/bin/bash

# Add symlink for libOpenCL, tflite hardcodes the .so, it doesn't properly dynamically link to .so.X
ln -sf /usr/lib/aarch64-linux-gnu/libOpenCL.so.1 /usr/lib/aarch64-linux-gnu/libOpenCL.so

# For CPUFreq to use performance governer
for i in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor ; do echo 'performance' > $i ; done

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
