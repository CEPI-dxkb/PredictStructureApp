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

# Model weights and databases
DB_DIR="${PREDICT_STRUCTURE_DB:-/local_databases}"
CACHE_DIR="${PREDICT_STRUCTURE_CACHE:-/tmp/predict-structure-cache}"
mkdir -p "$CACHE_DIR"

AF2_DB_DIR="${PREDICT_STRUCTURE_AF2_DB:-$DB_DIR/alphafold/databases}"

exec apptainer exec \
    --nv \
    --bind "$REPO_DIR":/app/predict-structure \
    --bind "$DB_DIR":/local_databases \
    --bind "$AF2_DB_DIR":/databases \
    --bind "$CACHE_DIR":/cache \
    "$SIF" \
    env PYTHONPATH=/app/predict-structure/container/deps:/app/predict-structure \
        BOLTZ_CACHE=/local_databases/boltz \
        CHAI_DOWNLOADS_DIR=/local_databases/chai \
        HF_HOME=/cache/huggingface \
        TORCH_HOME=/cache/torch \
    /opt/miniforge/bin/python -m predict_structure.cli "$@"
