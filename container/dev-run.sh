#!/usr/bin/env bash
# Development wrapper: run predict-structure CLI inside the all-in-one container
# using bind-mount + pre-built deps (no overlay, instant code iteration).
#
# Usage:
#   ./container/dev-run.sh --help
#   ./container/dev-run.sh boltz input.fasta -o output/ --debug
#   ./container/dev-run.sh esmfold input.fasta -o output/ --debug
#
# Rebuild deps after changing pyproject.toml:
#   rm -rf container/deps && ./container/build-deps.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SIF="${PREDICT_STRUCTURE_SIF:-/disks/tmp/all-2026-0224b.sif}"
DEPS_DIR="$SCRIPT_DIR/deps"

if [ ! -d "$DEPS_DIR" ]; then
    echo "ERROR: deps not found at $DEPS_DIR" >&2
    echo "Run: ./container/build-deps.sh" >&2
    exit 1
fi

if [ ! -f "$SIF" ]; then
    echo "ERROR: SIF image not found at $SIF" >&2
    echo "Set PREDICT_STRUCTURE_SIF to the correct path" >&2
    exit 1
fi

exec apptainer exec \
    --bind "$REPO_DIR":/app/predict-structure \
    "$SIF" \
    env PYTHONPATH=/app/predict-structure/container/deps:/app/predict-structure \
    /opt/miniforge/bin/python -m predict_structure.cli "$@"
