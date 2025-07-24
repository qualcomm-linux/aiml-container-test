FROM debian:trixie-slim AS build

RUN mkdir ~/build

# Add deb-src for everything
RUN sed -Ei 's/^Types: deb$/Types: deb deb-src/'  /etc/apt/sources.list.d/debian.sources

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install build tools
RUN DEBIAN_FRONTEND=noninteractive apt -y install git meson wget curl unzip

# Pull mesa builds from Qartifactory repo
RUN wget https://github.com/qualcomm-linux/qcom-deb-images/raw/refs/heads/main/debos-recipes/overlays/qsc-deb-releases/etc/apt/keyrings/qsc-deb-releases.asc -O /etc/apt/keyrings/qsc-deb-releases.asc
COPY <<EOF /etc/apt/sources.list.d/qsc-deb-releases.sources
# QArtifactory qsc-deb-releases repository
# NB: publishing Sources indices for deb-src isn't supported by Artifactory,
# but sources are published with other packages files
Types: deb
URIs: https://qartifactory-edge.qualcomm.com/artifactory/qsc-deb-releases
Suites: trixie-overlay
Components: main
Signed-By: /etc/apt/keyrings/qsc-deb-releases.asc
Enabled: yes
EOF

# Update again
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install the basic mesa dependencies to make our build work
RUN DEBIAN_FRONTEND=noninteractive apt -y install mesa-common-dev libegl-dev libgles-dev cmake ninja-build


RUN git config --global user.email "container@nohardware.com"
RUN git config --global user.name "Container Entity"

# Fetch & patch tflite
RUN cd ~/build ; \
    git clone https://github.com/tensorflow/tensorflow.git --single-branch -b master
COPY patches/0001-OpenCL-wrapper-try-loading-libOpenCL.so.1-if-libOpen.patch /root/build/tensorflow/
COPY patches/0002-PATCH-tensorflow-c-library-enable-delegates.patch /root/build/tensorflow/
RUN cd ~/build/tensorflow ; \
    git remote add robclark https://github.com/robclark/tensorflow.git ; \
    git fetch robclark rusticl-fixes ; \
    git merge robclark/rusticl-fixes && git rebase origin/master ; \
    git am 0001-OpenCL-wrapper-try-loading-libOpenCL.so.1-if-libOpen.patch

# Grab bazel binaries and start the build.
RUN wget -O /usr/local/bin/bazel https://github.com/bazelbuild/bazel/releases/download/7.4.1/bazel-7.4.1-linux-arm64
RUN chmod +x /usr/local/bin/bazel
RUN cd ~/build/tensorflow &&  bazel build --copt -DCL_DELEGATE_NO_GL //tensorflow/lite:libtensorflowlite.so ; \
    bazel build --copt -DCL_DELEGATE_NO_GL //tensorflow/lite/c:libtensorflowlite_c.so ; \
    bazel build --copt -DCL_DELEGATE_NO_GL //tensorflow/lite/delegates/gpu:libtensorflowlite_gpu_delegate.so \
    bazel build --copt -DCL_DELEGATE_NO_GL //tensorflow/lite/tools/benchmark:benchmark_model ; \
    bazel build --copt -DCL_DELEGATE_NO_GL //tensorflow/lite/examples/label_image:label_image
RUN cd ~/build/tensorflow && bazel build --copt -DCL_DELEGATE_NO_GL //tensorflow/lite/delegates/gpu:libtensorflowlite_gpu_delegate.so

# This likely needs a new place so we can delete ~/build/tensorflow
RUN cd ~/build/tensorflow ; \
    cp tensorflow/lite/examples/label_image/testdata/grace_hopper.bmp bazel-bin/tensorflow/lite/examples/label_image/ ; \
    cd bazel-bin/tensorflow/lite/examples/label_image ; \
    wget https://storage.googleapis.com/download.tensorflow.org/models/tflite/mobilenet_v1_224_android_quant_2017_11_08.zip ; \
    unzip mobilenet_v1_224_android_quant_2017_11_08.zip 

RUN mv ~/build/tensorflow/bazel-bin/tensorflow ~

# Remove build folder
RUN rm -rf ~/build

# Remove cached files
RUN rm ~/.cache -rf
RUN apt clean

#######################################################################

FROM debian:bookworm-slim AS models

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update
RUN DEBIAN_FRONTEND=noninteractive apt -y upgrade
RUN DEBIAN_FRONTEND=noninteractive apt -y --no-install-recommends install wget curl unzip ca-certificates

# Install pip to fetch qai_hub, and do the pip thing where you need to break the system
RUN DEBIAN_FRONTEND=noninteractive apt -y install python3-pip python3-backoff python3-deprecation python3-numpy python3-protobuf python3-requests python3-requests-toolbelt python3-wcwidth python3-idna python3-urllib3 python3-certifi python3-jmespath 
# Install extra build deps
RUN DEBIAN_FRONTEND=noninteractive apt -y install gcc libc++-dev

# Install Qualcomm AI hub infrastructure - You CANNOT have 'git' installed, the mmcv install will hang.
RUN pip install --break-system-packages qai-hub mmcv ultralytics

#   Install the basic mesa dependencies to make the model export work
RUN DEBIAN_FRONTEND=noninteractive apt -y --no-install-recommends install git libgl1 libglib2.0-0 libgl1-mesa-dri mesa-opencl-icd

# Install Yolo-X"  model
RUN pip install --break-system-packages "qai-hub-models[yolox]"
RUN pip install --break-system-packages "pyarrow==20.0.0"
RUN python3 -m qai_hub_models.models.yolox.export --target-runtime tflite --precision float  
RUN mkdir -p /root/models ; mv /build/yolox/ /root/models/

# Uninstall qai-hub-models, then reinstall it, yay python!
RUN pip uninstall --break-system-package --no-input -y "qai-hub-models"
RUN pip install --break-system-packages "qai-hub-models[hrnet_pose]"
#RUN python3 -m qai_hub_models.models.hrnet_pose.export --target-runtime tflite --precision float  


#######################################################################

FROM debian:trixie-slim AS deploy

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update
RUN DEBIAN_FRONTEND=noninteractive apt -y upgrade
RUN DEBIAN_FRONTEND=noninteractive apt -y --no-install-recommends install wget curl unzip ca-certificates

# Pull mesa builds from Qartifactory repo
RUN wget https://github.com/qualcomm-linux/qcom-deb-images/raw/refs/heads/main/debos-recipes/overlays/qsc-deb-releases/etc/apt/keyrings/qsc-deb-releases.asc -O /etc/apt/keyrings/qsc-deb-releases.asc
COPY <<EOF /etc/apt/sources.list.d/qsc-deb-releases.sources
# QArtifactory qsc-deb-releases repository
# NB: publishing Sources indices for deb-src isn't supported by Artifactory,
# but sources are published with other packages files
Types: deb
URIs: https://qartifactory-edge.qualcomm.com/artifactory/qsc-deb-releases
Suites: trixie-overlay
Components: main
Signed-By: /etc/apt/keyrings/qsc-deb-releases.asc
Enabled: yes
EOF

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install the basic mesa dependencies to make our build work
RUN DEBIAN_FRONTEND=noninteractive apt -y --no-install-recommends install libgl1-mesa-dri libgles2 mesa-opencl-icd clpeak

# Copy models from models container
COPY --from=models /root/models /root/models

# Install tensorflow build, no proper debian package
COPY --from=build /root/tensorflow /root/tensorflow
COPY run-tflite.sh /
COPY benchmark-tflite.sh /
COPY install-gstreamer.sh /
RUN chmod +x /*.sh

# Remove cached files
RUN rm ~/.cache -rf
RUN apt clean

# Test tensorflow
RUN cd ~/tensorflow/lite/examples/label_image ; \
    ./label_image --image=grace_hopper.bmp

ENTRYPOINT ["/bin/bash"]
