FROM debian:trixie-slim AS build

RUN mkdir ~/build

# Add deb-src for everything
RUN sed -Ei 's/^Types: deb$/Types: deb deb-src/'  /etc/apt/sources.list.d/debian.sources

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install build tools
RUN DEBIAN_FRONTEND=noninteractive apt -y install git meson wget curl unzip

# Pull modified packages builds from Qartifactory repo
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
Enabled: no
EOF

# Enable Backports repo, grab mesa from there
COPY <<EOF /etc/apt/sources.list.d/trixie-backports.sources
Types: deb deb-src
URIs: http://deb.debian.org/debian
Suites: trixie-backports
Components: main
Enabled: yes
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
EOF

COPY <<EOF /etc/apt/preferences.d/debian-backports.pref
# for binary packages built from these source packages, score the version from
# Debian backports higher as to get hardware enabled or better hardware support

Package: src:alsa-ucm-conf:any src:firmware-free:any src:firmware-nonfree:any src:linux:any src:linux-signed-arm64:any src:mesa:any
Pin: release n=trixie-backports
Pin-Priority: 900
EOF


# Update again
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install the basic mesa dependencies to make our build work
RUN DEBIAN_FRONTEND=noninteractive apt -y install mesa-common-dev libegl-dev libgles-dev cmake ninja-build


RUN git config --global user.email "container@nohardware.com"
RUN git config --global user.name "Container Entity"

# Fetch & patch tflite
RUN cd ~/build ; \
    git clone https://github.com/tensorflow/tensorflow.git --single-branch -b r2.20
COPY patches/0001-OpenCL-wrapper-try-loading-libOpenCL.so.1-if-libOpen.patch /root/build/tensorflow/
COPY patches/0002-PATCH-tensorflow-c-library-enable-delegates.patch /root/build/tensorflow/
RUN cd ~/build/tensorflow ; \
    git remote add robclark https://github.com/robclark/tensorflow.git ; \
    git fetch robclark rusticl-fixes ; \
    git merge robclark/rusticl-fixes && git rebase origin/r2.20 ; \
    git am 0001-OpenCL-wrapper-try-loading-libOpenCL.so.1-if-libOpen.patch 0002-PATCH-tensorflow-c-library-enable-delegates.patch

RUN cd ~/build/tensorflow ; \
    mkdir -p /usr/src ; \
    git archive --format=tar.gz --output=/usr/src/tensorflow-lite-2.20.tar.gz --prefix=tensorflow-2.20/ HEAD -v

# Grab bazel binaries and start the build.
RUN wget -O /usr/local/bin/bazel https://github.com/bazelbuild/bazel/releases/download/7.4.1/bazel-7.4.1-linux-arm64
RUN chmod +x /usr/local/bin/bazel
RUN cd ~/build/tensorflow &&  bazel build --copt -DCL_DELEGATE_NO_GL //tensorflow/lite:libtensorflowlite.so ; \
    bazel build --copt -DCL_DELEGATE_NO_GL //tensorflow/lite/c:libtensorflowlite_c.so ; \
    bazel build --copt -DCL_DELEGATE_NO_GL //tensorflow/lite/delegates/gpu:libtensorflowlite_gpu_delegate.so ; \
    bazel build --copt -DCL_DELEGATE_NO_GL //tensorflow/lite/examples/label_image:label_image ; \
    bazel build --copt -DCL_DELEGATE_NO_GL //tensorflow/lite/tools/benchmark:benchmark_model
RUN cd ~/build/tensorflow && bazel build --copt -DCL_DELEGATE_NO_GL //tensorflow/lite/delegates/gpu:libtensorflowlite_gpu_delegate.so

# This likely needs a new place so we can delete ~/build/tensorflow
RUN cd ~/build/tensorflow ; \
    cp tensorflow/lite/examples/label_image/testdata/grace_hopper.bmp bazel-bin/tensorflow/lite/examples/label_image/ ; \
    cd bazel-bin/tensorflow/lite/examples/label_image ; \
    wget https://storage.googleapis.com/download.tensorflow.org/models/tflite/mobilenet_v1_224_android_quant_2017_11_08.zip ; \
    unzip mobilenet_v1_224_android_quant_2017_11_08.zip ; \
    rm *.zip

RUN mv ~/build/tensorflow/bazel-bin/tensorflow ~

# Remove build folder
RUN rm -rf ~/build

# Remove cached files
RUN rm ~/.cache -rf
RUN apt clean

#######################################################################
 
FROM debian:trixie-slim AS fastrpc-build

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install build tools
RUN DEBIAN_FRONTEND=noninteractive apt -y install git wget unzip

# Install QNN
RUN mkdir -p ~/build
RUN cd ~/build ; \
       wget https://softwarecenter.qualcomm.com/api/download/software/sdks/Qualcomm_AI_Runtime_Community/All/2.36.0.250627/v2.36.0.250627.zip; \
       unzip v2.36.0.250627.zip ; \
       rm ~/build/v2.36.0.250627.zip
RUN mkdir -p /usr/lib/dsp/cdsp /usr/local/lib
RUN cp -v ~/build/qairt/2.36.0.250627/lib/aarch64-oe-linux-gcc11.2/* /usr/local/lib/ ;  \
       cp -v ~/build/qairt/2.36.0.250627/lib/hexagon-v68/unsigned/* /usr/lib/dsp/cdsp ; \
       rm /usr/local/lib/libSNPE* -rf ; \
       rm /usr/local/lib/libSnpe* -rf ; \
       rm ~/build/qairt -rf

# Install hexagon binaries and copy binaries for RB3Gen2 : TODO add for others
RUN cd ~/build; \
       mkdir -p /usr/lib/dsp/cdsp ; \
       git clone https://github.com/linux-msm/hexagon-dsp-binaries.git ; \
       cp -v hexagon-dsp-binaries/qcm6490/Thundercomm/RB3gen2/CDSP.HT.2.5.c3-00077-KODIAK-1/* /usr/lib/dsp/cdsp/ ; \
       rm ~/build/hexagon-dsp-binaries -rf

# Remove build folder
RUN rm -rf ~/build

# Remove cached files
RUN rm ~/.cache -rf
RUN apt clean

#######################################################################

FROM debian:bookworm-slim AS models

RUN mkdir /build

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

# Install Yolov6"  model
RUN pip install --break-system-packages "torch>=2.1,<2.9.0" "setuptools>=77.0.3"
RUN pip install --break-system-packages "qai-hub-models[yolov6]"
RUN pip install --break-system-packages "pyarrow==20.0.0"
RUN python3 -m qai_hub_models.models.yolov6.export --target-runtime tflite --precision float  
RUN ls /build -la --color
RUN mkdir -p /root/models
#RUN mv /build/yolov6_float/ /root/models/

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

# Pull modified packages builds from Qartifactory repo
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
Enabled: no
EOF

# Enable Backports repo, grab mesa from there
COPY <<EOF /etc/apt/sources.list.d/trixie-backports.sources
Types: deb deb-src
URIs: http://deb.debian.org/debian
Suites: trixie-backports
Components: main
Enabled: yes
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
EOF

COPY <<EOF /etc/apt/preferences.d/debian-backports.pref
# for binary packages built from these source packages, score the version from
# Debian backports higher as to get hardware enabled or better hardware support

Package: src:alsa-ucm-conf:any src:firmware-free:any src:firmware-nonfree:any src:linux:any src:linux-signed-arm64:any src:mesa:any
Pin: release n=trixie-backports
Pin-Priority: 900
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

#######################################################################

FROM deploy AS fastrpc-deploy

# Add repo containing fastrpc, dsp binaries and tflite
COPY <<EOF /etc/apt/sources.list.d/debusine.sources
Types: deb deb-src
URIs: https://deb.debusine.debian.net/debian/r-rbasak-qcom-hexagon-stack-2
Suites: sid
Components: main non-free-firmware
Signed-By:
 -----BEGIN PGP PUBLIC KEY BLOCK-----
 .
 mDMEaWpOVhYJKwYBBAHaRw8BAQdA6gdtyg0BKTS9EA9CAbbY3gk7bOYKY74Clfak
 3FjWn220PEFyY2hpdmUgc2lnbmluZyBrZXkgZm9yIGRlYmlhbi9yLXJiYXNhay1x
 Y29tLWhleGFnb24tc3RhY2stMoiQBBMWCgA4FiEEWi95OlWxjLyNwWscPETQboDo
 XeEFAmlqTlYCGwMFCwkIBwIGFQoJCAsCBBYCAwECHgECF4AACgkQPETQboDoXeFL
 AQD+Pm5ERzQPJRdxcqekaUVbqKrbyo1i7NPztV0j0YnyDFUA/24Ms1ZS8eV1um+R
 pqm6Uf5gvyZjJrjMGZWx/hqvriED
 =P90u
 -----END PGP PUBLIC KEY BLOCK-----
EOF

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install libyaml, fastrpc depends on it. Once we use proper debian packages, this workaround can go away
RUN DEBIAN_FRONTEND=noninteractive apt -y --no-install-recommends install fastrpc-tests

# Copy QNN host side libraries and DSP side libraries from the fastrpc-build layer
COPY --from=fastrpc-build /usr/local/lib /usr/local/lib
RUN find /usr/local/lib

# Copy over DSP libraries
COPY --from=fastrpc-build /usr/lib/dsp /usr/lib/dsp
RUN find /usr/lib/dsp

# Remove cached files
RUN rm ~/.cache -rf
RUN apt clean

