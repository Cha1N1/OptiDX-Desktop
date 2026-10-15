#!/bin/bash
set -euo pipefail
image_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export APPDIR="$image_root"
exec "$image_root/usr/bin/python3" -B -m optidx_desktop "$@"
