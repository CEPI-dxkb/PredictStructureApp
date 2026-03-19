#!/usr/bin/env bash
# Build predict-structure dependencies into container/deps/ using the
# container's Python so wheels match the runtime platform.
#
# Re-run after changing pyproject.toml:
#   rm -rf container/deps && ./container/build-deps.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SIF="${PREDICT_STRUCTURE_SIF:-/disks/tmp/all-2026-0224b.sif}"
DEPS_DIR="$SCRIPT_DIR/deps"

if [ ! -f "$SIF" ]; then
    echo "ERROR: SIF image not found at $SIF" >&2
    echo "Set PREDICT_STRUCTURE_SIF to the correct path" >&2
    exit 1
fi

rm -rf "$DEPS_DIR"

echo "Installing deps into $DEPS_DIR ..."
apptainer exec \
    --bind "$REPO_DIR":/app/predict-structure \
    "$SIF" \
    /opt/miniforge/bin/pip install --no-cache-dir \
        --target=/app/predict-structure/container/deps \
        "/app/predict-structure[boltz,chai,cwl]"

echo "Done. Deps installed to $DEPS_DIR"
