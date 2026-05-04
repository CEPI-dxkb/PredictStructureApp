#!/usr/bin/env python3
"""Phase 3 service-script Q/A test runner.

Reads a `<case>.expected.json` file, executes the BV-BRC service script
inside an Apptainer SIF with the case's input params, and evaluates the
declared predicates against the produced output directory. Emits a
result JSON suitable for an external testing framework to ingest.

Format spec: see `test_data/service_params/README.md`.

Usage:
    python scripts/run_qa_case.py <case>.expected.json [--sif PATH] [--out RESULT.json]

Exit code 0 if all predicates passed, 1 if any failed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from _qa_predicates import evaluate
from instantiate_params import expand_ws_placeholders

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SIF = "/scout/containers/folding_260425.1.sif"
DEFAULT_SCHEMA_DIR = REPO / "tests" / "acceptance" / "schemas"
DEFAULT_TEST_DATA = REPO / "test_data"


def _build_apptainer_cmd(
    sif: Path,
    binds: dict[str, str],
    env: dict[str, str],
    cmd: list[str],
    *,
    gpu: bool,
    dev_overlay: bool = False,
) -> list[str]:
    argv = ["apptainer", "exec", "--pwd", "/tmp"]
    if gpu:
        argv.append("--nv")
    if dev_overlay:
        # Overlay the host's predict_structure package + service-scripts +
        # app_specs over the SIF's baked-in copies. Use this when the SIF
        # is older than the source tree and you want to validate the
        # current code, not the frozen one. Mirrors
        # tests/acceptance/conftest.py::ApptainerRunner behavior.
        env.setdefault("PYTHONPATH", "/mnt/predict-structure")
        binds[str(REPO)] = "/mnt/predict-structure"
        binds[str(REPO / "service-scripts")] = "/kb/module/service-scripts"
        binds[str(REPO / "app_specs")] = "/kb/module/app_specs"
    for k, v in env.items():
        argv.extend(["--env", f"{k}={v}"])
    for host, ctr in binds.items():
        argv.extend(["--bind", f"{host}:{ctr}"])
    argv.append(str(sif))
    argv.extend(cmd)
    return argv


def run_case(case_path: Path, sif: Path, schema_dir: Path,
             *, dev_overlay: bool = False) -> dict:
    case = json.loads(case_path.read_text())
    inp = case.get("input", {})
    expected = case.get("expected", {})

    params_basename = inp.get("params_file") or (case_path.name.replace(".expected.json", ".json"))
    params_src = case_path.parent / params_basename
    if not params_src.is_file():
        return {
            "name": case.get("name", case_path.stem),
            "passed": False,
            "failures": [{"predicate": "case_setup",
                          "expected": str(params_src),
                          "actual": "params file missing"}],
            "summary": {"checked": 0, "failed": 1},
        }

    timeout = expected.get("timeout_s", 1800)
    output_dir_in_container = expected.get("output_dir", "/output/output")

    with tempfile.TemporaryDirectory(prefix="qa-case-") as tmp:
        tmp_path = Path(tmp)
        params_dst = tmp_path / "params.json"
        # Expand ${WS_HOME} / ${WS_USER} placeholders if a token is
        # available. Without a token the placeholders pass through
        # untouched -- the workspace upload step will then fail, but
        # the prediction itself still completes.
        params_text = params_src.read_text()
        token_path = Path(os.environ.get("PATRIC_TOKEN_PATH",
                                         os.path.expanduser("~/.patric_token")))
        if "${WS_" in params_text and token_path.is_file():
            params_text = expand_ws_placeholders(
                params_text, token_path.read_text().strip()
            )
        params_dst.write_text(params_text)
        local_output = tmp_path / "output"
        local_output.mkdir()

        binds = {
            str(tmp_path): "/params",
            str(local_output): "/output",
            str(DEFAULT_TEST_DATA): "/data",
            "/local_databases": "/local_databases",
        }
        for host_rel, ctr in inp.get("binds", {}).items():
            host_abs = REPO / host_rel
            if host_abs.is_dir() or host_abs.is_file():
                binds[str(host_abs)] = ctr

        env = {
            "P3_WORKDIR": "/output",
            "HF_HOME": "/local_databases/cache",
            "TRANSFORMERS_CACHE": "/local_databases/cache",
            "TORCH_HOME": "/local_databases/cache",
            "XDG_CACHE_HOME": "/local_databases/cache/tmp",
        }
        if inp.get("needs_workspace_token"):
            token_path = os.environ.get("PATRIC_TOKEN_PATH",
                                        os.path.expanduser("~/.patric_token"))
            if not Path(token_path).is_file():
                return {
                    "name": case.get("name", case_path.stem),
                    "passed": False,
                    "failures": [{"predicate": "case_setup",
                                  "expected": "PATRIC_TOKEN_PATH",
                                  "actual": "token not found"}],
                    "summary": {"checked": 0, "failed": 1},
                }
            env["KB_AUTH_TOKEN"] = Path(token_path).read_text().strip()

        argv = _build_apptainer_cmd(
            sif, binds, env,
            cmd=[
                "perl",
                "/kb/module/service-scripts/App-PredictStructure.pl",
                "http://localhost",
                "/kb/module/app_specs/PredictStructure.json",
                "/params/params.json",
            ],
            gpu=inp.get("needs_gpu", True),
            dev_overlay=dev_overlay,
        )

        start = time.monotonic()
        try:
            proc = subprocess.run(
                argv, capture_output=True, encoding="utf-8",
                errors="replace", timeout=timeout,
            )
            exit_code = proc.returncode
            stdout, stderr = proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            return {
                "name": case.get("name", case_path.stem),
                "passed": False,
                "failures": [{"predicate": "timeout",
                              "expected": timeout,
                              "actual": "exceeded"}],
                "summary": {"checked": 1, "failed": 1},
                "elapsed_s": round(time.monotonic() - start, 2),
            }
        elapsed = round(time.monotonic() - start, 2)

        # Resolve output_dir relative to the local mount.
        if output_dir_in_container.startswith("/output"):
            tail = output_dir_in_container[len("/output"):].lstrip("/")
            actual_out = local_output / tail
        else:
            actual_out = local_output

        result = evaluate(
            case, actual_out, schema_dir,
            stdout=stdout, stderr=stderr, exit_code=exit_code,
        )
        result["name"] = case.get("name", case_path.stem)
        result["elapsed_s"] = elapsed
        result["exit_code"] = exit_code
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("case", type=Path, help=".expected.json case file")
    parser.add_argument("--sif", type=Path, default=Path(DEFAULT_SIF),
                        help=f"Apptainer SIF [default: {DEFAULT_SIF}]")
    parser.add_argument("--schema-dir", type=Path, default=DEFAULT_SCHEMA_DIR,
                        help="Directory containing JSON Schemas")
    parser.add_argument("--out", type=Path, default=None,
                        help="Write the result JSON here (default: stdout)")
    parser.add_argument("--dev-overlay", action="store_true",
                        help="Bind-mount the host's predict_structure/ + "
                             "service-scripts/ + app_specs/ over the SIF's "
                             "baked-in copies. Use when iterating on the "
                             "source faster than the SIF can be rebuilt.")
    args = parser.parse_args()

    if not args.sif.is_file():
        print(f"ERROR: SIF not found: {args.sif}", file=sys.stderr)
        return 2
    if not args.case.is_file():
        print(f"ERROR: case not found: {args.case}", file=sys.stderr)
        return 2

    result = run_case(args.case, args.sif, args.schema_dir,
                      dev_overlay=args.dev_overlay)
    payload = json.dumps(result, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload)
    else:
        print(payload)

    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
