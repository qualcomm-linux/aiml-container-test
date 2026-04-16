#######################################################################
 
FROM debian:trixie-slim AS fastrpc-build

# Update
RUN DEBIAN_FRONTEND=noninteractive apt-get update

# Install build tools
RUN DEBIAN_FRONTEND=noninteractive apt -y install git wget unzip

# Install QNN
RUN mkdir -p ~/build /usr/lib/dsp/cdsp /usr/local/lib
RUN cd ~/build ; \
       wget https://softwarecenter.qualcomm.com/api/download/software/sdks/Qualcomm_AI_Runtime_Community/All/2.36.0.250627/v2.36.0.250627.zip; \
       unzip v2.36.0.250627.zip ; \
       rm ~/build/v2.36.0.250627.zip ; \
       cp -v ~/build/qairt/2.36.0.250627/lib/aarch64-oe-linux-gcc11.2/* /usr/local/lib/ ;  \
       cp -v ~/build/qairt/2.36.0.250627/lib/hexagon-v68/unsigned/* /usr/lib/dsp/cdsp/ ; \
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

