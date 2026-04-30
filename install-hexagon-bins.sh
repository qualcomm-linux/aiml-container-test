#!/usr/bin/env bash
set -e

DEVICES_YAML="devices.yaml"

CDSP_DIRS=(
"/sys/kernel/debug/qcom_socinfo/cdsp"
"/sys/kernel/debug/qcom_socinfo/cdsp1"
"/sys/kernel/debug/qcom_socinfo/cdsp2"
"/sys/kernel/debug/qcom_socinfo/cdsp3"
)

read_soc_id() {
    if [[ -f /sys/devices/soc0/soc_id ]]; then
        tr -d '\0' < /sys/devices/soc0/soc_id | xargs
    fi
}

read_device_model() {
    if [[ -f /sys/firmware/devicetree/base/model ]]; then
        tr -d '\0' < /sys/firmware/devicetree/base/model | xargs
    fi
}

get_cdsp_firmware_version() {
    for dir in "${CDSP_DIRS[@]}"; do
        file="$dir/name"
        if [[ -f "$file" ]]; then
            line=$(cat "$file")
            if [[ -n "$line" ]]; then
                echo "$line" | awk -F: '{print $2}' | xargs
                return
            fi
        fi
    done
}

get_hexagon_version_by_soc() {
    local soc_id="$1"
    yq -r ".devices[] | select(.soc_ids[] == \"$soc_id\") | .hexagon_tensor_processor.version" "$DEVICES_YAML"
}

get_hexagon_bin_dir_by_model() {
    local model="$1"
    yq -r ".devices[] | select(.device_dt_model[] == \"$model\") | .hexagon_bin_dir" "$DEVICES_YAML"
}

get_hexagon_prefix_by_model() {
    local model="$1"
    yq -r ".devices[] | select(.device_dt_model[] == \"$model\") | .hexagon_bin_dir_prefix" "$DEVICES_YAML"
}

get_hexagon_src_dir() {
    model=$(read_device_model)
    bin_dir=$(get_hexagon_bin_dir_by_model "$model")
    prefix=$(get_hexagon_prefix_by_model "$model")
    fw_name=$(get_cdsp_firmware_version)

    echo "/root/hexagon-binaries/${bin_dir}${prefix}${fw_name}/"
}

get_hexagon_dest_dir() {
    soc_id=$(read_soc_id)
    hex_ver=$(get_hexagon_version_by_soc "$soc_id")
    echo "/usr/share/qcom/hexagon-${hex_ver}/"
}

copy_hexagon_bins() {
    src=$(get_hexagon_src_dir)
    dst=$(get_hexagon_dest_dir)

    echo "Copying Hexagon bins:"
    echo "SRC: $src"
    echo "DST: $dst"

    mkdir -p "$dst"
    cp -r "$src"* "$dst"
}

copy_hexagon_bins

