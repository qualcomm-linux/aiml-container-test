#!/bin/sh

# Based on scripts from https://github.com/qualcomm-linux/test-definitions, notably https://github.com/qualcomm-linux/test-definitions/blob/f6c0d5586bfd4ca109b97524e05468eb7731d9fa/automated/linux/docker/docker.sh
# License: GPL-2.0-only

# shellcheck disable=SC1091
. ./sh-test-lib

OUTPUT="$(pwd)/output"
RESULT_FILE="${OUTPUT}/result.txt"
export RESULT_FILE


usage() {
    echo "$0 -i <image> [-o <OCI tarball>]" 1>&2
    exit 1
}

while getopts "i:o:t:h" o; do
    case "$o" in
        i) IMAGE="${OPTARG}" ;;
        o) OCITARBALL="${OPTARG}" ;;
        t) TESTS="${OPTARG}" ;;
        h|*) usage ;;
    esac
done

if [ -z "${IMAGE}" ] ; then
	error_msg "The image argument is mandatory, exiting"
	exit
fi

! check_root && error_msg "You need to be root to run this script."
create_out_dir "${OUTPUT}"
cd "${OUTPUT}" || exit

install_docker() {
    # If docker is installed, be naive and trust it
    which docker && echo "Docker already installed"

    # Check if the installed version is recent enough (v28 or newer)
    DOCKER_MAJOR_VERSION="$(docker version -f "{{.Server.Version}}" | cut -d'.' -f 1 )"
    if [ "${DOCKER_MAJOR_VERSION}" -ge 28 ] ; then
        return
    fi

    dist_name
    # shellcheck disable=SC2154
    case "${dist}" in
        debian|ubuntu)
            echo "Installed version not recent enough, Installing docker devops style, curl straight to shell"
            export DEBIAN_FRONTEND=noninteractive
	    apt -y purge docker.io || true
            install_deps curl
            curl -fsSL get.docker.com -o get-docker.sh
            sh get-docker.sh
	    cat << EOF > /etc/docker/daemon.json
{
  "features": {
    "containerd-snapshotter": true
  }
}
EOF
            ;;
        *)
            warn_msg "No package installation support on ${dist}"
            error_msg "And docker not pre-installed, exiting..."
            ;;
    esac
}

skip_list="start-docker-service run-docker-image import-oci"
install_docker
exit_on_fail "install-docker" "${skip_list}"

skip_list="run-docker-image import-oci"
systemctl restart docker
exit_on_fail "start-docker-service" "${skip_list}"

if [ -n "${OCITARBALL}" ] ; then
	# Output docker config for checking e.g CDI entries
	docker info
	# The tarball is located in the same folder as this script, but we're executing in a subfolder
	OCITARBALL="$(find ../ -name ${OCITARBALL})"
	docker import ${OCITARBALL} ${IMAGE}
	exit_on_fail "importoci" "${skip_list}"
fi

docker run --rm --network host -it "${IMAGE}" /run-tflite.sh 
check_return "run-docker-image"
