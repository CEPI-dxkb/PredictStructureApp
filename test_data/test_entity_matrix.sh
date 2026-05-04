#!/usr/bin/env bash
# Test entity flag combinations across tools via apptainer.
# Actually executes the tools and times each run.
# Uses a pre-computed MSA (no MSA server needed).
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
DEV_RUN="$REPO_DIR/container/dev-run.sh"

PROTEIN="$SCRIPT_DIR/simple_protein.fasta"
MULTIMER="$SCRIPT_DIR/multimer.fasta"
DNA="$SCRIPT_DIR/dna.fasta"
RNA="$SCRIPT_DIR/rna.fasta"
MSA="$SCRIPT_DIR/msa/crambin.a3m"
OUT_BASE="/tmp/predict-structure-test"
rm -rf "$OUT_BASE"

PASS=0
FAIL=0
ERRORS=""

run_test() {
    local label="$1"
    shift
    local out_dir="$OUT_BASE/$label"

    echo "══════════════════════════════════════════════"
    echo "TEST: $label"
    echo "CMD:  dev-run.sh $*"
    echo "START: $(date '+%H:%M:%S')"
    echo ""

    local subcmd="$1"
    shift

    local start=$SECONDS
    "$DEV_RUN" --verbose "$subcmd" "$@" -o "$out_dir" 2>&1
    local rc=$?
    local elapsed=$((SECONDS - start))

    echo ""
    if [ $rc -eq 0 ]; then
        echo "RESULT: PASS  (${elapsed}s)"
        PASS=$((PASS + 1))
        echo "OUTPUT:"
        ls -lh "$out_dir"/ 2>/dev/null || echo "  (no output dir)"
    else
        echo "RESULT: FAIL  (exit $rc, ${elapsed}s)"
        FAIL=$((FAIL + 1))
        ERRORS="${ERRORS}  FAIL: ${label} (exit ${rc}, ${elapsed}s)\n"
    fi
    echo ""
}

echo "=============================================="
echo " Entity matrix test — LIVE EXECUTION"
echo " GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"
echo " SIF: ${PREDICT_STRUCTURE_SIF:-/disks/tmp/all-2026-0224b.sif}"
echo " MSA: $MSA"
echo " Started: $(date)"
echo "=============================================="
echo ""

# ── Test 1: Single protein (all tools + auto) ───────────────────────
echo "=============================================="
echo " Test 1: Single protein"
echo "=============================================="
run_test "boltz_protein"      boltz     --protein "$PROTEIN" --msa "$MSA"
run_test "chai_protein"       chai      --protein "$PROTEIN" --msa "$MSA"
run_test "alphafold_protein"  alphafold --protein "$PROTEIN" --af2-data-dir /databases --af2-db-preset reduced_dbs
run_test "auto_protein"       auto      --protein "$PROTEIN" --msa "$MSA"

# ── Test 2: Multimer (multi-chain protein) ───────────────────────────
echo "=============================================="
echo " Test 2: Multimer (multi-chain FASTA)"
echo "=============================================="
run_test "boltz_multimer"      boltz     --protein "$MULTIMER" --msa "$MSA"
run_test "chai_multimer"       chai      --protein "$MULTIMER" --msa "$MSA"
run_test "alphafold_multimer"  alphafold --protein "$MULTIMER" --af2-data-dir /databases --af2-db-preset reduced_dbs --af2-model-preset multimer

# ── Test 3: Protein + ligand ─────────────────────────────────────────
echo "=============================================="
echo " Test 3: Protein + ligand"
echo "=============================================="
run_test "boltz_protein_ligand" boltz --protein "$PROTEIN" --ligand ATP --msa "$MSA"
run_test "chai_protein_ligand"  chai  --protein "$PROTEIN" --ligand ATP --msa "$MSA"
run_test "auto_protein_ligand"  auto  --protein "$PROTEIN" --ligand ATP --msa "$MSA"

# ── Test 4: Protein + DNA ───────────────────────────────────────────
echo "=============================================="
echo " Test 4: Protein + DNA"
echo "=============================================="
run_test "boltz_protein_dna" boltz --protein "$PROTEIN" --dna "$DNA" --msa "$MSA"
run_test "chai_protein_dna"  chai  --protein "$PROTEIN" --dna "$DNA" --msa "$MSA"

# ── Test 5: Protein + RNA ───────────────────────────────────────────
echo "=============================================="
echo " Test 5: Protein + RNA"
echo "=============================================="
run_test "boltz_protein_rna" boltz --protein "$PROTEIN" --rna "$RNA" --msa "$MSA"
run_test "chai_protein_rna"  chai  --protein "$PROTEIN" --rna "$RNA" --msa "$MSA"

# ── Test 6: Protein + SMILES (Boltz only) ───────────────────────────
echo "=============================================="
echo " Test 6: Protein + SMILES"
echo "=============================================="
run_test "boltz_protein_smiles" boltz --protein "$PROTEIN" --smiles "CCO" --msa "$MSA"

# ── Test 7: Expected rejections ─────────────────────────────────────
echo "=============================================="
echo " Test 7: Expected rejections (should fail)"
echo "=============================================="
run_test "chai_reject_smiles"      chai      --protein "$PROTEIN" --smiles "CCO"
run_test "alphafold_reject_ligand" alphafold --protein "$PROTEIN" --ligand ATP --af2-data-dir /databases --af2-db-preset reduced_dbs
run_test "esmfold_reject_dna"      esmfold   --protein "$PROTEIN" --dna "$DNA"

echo ""
echo "=============================================="
echo " SUMMARY"
echo "=============================================="
echo "PASS: $PASS  (expected: 16)"
echo "FAIL: $FAIL  (expected: 3 rejections)"
if [ -n "$ERRORS" ]; then
    echo -e "\nFailed tests:\n$ERRORS"
fi
echo "Finished: $(date)"
