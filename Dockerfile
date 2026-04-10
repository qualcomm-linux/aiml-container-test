#######################################################################
 
FROM debian:trixie-slim AS fastrpc-build

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install build tools
RUN DEBIAN_FRONTEND=noninteractive apt -y install git wget unzip

# Install QAIRT host libraries and DSP skeletons for every supported Hexagon architecture
ARG QAIRT_VERSION=2.47.0.260601
RUN mkdir -p ~/build /usr/lib/dsp/cdsp /usr/local/lib /usr/share/aiml-container
RUN cd ~/build ; \
       wget "https://softwarecenter.qualcomm.com/api/download/software/sdks/Qualcomm_AI_Runtime_Community/All/${QAIRT_VERSION}/v${QAIRT_VERSION}.zip"; \
       unzip "v${QAIRT_VERSION}.zip" ; \
       rm ~/build/v${QAIRT_VERSION}.zip ; \
       cp -v ~/build/qairt/${QAIRT_VERSION}/lib/aarch64-oe-linux-gcc11.2/* /usr/local/lib/ ;  \
       cp -v ~/build/qairt/${QAIRT_VERSION}/lib/hexagon-v*/unsigned/* /usr/lib/dsp/cdsp/ ; \
       printf '%s\n' "${QAIRT_VERSION}" >/usr/share/aiml-container/qairt-version ; \
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

FROM debian:trixie-slim AS deploy

# Rusticl leaves drivers disabled by default, so explicitly expose Freedreno to
# OpenCL consumers instead of letting GPU workloads fail with no devices.
ENV RUSTICL_ENABLE=freedreno

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update
RUN DEBIAN_FRONTEND=noninteractive apt -y upgrade
RUN DEBIAN_FRONTEND=noninteractive apt -y --no-install-recommends install wget curl unzip ca-certificates

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

# Remove cached files
RUN rm ~/.cache -rf
RUN apt clean


ENTRYPOINT [ "/bin/bash", "-l", "-c" ]

#######################################################################

FROM deploy AS fastrpc-deploy

# FastRPC's domain-neutral override reaches the QNN skeletons kept in their
# CDSP-specific subdirectory without relying on its legacy ADSP-named alias.
ENV DSP_LIBRARY_PATH=/usr/lib/dsp/cdsp

# CDI supplies MACHINE_NAME and mounts the matching host DSP directory; these
# mappings let FastRPC select that directory without another runtime bind.
COPY <<EOF /usr/share/hexagon-dsp/conf.d/aiml-container-machines.yaml
machines:
  Qualcomm Technologies, Inc. Robotics RB3gen2:
    DSP_LIBRARY_PATH: qcm6490/Thundercomm/RB3gen2/dsp
  Arduino Monza:
    DSP_LIBRARY_PATH: qcs8300/Arduino/Monza/dsp
  Arduino VENTUNO Q:
    DSP_LIBRARY_PATH: qcs8300/Arduino/Monza/dsp
  Qualcomm Technologies, Inc. Monaco Monza addons:
    DSP_LIBRARY_PATH: qcs8300/Arduino/Monza/dsp
EOF

# Use the same maintained FastRPC packages as the qcom-deb host image so the
# container userspace stays compatible with its kernel and CDSP firmware.
COPY <<EOF /etc/apt/sources.list.d/qli.sources
Types: deb
URIs: https://deb.debusine.qualcomm.com/qualcomm/qli
Suites: trixie
Components: main contrib non-free-firmware non-free
Enabled: yes
Signed-By:
 -----BEGIN PGP PUBLIC KEY BLOCK-----
 .
 mDMEag8p/xYJKwYBBAHaRw8BAQdAdB6JSNF1OXxnsTgp4VTUekW52BM7e6ZQVRsq
 QT5QDaS0JEFyY2hpdmUgc2lnbmluZyBrZXkgZm9yIHF1YWxjb21tL3FsaYiQBBMW
 CgA4FiEEOwuFfyf8aPE5SQakb8qSvoHfw8IFAmoPKf8CGwMFCwkIBwIGFQoJCAsC
 BBYCAwECHgECF4AACgkQb8qSvoHfw8Lz1gEA9XocADbvqUgZQc0LceThn7vMI98d
 kTJoiInuulQ6rEUBANo+GOKILH71VRnZ5jWtsu7IlVk7oUMlTtC0eE5tcBwB
 =bX6V
 -----END PGP PUBLIC KEY BLOCK-----
EOF

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install the FastRPC userspace and its executable CDSP diagnostics.
RUN DEBIAN_FRONTEND=noninteractive apt -y --no-install-recommends install fastrpc-tests

# Copy QNN host side libraries and DSP side libraries from the fastrpc-build layer
COPY --from=fastrpc-build /usr/local/lib /usr/local/lib
RUN find /usr/local/lib

# Copy over DSP libraries
COPY --from=fastrpc-build /usr/lib/dsp /usr/lib/dsp
COPY --from=fastrpc-build /usr/share/aiml-container /usr/share/aiml-container
RUN find /usr/lib/dsp

# Remove cached files
RUN rm ~/.cache -rf
RUN apt clean
