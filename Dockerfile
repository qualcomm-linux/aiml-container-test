FROM debian:trixie-slim

# Add deb-src for everything
RUN sed -Ei 's/^Types: deb$/Types: deb deb-src/'  /etc/apt/sources.list.d/debian.sources

# Update & upgrade
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install build tools
RUN DEBIAN_FRONTEND=noninteractive apt -y build-dep mesa
RUN DEBIAN_FRONTEND=noninteractive apt -y install git meson wget curl unzip libegl-dev libgles-dev

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
RUN cd ~/build/tensorflow ; \ 
    bazel build --copt -DCL_DELEGATE_NO_GL //tensorflow/lite:libtensorflowlite.so ; \
    bazel build --copt -DCL_DELEGATE_NO_GL  //tensorflow/lite/tools/benchmark:benchmark_model ; \
    bazel build --copt -DCL_DELEGATE_NO_GL  //tensorflow/lite/examples/label_image:label_image

# This likely needs a new place so we can delete ~/build/tensorflow
RUN cd ~/build/tensorflow ; \
    cp tensorflow/lite/examples/label_image/testdata/grace_hopper.bmp bazel-bin/tensorflow/lite/examples/label_image/ ; \
    cd bazel-bin/tensorflow/lite/examples/label_image ; \
    wget https://storage.googleapis.com/download.tensorflow.org/models/tflite/mobilenet_v1_224_android_quant_2017_11_08.zip ; \
    unzip mobilenet_v1_224_android_quant_2017_11_08.zip 


# Remove cached files
RUN apt clean
