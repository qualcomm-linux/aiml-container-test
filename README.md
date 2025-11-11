## About The Project

This repository hosts a Dockerfile and its dependencies that aims to build a container with TFLite installed to aid in testing Qualcomm platforms. 

### How to build

This isn't using any fancy features, so a regular build command will work:

```bash
docker build  --platform linux/arm64 .
```

## How to use the container

Start the container with `host` networking and forwarding the GPU devices nodes inside `/dev/dri`:

```bash
docker run --network host --device /dev/dri -it --entrypoint /bin/bash <container URI>
```

Once inside run the helper script:

```bash
root@qrb2210-rb1-core-kit:/# ./run-tflite.sh
+ echo 'Running label_image using CPU'
Running label_image using CPU
+ ./label_image --image=grace_hopper.bmp --use_gpu=false
INFO: Loaded model ./mobilenet_quant_v1_224.tflite
INFO: resolved reporter
INFO: Created TensorFlow Lite XNNPACK delegate for CPU.
INFO: invoked
INFO: average time: 31.488 ms
INFO: 0.698039: 458 bow tie
INFO: 0.258824: 653 military uniform
INFO: 0.0117647: 835 suit
INFO: 0.00784314: 611 jersey
INFO: 0.00392157: 922 book jacket
+ echo 'Running label_image using GPU'
Running label_image using GPU
+ ./label_image --image=grace_hopper.bmp --use_gpu=true
INFO: Loaded model ./mobilenet_quant_v1_224.tflite
INFO: resolved reporter
INFO: Created TensorFlow Lite delegate for GPU.
INFO: GPU delegate created.
INFO: Loaded OpenCL library with dlopen.
INFO: Initialized OpenCL-based API.
INFO: Created 1 GPU delegate kernels.
INFO: Applied GPU delegate.
INFO: invoked
INFO: average time: 247.36 ms
INFO: 0.0470588: 593 hard disc
INFO: 0.0392157: 592 handkerchief
INFO: 0.0313726: 634 loupe
INFO: 0.027451: 849 tape player
INFO: 0.027451: 819 spotlight
+ cd /root/tensorflow/lite/tools/benchmark
+ cp ../../examples/label_image/mobilenet_quant_v1_224.tflite ../../examples/label_image/mobilenet_v1_224_android_quant_2017_11_08.zip .
+ echo 'running benchmark_model using CPU'
running benchmark_model using CPU
+ ./benchmark_model --graph=mobilenet_quant_v1_224.tflite --use_gpu=false
INFO: STARTING!
INFO: Log parameter values verbosely: [0]
INFO: Graph: [mobilenet_quant_v1_224.tflite]
INFO: Signature to run: []
INFO: Use gpu: [0]
INFO: Loaded model mobilenet_quant_v1_224.tflite
INFO: Created TensorFlow Lite XNNPACK delegate for CPU.
INFO: The input model file size (MB): 4.2761
INFO: Initialized session in 87.639ms.
INFO: Running benchmark for at least 1 iterations and at least 0.5 seconds but terminate if exceeding 150 seconds.
INFO: count=5 first=106436 curr=105929 min=105929 max=106436 avg=106065 std=193 p5=105929 median=105948 p95=106436

INFO: Running benchmark for at least 50 iterations and at least 1 seconds but terminate if exceeding 150 seconds.
INFO: count=50 first=106022 curr=105780 min=105416 max=106528 avg=105784 std=260 p5=105485 median=105718 p95=106281

INFO: Inference timings in us: Init: 87639, First inference: 106436, Warmup (avg): 106065, Inference (avg): 105784
INFO: Note: as the benchmark tool itself affects memory footprint, the following is only APPROXIMATE to the actual memory footprint of the model at runtime. Take the information at your discretion.
INFO: Memory footprint delta from the start of the tool (MB): init=14.4414 overall=14.8164
+ echo 'running benchmark_model using GPU'
running benchmark_model using GPU
+ ./benchmark_model --graph=mobilenet_quant_v1_224.tflite --use_gpu=true
INFO: STARTING!
INFO: Log parameter values verbosely: [0]
INFO: Graph: [mobilenet_quant_v1_224.tflite]
INFO: Signature to run: []
INFO: Use gpu: [1]
INFO: Loaded model mobilenet_quant_v1_224.tflite
INFO: Created TensorFlow Lite delegate for GPU.
INFO: GPU delegate created.
INFO: Loaded OpenCL library with dlopen.
INFO: Initialized OpenCL-based API.
INFO: Created 1 GPU delegate kernels.
INFO: Explicitly applied GPU delegate, and the model graph will be completely executed by the delegate.
INFO: The input model file size (MB): 4.2761
INFO: Initialized session in 1361.24ms.
INFO: Running benchmark for at least 1 iterations and at least 0.5 seconds but terminate if exceeding 150 seconds.
INFO: count=5 first=125113 curr=112537 min=111758 max=125113 avg=115344 std=4959 p5=111758 median=112912 p95=125113

INFO: Running benchmark for at least 50 iterations and at least 1 seconds but terminate if exceeding 150 seconds.
INFO: count=50 first=119614 curr=115889 min=111842 max=119614 avg=115246 std=1329 p5=112107 median=115350 p95=116620

INFO: Inference timings in us: Init: 1361236, First inference: 125113, Warmup (avg): 115344, Inference (avg): 115246
INFO: Note: as the benchmark tool itself affects memory footprint, the following is only APPROXIMATE to the actual memory footprint of the model at runtime. Take the information at your discretion.
INFO: Memory footprint delta from the start of the tool (MB): init=132.816 overall=132.816
```

## About The QIMSDK-Debian Docker Image

### Table of Contents

* [Scripts](#Scripts)
    * [build.sh](#build.sh)
    * [env_setup.sh](#env_setup.sh)
    * [setup.sh](#setup.sh)

<div id="Scripts">

### Scripts

The functions inside these scripts are generally for building and maintaining the docker images.

<div id="build.sh">

#### build.sh

Handles the compilation and installation of open-source and QTI GStreamer plugins.

- qimsdk-cmake-configure - Configures a CMake project with security-hardened flags and custom build options
- qimsdk-cmake-compile - Compiles a configured CMake target with logging
- qimsdk-cmake-install - Installs CMake build artifacts to debug and deployment directories
- qimsdk-debian-rules-build - Wrapper function that calls configure, compile and install for projects, which need to be built using debian/rules
- qimsdk-cmake-build - Wrapper function that calls configure, compile and install for CMake projects
- qimsdk-debian-rules-build-\<name-of-project\> - Builds specific open-source component with custom configuration
- qimsdk-debian-rules-clean-\<name-of-project\> - Cleans build directory for specific open-source component
- qimsdk-incremental-build-qti - Base QTI GStreamer plugins that the others depend on are built. After which, a hardcoded list of QTI GStreamer plugins is built in paralel. If one wishes to add a new GStreamer plugin to build using CMake, simply add the plugin directory name under gst-plugins-qti-oss/ source dir to the list.
- qimsdk-incremental-build - Main entry point that builds all GStreamer components in sequence with success reporting. Also calls qimsdk-incremental-build-qti, to build QTI GStreamer plugins.
- qimsdk-cmake-build-qcom-gstreamer1.0-plugins-oss \<dir-name-of-qti-gst-plugin-src\> - CMake build of a specified QTI gst plugin. Plugin directory name under gst-plugins-qti-oss/ must be provided as first argument.
- qimsdk-cmake-clean-qcom-gstreamer1.0-plugins-oss \<dir-name-of-qti-gst-plugin-src\> - Clean a specified QTI gst plugin build dir. Plugin directory name under gst-plugins-qti-oss/ must be provided as first argument.

<div id="env_setup.sh">

#### env_setup.sh

env_setup.sh is a script which sources all other scripts inside scripts dir inside build image environment.

<div id="setup.sh">

#### setup.sh

Handles patching, library propagation, and dependency management for GStreamer plugins and TensorFlow Lite components.

- qimsdk-apply-patch - A wrapper for git am command that applies patch files
- qimsdk-apply-patches - Master wrapper that calls functions to apply patches to all required open-source projects
- qimsdk-apply-patches-\<open-source-project\> - Applies patches specifically to targeted open source package
- qimsdk-propagate-prebuilt-tflite-libs - Copies the prebuilt TensorFlow Lite C library (libtensorflowlite_c.so)
- qimsdk-propagate-prebuilt-libs - Sets up the directory structure and calls functions for prebuilt libraries propagation. As of now, only tflite prebuilt libs are being propagated
- qimsdk-copy-tf-lite-headers-to-sysroot - Copies all necessary headers to the sysroot while maintaining proper directory structure
- qimsdk-reset-project-to-initial-commit - Resets a git repository back to its very first commit - This is done to setup the projects for patch application
