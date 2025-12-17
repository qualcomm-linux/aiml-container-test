#!/bin/bash

ln -sf /usr/lib/aarch64-linux-gnu/libOpenCL.so.1 /usr/lib/aarch64-linux-gnu/libOpenCL.so 
cd ~/tensorflow/lite/examples/label_image

set -x

echo "Running label_image using CPU"
./label_image --image=grace_hopper.bmp --use_gpu=false

echo "Running label_image using GPU"
./label_image --image=grace_hopper.bmp --use_gpu=true

echo "Running label_image using CDSP"
./label_image --image=grace_hopper.bmp --external_delegate_path=/usr/local/lib/libQnnTFLiteDelegate.so --external_delegate_options='backend_type:htp'


cd ~/tensorflow/lite/tools/benchmark
cp ../../examples/label_image/*mobile* .

echo "running benchmark_model using CPU"
./benchmark_model --graph=mobilenet_quant_v1_224.tflite --use_gpu=false

echo "running benchmark_model using GPU"
./benchmark_model --graph=mobilenet_quant_v1_224.tflite --use_gpu=true

echo "running benchmark_model using CDSP"
./benchmark_model --graph=mobilenet_quant_v1_224.tflite --external_delegate_path=/usr/local/lib/libQnnTFLiteDelegate.so --external_delegate_options='backend_type:htp'
