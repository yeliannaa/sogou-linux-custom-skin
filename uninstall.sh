#!/usr/bin/env bash
set -euo pipefail
SKIN_PACKAGE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 -B "$SKIN_PACKAGE_DIR/bundle.py" uninstall "$@"
