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
RUN DEBIAN_FRONTEND=noninteractive apt -y install git build-essential libtool wget unzip

# Build & Install fastrpc
RUN mkdir ~/build
RUN cd ~/build ; \
	git clone https://github.com/qualcomm/fastrpc.git ; \
        cd fastrpc ; \
        GITCOMPILE_NO_MAKE=yes ./gitcompile ; \
        make -j$(nproc) ; \
        make install DESTDIR=/opt/fastrpc ; \
        rm ~/build/fastrpc -rf

# Install hexagon binaries and copy binaries for RB3Gen2 : TODO add for others
RUN cd ~/build; \
	mkdir -p /lib/dsp/cdsp ; \
	git clone https://github.com/linux-msm/hexagon-dsp-binaries.git ; \
	cp -v hexagon-dsp-binaries/qcm6490/Thundercomm/RB3gen2/CDSP.HT.2.5.c3-00077-KODIAK-1/* /lib/dsp/cdsp/ ; \
	rm ~/build/hexagon-dsp-binaries -rf

# Install QNN
RUN cd ~/build ; \
	wget https://softwarecenter.qualcomm.com/api/download/software/sdks/Qualcomm_AI_Runtime_Community/All/2.36.0.250627/v2.36.0.250627.zip; \
	unzip v2.36.0.250627.zip ; \
	rm ~/build/v2.36.0.250627.zip ; \
	cp -v ~/build/qairt/2.36.0.250627/lib/aarch64-oe-linux-gcc11.2/* /usr/local/lib/ ;  \
	cp -v ~/build/qairt/2.36.0.250627/lib/hexagon-v68/unsigned/* /lib/dsp/cdsp/ ; \
	rm /usr/local/lib/libSNPE* -rf ; \
	rm /usr/local/lib/libSnpe* -rf ; \
	rm ~/build/qairt -rf

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

# Copy fastrpc, host side libraries and DSP side libraries from the fastrpc-build layer
COPY --from=fastrpc-build /opt/fastrpc/usr /usr/
RUN find /usr/local/ | grep fastrpc
COPY --from=fastrpc-build /usr/local/lib /usr/local/lib
RUN find /usr/local/lib
COPY --from=fastrpc-build /lib/dsp /lib/dsp
RUN find /lib/dsp
RUN ldconfig

#######################################################################

# QIMSDK Development Image
FROM build AS qimsdk-build

# build time dependencies, needed for gst-plugins-qti-oss compilation:
# gst-plugins-qti-oss is not an apt package, so we need to install its build dependencies manually
#   instead of doing it using 'apt-get build-dep'
#  gst-plugin-mlaconverter:       libeigen3-dev
#  gst-plugin-mlaclassification:  libcairo-dev
#  gst-plugin-mlmetaparser:       libjson-glib-dev
#  gst-plugin-msgbroker:          libmosquitto-dev,
#                                 librdkafka-dev
#  gst-plugin-overlay:            opencl-headers
#  gst-plugin-redissink:          libhiredis-dev
#  gst-plugin-rtspbin:            libgstrtspserver-1.0-dev
#  gst-plugin-restricted-zonedbg: libgstreamer-plugins-bad1.0-dev

# Installing dependencies, needed in order for gst plugins to load succesfully runtime:
#  gstreamer base plugins:        gobject-introspection,
#                                 flex,
#                                 bison,
#                                 libglib2.0-0,
#  glimagesink:                   gstreamer1.0-gl,
#                                 gstreamer1.0-plugins-good,
#                                 libgraphene-1.0-dev,
#                                 libgl1,
#                                 libegl1,
#                                 libwayland-egl1,
#                                 libwayland-dev
#  opencl for tflite:             ocl-icd-libopencl1,
#                                 mesa-opencl-icd,
#                                 libopencl-clang-19-dev
#  software encoder needed for
#    rtspsrc usecases:            gstreamer1.0-plugins-ugly
#  pulseaudio runtime dependency: pulseaudio

# Installing required apt packages
RUN apt-get update                                                                              && \
        DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC apt-get install -y                               \
        git tar unzip ssh rsync bash-completion jq cmake android-tools-adb wget pipx xz-utils curl \
        gobject-introspection flex bison locales-all meson ninja-build gpg git-buildpackage        \
        libeigen3-dev libcairo-dev libjson-glib-dev libmosquitto-dev opencl-headers libhiredis-dev \
        libgstrtspserver-1.0-dev libgstreamer-plugins-bad1.0-dev gstreamer1.0-gl libglib2.0-0      \
        gstreamer1.0-plugins-good libgl1 libegl1 libwayland-egl1 pulseaudio ocl-icd-libopencl1     \
        gstreamer1.0-plugins-ugly mesa-opencl-icd libopencl-clang-19-dev librdkafka-dev         && \
        apt-get build-dep -y gst-plugins-base1.0 gst-plugins-good1.0                            && \
        apt -y upgrade                                                                          && \
        apt-get autoremove -y                                                                   && \
        apt-get clean                                                                           && \
        rm -rf /var/lib/apt/lists* /var/tmp/*

# Set base directory
ENV QIMSDK_BASE_DIR=/mnt/work
ENV QIMSDK_TMP_DIR=${QIMSDK_BASE_DIR}/tmp
RUN mkdir -p ${QIMSDK_TMP_DIR}

# Add qimsdk install directory
ENV QIMSDK_INSTALL_DIR=${QIMSDK_BASE_DIR}/deploy

# Add qimsdk prebuilt directory
ENV QIMSDK_PREBUILT_DIR=${QIMSDK_BASE_DIR}/prebuilt

# Add qimsdk debug install directory
ENV QIMSDK_INSTALL_DEBUG_DIR=${QIMSDK_BASE_DIR}/deploy_dbg

# Add qimsdk build directory and logs directory
ENV QIMSDK_BUILD_DIR=${QIMSDK_BASE_DIR}/build
ENV QIMSDK_LOGS_DIR=${QIMSDK_BASE_DIR}/logs
RUN mkdir -p ${QIMSDK_BUILD_DIR}
RUN mkdir -p ${QIMSDK_LOGS_DIR}
RUN mkdir -p ${QIMSDK_PREBUILT_DIR}

# Set up download directory
ENV QIMSDK_DOWNLOAD_DIR=${QIMSDK_BASE_DIR}/downloads
RUN mkdir -p ${QIMSDK_DOWNLOAD_DIR}

# Update and clean, fetch GStreamer base and good plugins
RUN DEBIAN_FRONTEND=noninteractive apt-get update && cd ${QIMSDK_DOWNLOAD_DIR}                  && \
    apt source gst-plugins-base1.0 gst-plugins-good1.0 && apt-get autoremove -y                 && \
    apt-get clean && rm -rf /var/lib/apt/lists* /var/tmp/*

RUN git -C ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-base1.0-1.26.2                                       \
        init                                                                                    && \
    git config --global --add safe.directory                                                       \
        ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-base1.0-1.26.2                                       && \
    git -C ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-base1.0-1.26.2                                       \
        config --global user.name "username"                                                    && \
    git -C ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-base1.0-1.26.2                                       \
        config --global user.email "email"                                                      && \
    git -C ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-base1.0-1.26.2                                       \
        add --all                                                                               && \
    git -C ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-base1.0-1.26.2                                       \
        commit -m "Initial Plugins Base Commit"

RUN git -C ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-good1.0-1.26.2                                       \
        init                                                                                    && \
    git config --global --add safe.directory                                                       \
        ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-good1.0-1.26.2                                       && \
    git -C ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-good1.0-1.26.2                                       \
        config --global user.name "username"                                                    && \
    git -C ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-good1.0-1.26.2                                       \
        config --global user.email "email"                                                      && \
    git -C ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-good1.0-1.26.2                                       \
        add --all                                                                               && \
    git -C ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-good1.0-1.26.2                                       \
        commit -m "Initial Plugins Good Commit"

# Setup Tensorflow Lite 2.20
ENV QIMSDK_TF_SRC_TAR=/usr/src/tensorflow-lite-2.20.tar.gz
ENV QIMSDK_TF_SRC_DIR=/usr/src/tensorflow-2.20

RUN tar -xvzf ${QIMSDK_TF_SRC_TAR} -C /usr/src/

# Initialize environment variables
ENV QIMSDK_SRC_DIR=${QIMSDK_BASE_DIR}/src
ENV QIMSDK_PATH_TO_GST_META=${QIMSDK_SRC_DIR}/meta-qti-gst

# meta-qti-gst: fetch
RUN git clone --progress https://git.codelinaro.org/clo/le/meta-qti-gst.git                        \
        --single-branch --branch imsdk.lnx.2.0.0 ${QIMSDK_SRC_DIR}/meta-qti-gst

# gst-plugins-qti-oss: fetch
RUN git clone --progress                                                                           \
        https://git.codelinaro.org/clo/le/platform/vendor/qcom-opensource/gst-plugins-qti-oss.git  \
        --single-branch --branch imsdk.lnx.2.0.0 ${QIMSDK_SRC_DIR}/gst-plugins-qti-oss

# Add development image scripts
ENV QIMSDK_SCRIPTS=${QIMSDK_BASE_DIR}/scripts/
COPY scripts ${QIMSDK_SCRIPTS}

# Source container helper scripts from bashrc
RUN echo "source ${QIMSDK_SCRIPTS}/env_setup.sh" >> /root/.bashrc

# Change workdir back to base dir from downloads dir
WORKDIR ${QIMSDK_BASE_DIR}

# Copy the Tensorflow Lite's headers and dependent headers to the sysroot
RUN bash /root/.bashrc qimsdk-copy-tf-lite-headers-to-sysroot

# Sync prebuilt libs
RUN bash /root/.bashrc qimsdk-propagate-prebuilt-libs

# Call wrapper function to apply all patches
RUN bash /root/.bashrc qimsdk-apply-patches

# Call wrapper build function to compile and install gst plugins
RUN bash /root/.bashrc qimsdk-incremental-build

# Create directory to save deb packages
RUN mkdir -p ${QIMSDK_DOWNLOAD_DIR}/debs/

# Copy selected packages to install
RUN cp ${QIMSDK_DOWNLOAD_DIR}/*base-1.0_* ${QIMSDK_DOWNLOAD_DIR}/*alsa_*                           \
       ${QIMSDK_DOWNLOAD_DIR}/*gl_* ${QIMSDK_DOWNLOAD_DIR}/*gtk3_* ${QIMSDK_DOWNLOAD_DIR}/*base_*  \
       ${QIMSDK_DOWNLOAD_DIR}/*base-apps_* ${QIMSDK_DOWNLOAD_DIR}/*good_*                          \
       ${QIMSDK_DOWNLOAD_DIR}/*pulseaudio_* ${QIMSDK_DOWNLOAD_DIR}/*x_*                            \
       ${QIMSDK_DOWNLOAD_DIR}/*gl1.0-0_* ${QIMSDK_DOWNLOAD_DIR}/*base1.0-0_1*                      \
       ${QIMSDK_DOWNLOAD_DIR}/debs/

# --------------------------------------------------------------------------------------------------

# QIMSDK Device Image
FROM debian:trixie-slim AS qimsdk-deploy

# Set base directory
ENV QIMSDK_BASE_DIR=/mnt/work
ENV QIMSDK_INSTALL_DIR=${QIMSDK_BASE_DIR}/deploy
ENV QIMSDK_PREBUILT_DIR=${QIMSDK_BASE_DIR}/prebuilt
ENV QIMSDK_DEB_DIR=${QIMSDK_BASE_DIR}/downloads/debs

# Installing dependencies, needed in order for gst plugins to load succesfully runtime:
#  gstreamer base plugins:        gstreamer1.0-tools,
#                                 gstreamer1.0-plugins-base,
#  gst-plugin-redissink:          libhiredis1.1.0
#  gst-plugin-restrictedzonedbg:  libopencv-imgproc410
#  gst-plugin-rtspbin:            libgstrtspserver-1.0-0
#  gst-plugin-msgbroker:          librdkafka1
#  gstreamer base plugins:        gobject-introspection,
#                                 flex,
#                                 bison,
#                                 libglib2.0-0,
#  glimagesink:                   gstreamer1.0-gl,
#                                 gstreamer1.0-plugins-good,
#                                 libgraphene-1.0-dev,
#                                 libgl1,
#                                 libegl1,
#                                 libwayland-egl1,
#                                 libwayland-dev
#  opencl for tflite:             ocl-icd-libopencl1,
#                                 mesa-opencl-icd,
#                                 libopencl-clang-19-dev
#  software encoder needed for
#    rtspsrc usecases:            gstreamer1.0-plugins-ugly
#  pulseaudio runtime dependency: pulseaudio
RUN apt-get update                                                                              && \
        DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC apt-get install -y                               \
        adduser bash-completion nano libhiredis1.1.0 gstreamer1.0-tools ocl-icd-libopencl1 wget    \
        mesa-opencl-icd libopencl-clang-19-dev libgstrtspserver-1.0-0 libopencv-imgproc410         \
        gstreamer1.0-plugins-good pulseaudio gstreamer1.0-plugins-base gstreamer1.0-gl             \
        libgraphene-1.0-dev libgl1 libegl1 libwayland-egl1 libwayland-dev librdkafka1              \
        gstreamer1.0-plugins-ugly                                                               && \
        apt -y upgrade                                                                          && \
        apt-get autoremove -y                                                                   && \
        apt-get clean                                                                           && \
        rm -rf /var/lib/apt/lists* /var/tmp/*

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
# Install the basic mesa dependencies to make our build work
# Install libegl-mesa0 which contains the mesa vendor library for EGL.
RUN DEBIAN_FRONTEND=noninteractive apt-get update                                               && \
    apt -y install --no-install-recommends mesa-common-dev libegl-dev libgles-dev                  \
        libgl1-mesa-dri libegl-mesa0 libgles2 mesa-opencl-icd clpeak                               \
        gir1.2-gst-plugins-base-1.0                                                             && \
        apt -y upgrade                                                                          && \
        apt-get autoremove -y                                                                   && \
        apt-get clean                                                                           && \
        rm -rf /var/lib/apt/lists* /var/tmp/*

# Create USER and add to video group for accessing v4ls devices
RUN addgroup qcom                                                                               && \
    useradd -s /bin/bash -m -g qcom qimsdk                                                      && \
    usermod -aG video qimsdk                                                                    && \
    usermod -aG kmem qimsdk                                                                     && \
    echo qimsdk:asd | chpasswd

# Increase max number of fd to be opened by one process
RUN ulimit -n 16192

# Copy installed binaries to device image
COPY --from=qimsdk-build ${QIMSDK_INSTALL_DIR}/usr /usr

# Copy prebuilt binaries to device image
COPY --from=qimsdk-build ${QIMSDK_PREBUILT_DIR}/usr /usr

# Copy deb packages to device image
COPY --from=qimsdk-build /mnt/work/downloads/debs ${QIMSDK_DEB_DIR}

# Install deb packages to deploy image and remove the directory after install
RUN dpkg -i ${QIMSDK_DEB_DIR}/* && rm -rf ${QIMSDK_DEB_DIR}

# Copy prebuilt libraries from AIML to device image

# Dependencies of qtioverlay,
#                 gstqtivoverlay,
#                 gstqtimlvdetection,
#                 gstqtimlaclassification,
#                 gstqtimlvpose,
#                 gstqtimlvclassification
COPY --from=deploy /usr/lib/aarch64-linux-gnu/libexpat.so*               /usr/lib/aarch64-linux-gnu/
COPY --from=deploy /usr/lib/aarch64-linux-gnu/libbrotlidec.so*           /usr/lib/aarch64-linux-gnu/
COPY --from=deploy /usr/lib/aarch64-linux-gnu/libbrotlicommon.so*        /usr/lib/aarch64-linux-gnu/
# Dependency of gstqtivoverlay,
#               gstqtimldemux,
#               gstqtimlvdetection,
#               gstqtimltflite,
#               gstqtivcomposer,
#               gstqtimlvconverter,
#               gstqtimlvsuperresolution,
#               gstqtimetamux,
#               qtioverlay,
#               gstqtimlaconverter,
#               gstqtivtransform,
#               gstqtimlaclassification,
#               qtisocketsink,
#               ml-vdetection-qpd,
#               ml-vpose-posenet,
#               ml-vdetection-yolov8,
#               ml-vdetection-yolov5,
#               ml-vsuperresolution-srnet,
#               ml-vclassification-qfr,
#               ml-aclassification-yamnet,
#               ml-vdetection-east-textdt,
#               ml-vsegmentation-deeplab-argmax,
#               ml-vdetection-qfd,
#               ml-vclassification-mobilenet,
#               ml-vsegmentation-midas-v2,
#               ml-vdetection-ssd-mobilenet,
#               ml-vdetection-yolo-nas,
#               ml-vpose-hrnet,
#               ml-vsegmentation-yolov8,
#               ml-vclassification-ocr,
#               ml-vpose-lite-3dmm,
#               gstqtimlvsegmentation,
#               gstvideo4linux2,
#               qtisocketsrc,
#               meta-transform-roi-label-moving-average,
#               ml-meta-parser-json,
#               gstqtimlvpose,
#               gstqtivsplit,
#               gstqtimlmetaextractor,
#               gstqtimlvclassification
COPY --from=deploy /usr/lib/aarch64-linux-gnu/libdrm.so*                 /usr/lib/aarch64-linux-gnu/

# Change user to qimsdk
USER qimsdk

# Change workdir to user home
WORKDIR /home/qimsdk

# Add glimagesink exports
ENV DISPLAY=:0

# Add gstreamer exports
ENV GST_DEBUG_NO_COLOR=1
ENV GST_DEBUG=2
ENV GST_PLUGIN_SCANNER="/usr/lib/aarch64-linux-gnu/gstreamer1.0/gstreamer-1.0/gst-plugin-scanner"
ENV XDG_RUNTIME_DIR="/run/user/1000"
