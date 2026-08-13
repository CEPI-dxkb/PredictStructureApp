#!/usr/bin/env python3
"""Submit and monitor PredictStructure jobs via the BV-BRC API.

Usage:
    # Run the 24-case test matrix
    python scripts/submit_api_tests.py matrix

    # Submit 10 jobs for a single tool (host saturation)
    python scripts/submit_api_tests.py saturate esmfold
    python scripts/submit_api_tests.py saturate boltz
    python scripts/submit_api_tests.py saturate openfold
    python scripts/submit_api_tests.py saturate chai
    python scripts/submit_api_tests.py saturate alphafold

    # Poll status for previously submitted jobs
    python scripts/submit_api_tests.py status 22200613 22200616 22200617

    # Poll all jobs from a results JSON
    python scripts/submit_api_tests.py status --file results.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

API_URL = "https://p3.theseed.org/services/app_service"
BASE_URL = "https://alpha.bv-brc.org"
WS_INPUTS = "/awilke@bvbrc/home/AppTests/inputs"
WS_OUTPUT = "/awilke@bvbrc/home/AppTests"
MATRIX_PATH = Path(__file__).parent.parent / "test_data" / "service_params" / "api_test_matrix.json"

# Fields from the test matrix that become app params
APP_PARAM_KEYS = {
    "tool", "input_file", "dna_file", "rna_file", "msa_file",
    "ligand", "smiles", "output_format", "debug",
    "num_samples", "num_recycles", "seed",
}


def load_token() -> str:
    token_path = Path.home() / ".patric_token"
    if not token_path.exists():
        sys.exit(f"Auth token not found at {token_path}")
    return token_path.read_text().strip()


def rpc(token: str, method: str, params: list, timeout: int = 120) -> dict:
    """Send a JSON-RPC request to the BV-BRC AppService."""
    resp = requests.post(
        API_URL,
        headers={
            "Content-Type": "application/jsonrpc+json",
            "Authorization": token,
        },
        json={"id": 1, "method": f"AppService.{method}", "params": params, "jsonrpc": "2.0"},
        timeout=timeout,
    )
    if resp.status_code >= 400:
        # raise_for_status() reports only the status line and URL, discarding
        # the body — which is where a preflight rejection's message lives. The
        # matrix checks rejections by their reason, so the body must survive.
        raise RuntimeError(
            f"HTTP {resp.status_code} from {API_URL}: {resp.text.strip()[:2000]}"
        )
    data = resp.json()
    if "error" in data:
        # RuntimeError, not sys.exit: the caller catches Exception per job, and
        # SystemExit would abort the whole run and lose already-submitted jobs.
        raise RuntimeError(f"API error: {data['error']}")
    return data


#: start_app2 runs preflight inside the app's container on the scheduler node.
#: The first submission after a container switch blocks while a ~32 GB SIF is
#: staged into the cluster's container cache — measured at 464s on 2026-08-13.
#: A short timeout turns that routine cold start into a spurious failure.
SUBMIT_TIMEOUT = 900


def submit_job(token: str, app_params: dict, output_file: str) -> int:
    """Submit a single PredictStructure job. Returns task ID."""
    params = {**app_params, "output_path": WS_OUTPUT, "output_file": output_file}
    data = rpc(token, "start_app2", ["PredictStructure", params, {"base_url": BASE_URL}],
               timeout=SUBMIT_TIMEOUT)
    return data["result"][0]["id"]


def poll_tasks(token: str, task_ids: set[int], interval: int = 30, timeout: int = 7200) -> dict[int, dict]:
    """Poll until all tasks reach a terminal state. Returns {id: task_dict}."""
    terminal = {"completed", "failed"}
    results = {}
    deadline = time.time() + timeout

    while time.time() < deadline:
        data = rpc(token, "enumerate_tasks", [0, 100], timeout=30)
        for t in data["result"][0]:
            if t["id"] in task_ids:
                results[t["id"]] = t
        pending = task_ids - {tid for tid, t in results.items() if t["status"] in terminal}
        if not pending:
            break
        done = len(task_ids) - len(pending)
        print(f"  [{datetime.now().strftime('%H:%M:%S')}] {done}/{len(task_ids)} done, {len(pending)} pending", flush=True)
        time.sleep(interval)

    return results


def query_hosts(token: str, task_ids: list[int]) -> dict[int, str]:
    """Get hostname for each task."""
    hosts = {}
    for tid in task_ids:
        try:
            data = rpc(token, "query_task_details", [str(tid)], timeout=15)
            hostname = data["result"][0].get("hostname", "--")
            # Shorten FQDN
            if hostname and "." in hostname:
                hostname = hostname.split(".")[0]
            hosts[tid] = hostname or "--"
        except Exception:
            hosts[tid] = "--"
    return hosts


def build_matrix_jobs(tests: list[dict]) -> tuple[list[tuple[str, dict]], dict[str, dict]]:
    """Convert test matrix entries to (label, app_params) pairs.

    Also returns per-label expectations so the report can judge the outcome
    instead of assuming every submitted job was meant to run.
    """
    jobs = []
    expectations = {}
    for test in tests:
        label = f"{test['id']}_{test['name']}"
        params = {}
        for key in APP_PARAM_KEYS:
            if key in test:
                val = test[key]
                # Resolve workspace paths for file fields
                if key.endswith("_file") and isinstance(val, str) and not val.startswith("/"):
                    val = f"{WS_INPUTS}/{val}"
                params[key] = val
        jobs.append((label, params))
        expectations[label] = {
            "expected": test.get("expected", "pass"),
            "expected_error": test.get("expected_error"),
        }
    return jobs, expectations


def build_saturate_jobs(tool: str, n: int = 10) -> list[tuple[str, dict]]:
    """Build n identical jobs for a tool to test host scheduling."""
    base = {"tool": tool, "input_file": f"{WS_INPUTS}/simple_protein.fasta"}
    # Add MSA for tools that need it
    if tool in ("boltz", "openfold", "chai"):
        base["msa_file"] = f"{WS_INPUTS}/crambin.a3m"
    jobs = []
    for i in range(1, n + 1):
        jobs.append((f"{tool}_{i:02d}", dict(base)))
    return jobs


def run_submit(token: str, jobs: list[tuple[str, dict]], tag: str, poll: bool = True,
               expectations: dict[str, dict] | None = None) -> list[dict]:
    """Submit jobs, optionally poll, report results."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    expectations = expectations or {}
    submitted = []

    print(f"\nSubmitting {len(jobs)} jobs (tag: {tag}_{ts})...\n")
    for label, params in jobs:
        output_file = f"{tag}_{label}_{ts}"
        expect = expectations.get(label, {})
        try:
            tid = submit_job(token, params, output_file)
            print(f"  {tid}  {label}")
            submitted.append({"task_id": tid, "label": label, "params": params,
                              "output_file": output_file, **expect})
        except Exception as e:
            # Not necessarily a problem: expected=reject cases are supposed to
            # be refused right here, before anything is scheduled (#84).
            marker = "reject" if expect.get("expected") == "reject" else "FAIL"
            print(f"  {marker}  {label}: {e}")
            submitted.append({"task_id": None, "label": label, "error": str(e), **expect})

    task_ids = {s["task_id"] for s in submitted if s["task_id"]}
    print(f"\n{len(task_ids)} jobs submitted.")

    if not poll or not task_ids:
        # Still report: a reject-only run has no task IDs by design, and that is
        # exactly the run whose verdicts we need to see.
        save_results(submitted, {}, {}, tag, ts)
        print_report(submitted)
        return submitted

    print(f"\nPolling for completion...\n")
    results = poll_tasks(token, task_ids)
    hosts = query_hosts(token, list(task_ids))

    # Merge results
    for s in submitted:
        tid = s.get("task_id")
        if tid and tid in results:
            s["status"] = results[tid]["status"]
            s["elapsed"] = results[tid].get("elapsed_time", "--")
            s["host"] = hosts.get(tid, "--")
        elif tid:
            s["status"] = "unknown"

    save_results(submitted, results, hosts, tag, ts)
    print_report(submitted)
    return submitted


def save_results(submitted, results, hosts, tag, ts):
    """Save results JSON to docs/test-reports/."""
    out_dir = Path(__file__).parent.parent / "docs" / "test-reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tag}_{ts}.json"
    out_path.write_text(json.dumps(submitted, indent=2, default=str))
    print(f"\nResults saved to {out_path}")


def judge(s: dict) -> tuple[bool | None, str]:
    """Decide whether one result matches what the matrix expected.

    Three expectations:
      pass    the job runs to completion
      fail    the job is scheduled, then fails on the worker
      reject  the job is refused at submit time, before SLURM allocates
              anything — so no task ID is the *correct* outcome (#84)
    """
    expected = s.get("expected", "pass")
    error = s.get("error")
    status = s.get("status")

    # Submitted but never polled (--no-poll): there is no outcome to judge yet.
    if not error and not status:
        return None, "submitted"

    if expected == "reject":
        if not error:
            return False, "scheduled!"
        want = s.get("expected_error")
        if want and want.lower() not in error.lower():
            return False, "wrong reason"
        return True, "rejected"

    if error:
        return False, "submit err"
    if expected == "fail":
        return (status == "failed"), (status or "unknown")
    return (status == "completed"), (status or "unknown")


def print_report(submitted: list[dict]):
    """Print results table."""
    print(f"\n{'Task ID':>10}  {'Label':<25}  {'Status':<12}  {'Want':<7}  {'Verdict':<8}  {'Elapsed':>10}  {'Host':<12}")
    print("-" * 95)
    pass_count = fail_count = 0
    for s in submitted:
        tid = str(s.get("task_id") or "--")
        status = s.get("status") or s.get("error", "error")
        elapsed = s.get("elapsed") or "--"
        host = s.get("host") or "--"
        label = s["label"]
        ok, detail = judge(s)
        if ok is None:
            status = "submitted"
        # Truncate long error messages
        if len(status) > 12:
            status = status[:11] + "…"
        verdict = "—" if ok is None else ("PASS" if ok else "FAIL")
        print(f"{tid:>10}  {label:<25}  {status:<12}  {s.get('expected','pass'):<7}  "
              f"{verdict:<8}  {elapsed:>10}  {host:<12}")
        if ok is None:
            continue  # not polled — no verdict to count
        if ok:
            pass_count += 1
        else:
            fail_count += 1
            print(f"{'':>10}  └─ expected {s.get('expected','pass')}, got {detail}")

    print(f"\nTotal: {pass_count} pass, {fail_count} fail")

    # Host distribution
    host_counts: dict[str, int] = {}
    for s in submitted:
        h = s.get("host", "--")
        host_counts[h] = host_counts.get(h, 0) + 1
    if any(h != "--" for h in host_counts):
        print(f"\nHost distribution:")
        for h, c in sorted(host_counts.items()):
            print(f"  {h}: {c}")


def cmd_matrix(args):
    token = load_token()
    matrix = json.loads(MATRIX_PATH.read_text())
    tests = matrix["tests"]
    if args.tests:
        ids = set(args.tests.split(","))
        tests = [t for t in tests if t["id"] in ids]
    if not args.include_negative:
        tests = [t for t in tests if t.get("expected") not in ("fail", "reject")]
    if not args.include_alphafold:
        tests = [t for t in tests if t["tool"] != "alphafold"]
    jobs, expectations = build_matrix_jobs(tests)
    run_submit(token, jobs, "matrix", poll=not args.no_poll, expectations=expectations)


def cmd_saturate(args):
    token = load_token()
    jobs = build_saturate_jobs(args.tool, n=args.count)
    run_submit(token, jobs, f"sat_{args.tool}", poll=not args.no_poll)


def cmd_status(args):
    token = load_token()
    if args.file:
        data = json.loads(Path(args.file).read_text())
        task_ids = {d["task_id"] for d in data if d.get("task_id")}
    else:
        task_ids = {int(x) for x in args.task_ids}

    if not task_ids:
        sys.exit("No task IDs provided")

    results = poll_tasks(token, task_ids, interval=15, timeout=60)
    hosts = query_hosts(token, list(task_ids))

    submitted = []
    for tid in sorted(task_ids):
        r = results.get(tid, {})
        submitted.append({
            "task_id": tid,
            "label": r.get("output_file", "--"),
            "status": r.get("status", "unknown"),
            "elapsed": r.get("elapsed_time", "--"),
            "host": hosts.get(tid, "--"),
        })
    print_report(submitted)


def main():
    parser = argparse.ArgumentParser(description="BV-BRC API test runner for PredictStructure")
    sub = parser.add_subparsers(dest="command", required=True)

    p_matrix = sub.add_parser("matrix", help="Run the 24-case test matrix")
    p_matrix.add_argument("--tests", help="Comma-separated test IDs (e.g. T01,T07)")
    p_matrix.add_argument("--include-negative", action="store_true", help="Include negative test cases")
    p_matrix.add_argument("--include-alphafold", action="store_true", help="Include AlphaFold (slow)")
    p_matrix.add_argument("--no-poll", action="store_true", help="Submit only, don't wait")
    p_matrix.set_defaults(func=cmd_matrix)

    p_sat = sub.add_parser("saturate", help="Submit N jobs for one tool (host coverage)")
    p_sat.add_argument("tool", choices=["esmfold", "boltz", "openfold", "chai", "alphafold", "auto"])
    p_sat.add_argument("--count", "-n", type=int, default=10, help="Number of jobs (default: 10)")
    p_sat.add_argument("--no-poll", action="store_true", help="Submit only, don't wait")
    p_sat.set_defaults(func=cmd_saturate)

    p_status = sub.add_parser("status", help="Poll status of previously submitted jobs")
    p_status.add_argument("task_ids", nargs="*", help="Task IDs to check")
    p_status.add_argument("--file", "-f", help="Results JSON from a previous run")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
