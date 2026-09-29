#!/usr/bin/env bash
set -euo pipefail
SKIN_PACKAGE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == --check ]]; then
    shift
    exec python3 -B "$SKIN_PACKAGE_DIR/bundle.py" check "$@"
fi
exec python3 -B "$SKIN_PACKAGE_DIR/bundle.py" install "$@"
