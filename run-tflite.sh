#!/bin/bash
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.

# Workaround binaries expecting .so instead of proper SOVERSIONed name
ln -sf /usr/lib/aarch64-linux-gnu/libOpenCL.so.1 /usr/lib/aarch64-linux-gnu/libOpenCL.so 
ln -sf /usr/lib/aarch64-linux-gnu/libcdsprpc.so.1.0.0 /usr/lib/aarch64-linux-gnu/libcdsprpc.so

cd ~/tensorflow/lite/examples/label_image

set -x

echo "Running label_image using CPU"
./label_image --image=grace_hopper.bmp --use_gpu=false

# Only run when there's at least one device node present
rendernode="$(ls -1 /dev/card/renderD* | head -n1)"
if [ -e "${rendernode}" ] ; then
	echo "Running label_image using GPU"
	./label_image --image=grace_hopper.bmp --use_gpu=true
fi

# Only run when there's at least one device node present
fastrpcnode="$(ls -1 /dev/fastrpc-cdsp* | head -n1)"
if [ -e "${fastrpcnode}" ] ; then
	echo "Running label_image using CDSP"
	./label_image --image=grace_hopper.bmp --external_delegate_path=/usr/local/lib/libQnnTFLiteDelegate.so --external_delegate_options='backend_type:htp'
fi

cd ~/tensorflow/lite/tools/benchmark
cp ../../examples/label_image/*mobile* .

echo "running benchmark_model using CPU"
./benchmark_model --graph=mobilenet_quant_v1_224.tflite --use_gpu=false

# Only run when there's at least one device node present
rendernode="$(ls -1 /dev/card/renderD* | head -n1)"
if [ -e "${rendernode}" ] ; then
	echo "running benchmark_model using GPU"
	./benchmark_model --graph=mobilenet_quant_v1_224.tflite --use_gpu=true
fi

# Only run when there's at least one device node present
fastrpcnode="$(ls -1 /dev/fastrpc-cdsp* | head -n1)"
if [ -e "${fastrpcnode}" ] ; then
	echo "running benchmark_model using CDSP"
	./benchmark_model --graph=mobilenet_quant_v1_224.tflite --external_delegate_path=/usr/local/lib/libQnnTFLiteDelegate.so --external_delegate_options='backend_type:htp'
fi
