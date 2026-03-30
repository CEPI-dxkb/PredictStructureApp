#!/usr/bin/env bash
# =============================================================================
# CWL Integration Test Suite — Round 2
# =============================================================================
# Runs all CWL tool and workflow tests via GoWe cwl-runner and cwltool.
# Produces a machine-readable results file and a human-readable summary.
#
# Usage:
#   ./tests/run_cwl_tests.sh                  # run all tests
#   ./tests/run_cwl_tests.sh --phase 1        # pre-flight + print-command only
#   ./tests/run_cwl_tests.sh --phase 2        # execution tests only
#   ./tests/run_cwl_tests.sh --phase 3        # cross-runner verification only
#   ./tests/run_cwl_tests.sh --skip-slow      # skip AlphaFold/auto (long-running)
#   ./tests/run_cwl_tests.sh --outdir /path   # override output directory
#
# Environment variables (override defaults):
#   CWL_RUNNER     GoWe binary            (default: /scout/Experiments/GoWe/bin/cwl-runner)
#   IMAGE_DIR      Apptainer SIF directory (default: /scout/containers)
#   BIND_PATHS     Apptainer bind mounts   (default: /scout:/scout,/local_databases:/local_databases)
#   OUTDIR_BASE    Base output directory    (default: /scout/tmp/cwl-tests-<date>)
# =============================================================================
set -uo pipefail

# ─── Defaults ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
CWL_RUNNER="${CWL_RUNNER:-/scout/Experiments/GoWe/bin/cwl-runner}"
IMAGE_DIR="${IMAGE_DIR:-/scout/containers}"
BIND_PATHS="${BIND_PATHS:-/scout:/scout,/local_databases:/local_databases}"
DATE_TAG="$(date +%y%m%d.%H%M)"
OUTDIR_BASE="${OUTDIR_BASE:-/scout/tmp/cwl-tests-${DATE_TAG}}"

PHASE=""
SKIP_SLOW=false

# ─── Parse arguments ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase)   PHASE="$2"; shift 2 ;;
        --skip-slow) SKIP_SLOW=true; shift ;;
        --outdir)  OUTDIR_BASE="$2"; shift 2 ;;
        -h|--help)
            awk '/^# =====/{ c++; if(c==3) exit } c>=1{ sub(/^# ?/,""); print }' "$0"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ─── Directories ─────────────────────────────────────────────────────────────
RESULTS_DIR="${OUTDIR_BASE}/results"
mkdir -p "$RESULTS_DIR"

CWL_TOOLS="${REPO_DIR}/cwl/tools"
CWL_WORKFLOWS="${REPO_DIR}/cwl/workflows"
CWL_JOBS="${REPO_DIR}/cwl/jobs"

# ─── Counters ────────────────────────────────────────────────────────────────
TOTAL=0; PASS=0; FAIL=0; SKIP=0; XFAIL=0
declare -A RESULTS  # test_id -> PASS|FAIL|SKIP|XFAIL

# ─── Colours (if terminal) ──────────────────────────────────────────────────
if [[ -t 1 ]]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; CYAN=''; BOLD=''; RESET=''
fi

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG="${OUTDIR_BASE}/test.log"
exec > >(tee -a "$LOG") 2>&1

log()  { echo -e "${CYAN}[$(date '+%H:%M:%S')]${RESET} $*"; }
pass() { echo -e "  ${GREEN}PASS${RESET} $1"; }
fail() { echo -e "  ${RED}FAIL${RESET} $1"; }
skip() { echo -e "  ${YELLOW}SKIP${RESET} $1"; }
section() { echo ""; echo -e "${BOLD}════════════════════════════════════════════════════════════${RESET}"; echo -e "${BOLD}  $1${RESET}"; echo -e "${BOLD}════════════════════════════════════════════════════════════${RESET}"; }

# ─── Result recording ────────────────────────────────────────────────────────
record_result() {
    # Usage: record_result TEST_ID PASS|FAIL|XFAIL|SKIP [message]
    local id="$1" status="$2" msg="${3:-}"
    RESULTS[$id]="$status"
    TOTAL=$((TOTAL + 1))
    case "$status" in
        PASS)  PASS=$((PASS + 1)); pass "$id${msg:+: $msg}" ;;
        FAIL)  FAIL=$((FAIL + 1)); fail "$id${msg:+: $msg}" ;;
        XFAIL) XFAIL=$((XFAIL + 1)); echo -e "  ${YELLOW}XFAIL${RESET} $id${msg:+: $msg}" ;;
        SKIP)  SKIP=$((SKIP + 1)); skip "$id${msg:+: $msg}" ;;
    esac
    # Append to TSV results file
    echo -e "${id}\t${status}\t${msg}" >> "${RESULTS_DIR}/results.tsv"
}

# ─── Helper: run GoWe print-command ──────────────────────────────────────────
run_print_command() {
    # Usage: run_print_command TEST_ID CWL_FILE JOB_FILE [EXPECTED_PATTERN]
    local id="$1" cwl="$2" job="$3" pattern="${4:-}"
    local outfile="${RESULTS_DIR}/${id}.print-command.txt"

    log "print-command: $id"
    local start=$SECONDS
    "$CWL_RUNNER" print-command "$cwl" "$job" > "$outfile" 2>&1
    local rc=$?
    local elapsed=$((SECONDS - start))

    echo -e "${id}\t${rc}\t${elapsed}" >> "${RESULTS_DIR}/timing.tsv"

    if [[ $rc -ne 0 ]]; then
        record_result "$id" FAIL "exit code $rc"
        return 1
    fi

    if [[ -n "$pattern" ]]; then
        if grep -qE -- "$pattern" "$outfile"; then
            record_result "$id" PASS
        else
            record_result "$id" FAIL "pattern '$pattern' not found"
            return 1
        fi
    else
        record_result "$id" PASS
    fi
}

# ─── Helper: run GoWe execution ─────────────────────────────────────────────
run_execution() {
    # Usage: run_execution TEST_ID CWL_FILE JOB_FILE GPU_ID [EXPECT_FAIL]
    local id="$1" cwl="$2" job="$3" gpu="${4:-none}" expect_fail="${5:-false}"
    local outdir="${OUTDIR_BASE}/${id}"
    local logfile="${RESULTS_DIR}/${id}.execution.log"

    rm -rf "$outdir"
    mkdir -p "$outdir"

    local env_vars=(
        SINGULARITY_BIND="$BIND_PATHS"
    )
    if [[ "$gpu" != "none" ]]; then
        env_vars+=(APPTAINER_NV=1)
        env_vars+=(APPTAINERENV_CUDA_VISIBLE_DEVICES="$gpu")
    fi

    log "execute: $id (GPU=${gpu})"
    local start=$SECONDS

    env "${env_vars[@]}" \
        "$CWL_RUNNER" --image-dir "$IMAGE_DIR" --outdir "$outdir" \
        "$cwl" "$job" > "$logfile" 2>&1
    local rc=$?
    local elapsed=$((SECONDS - start))

    echo "exit_code=$rc elapsed=${elapsed}s" >> "$logfile"

    # Record timing
    echo -e "${id}\t${rc}\t${elapsed}" >> "${RESULTS_DIR}/timing.tsv"

    if [[ "$expect_fail" == "true" ]]; then
        if [[ $rc -ne 0 ]]; then
            record_result "$id" XFAIL "exit $rc in ${elapsed}s (expected failure)"
        else
            record_result "$id" FAIL "expected failure but got exit 0 in ${elapsed}s"
        fi
    else
        if [[ $rc -eq 0 ]]; then
            record_result "$id" PASS "exit 0 in ${elapsed}s"
        else
            record_result "$id" FAIL "exit $rc in ${elapsed}s"
        fi
    fi
    return $rc
}

# ─── Helper: run GoWe execution in background ───────────────────────────────
BG_PIDS=()
BG_IDS=()

run_execution_bg() {
    # Same args as run_execution, but runs in background
    local id="$1"
    run_execution "$@" &
    local pid=$!
    BG_PIDS+=("$pid")
    BG_IDS+=("$id")
    log "  → background PID=$pid"
}

wait_bg_all() {
    log "Waiting for ${#BG_PIDS[@]} background jobs..."
    for i in "${!BG_PIDS[@]}"; do
        wait "${BG_PIDS[$i]}" 2>/dev/null
        log "  → ${BG_IDS[$i]} finished"
    done
    # Reconcile: background subshells wrote to results.tsv but couldn't
    # update the in-memory RESULTS array. Re-read any missing entries.
    while IFS=$'\t' read -r tid status msg; do
        [[ "$tid" == "test_id" ]] && continue
        if [[ -z "${RESULTS[$tid]+x}" ]]; then
            RESULTS[$tid]="$status"
            TOTAL=$((TOTAL + 1))
            case "$status" in
                PASS)  PASS=$((PASS + 1)) ;;
                FAIL)  FAIL=$((FAIL + 1)) ;;
                XFAIL) XFAIL=$((XFAIL + 1)) ;;
                SKIP)  SKIP=$((SKIP + 1)) ;;
            esac
            log "  → reconciled $tid: $status"
        fi
    done < "${RESULTS_DIR}/results.tsv"
    BG_PIDS=()
    BG_IDS=()
}

# ─── Helper: run cwltool execution ──────────────────────────────────────────
run_cwltool() {
    # Usage: run_cwltool TEST_ID CWL_FILE JOB_FILE GPU_ID
    local id="$1" cwl="$2" job="$3" gpu="${4:-none}"
    local outdir="${OUTDIR_BASE}/${id}"
    local logfile="${RESULTS_DIR}/${id}.cwltool.log"

    rm -rf "$outdir"
    mkdir -p "$outdir"

    local env_vars=(
        SINGULARITY_BIND="$BIND_PATHS"
    )
    if [[ "$gpu" != "none" ]]; then
        env_vars+=(APPTAINER_NV=1)
        env_vars+=(APPTAINERENV_CUDA_VISIBLE_DEVICES="$gpu")
    fi

    log "cwltool: $id (GPU=${gpu})"
    local start=$SECONDS

    env "${env_vars[@]}" \
        conda run -n predict-structure cwltool --singularity \
        --outdir "$outdir" "$cwl" "$job" > "$logfile" 2>&1
    local rc=$?
    local elapsed=$((SECONDS - start))

    echo "exit_code=$rc elapsed=${elapsed}s" >> "$logfile"
    echo -e "${id}\t${rc}\t${elapsed}" >> "${RESULTS_DIR}/timing.tsv"

    if [[ $rc -eq 0 ]]; then
        record_result "$id" PASS "exit 0 in ${elapsed}s"
    else
        record_result "$id" FAIL "exit $rc in ${elapsed}s"
    fi
    return $rc
}

# ─── Helper: validate output directory ───────────────────────────────────────
validate_outputs() {
    # Usage: validate_outputs TEST_ID CHECK [CHECK ...]
    # Checks: metadata, confidence, pdb, cif, report, raw
    local id="$1"; shift
    local outdir="${OUTDIR_BASE}/${id}"
    local ok=true

    for check in "$@"; do
        case "$check" in
            metadata)
                local f
                f=$(find "$outdir" -name metadata.json -print -quit 2>/dev/null)
                if [[ -n "$f" && -s "$f" ]]; then
                    local tool
                    tool=$(python3 -c "import json,sys; print(json.load(open('$f'))['tool'])" 2>/dev/null)
                    echo "  metadata: tool=$tool" >> "${RESULTS_DIR}/${id}.validation.txt"
                else
                    echo "  metadata: MISSING" >> "${RESULTS_DIR}/${id}.validation.txt"
                    ok=false
                fi
                ;;
            confidence)
                local f
                f=$(find "$outdir" -name confidence.json -print -quit 2>/dev/null)
                if [[ -n "$f" && -s "$f" ]]; then
                    local plddt
                    plddt=$(python3 -c "import json,sys; print(json.load(open('$f'))['plddt_mean'])" 2>/dev/null)
                    echo "  confidence: plddt_mean=$plddt" >> "${RESULTS_DIR}/${id}.validation.txt"
                else
                    echo "  confidence: MISSING" >> "${RESULTS_DIR}/${id}.validation.txt"
                    ok=false
                fi
                ;;
            pdb)
                local f
                f=$(find "$outdir" -name "*.pdb" -size +1k -print -quit 2>/dev/null)
                if [[ -n "$f" ]]; then
                    local sz
                    sz=$(stat -c%s "$f")
                    echo "  pdb: $(basename "$f") ${sz} bytes" >> "${RESULTS_DIR}/${id}.validation.txt"
                else
                    echo "  pdb: MISSING or empty" >> "${RESULTS_DIR}/${id}.validation.txt"
                    ok=false
                fi
                ;;
            cif)
                local f
                f=$(find "$outdir" -name "*.cif" -size +1k -print -quit 2>/dev/null)
                if [[ -n "$f" ]]; then
                    local sz
                    sz=$(stat -c%s "$f")
                    echo "  cif: $(basename "$f") ${sz} bytes" >> "${RESULTS_DIR}/${id}.validation.txt"
                else
                    echo "  cif: MISSING or empty" >> "${RESULTS_DIR}/${id}.validation.txt"
                    ok=false
                fi
                ;;
            report)
                local f
                f=$(find "$outdir" -name "*.html" -size +10k -print -quit 2>/dev/null)
                if [[ -n "$f" ]]; then
                    local sz
                    sz=$(stat -c%s "$f")
                    local valid_html
                    valid_html=$(head -1 "$f" | grep -c "<!DOCTYPE\|<html")
                    echo "  report: $(basename "$f") ${sz} bytes valid_html=${valid_html}" >> "${RESULTS_DIR}/${id}.validation.txt"
                else
                    echo "  report: MISSING or < 10KB" >> "${RESULTS_DIR}/${id}.validation.txt"
                    ok=false
                fi
                ;;
        esac
    done

    if $ok; then
        echo "  validation: ALL CHECKS PASSED" >> "${RESULTS_DIR}/${id}.validation.txt"
    else
        echo "  validation: SOME CHECKS FAILED" >> "${RESULTS_DIR}/${id}.validation.txt"
    fi
}

# =============================================================================
# Phase 1: Pre-flight + print-command
# =============================================================================
run_phase_1() {
    section "PHASE 1: Pre-flight Checks"

    # F1: Container SIF files
    log "F1: Container SIF files"
    local prod_sif="${IMAGE_DIR}/folding_prod.sif"
    local compare_sif="${IMAGE_DIR}/folding_compare_260329.sif"
    if [[ -f "$prod_sif" ]]; then
        record_result F1a PASS "$(ls -lh "$prod_sif" | awk '{print $5, $NF}')"
    else
        record_result F1a FAIL "$prod_sif not found"
    fi
    if [[ -f "$compare_sif" ]]; then
        record_result F1b PASS "$(ls -lh "$compare_sif" | awk '{print $5, $NF}')"
    else
        record_result F1b FAIL "$compare_sif not found"
    fi

    # F2: Container provenance
    log "F2: Container checksums"
    md5sum "$prod_sif" "$compare_sif" > "${RESULTS_DIR}/F2.checksums.txt" 2>&1
    record_result F2 PASS "checksums recorded"

    # F3: GPU availability
    log "F3: GPU availability"
    local gpu_count
    gpu_count=$(nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null | wc -l)
    if [[ "$gpu_count" -ge 1 ]]; then
        nvidia-smi --query-gpu=index,name,memory.used --format=csv,noheader \
            > "${RESULTS_DIR}/F3.gpus.txt" 2>&1
        record_result F3 PASS "${gpu_count} GPU(s)"
    else
        record_result F3 FAIL "no GPUs found"
    fi

    # F4: GoWe version
    log "F4: GoWe version"
    local gowe_version
    gowe_version=$("$CWL_RUNNER" --version 2>&1)
    echo "$gowe_version" > "${RESULTS_DIR}/F4.version.txt"
    record_result F4 PASS "$gowe_version"

    # F5: AlphaFold databases
    log "F5: AlphaFold databases"
    local af_db="/local_databases/alphafold/databases"
    if [[ -d "$af_db" ]]; then
        ls "$af_db" > "${RESULTS_DIR}/F5.databases.txt" 2>&1
        record_result F5 PASS "$(ls "$af_db" | wc -l) directories"
    else
        record_result F5 FAIL "$af_db not found"
    fi

    # F6: Unit tests
    log "F6: Unit tests"
    local test_output="${RESULTS_DIR}/F6.pytest.txt"
    conda run -n predict-structure pytest "${REPO_DIR}/tests/" \
        --ignore="${REPO_DIR}/tests/test_integration.py" -v --tb=short \
        > "$test_output" 2>&1
    local test_rc=$?
    if [[ $test_rc -eq 0 ]]; then
        local test_summary
        test_summary=$(tail -1 "$test_output")
        record_result F6 PASS "$test_summary"
    else
        record_result F6 FAIL "pytest exit $test_rc"
    fi

    # ── A1–A4: Per-tool print-command ─────────────────────────────────────
    section "A1–A4: Per-Tool CWL print-command"

    run_print_command A1 \
        "${CWL_TOOLS}/esmfold.cwl" "${CWL_JOBS}/crambin-esmfold.yml" \
        "esm-fold-hf"

    run_print_command A2 \
        "${CWL_TOOLS}/boltz.cwl" "${CWL_JOBS}/crambin-boltz.yml" \
        "boltz predict"

    run_print_command A3 \
        "${CWL_TOOLS}/chai.cwl" "${CWL_JOBS}/crambin-chai.yml" \
        "chai-lab fold"

    run_print_command A4 \
        "${CWL_TOOLS}/alphafold.cwl" "${CWL_JOBS}/crambin-alphafold.yml" \
        "run_alphafold.py"

    # ── B2: predict-structure.cwl new parameter sweep ─────────────────────
    section "B2: predict-structure.cwl Parameter Sweep"

    run_print_command B2a \
        "${CWL_TOOLS}/predict-structure.cwl" "${CWL_JOBS}/test-predict-esmfold-cpu.yml" \
        "esmfold --device cpu"

    run_print_command B2b \
        "${CWL_TOOLS}/predict-structure.cwl" "${CWL_JOBS}/test-predict-multichain.yml" \
        "--protein.*--protein"

    # ── C2: Auto mode print-command ───────────────────────────────────────
    section "C2: Auto Mode print-command"

    for job in "${CWL_JOBS}"/test-auto-*.yml; do
        local name
        name=$(basename "$job" .yml | sed 's/test-//')
        run_print_command "C2-${name}" \
            "${CWL_TOOLS}/predict-structure.cwl" "$job" \
            "predict-structure auto"
    done

    # ── D8: Workflow print-command ────────────────────────────────────────
    section "D8: Workflow print-command"

    run_print_command D8a \
        "${CWL_WORKFLOWS}/esmfold-report.cwl" "${CWL_JOBS}/crambin-esmfold-report.yml" \
        "predict-structure"

    run_print_command D8b \
        "${CWL_WORKFLOWS}/predict-report.cwl" "${CWL_JOBS}/crambin-predict-esmfold-report.yml" \
        "predict-structure esmfold"

    run_print_command D8c \
        "${CWL_WORKFLOWS}/predict-report.cwl" "${CWL_JOBS}/crambin-predict-auto-report.yml" \
        "predict-structure auto"

    run_print_command D8d \
        "${CWL_WORKFLOWS}/boltz-report.cwl" "${CWL_JOBS}/crambin-boltz-report.yml" \
        "predict-structure"

    run_print_command D8e \
        "${CWL_WORKFLOWS}/boltz-report-msa.cwl" "${CWL_JOBS}/crambin-boltz-msa-report.yml" \
        "use-msa-server"

    run_print_command D8f \
        "${CWL_WORKFLOWS}/chai-report.cwl" "${CWL_JOBS}/crambin-chai-report.yml" \
        "predict-structure"

    run_print_command D8g \
        "${CWL_WORKFLOWS}/alphafold-report.cwl" "${CWL_JOBS}/crambin-alphafold-report.yml" \
        "predict-structure"
}

# =============================================================================
# Phase 2: Execution tests (GPU required)
# =============================================================================
run_phase_2() {
    section "PHASE 2: Execution Tests"

    # ── A5: ESMFold per-tool (fast, CPU) ──────────────────────────────────
    log "A5: ESMFold per-tool"
    run_execution A5 \
        "${CWL_TOOLS}/esmfold.cwl" "${CWL_JOBS}/crambin-esmfold.yml" \
        none
    validate_outputs A5 pdb

    # ── A6: Boltz per-tool (GPU) ──────────────────────────────────────────
    log "A6: Boltz per-tool"
    run_execution A6 \
        "${CWL_TOOLS}/boltz.cwl" "${CWL_JOBS}/crambin-boltz.yml" \
        1
    validate_outputs A6 cif

    # ── A7: Chai per-tool (GPU) ───────────────────────────────────────────
    log "A7: Chai per-tool"
    run_execution A7 \
        "${CWL_TOOLS}/chai.cwl" "${CWL_JOBS}/crambin-chai.yml" \
        2
    validate_outputs A7 cif

    # ── A8: AlphaFold per-tool (GPU, long) ────────────────────────────────
    # Known issue: amber relax fails on H200 (OpenMM CUDA platform bug).
    # Model inference succeeds on GPU. Reports FAIL until relax is fixed.
    if $SKIP_SLOW; then
        record_result A8 SKIP "skipped (--skip-slow)"
    else
        log "A8: AlphaFold per-tool (long-running)"
        run_execution_bg A8 \
            "${CWL_TOOLS}/alphafold.cwl" "${CWL_JOBS}/crambin-alphafold.yml" \
            3
    fi

    # ── C3a: Auto mode execution (long) ───────────────────────────────────
    if $SKIP_SLOW; then
        record_result C3a SKIP "skipped (--skip-slow)"
    else
        log "C3a: Auto mode (protein+GPU)"
        run_execution_bg C3a \
            "${CWL_TOOLS}/predict-structure.cwl" "${CWL_JOBS}/test-auto-protein-gpu.yml" \
            4
    fi

    # ── C3b: Auto mode error test (no GPU needed) ─────────────────────────
    log "C3b: Auto mode error (expect failure)"
    run_execution C3b \
        "${CWL_TOOLS}/predict-structure.cwl" "${CWL_JOBS}/test-auto-multientity-nomsa.yml" \
        none true

    # ── D1: esmfold-report workflow ───────────────────────────────────────
    log "D1: esmfold-report workflow"
    run_execution D1 \
        "${CWL_WORKFLOWS}/esmfold-report.cwl" "${CWL_JOBS}/crambin-esmfold-report.yml" \
        5
    validate_outputs D1 metadata confidence pdb report

    # ── D2: predict-report (esmfold) ──────────────────────────────────────
    log "D2: predict-report (esmfold)"
    run_execution D2 \
        "${CWL_WORKFLOWS}/predict-report.cwl" "${CWL_JOBS}/crambin-predict-esmfold-report.yml" \
        6
    validate_outputs D2 metadata confidence pdb report

    # ── D3: predict-report (auto, long) ───────────────────────────────────
    if $SKIP_SLOW; then
        record_result D3 SKIP "skipped (--skip-slow)"
    else
        log "D3: predict-report (auto)"
        run_execution_bg D3 \
            "${CWL_WORKFLOWS}/predict-report.cwl" "${CWL_JOBS}/crambin-predict-auto-report.yml" \
            7
    fi

    # ── D4: boltz-report (expected fail — MSA required) ───────────────────
    log "D4: boltz-report (expect fail — MSA required)"
    run_execution D4 \
        "${CWL_WORKFLOWS}/boltz-report.cwl" "${CWL_JOBS}/crambin-boltz-report.yml" \
        1 true

    # ── D5: boltz-report-msa ──────────────────────────────────────────────
    log "D5: boltz-report-msa workflow"
    run_execution D5 \
        "${CWL_WORKFLOWS}/boltz-report-msa.cwl" "${CWL_JOBS}/crambin-boltz-msa-report.yml" \
        1
    validate_outputs D5 metadata confidence pdb report

    # ── D6: chai-report ───────────────────────────────────────────────────
    log "D6: chai-report workflow"
    run_execution D6 \
        "${CWL_WORKFLOWS}/chai-report.cwl" "${CWL_JOBS}/crambin-chai-report.yml" \
        2
    validate_outputs D6 metadata confidence pdb report

    # ── D7: alphafold-report (expected fail — GoWe bugs) ──────────────────
    log "D7: alphafold-report (expect fail — GoWe Directory/newline bugs)"
    run_execution D7 \
        "${CWL_WORKFLOWS}/alphafold-report.cwl" "${CWL_JOBS}/crambin-alphafold-report.yml" \
        4 true

    # ── Wait for background jobs ──────────────────────────────────────────
    if [[ ${#BG_PIDS[@]} -gt 0 ]]; then
        wait_bg_all

        # Validate background job outputs
        if ! $SKIP_SLOW; then
            validate_outputs C3a metadata
            validate_outputs A8 pdb  # may fail (amber relax)
            validate_outputs D3 metadata confidence pdb report
        fi
    fi
}

# =============================================================================
# Phase 3: Cross-runner verification
# =============================================================================
run_phase_3() {
    section "PHASE 3: Cross-Runner Verification"

    if $SKIP_SLOW; then
        record_result E-D7 SKIP "skipped (--skip-slow)"
        return
    fi

    # ── E-D7: alphafold-report via cwltool ────────────────────────────────
    log "E-D7: alphafold-report via cwltool (verifies GoWe bugs #7,#8)"
    run_cwltool E-D7 \
        "${CWL_WORKFLOWS}/alphafold-report.cwl" "${CWL_JOBS}/crambin-alphafold-report.yml" \
        6
    validate_outputs E-D7 metadata confidence pdb report
}

# =============================================================================
# Summary
# =============================================================================
print_summary() {
    section "TEST SUMMARY"

    echo ""
    echo "Results directory: ${OUTDIR_BASE}"
    echo "Log file:          ${LOG}"
    echo ""

    # Print all results
    printf "%-20s %s\n" "TEST" "RESULT"
    printf "%-20s %s\n" "----" "------"
    # Sort by test ID
    for id in $(echo "${!RESULTS[@]}" | tr ' ' '\n' | sort); do
        local status="${RESULTS[$id]}"
        case "$status" in
            PASS)  printf "%-20s ${GREEN}%s${RESET}\n" "$id" "$status" ;;
            FAIL)  printf "%-20s ${RED}%s${RESET}\n" "$id" "$status" ;;
            XFAIL) printf "%-20s ${YELLOW}%s${RESET}\n" "$id" "$status" ;;
            SKIP)  printf "%-20s ${YELLOW}%s${RESET}\n" "$id" "$status" ;;
        esac
    done

    echo ""
    echo "────────────────────────────────────────────"
    echo -e "Total: ${TOTAL}  ${GREEN}Pass: ${PASS}${RESET}  ${RED}Fail: ${FAIL}${RESET}  ${YELLOW}XFail: ${XFAIL}  Skip: ${SKIP}${RESET}"
    echo "────────────────────────────────────────────"

    # Timing summary for execution tests
    local timing_file="${RESULTS_DIR}/timing.tsv"
    if [[ -f "$timing_file" ]] && [[ $(wc -l < "$timing_file") -gt 1 ]]; then
        echo ""
        echo "Timing (execution tests):"
        printf "  %-20s %6s %10s\n" "TEST" "EXIT" "TIME"
        printf "  %-20s %6s %10s\n" "----" "----" "----"
        tail -n +2 "$timing_file" | while IFS=$'\t' read -r tid rc elapsed; do
            [[ -z "$elapsed" || "$elapsed" == "0" ]] && continue
            local mins=$((elapsed / 60))
            local secs=$((elapsed % 60))
            if [[ $mins -gt 0 ]]; then
                printf "  %-20s %6s %7dm%02ds\n" "$tid" "$rc" "$mins" "$secs"
            else
                printf "  %-20s %6s %10ss\n" "$tid" "$rc" "$elapsed"
            fi
        done
    fi
    echo ""

    # Exit code: fail if any unexpected failures
    if [[ $FAIL -gt 0 ]]; then
        echo -e "${RED}Some tests failed unexpectedly.${RESET}"
        return 1
    else
        echo -e "${GREEN}All tests passed (or expected to fail).${RESET}"
        return 0
    fi
}

# =============================================================================
# Report generation
# =============================================================================
generate_report() {
    local report="${OUTDIR_BASE}/report.md"
    log "Generating report: $report"

    cat > "$report" <<HEADER
# CWL Test Report

**Date:** $(date '+%Y-%m-%d %H:%M')
**Output:** \`${OUTDIR_BASE}\`

---

## Environment

| Item | Value |
|------|-------|
HEADER

    # Environment from results files
    [[ -f "${RESULTS_DIR}/F4.version.txt" ]] && \
        echo "| GoWe | $(cat "${RESULTS_DIR}/F4.version.txt") |" >> "$report"
    [[ -f "${RESULTS_DIR}/F3.gpus.txt" ]] && \
        echo "| GPUs | $(head -1 "${RESULTS_DIR}/F3.gpus.txt" | cut -d, -f2) × $(wc -l < "${RESULTS_DIR}/F3.gpus.txt") |" >> "$report"
    [[ -f "${RESULTS_DIR}/F2.checksums.txt" ]] && {
        while read -r sum path; do
            echo "| $(basename "$path") | \`${sum}\` |" >> "$report"
        done < "${RESULTS_DIR}/F2.checksums.txt"
    }
    echo "" >> "$report"

    # Results table
    cat >> "$report" <<'TABLE_HEADER'
## Results

| Test | Status | Details |
|------|--------|---------|
TABLE_HEADER

    tail -n +2 "${RESULTS_DIR}/results.tsv" | while IFS=$'\t' read -r tid status msg; do
        local icon
        case "$status" in
            PASS)  icon="PASS" ;;
            FAIL)  icon="**FAIL**" ;;
            XFAIL) icon="XFAIL" ;;
            SKIP)  icon="SKIP" ;;
            *)     icon="$status" ;;
        esac
        echo "| $tid | $icon | $msg |" >> "$report"
    done

    echo "" >> "$report"

    # Timing table
    cat >> "$report" <<'TIMING_HEADER'
## Timing

| Test | Exit | Elapsed |
|------|------|---------|
TIMING_HEADER

    tail -n +2 "${RESULTS_DIR}/timing.tsv" | while IFS=$'\t' read -r tid rc elapsed; do
        [[ -z "$elapsed" || "$elapsed" == "0" ]] && continue
        local mins=$((elapsed / 60))
        local secs=$((elapsed % 60))
        local fmt
        if [[ $mins -gt 0 ]]; then
            fmt="${mins}m${secs}s"
        else
            fmt="${elapsed}s"
        fi
        echo "| $tid | $rc | $fmt |" >> "$report"
    done

    echo "" >> "$report"

    # Validation details
    local has_validations=false
    for vfile in "${RESULTS_DIR}"/*.validation.txt; do
        [[ -f "$vfile" ]] || continue
        has_validations=true
        break
    done

    if $has_validations; then
        cat >> "$report" <<'VAL_HEADER'
## Output Validation

VAL_HEADER
        for vfile in "${RESULTS_DIR}"/*.validation.txt; do
            [[ -f "$vfile" ]] || continue
            local tid
            tid=$(basename "$vfile" .validation.txt)
            echo "**${tid}:**" >> "$report"
            echo '```' >> "$report"
            cat "$vfile" >> "$report"
            echo '```' >> "$report"
            echo "" >> "$report"
        done
    fi

    # Summary
    cat >> "$report" <<SUMMARY

---

## Summary

**Total: ${TOTAL} | Pass: ${PASS} | Fail: ${FAIL} | XFail: ${XFAIL} | Skip: ${SKIP}**
SUMMARY

    log "Report written to: $report"
}

# =============================================================================
# Main
# =============================================================================
main() {
    log "CWL Test Suite starting"
    log "Output: ${OUTDIR_BASE}"
    log "GoWe:   ${CWL_RUNNER}"
    log "Images: ${IMAGE_DIR}"
    echo ""

    # Initialize results file
    echo -e "test_id\tstatus\tmessage" > "${RESULTS_DIR}/results.tsv"
    echo -e "test_id\texit_code\telapsed_s" > "${RESULTS_DIR}/timing.tsv"

    case "$PHASE" in
        1)  run_phase_1 ;;
        2)  run_phase_2 ;;
        3)  run_phase_3 ;;
        "")
            run_phase_1
            run_phase_2
            run_phase_3
            ;;
        *)  echo "Unknown phase: $PHASE"; exit 1 ;;
    esac

    print_summary
    generate_report
}

cd "$REPO_DIR"
main
