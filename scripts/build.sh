#!/bin/bash

# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause-Clear

# Configure qimsdk CMake Target
#    ${1} - SOURCE_PATH - Path to top-level CMake Project Directory
#    ${2} - TARGET - CMake Target
#    ${3..} - CMAKE_CUSTOM_CONFIG_FLAGS - plugin specific flags to pass to CMake command
function qimsdk-cmake-configure() {
    local SOURCE_PATH=${1}
    local TARGET=${2}

    [ ! -d ${SOURCE_PATH} ]                                                                     && {
        print-red "No such source: ${SOURCE_PATH}"
        print-red "Configuration will be skipped !"

        return -1
    }

    shift;shift

    local CMAKE_CUSTOM_CONFIG_FLAGS=$@

    (
        export CFLAGS="-mbranch-protection=standard -fstack-protector-strong -O2 `
            `-D_FORTIFY_SOURCE=2 -Wformat -Wformat-security -Werror=format-security -pipe `
            `-feliminate-unused-debug-types"
        export CXXFLAGS="${CFLAGS}"

        local CMAKE_FLAGS="-DCMAKE_VERBOSE_MAKEFILE:BOOL=ON`
            ` -DSYSROOT_INCDIR=/usr/include`
            ` -DSYSROOT_LIBDIR=/usr/lib`
            ` -DGST_PLUGINS_QTI_OSS_INSTALL_INCDIR=/usr/include`
            ` -DGST_PLUGINS_QTI_OSS_INSTALL_BINDIR=/usr/bin`
            ` -DGST_PLUGINS_QTI_OSS_INSTALL_LIBDIR=/usr/lib/aarch64-linux-gnu`
            ` -DGST_PLUGINS_QTI_OSS_INSTALL_CONFIG=/etc/configs/`
            ` -DCMAKE_BUILD_TYPE=Debug`
            ` "${CMAKE_CUSTOM_CONFIG_FLAGS}""

        mkdir -p ${QIMSDK_BUILD_DIR}/${TARGET}

        cd ${QIMSDK_BUILD_DIR}/${TARGET}

        set -o pipefail

        cmake ${CMAKE_FLAGS} "${SOURCE_PATH}"                                                     |&
                tee "${QIMSDK_LOGS_DIR}/cmake_configure_${TARGET}_$(date "+%Y_%m_%d-%H_%M_%S").log"

    ) || {
        print-red "FAILED: qimsdk-cmake-configure-${TARGET}: cmake configure failed !!!"
        return -1
    }

    print-green "qimsdk ${TARGET} cmake configured successfully !!!"
    return 0
}

# Compile qimsdk CMake Target
#    ${1} - TARGET - CMake Target
function qimsdk-cmake-compile() {
    local TARGET=${1}

    [ ! -d ${QIMSDK_BUILD_DIR}/${TARGET} ]                                                      && {
        print-red "No such build dir: ${QIMSDK_BUILD_DIR}/${TARGET}"
        print-red "Compilation will be skipped !"

        return -1
    }

    (
        cd ${QIMSDK_BUILD_DIR}/${TARGET}

        set -o pipefail

        cmake --build .                                                                           |&
                tee "${QIMSDK_LOGS_DIR}/cmake_compile_${TARGET}_$(date "+%Y_%m_%d-%H_%M_%S").log"
    ) || {
        print-red "FAILED: qimsdk-cmake-compile-${TARGET}: cmake compile failed !!!"
        return -1
    }

    print-green "qimsdk ${TARGET} built successfully !!!"
    return 0
}

# Install qimsdk CMake Target
#    ${1} - TARGET - CMake Target
function qimsdk-cmake-install() {
    local TARGET=${1}

    local DATE=$(date "+%Y_%m_%d-%H_%M_%S")
    local LOG_FILE_NAME=${QIMSDK_LOGS_DIR}/cmake_install_${TARGET}_${DATE}.log
    local LOG_FILE_NAME_DBG=${QIMSDK_LOGS_DIR}/cmake_install_${TARGET}_dbg_${DATE}.log

    [ ! -d ${QIMSDK_BUILD_DIR}/${TARGET} ]                                                      && {
        print-red "No such build dir: ${QIMSDK_BUILD_DIR}/${TARGET}"
        print-red "Installation will be skipped !"

        return -1
    }

    (
        cd ${QIMSDK_BUILD_DIR}/${TARGET}

        set -o pipefail


        cmake --install . --prefix ${QIMSDK_INSTALL_DEBUG_DIR}/usr/                               |&
                tee ${LOG_FILE_NAME_DBG}                                                        && \
        cmake --install . --prefix /usr --strip                                                   |&
                tee ${LOG_FILE_NAME}                                                              |\
                grep -E 'Up-to-date:|Installing:|configuration:' | tail -n +2                     |\
                cut -d ' ' -f 3 | xargs -i rsync -aR {} ${QIMSDK_INSTALL_DIR}/ -f"- *.h"
    ) || {
        print-red "FAILED: qimsdk-cmake-install-${TARGET}: cmake install failed !!!"
        return -1
    }

    cat ${LOG_FILE_NAME}

    print-green "qimsdk ${TARGET} installed successfully !!!"

    return 0
}

# Wrapper function to configure, compile, install & clean qimsdk debian/rules Target
function qimsdk-debian-rules-build() {
    DEB_BUILD_OPTIONS=parallel=$(nproc) debian/rules build binary || {
        print-red "FAILED: qimsdk-debian-rules-build: debian/rules build failed !!!"
        return -1
    }

    # Install generated debian packages from patched and built gst-plugins-base and gst-plugins-good
    # Installing is done through dpkg instead of apt as dependencies of these packages has already
    #   been installed through 'apt-get build-dep' in qimsdk-build image setup
    # They need to be installed in build image environment as compilation of QTI plugins depend on
    #   these packages' outputs being present in the system
    dpkg -i ${QIMSDK_DOWNLOAD_DIR}/gstreamer1.0-*.deb ${QIMSDK_DOWNLOAD_DIR}/libgstreamer-*.deb    \
        ${QIMSDK_DOWNLOAD_DIR}/gir1.2-gst-*.deb || {
        print-red "FAILED: qimsdk-debian-rules-build: dpkg install to root failed !!!"
        return -1
    }
}

# Wrapper function to configure, compile & install qimsdk CMake Target
#    ${1} - SOURCE_PATH - Path to top-level CMake Project Directory
#    ${2} - CMAKE_CUSTOM_CONFIG_FLAGS - plugin specific flags to pass to CMake command
function qimsdk-cmake-build() {
    local SOURCE_PATH=${1}
    local T=`basename ${SOURCE_PATH}`

    shift

    local CMAKE_CUSTOM_CONFIG_FLAGS=$@

    qimsdk-cmake-configure ${SOURCE_PATH} ${T} ${CMAKE_CUSTOM_CONFIG_FLAGS}                     && \
            qimsdk-cmake-compile ${T}                                                           && \
            qimsdk-cmake-install ${T}
}

###########################################################

# debian/rules build gst-plugins-base-1.26.1
qimsdk-debian-rules-build-gst-plugins-base() {
    (
        cd ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-base1.0-1.26.2
        qimsdk-debian-rules-build
    )
}

# debian/rules build gst-plugins-good-1.26.1
qimsdk-debian-rules-build-gst-plugins-good() {
    (
        cd ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-good1.0-1.26.2
        qimsdk-debian-rules-build
    )
}

# Clean gst-plugins-base
function qimsdk-debian-rules-clean-gst-plugins-base() {
    (
        cd ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-base1.0-1.26.2
        DEB_BUILD_OPTIONS=parallel=$(nproc) debian/rules clean
    )

    print-green "${FUNCNAME} completed successfully!"
}

# Clean gst-plugins-good
function qimsdk-debian-rules-clean-gst-plugins-good() {
    (
        cd ${QIMSDK_DOWNLOAD_DIR}/gst-plugins-good1.0-1.26.2
        DEB_BUILD_OPTIONS=parallel=$(nproc) debian/rules clean
    )

    print-green "${FUNCNAME} completed successfully!"
}

# CMake Build qcom-gstreamer1.0-plugins-oss plugin
#    ${1} - PLUGIN_DIR_NAME - Name of top-level plugin directory under gst-plugins-qti-oss
function qimsdk-cmake-build-qcom-gstreamer1.0-plugins-oss () {
    local PLUGIN_DIR_NAME="${1}"

    [ -z "${PLUGIN_DIR_NAME}" ]                                                                 && {
        print-red "QTI Plugin directory name must be provided as first argument!"
        return -1
    }

    qimsdk-cmake-build ${QIMSDK_SRC_DIR}/gst-plugins-qti-oss/${PLUGIN_DIR_NAME}                 && \
        print-green "${FUNCNAME} ${PLUGIN_DIR_NAME} completed successfully!"

}

# CMake Clean qcom-gstreamer1.0-plugins-oss plugin
#    ${1} - PLUGIN_DIR_NAME - Name of top-level plugin directory under gst-plugins-qti-oss
function qimsdk-cmake-clean-qcom-gstreamer1.0-plugins-oss () {
    local PLUGIN_DIR_NAME="${1}"

    [ -z "${PLUGIN_DIR_NAME}" ]                                                                 && {
        print-red "QTI Plugin directory name must be provided as first argument!"
        return -1
    }

    rm -rf ${QIMSDK_BUILD_DIR}/${PLUGIN_DIR_NAME}                                               && \
            print-green "${FUNCNAME} ${PLUGIN_DIR_NAME} completed successfully!"
}

# Wrapper function to build all QTI gstreamer plugins incrementally
function qimsdk-incremental-build-qti() {
    qimsdk-cmake-build ${QIMSDK_SRC_DIR}/gst-plugins-qti-oss                                       \
            -DENABLE_GST_PLUGIN_VCOMPOSER=ON                                                       \
            -DENABLE_GST_PLUGIN_BATCH=ON                                                           \
            -DENABLE_GST_PLUGIN_METAMUX=ON                                                         \
            -DENABLE_GST_PLUGIN_SOCKET=ON                                                          \
            -DENABLE_GST_PLUGIN_VSPLIT=ON                                                          \
            -DENABLE_GST_PLUGIN_VTRANSFORM=ON                                                      \
            -DENABLE_GST_PLUGIN_VOVERLAY=ON                                                        \
            -DENABLE_GST_PLUGIN_OVERLAY=ON                                                         \
            -DENABLE_GST_PLUGIN_RESTRICTED_ZONE=ON                                                 \
            -DENABLE_GST_PLUGIN_RTSPBIN=ON                                                         \
            -DENABLE_GST_PLUGIN_REDISSINK=ON                                                       \
            -DENABLE_GST_PLUGIN_VIDEOTEMPLATE=ON                                                   \
            -DENABLE_GST_PLUGIN_MLACONVERTER=ON                                                    \
            -DENABLE_GST_PLUGIN_MLACLASSIFICATION=ON                                               \
            -DENABLE_GST_PLUGIN_MLDEMUX=ON                                                         \
            -DENABLE_GST_PLUGIN_MLVCONVERTER=ON                                                    \
            -DENABLE_GST_PLUGIN_MLVCLASSIFICATION=ON                                               \
            -DENABLE_GST_PLUGIN_MLVSUPERRESOLUTION=ON                                              \
            -DENABLE_GST_PLUGIN_MLVDETECTION=ON                                                    \
            -DENABLE_GST_PLUGIN_MLVPOSE=ON                                                         \
            -DENABLE_GST_PLUGIN_MLVSEGMENTATION=ON                                                 \
            -DENABLE_GST_PLUGIN_MLTFLITE=ON                                                        \
            -DENABLE_GST_PLUGIN_MLMETAPARSER=ON                                                    \
            -DENABLE_GST_PLUGIN_METATRANSFORM=ON                                                   \
            -DENABLE_GST_PLUGIN_OBJTRACKER=ON                                                      \
            -DENABLE_GST_PLUGIN_MLMETAEXTRACTOR=ON                                                 \
            -DENABLE_GST_PLUGIN_MLPOSTPROCESS=ON                                                   \
            -DENABLE_GST_PLUGIN_MSGBROKER=ON                                                    && \
            print-green "${FUNCNAME} completed successfully!"
}

# Configure and build gst plugins
function qimsdk-incremental-build() {
    qimsdk-debian-rules-build-gst-plugins-base                                                  && \
            qimsdk-debian-rules-build-gst-plugins-good                                          && \
            qimsdk-incremental-build-qti                                                        && \
            print-green "QIMSDK GStreamer targets built successfully !!!"
}

print-green "qimsdk-incremental-build"
echo "    Incremental build of gst plugins"
print-green "qimsdk-incremental-build-qti"
echo "    Incremental build of all QTI gst plugins"
print-yellow "qimsdk-cmake-build-qcom-gstreamer1.0-plugins-oss \${QTI_PLUGIN_DIR_NAME}"
echo "    CMake build of a QTI gst plugin. Plugin directory name under gst-plugins-qti-oss `
            `must be provided as first argument"
print-red "qimsdk-cmake-clean-qcom-gstreamer1.0-plugins-oss \${QTI_PLUGIN_DIR_NAME}"
echo "    Clean QTI gst plugin build dir. Plugin directory name under gst-plugins-qti-oss `
            `must be provided as first argument"
