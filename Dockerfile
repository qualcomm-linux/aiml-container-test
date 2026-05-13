#######################################################################

FROM debian:trixie-slim AS fastrpc-build

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install build tools
RUN DEBIAN_FRONTEND=noninteractive apt -y install git build-essential libtool wget unzip libyaml-dev libbsd-dev pkg-config

# Build & Install fastrpc
RUN mkdir ~/build
RUN cd ~/build ; \
	git clone https://github.com/qualcomm/fastrpc.git ; \
        cd fastrpc ; \
        GITCOMPILE_NO_MAKE=yes ./gitcompile ; \
        make -j$(nproc) && \
        make install DESTDIR=/opt/fastrpc ; \
        rm ~/build/fastrpc -rf

RUN find /opt/

# Remove build folder
RUN rm -rf ~/build

# Remove cached files
RUN rm ~/.cache -rf
RUN apt clean

#######################################################################

FROM debian-trixie-slim AS fastrpc-deb

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
RUN DEBIAN_FRONTEND=noninteractive apt -y --no-install-recommends install fastrpc-tests

# Remove cached files
RUN rm ~/.cache -rf
RUN apt clean

#######################################################################
 
FROM debian:trixie-slim AS qnn-install

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install build tools
RUN DEBIAN_FRONTEND=noninteractive apt -y install git wget unzip

# Install QNN
RUN mkdir -p ~/build /usr/lib/dsp/cdsp /usr/share/qcom /usr/local/lib -p
RUN cd ~/build ; \
	export QNNVERSION="2.43.0.260128" ; \
	wget https://apigwx-aws.qualcomm.com/qsc/public/v1/api/download/software/sdks/Qualcomm_AI_Runtime_Community/All/${QNNVERSION}/v${QNNVERSION}.zip; \
	unzip v${QNNVERSION}.zip ; \
	rm ~/build/v${QNNVERSION}.zip ; \
	rm ~/build/qairt/${QNNVERSION}/lib/aarch64-oe-linux-gcc11.2/libSNPE*; \
	rm ~/build/qairt/${QNNVERSION}/lib/aarch64-oe-linux-gcc11.2/libSnpe*; \
	cp ~/build/qairt/${QNNVERSION}/lib/aarch64-oe-linux-gcc11.2/* /usr/local/lib/ ; \
	cp ~/build/qairt/*/lib/hexagon-v* /usr/share/qcom/ -rf; \
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

# Remove cached files
RUN rm ~/.cache -rf
RUN apt clean


ENTRYPOINT [ "/bin/bash", "-l", "-c" ]

#######################################################################

FROM deploy AS fastrpc-build-deploy

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install libraries needed for fastrpc built-from-source
RUN DEBIAN_FRONTEND=noninteractive apt -y --no-install-recommends install libyaml-0-2 libbsd0

# Copy fastrpc, host side libraries and DSP side libraries from the fastrpc-build layer
COPY --from=fastrpc-build /opt/fastrpc/usr /usr/
RUN ldconfig
RUN find /usr | grep fastrpc

# Copy QNN host side libraries and DSP side libraries from the qnn-install layer
COPY --from=qnn-install /usr/local/lib /usr/local/lib
RUN find /usr/local/lib

# Copy over DSP libraries
COPY --from=qnn-install /usr/lib/dsp /usr/lib/dsp
RUN find /usr/lib/dsp

# Remove cached files
RUN rm ~/.cache -rf
RUN apt clean

#######################################################################

FROM deploy AS fastrpc-deb-deploy

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

RUN DEBIAN_FRONTEND=noninteractive apt -y --no-install-recommends install fastrpc-tests

# Copy QNN host side libraries and DSP side libraries from the qnn-install layer
COPY --from=qnn-install /usr/local/lib /usr/local/lib
RUN find /usr/local/lib

# Copy over DSP libraries
COPY --from=qnn-install /usr/lib/dsp /usr/lib/dsp
RUN find /usr/lib/dsp

# Remove cached files
RUN rm ~/.cache -rf
RUN apt clean

