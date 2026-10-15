#!/bin/bash
set -euo pipefail
image_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
tool_name=$(basename -- "$0")
if [[ $tool_name == curl && -z ${CURL_CA_BUNDLE:-} ]]; then
    for certificates in /etc/ssl/certs/ca-certificates.crt /etc/ssl/cert.pem "$image_root/usr/share/optidx-desktop/certificates.pem"; do
        if [[ -f $certificates ]]; then export CURL_CA_BUNDLE="$certificates"; break; fi
    done
fi
exec "$image_root/usr/lib/ld-linux-x86-64.so.2" --library-path "$image_root/usr/lib" "$image_root/usr/bin/$tool_name.real" "$@"
