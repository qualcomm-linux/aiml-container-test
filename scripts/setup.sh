#!/bin/bash

# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause-Clear

# git am wrapper function
#   $1 - Path to patch file
function qimsdk-apply-patch() {
    local PATCH_FILE=${1}

    # Legal notices are present in QTI specific .patch files, so they could gain legal approval
    # They need to be removed to avoid trouble with git am
    # This is done by removing all leading comment lines from the patch file and then applying it
    sed -i '1,/^[^+#]/ { /^[+]*#/d; }' ${PATCH_FILE}                                            && \
            git am ${PATCH_FILE}                                                                || {
        echo "Failed to apply patch ${PATCH_FILE}!"
        return -1
    }
}

# Wrapper function to apply qti patches to all needed opensource libs
function qimsdk-apply-patches() {
    qimsdk-apply-patches-gst-plugins-base                                                       && \
            qimsdk-apply-patches-gst-plugins-good
}

# Apply patches to gst-plugins-base
function qimsdk-apply-patches-gst-plugins-base() {
    [ ! -d "${QIMSDK_DOWNLOAD_DIR}/gst-plugins-base1.0-${GST_PLUGINS_BASE_VERSION}" ] && {
        echo "No such file or directory: ${QIMSDK_DOWNLOAD_DIR}/`
                `gst-plugins-base1.0-${GST_PLUGINS_BASE_VERSION} !"
        return -1
    }

    (
        local PATH_TO_PATCHES="${QIMSDK_PATH_TO_GST_META}/`
                `recipes-gst/gstreamer/gstreamer1.0-plugins-base/${GST_PLUGINS_BASE_VERSION}/"

        [ ! -d ${PATH_TO_PATCHES} ]                                                             && {
            print-red "gstreamer-plugins-base's patches NOT found in  ${PATH_TO_PATCHES} !!!"
            return -1
        }

        cd ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-base1.0-${GST_PLUGINS_BASE_VERSION}

        for PATCH in ${PATH_TO_PATCHES}*.patch; do
            qimsdk-apply-patch ${PATCH} || return -1
        done
    )
}

# Apply patches to gst-plugins-good
function qimsdk-apply-patches-gst-plugins-good() {

    [ ! -d "${QIMSDK_DOWNLOAD_DIR}/gst-plugins-good1.0-${GST_PLUGINS_GOOD_VERSION}" ] && {
        echo "No such file or directory: ${QIMSDK_DOWNLOAD_DIR}/`
                `gst-plugins-good1.0-${GST_PLUGINS_GOOD_VERSION} !"
        return -1
    }

    (
        local PATH_TO_PATCHES="${QIMSDK_PATH_TO_GST_META}/`
                `recipes-gst/gstreamer/gstreamer1.0-plugins-good/${GST_PLUGINS_GOOD_VERSION}/"

        [ ! -d ${PATH_TO_PATCHES} ]                                                             && {
            print-red "gstreamer-plugins-good's patches NOT found in ${PATH_TO_PATCHES}!!!"
            return -1
        }

        cd ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-good1.0-${GST_PLUGINS_GOOD_VERSION}

        for PATCH in ${PATH_TO_PATCHES}*.patch; do
            qimsdk-apply-patch ${PATCH} || return -1
        done
    )
}

# Sync prebuilt mesa libs
function qimsdk-propagate-prebuilt-mesa-libs() {
    local PREBUILT_AARCH_LINUX_GNU_DIR="${QIMSDK_PREBUILT_DIR}/usr/lib/aarch64-linux-gnu"

    # Dependencies of gles gfx plugins, alternative of packages:
    #     mesa-common-dev libegl-dev libgles-dev libegl-mesa0
    rsync -aP /usr/lib/aarch64-linux-gnu/libgbm.so*                                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gbm/dri_gbm.so*                                           \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gbm/                                                && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgallium-*                                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libLLVM.so.19.1*                                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libsensors.so.5*                                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libdrm_amdgpu.so.1*                                       \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libelf.so.1*                                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libelf-0.192.so*                                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libedit.so.2*                                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libz3.so.4*                                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libEGL_mesa.so.0*                                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libGLESv1_CM.so*                                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libGLESv2.so*                                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/share/drirc.d                                                                   \
            ${QIMSDK_PREBUILT_DIR}/usr/share/                                                   && \
    rsync -aP /usr/share/glvnd/egl_vendor.d/50_mesa.json                                           \
            ${QIMSDK_PREBUILT_DIR}/usr/share/glvnd/egl_vendor.d/                                || {
        print-red "Failed to sync mesa libraries to ${PREBUILT_AARCH_LINUX_GNU_DIR} !!!"
        return -1
    }
}

# Sync prebuilt opencl libs
function qimsdk-propagate-prebuilt-opencl-libs() {
    local PREBUILT_AARCH_LINUX_GNU_DIR="${QIMSDK_PREBUILT_DIR}/usr/lib/aarch64-linux-gnu"

    # Dependencies of OpenCL TFLite GPU backend, alternative of
    #     ocl-icd-libopencl1 mesa-opencl-icd libopencl-clang-19-dev packages
    rsync -aP /usr/lib/aarch64-linux-gnu/libOpenCL.so*                                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libRusticlOpenCL.so*                                      \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libclang-cpp.so.19.1                                      \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libLLVMSPIRVLib.so.19.1                                   \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/clc/spirv64-mesa3d-.spv                                                     \
            ${QIMSDK_PREBUILT_DIR}/usr/lib/clc/                                                 && \
    rsync -aP /usr/include/cclang/opencl-c-base.h                                                  \
            ${QIMSDK_PREBUILT_DIR}/usr/include                                                  || {
        print-red "Failed to sync OpenCL libraries to ${PREBUILT_AARCH_LINUX_GNU_DIR} !!!"
        return -1
    }
}

# Sync prebuilt rtsp libs
function qimsdk-propagate-prebuilt-rtsp-libs() {
    local PREBUILT_AARCH_LINUX_GNU_DIR="${QIMSDK_PREBUILT_DIR}/usr/lib/aarch64-linux-gnu"

    # Dependencies of gst-plugin-rtspbin, alternative of libgstrtspserver-1.0-0 package
    rsync -aP /usr/lib/aarch64-linux-gnu/libgstrtspserver-1.0.so*                                  \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgstrtp-1.0.so*                                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstrtsp.so                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstrtp.so                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      || {
        print-red "Failed to sync rtsp libraries to ${PREBUILT_AARCH_LINUX_GNU_DIR} !!!"
        return -1
    }
}

# Sync prebuilt restricted zone libs
function qimsdk-propagate-prebuilt-rz-libs() {
    local PREBUILT_AARCH_LINUX_GNU_DIR="${QIMSDK_PREBUILT_DIR}/usr/lib/aarch64-linux-gnu"

    # Dependencies of qtirestrictedzonedbg, alternative of libopencv-imgproc410 package
    rsync -aP /usr/lib/aarch64-linux-gnu/libopencv_imgproc.so*                                     \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libopencv_core.so*                                        \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libjson-glib-1.0.so*                                      \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libGLX.so*                                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/lapack/liblapack.so*                                      \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/blas/libblas.so*                                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libtbb.so*                                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgfortran.so*                                           \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    || {
        print-red "Failed to sync restricted zone libraries to ${PREBUILT_AARCH_LINUX_GNU_DIR} !!!"
        return -1
    }
}

# Sync prebuilt qti-plugins-base libs
function qimsdk-propagate-prebuilt-qti-plugins-base-libs() {
    local PREBUILT_AARCH_LINUX_GNU_DIR="${QIMSDK_PREBUILT_DIR}/usr/lib/aarch64-linux-gnu"

    # Dependencies of gstreamer-qcom-oss-base-1.0, alternative of gstreamer1.0-plugins-good package
    rsync -aP /usr/lib/aarch64-linux-gnu/libgstallocators-1.0.so*                                  \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libcairo.so.2*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/liborc-0.4.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgstrtsp-1.0.so*                                        \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgstaudio-1.0.so*                                       \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgudev-1.0.so*                                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libpng16.so*                                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libGLdispatch.so*                                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgsttag-1.0.so*                                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgstsdp-1.0.so*                                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libX11.so*                                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxcb.so*                                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libXau.so*                                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libXdmcp.so*                                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libfontconfig.so*                                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libfreetype.so*                                           \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgstrtp-1.0.so*                                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libsndfile.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libXext.so*                                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgstapp-1.0.so*                                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libFLAC.so*                                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libXrender.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgstpbutils-1.0.so*                                     \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libvorbis.so*                                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxcb-render.so*                                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libvorbisenc.so*                                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxcb-shm.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libopus.so*                                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libpixman-1.so*                                           \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libogg.so*                                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libmpg123.so*                                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libmp3lame.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \

    # Add needed libraries from gst-plugins base
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstvideotestsrc.so                       \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \

    # Add needed libraries from gst-plugins good
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstmultifile.so                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \

    # Add needed libraries from gst-plugins bad
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstopengl.so                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstvideoparsersbad.so*                   \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstvideoconvertscale.so*                 \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstisomp4.so*                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstdebugutilsbad.so                      \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgstcodecparsers-1.0.so*                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    || {
        print-red "Failed to sync qti base deps libraries to ${PREBUILT_AARCH_LINUX_GNU_DIR} !!!"
        return -1
    }
}

# Sync prebuilt glimagesink libs
function qimsdk-propagate-prebuilt-glimagesink-libs() {
    local PREBUILT_AARCH_LINUX_GNU_DIR="${QIMSDK_PREBUILT_DIR}/usr/lib/aarch64-linux-gnu"

    # Dependencies of glimagesink
    rsync -aP /usr/lib/aarch64-linux-gnu/libgstgl-1.0.so*                                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgraphene-1.0.so*                                       \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libGL.so.1*                                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libEGL.so.1*                                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libwayland-egl.so.1*                                      \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libwayland-client.so*                                     \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libwayland-cursor.so*                                     \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libjpeg.so*                                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libGLX.so*                                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libGLX_indirect.so*                                       \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libGLX_mesa.so.0*                                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libX11-xcb.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libX11.so*                                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libXau.so*                                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libXdmcp.so*                                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libXext.so*                                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libXrender.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libXxf86vm.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxcb-dri3.so*                                           \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxcb-glx.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxcb-present.so*                                        \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxcb-randr.so*                                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxcb-render.so*                                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxcb-shm.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxcb-sync.so*                                           \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxcb-xfixes.so*                                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxcb.so*                                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxml2.so*                                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxshmfence.so*                                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libxxhash.so*                                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    || {
        print-red "Failed to sync glimagesink libraries to ${PREBUILT_AARCH_LINUX_GNU_DIR} !!!"
        return -1
    }
}

# Sync prebuilt pulse libs
function qimsdk-propagate-prebuilt-pulse-libs() {
    local PREBUILT_AARCH_LINUX_GNU_DIR="${QIMSDK_PREBUILT_DIR}/usr/lib/aarch64-linux-gnu"

    # Dependencies of pulse plugins, alternative of pulseaudio package
    rsync -aP /usr/lib/aarch64-linux-gnu/libpulse.so*                                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/pulseaudio/libpulsecommon-17.0.so*                        \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libdbus-1.so*                                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libasyncns.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    # Plugin libraries needed for audio use-case from gstreamer1.0-plugins-base and dependencies
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstaudiotestsrc.so*                      \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstaudioconvert.so*                      \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstwavparse.so*                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstwavenc.so*                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstaudioresample.so*                     \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstaudiobuffersplit.so*                  \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgstreamer-1.0.so*                                      \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgstbase-1.0.so*                                        \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgstriff-1.0.so*                                        \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    || {
        print-red "Failed to sync pulse libraries to ${PREBUILT_AARCH_LINUX_GNU_DIR} !!!"
        return -1
    }
}

# Sync prebuilt tflite libs
function qimsdk-propagate-prebuilt-tflite-libs() {
    local PREBUILT_AARCH_LINUX_GNU_DIR="${QIMSDK_PREBUILT_DIR}/usr/lib/aarch64-linux-gnu"

    # Copy prebuilt tensorflow library to libdir (dependency of qtimltflite plugin)
    rsync -aP  /root/tensorflow/lite/c/libtensorflowlite_c.so                                      \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    || {
        print-red "Failed to sync tflite libraries to ${PREBUILT_AARCH_LINUX_GNU_DIR} !!!"
        return -1
    }
}

# Sync prebuilt rtspsrc libs
function qimsdk-propagate-prebuilt-rtspsrc-libs() {
    local PREBUILT_AARCH_LINUX_GNU_DIR="${QIMSDK_PREBUILT_DIR}/usr/lib/aarch64-linux-gnu"

    # Dependencies of rtspsrc
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgst1394.so                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstaasink.so                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstadaptivedemux2.so                     \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstalaw.so                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstalpha.so                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstalphacolor.so                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstapetag.so                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstaudiofx.so                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstaudioparsers.so                       \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstauparse.so                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstautodetect.so                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstavi.so                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstcacasink.so                           \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstcairo.so                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstcamerabin.so                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstcutter.so                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstdebug.so                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstdeinterlace.so                        \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstdtmf.so                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstdv.so                                 \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgsteffectv.so                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstequalizer.so                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstflac.so                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstflv.so                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstflxdec.so                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstgdkpixbuf.so                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstgoom.so                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstgoom2k1.so                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgsticydemux.so                           \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstid3demux.so                           \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstimagefreeze.so                        \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstinterleave.so                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstisomp4.so                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstjack.so                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstjpeg.so                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstjpegformat.so                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstlame.so                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstlevel.so                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstmatroska.so                           \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstmonoscope.so                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstmpg123.so                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstmulaw.so                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstmultifile.so                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstmultipart.so                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstnavigationtest.so                     \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstoss4.so                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstossaudio.so                           \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstpng.so                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstpulseaudio.so                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstreplaygain.so                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstrtp.so                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstrtpmanager.so                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstrtsp.so                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstshapewipe.so                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstshout2.so                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstsmpte.so                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstsoup.so                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstspectrum.so                           \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstspeex.so                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgsttaglib.so                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgsttwolame.so                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstudp.so                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstvideo4linux2.so                       \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstvideobox.so                           \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstvideocrop.so                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstvideofilter.so                        \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstvideomixer.so                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstvpx.so                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstwavenc.so                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstwavpack.so                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstwavparse.so                           \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstximagesrc.so                          \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstxingmux.so                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgsty4menc.so                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \

    rsync -aP /usr/lib/aarch64-linux-gnu/libgstfft-1.0.so*                                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libshout.so*                                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libdv.so*                                                 \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libXfixes.so*                                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libvpx.so*                                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libaa.so*                                                 \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libspeex.so*                                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libtag.so*                                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libcairo-gobject.so*                                      \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libv4l2.so*                                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libtwolame.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libcaca.so*                                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libjack.so*                                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libgdk_pixbuf-2.0.so*                                     \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libwavpack.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libraw1394.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libtheora.so*                                             \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libXdamage.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libncurses.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libv4lconvert.so*                                         \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libslang.so*                                              \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/libavc1394.so*                                            \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \

    # Enable software encoder for qtirtspbin usecases
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstx264.so                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      && \

    # Dependency of libgstx264.so
    rsync -aP /usr/lib/aarch64-linux-gnu/libx264.so*                                               \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/                                                    && \
    rsync -aP /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstapp.so                                \
            ${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0/                                      || {
        print-red "Failed to sync rtspsrc libraries to ${PREBUILT_AARCH_LINUX_GNU_DIR} !!!"
        return -1
    }
}

# Sync prebuilt libs
function qimsdk-propagate-prebuilt-libs() {
    local PREBUILT_AARCH_LINUX_GNU_DIR="${QIMSDK_PREBUILT_DIR}/usr/lib/aarch64-linux-gnu"
    mkdir -p "${PREBUILT_AARCH_LINUX_GNU_DIR}"                                                  && \
        qimsdk-propagate-prebuilt-tflite-libs                                                   || {
                print-red "Failed to sync libraries to ${PREBUILT_AARCH_LINUX_GNU_DIR} !!!"
                return -1
        }
}

# Sync prebuilt libs from dependency packages instead of installing whole packages
# Not using this function and installing whole packages through apt is adding ~1.2GB to image size
function qimsdk-propagate-all-prebuilt-libs() {
    local PREBUILT_AARCH_LINUX_GNU_DIR="${QIMSDK_PREBUILT_DIR}/usr/lib/aarch64-linux-gnu"
    mkdir -p "${PREBUILT_AARCH_LINUX_GNU_DIR}"                                                  && \
        mkdir -p "${QIMSDK_PREBUILT_DIR}/usr/include"                                           && \
        mkdir -p "${QIMSDK_PREBUILT_DIR}/usr/lib/clc/"                                          && \
        mkdir -p "${PREBUILT_AARCH_LINUX_GNU_DIR}/gstreamer-1.0"                                && \
        mkdir -p "${PREBUILT_AARCH_LINUX_GNU_DIR}/gbm"                                          && \
        mkdir -p "${QIMSDK_PREBUILT_DIR}/usr/share/glvnd/egl_vendor.d"                          && \

        qimsdk-propagate-prebuilt-mesa-libs                                                     && \
        qimsdk-propagate-prebuilt-opencl-libs                                                   && \
        qimsdk-propagate-prebuilt-rtsp-libs                                                     && \
        qimsdk-propagate-prebuilt-rz-libs                                                       && \
        qimsdk-propagate-prebuilt-qti-plugins-base-libs                                         && \
        qimsdk-propagate-prebuilt-glimagesink-libs                                              && \
        qimsdk-propagate-prebuilt-pulse-libs                                                    && \
        qimsdk-propagate-prebuilt-tflite-libs                                                   && \
        qimsdk-propagate-prebuilt-rtspsrc-libs                                                  || {
                print-red "Failed to sync libraries to ${PREBUILT_AARCH_LINUX_GNU_DIR} !!!"
                return -1
        }
}

# Copy the Tensorflow Lite's headers and dependent headers to the sysroot
function qimsdk-copy-tf-lite-headers-to-sysroot() {
    local SRC_DIR=${QIMSDK_TF_SRC_DIR}
    local DST_INC_DIR="/usr/include/"

    local PENDING_LIST_INIT=""

    local ML_TFLITE_ENGINE_CC="${QIMSDK_SRC_DIR}/`
        `gst-plugins-qti-oss/gst-plugin-mltflite/ml-tflite-engine-c-api.cc"
    local ML_TFLITE_ENGINE_H="${QIMSDK_SRC_DIR}/`
        `gst-plugins-qti-oss/gst-plugin-mltflite/ml-tflite-engine.h"

    local ML_TFLITE_ENGINE_CC_INCS=""

    ML_TFLITE_ENGINE_CC_INCS=$(
        cat ${ML_TFLITE_ENGINE_CC}                                                                 |
            grep "include.*.tensorflow"                                                            |
            cut -f2 -d "<" | rev | cut -f2 -d ">" | rev
    )

    PENDING_LIST_INIT+="${ML_TFLITE_ENGINE_CC_INCS}"
    PENDING_LIST_INIT+=$'\n'

    local ML_TFLITE_ENGINE_H_INCS=""

    ML_TFLITE_ENGINE_H_INCS=$(
        cat ${ML_TFLITE_ENGINE_H}                                                                  |
            grep "include.*.tensorflow"                                                            |
            cut -f2 -d "<" | rev | cut -f2 -d ">" | rev
    )

    PENDING_LIST_INIT+="${ML_TFLITE_ENGINE_H_INCS}"
    PENDING_LIST_INIT+=$'\n'

    local PENDING_LIST=()

    for i in ${PENDING_LIST_INIT}; do
        PENDING_LIST+=($i)
    done

    # Remove the header from pending_list if it doesn't exist
    for HEADER in "${!PENDING_LIST[@]}"; do
        [ ! -f "${QIMSDK_TF_SRC_DIR}/${PENDING_LIST[${HEADER}]}" ] && {
            unset 'PENDING_LIST[HEADER]'
        }
    done

    local PROCESSED_LIST=()

    while [ ${#PENDING_LIST[@]} -gt 0 ]; do
        # Get next file to be processed
        local H_FILE=${PENDING_LIST[0]}

        [ -z ${H_FILE} ] && {
            # Remove file from pending list
            PENDING_LIST=( "${PENDING_LIST[@]:1}" )
            continue
        }

        local H_FILE_PATH_tensorflow="${SRC_DIR}"
        local H_FILE_LIB=$(echo ${H_FILE} | cut -d '/' -f 1)
        local H_FILE_PATH=H_FILE_PATH_${H_FILE_LIB}
        local H_FILE_SRC="${!H_FILE_PATH}/${H_FILE}"

        # Find next set of included files
        local NEXT_H_FILES=(
            $(grep "#include" ${H_FILE_SRC} | grep -E 'tensorflow' | cut -d "\"" -f 2)
        )

        # Append file to processed list
        PROCESSED_LIST+=("${H_FILE}")

        # Remove file from pending list
        PENDING_LIST=( "${PENDING_LIST[@]:1}" )

        # Check whether next files needs to be appended to pending list
        for NEXT_H_FILE in "${NEXT_H_FILES[@]}"; do
            if [[ ! " ${PENDING_LIST[*]} " =~ " ${NEXT_H_FILE} " ]]; then
                if [[ ! " ${PROCESSED_LIST[*]} " =~ " ${NEXT_H_FILE} " ]]; then
                    PENDING_LIST+=( "${NEXT_H_FILE}" )
                fi
            fi
        done

        # Copy file from src to destination
        local H_FILE_SRC="${!H_FILE_PATH}/./${H_FILE}"

        rsync -a --relative "${H_FILE_SRC}" "${DST_INC_DIR}"
    done
}

# Invoke Recipe Parser script
function qimsdk-invoke-recipe-parser() {
    local PYTHON_ARG_FOR_LAYERS="${QIMSDK_TMP_DIR}"

    python3 ${QIMSDK_SCRIPTS}/RecipeParser.py                                                      \
            -l ${PYTHON_ARG_FOR_LAYERS}                                                            \
            -m ${QIMSDK_PATH_TO_GST_META}                                                          \
            -t ${QIMSDK_SCRIPTS}                                                                   \
            "BuildCodeGenerator"                                                                || {
        print-red "Python Parser returns error, mode ${PYTHON_ARG_FOR_CODE_GENERATOR} !!!"
        return -1
    }

    return 0
}

# Reset project to the initial commmit
#   $1 - Path to project to reset to initial commit
function qimsdk-reset-project-to-initial-commit() {
    local PATH_TO_PROJECT=${1}

    local rc

    while true; do
        git -C ${PATH_TO_PROJECT} reset --hard HEAD~1

        rc=$?
        [ ${rc} -ne 0 ] && {
            print-green "Reached the initial commit."
            return 0
        }
    done
}
