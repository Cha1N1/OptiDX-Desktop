#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
apps_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$apps_dir"
cat > "$apps_dir/optidx-desktop.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=OptiDX Desktop
Comment=Manage Linux game HDR mods and upscalers
Exec="$project_dir/run.sh"
Icon=applications-games
Terminal=false
Categories=Game;Utility;
EOF
printf 'Application launcher installed in %s\n' "$apps_dir"
