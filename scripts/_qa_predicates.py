"""Predicate evaluators for the Phase 3 service-script Q/A format.

Used by `scripts/run_qa_case.py`. Pure-Python, stdlib + jsonschema only.

Format: `<case>.expected.json` is a sibling of `<case>.json` (the
service-script params input). The runner runs the app-script with the
input, then evaluates each predicate against the produced output dir.

See `test_data/service_params/README.md` for the full spec.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class PredicateFailure(Exception):
    """Raised by a predicate when the actual value doesn't match expected."""

    def __init__(self, predicate: str, expected: Any, actual: Any, where: str = ""):
        suffix = f" at {where}" if where else ""
        super().__init__(
            f"{predicate} failed{suffix}: expected={expected!r} actual={actual!r}"
        )
        self.predicate = predicate
        self.expected = expected
        self.actual = actual
        self.where = where


# ---------------------------------------------------------------------------
# Atom evaluators -- each takes a single concrete value + an atom dict
# ---------------------------------------------------------------------------


def _eval_atom(atom: Any, actual: Any, where: str) -> None:
    """Evaluate a single constraint atom against `actual`. Raises on mismatch."""
    if atom == "null":
        if actual is not None:
            raise PredicateFailure("null", "null", actual, where)
        return

    if not isinstance(atom, dict):
        if actual != atom:
            raise PredicateFailure("equals", atom, actual, where)
        return

    if "equals" in atom:
        if actual != atom["equals"]:
            raise PredicateFailure("equals", atom["equals"], actual, where)

    if "min" in atom or "max" in atom:
        if not isinstance(actual, (int, float)):
            raise PredicateFailure("numeric", "number", actual, where)
        if "min" in atom and actual < atom["min"]:
            raise PredicateFailure("min", atom["min"], actual, where)
        if "max" in atom and actual > atom["max"]:
            raise PredicateFailure("max", atom["max"], actual, where)

    if "length" in atom:
        try:
            n = len(actual)
        except TypeError as exc:
            raise PredicateFailure("length", atom["length"], actual, where) from exc
        if n != atom["length"]:
            raise PredicateFailure("length", atom["length"], n, where)

    if "matches" in atom:
        if not isinstance(actual, str):
            raise PredicateFailure("matches", atom["matches"], actual, where)
        if not re.search(atom["matches"], actual):
            raise PredicateFailure("matches", atom["matches"], actual, where)

    if "oneOf" in atom:
        for sub in atom["oneOf"]:
            try:
                _eval_atom(sub, actual, where)
                return
            except PredicateFailure:
                continue
        raise PredicateFailure("oneOf", atom["oneOf"], actual, where)


# ---------------------------------------------------------------------------
# Field-path resolution
# ---------------------------------------------------------------------------


def _resolve(data: Any, path: str) -> list[tuple[str, Any]]:
    """Resolve a dotted field path with optional `[*]` array fan-out.

    Returns list of (concrete_path, value) so each match can be reported
    individually on failure.

    Examples:
        "plddt_mean"               -> [("plddt_mean", 82.14)]
        "per_residue_plddt"        -> [("per_residue_plddt", [...])]
        "per_residue_plddt[*]"     -> [("per_residue_plddt[0]", v0), ...]
        "outputs[*].sha256"        -> [("outputs[0].sha256", "..."), ...]
    """
    parts = re.split(r"\.", path) if path else []
    nodes: list[tuple[str, Any]] = [("", data)]
    for part in parts:
        next_nodes: list[tuple[str, Any]] = []
        m = re.match(r"^([^\[]+)(\[\*\])?$", part)
        if not m:
            raise ValueError(f"unsupported path segment: {part}")
        key, fanout = m.group(1), m.group(2)
        for trail, node in nodes:
            sep = "" if not trail else "."
            if not isinstance(node, dict) or key not in node:
                raise PredicateFailure(
                    "path_exists", path, f"missing key {key}", trail or "<root>"
                )
            child = node[key]
            new_trail = f"{trail}{sep}{key}"
            if fanout:
                if not isinstance(child, list):
                    raise PredicateFailure(
                        "fanout", "array", type(child).__name__, new_trail
                    )
                for i, item in enumerate(child):
                    next_nodes.append((f"{new_trail}[{i}]", item))
            else:
                next_nodes.append((new_trail, child))
        nodes = next_nodes
    return nodes


# ---------------------------------------------------------------------------
# Top-level predicate runners. Each returns list of failure dicts for the
# external framework's result JSON.
# ---------------------------------------------------------------------------


def check_files_exist(out_dir: Path, paths: list[str]) -> list[dict]:
    failures = []
    for p in paths:
        if not (out_dir / p).exists():
            failures.append({"predicate": "files_exist", "path": p, "actual": "missing"})
    return failures


def check_files_forbidden(out_dir: Path, paths: list[str]) -> list[dict]:
    failures = []
    for p in paths:
        if (out_dir / p).exists():
            failures.append({"predicate": "files_forbidden", "path": p, "actual": "present"})
    return failures


def check_schemas(out_dir: Path, schema_dir: Path, mapping: dict) -> list[dict]:
    import jsonschema

    failures = []
    for path, schema_rel in mapping.items():
        target = out_dir / path
        if not target.is_file():
            failures.append({"predicate": "schemas", "path": path, "actual": "missing"})
            continue
        schema_path = schema_dir / Path(schema_rel).name
        try:
            schema = json.loads(schema_path.read_text())
            data = json.loads(target.read_text())
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as exc:
            failures.append({
                "predicate": "schemas", "path": path,
                "actual": exc.message,
            })
        except (OSError, json.JSONDecodeError) as exc:
            failures.append({
                "predicate": "schemas", "path": path, "actual": str(exc),
            })
    return failures


def check_json_constraints(out_dir: Path, mapping: dict) -> list[dict]:
    failures = []
    for path, constraints in mapping.items():
        target = out_dir / path
        if not target.is_file():
            failures.append({
                "predicate": "json_constraints", "path": path, "actual": "missing"
            })
            continue
        try:
            data = json.loads(target.read_text())
        except json.JSONDecodeError as exc:
            failures.append({
                "predicate": "json_constraints", "path": path, "actual": str(exc),
            })
            continue
        for field_path, atom in constraints.items():
            try:
                for trail, value in _resolve(data, field_path):
                    _eval_atom(atom, value, f"{path}::{trail}")
            except PredicateFailure as exc:
                failures.append({
                    "predicate": exc.predicate, "path": path,
                    "field": exc.where, "expected": exc.expected,
                    "actual": exc.actual,
                })
    return failures


def check_pdb_constraints(out_dir: Path, mapping: dict) -> list[dict]:
    failures = []
    for path, c in mapping.items():
        target = out_dir / path
        if not target.is_file():
            failures.append({"predicate": "pdb_constraints", "path": path, "actual": "missing"})
            continue
        size = target.stat().st_size
        if "min_size_bytes" in c and size < c["min_size_bytes"]:
            failures.append({
                "predicate": "pdb_min_size", "path": path,
                "expected": c["min_size_bytes"], "actual": size,
            })
        text = target.read_text(errors="replace")
        atom_count = sum(1 for line in text.splitlines() if line.startswith("ATOM"))
        if "min_atoms" in c and atom_count < c["min_atoms"]:
            failures.append({
                "predicate": "pdb_min_atoms", "path": path,
                "expected": c["min_atoms"], "actual": atom_count,
            })
        if "first_record_type" in c:
            for line in text.splitlines():
                if line.startswith(("ATOM", "HETATM", "HEADER", "TITLE", "REMARK", "MODEL")):
                    if not line.startswith(c["first_record_type"]):
                        failures.append({
                            "predicate": "pdb_first_record", "path": path,
                            "expected": c["first_record_type"],
                            "actual": line.split()[0] if line.strip() else "<empty>",
                        })
                    break
    return failures


def check_text(actual: str, expected: list[str], predicate_name: str) -> list[dict]:
    failures = []
    for needle in expected:
        if needle not in actual:
            failures.append({
                "predicate": predicate_name,
                "expected": needle,
                "actual": "not present",
            })
    return failures


# ---------------------------------------------------------------------------
# Master entry point used by the runner
# ---------------------------------------------------------------------------


def evaluate(case: dict, out_dir: Path, schema_dir: Path,
             stdout: str = "", stderr: str = "",
             exit_code: int = 0) -> dict:
    """Run all predicates from `case["expected"]` and return a result dict.

    Returns:
        {
            "passed": bool,
            "failures": [...],
            "summary": {"checked": N, "failed": M},
        }
    """
    expected = case.get("expected", {})
    failures: list[dict] = []
    checked = 0

    if "exit_code" in expected:
        checked += 1
        if exit_code != expected["exit_code"]:
            failures.append({
                "predicate": "exit_code",
                "expected": expected["exit_code"],
                "actual": exit_code,
            })

    if "files_exist" in expected:
        checked += len(expected["files_exist"])
        failures.extend(check_files_exist(out_dir, expected["files_exist"]))

    if "files_forbidden" in expected:
        checked += len(expected["files_forbidden"])
        failures.extend(check_files_forbidden(out_dir, expected["files_forbidden"]))

    if "schemas" in expected:
        checked += len(expected["schemas"])
        failures.extend(check_schemas(out_dir, schema_dir, expected["schemas"]))

    if "json_constraints" in expected:
        checked += sum(len(v) for v in expected["json_constraints"].values())
        failures.extend(check_json_constraints(out_dir, expected["json_constraints"]))

    if "pdb_constraints" in expected:
        checked += len(expected["pdb_constraints"])
        failures.extend(check_pdb_constraints(out_dir, expected["pdb_constraints"]))

    if "stdout_contains" in expected:
        checked += len(expected["stdout_contains"])
        failures.extend(check_text(stdout, expected["stdout_contains"], "stdout_contains"))

    if "stderr_contains" in expected:
        checked += len(expected["stderr_contains"])
        failures.extend(check_text(stderr, expected["stderr_contains"], "stderr_contains"))

    return {
        "passed": not failures,
        "failures": failures,
        "summary": {"checked": checked, "failed": len(failures)},
    }
