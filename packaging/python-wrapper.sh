#!/bin/bash
set -euo pipefail
image_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
if [[ -z ${OPTIDX_APPIMAGE_CONTEXT:-} ]]; then
    for key in PATH PYTHONHOME PYTHONPATH QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH PYTHONNOUSERSITE; do
        if [[ -v $key ]]; then
            export "OPTIDX_ORIG_${key}_SET=1" "OPTIDX_ORIG_${key}=${!key}"
        else
            export "OPTIDX_ORIG_${key}_SET=0"
        fi
    done
fi
export OPTIDX_APPIMAGE_CONTEXT=1
export OPTIDX_BUNDLED_PYTHON="$image_root/usr/bin/python3"
export PYTHONHOME="$image_root/usr"
export PYTHONPATH="$image_root/usr/share/optidx-desktop:$image_root/usr/lib/@PYTHON@/site-packages"
export PYTHONNOUSERSITE=1
export QT_PLUGIN_PATH="$image_root/usr/lib/qt6/plugins"
export QT_QPA_PLATFORM_PLUGIN_PATH="$image_root/usr/lib/qt6/plugins/platforms"
export PATH="$image_root/usr/bin:${OPTIDX_ORIG_PATH:-/usr/bin:/bin}"
exec "$image_root/usr/lib/ld-linux-x86-64.so.2" --library-path "$image_root/usr/lib" "$image_root/usr/bin/python3.real" -B -P "$@"
