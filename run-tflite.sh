#!/bin/bash
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.

set -euo pipefail
shopt -s nullglob

# Workaround binaries expecting .so instead of proper SOVERSIONed name
ln -sf /usr/lib/aarch64-linux-gnu/libOpenCL.so.1 /usr/lib/aarch64-linux-gnu/libOpenCL.so
ln -sf /usr/lib/aarch64-linux-gnu/libcdsprpc.so.1.0.0 /usr/lib/aarch64-linux-gnu/libcdsprpc.so

cd ~/tensorflow/lite/examples/label_image

set -x

echo "Running label_image using CPU"
./label_image --image=grace_hopper.bmp --use_gpu=false

# Some supported boards omit individual accelerators, so absence is a skip
# while failure of any accelerator that is exposed remains fatal.
rendernodes=(/dev/card/renderD*)
if (( ${#rendernodes[@]} > 0 )); then
	echo "Running label_image using GPU"
	./label_image --image=grace_hopper.bmp --use_gpu=true
fi

fastrpcnodes=(/dev/fastrpc-cdsp*)
if (( ${#fastrpcnodes[@]} > 0 )); then
	echo "Verifying FastRPC from inside the container"
	fastrpc_test -d 3 -U 1 -t linux -a v68
	echo "Running label_image using CDSP"
	./label_image --image=grace_hopper.bmp --external_delegate_path=/usr/local/lib/libQnnTFLiteDelegate.so --external_delegate_options='backend_type:htp'
fi

cd ~/tensorflow/lite/tools/benchmark
cp ../../examples/label_image/*mobile* .

echo "running benchmark_model using CPU"
./benchmark_model --graph=mobilenet_quant_v1_224.tflite --use_gpu=false

if (( ${#rendernodes[@]} > 0 )); then
	echo "running benchmark_model using GPU"
	./benchmark_model --graph=mobilenet_quant_v1_224.tflite --use_gpu=true
fi

if (( ${#fastrpcnodes[@]} > 0 )); then
	echo "running benchmark_model using CDSP"
	./benchmark_model --graph=mobilenet_quant_v1_224.tflite --external_delegate_path=/usr/local/lib/libQnnTFLiteDelegate.so --external_delegate_options='backend_type:htp'
fi
