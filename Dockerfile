FROM debian:trixie-slim AS build

# Add deb-src for everything
RUN sed -Ei 's/^Types: deb$/Types: deb deb-src/'  /etc/apt/sources.list.d/debian.sources

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install build tools
RUN DEBIAN_FRONTEND=noninteractive apt -y build-dep mesa
RUN DEBIAN_FRONTEND=noninteractive apt -y install git meson wget curl unzip libegl-dev libgles-dev

RUN git config --global user.email "container@nohardware.com"
RUN git config --global user.name "Container Entity"

RUN mkdir ~/build ; \
    cd ~/build ; \
    git clone https://gitlab.freedesktop.org/mesa/mesa.git --single-branch --depth 10 -b main
RUN cd ~/build/mesa ; \
    meson setup builddir/ -Dgallium-drivers=freedreno -Dvulkan-drivers=freedreno -Dgallium-rusticl=true -Dprefix=/usr/ ; \
    meson compile -C builddir/ ; \
    meson install -C builddir/

# Remove ~/build/mesa
RUN cd ~/; \
    rm -rf ~/build/mesa

# Yeah....
RUN wget -O /usr/local/bin/bazel https://github.com/bazelbuild/bazel/releases/download/7.4.0/bazel-7.4.0-linux-arm64
RUN chmod +x /usr/local/bin/bazel

RUN cd ~/build ; \
    git clone https://github.com/tensorflow/tensorflow.git --single-branch -b master
COPY 0001-FIXES.patch /root/build/tensorflow
RUN cd ~/build/tensorflow ; \
    git am 0001-FIXES.patch ; \ 
    bazel build --copt -DCL_DELEGATE_NO_GL //tensorflow/lite:libtensorflowlite.so ; \
    bazel build --copt -DCL_DELEGATE_NO_GL  //tensorflow/lite/tools/benchmark:benchmark_model ; \
    bazel build --copt -DCL_DELEGATE_NO_GL  //tensorflow/lite/examples/label_image:label_image

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

FROM debian:trixie-slim AS deploy

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update
RUN DEBIAN_FRONTEND=noninteractive apt -y install wget curl unzip

# Pull mesa builds from Dmitry's OBS
RUN wget https://download.opensuse.org/repositories/home:/lumag_lumag/Debian_Testing/Release.key -O /etc/apt/trusted.gpg.d/obs-lumag.asc
COPY <<EOF /etc/apt/sources.list.d/obs.lumag.sources
Types: deb deb-src 
URIs: https://download.opensuse.org/repositories/home:/lumag_lumag/Debian_Testing/
Suites: /
Components:
Signed-By: /etc/apt/trusted.gpg.d/obs-lumag.asc
EOF

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install the basic mesa dependencies to make our build work
RUN DEBIAN_FRONTEND=noninteractive apt -y install libgl1-mesa-dri mesa-opencl-icd

# Install tensorflow build, also no proper debian package
COPY --from=build /root/tensorflow /root/tensorflow

# Remove cached files
RUN rm ~/.cache -rf
RUN apt clean

# Test tensorflow
RUN cd ~/tensorflow/lite/examples/label_image ; \
    ./label_image --image=grace_hopper.bmp


