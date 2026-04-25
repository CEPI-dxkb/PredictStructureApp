#!/usr/bin/env bash
# Generate MSAs for the medium/large test fixtures via the ColabFold MSA
# server (mmseqs2 web). Run ONCE, out-of-band; the resulting .a3m files
# are committed to the repo so tests stay offline.
#
# Re-run this when the fixtures change. The output filenames must match
# tests/acceptance/matrix.py constants:
#   medium_protein.fasta -> test_data/msa/medium_protein.a3m
#   large_protein.fasta  -> test_data/msa/large_protein.a3m
#
# Requirements:
#   - colabfold_search (from ColabFold/MMseqs2). Available inside
#     /scout/containers/folding_prod.sif under
#     /opt/conda-colabfold/bin/colabfold_search (verify path with
#     `apptainer exec <sif> which colabfold_search`).
#   - Network access to colabfold MSA server, OR local MMseqs2 databases.
#
# Cost: ~1-5 minutes per query against the server. ~5-100 KB output per fixture.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TEST_DATA="$REPO/test_data"
MSA_DIR="$TEST_DATA/msa"
mkdir -p "$MSA_DIR"

# Two paths supported:
#  1. Local colabfold_search (via $COLABFOLD_SEARCH) -- preferred when
#     a local MMseqs2 install is available.
#  2. Direct REST calls to https://api.colabfold.com via the bundled
#     Python helper at scripts/_colabfold_api_msa.py -- used as a
#     fallback when colabfold_search isn't installed.

COLABFOLD_SEARCH="${COLABFOLD_SEARCH:-}"
SIF="${PREDICT_STRUCTURE_SIF:-/scout/containers/folding_prod.sif}"

run_one_via_local() {
    local fasta="$1"
    local out_basename="$2"
    local tmp="$(mktemp -d)"
    echo "=== Generating MSA for $fasta -> $out_basename.a3m (colabfold_search) ==="
    "$COLABFOLD_SEARCH" "$fasta" "$tmp" --use-env 1 --use-templates 0 --filter 1
    local a3m
    a3m=$(ls "$tmp"/*.a3m 2>/dev/null | head -1)
    if [ -z "$a3m" ]; then
        echo "ERROR: no .a3m produced in $tmp" >&2
        rm -rf "$tmp"
        exit 1
    fi
    cp "$a3m" "$MSA_DIR/${out_basename}.a3m"
    rm -rf "$tmp"
    echo "  -> $MSA_DIR/${out_basename}.a3m ($(wc -l < "$MSA_DIR/${out_basename}.a3m") lines)"
}

run_one_via_api() {
    local fasta="$1"
    local out_basename="$2"
    echo "=== Generating MSA for $fasta -> $out_basename.a3m (REST API) ==="
    python "$REPO/scripts/_colabfold_api_msa.py" "$fasta" \
        "$MSA_DIR/${out_basename}.a3m"
}

run_one() {
    if [ -n "$COLABFOLD_SEARCH" ] && [ -x "$COLABFOLD_SEARCH" ]; then
        run_one_via_local "$@"
    else
        run_one_via_api "$@"
    fi
}

run_one "$TEST_DATA/medium_protein.fasta" medium_protein
run_one "$TEST_DATA/large_protein.fasta"  large_protein

echo
echo "Done. Commit the new .a3m files in $MSA_DIR/."
