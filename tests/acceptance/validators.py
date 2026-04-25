"""Output validation for acceptance tests.

Python replacement for validate_output.sh -- validates the normalized
prediction output directory structure.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema

SCHEMA_DIR = Path(__file__).parent / "schemas"


@dataclass
class ValidationResult:
    """Accumulated pass/fail/warn results from output validation."""

    checks: list[tuple[str, str, str]] = field(default_factory=list)  # (status, name, detail)

    def passed(self, name: str, detail: str = ""):
        self.checks.append(("PASS", name, detail))

    def failed(self, name: str, detail: str = ""):
        self.checks.append(("FAIL", name, detail))

    def warned(self, name: str, detail: str = ""):
        self.checks.append(("WARN", name, detail))

    @property
    def ok(self) -> bool:
        return all(s != "FAIL" for s, _, _ in self.checks)

    @property
    def failures(self) -> list[tuple[str, str]]:
        return [(n, d) for s, n, d in self.checks if s == "FAIL"]

    @property
    def warnings(self) -> list[tuple[str, str]]:
        return [(n, d) for s, n, d in self.checks if s == "WARN"]

    def summary(self) -> str:
        p = sum(1 for s, _, _ in self.checks if s == "PASS")
        f = sum(1 for s, _, _ in self.checks if s == "FAIL")
        w = sum(1 for s, _, _ in self.checks if s == "WARN")
        lines = [f"Validation: {p} passed, {f} failed, {w} warnings"]
        for status, name, detail in self.checks:
            suffix = f" -- {detail}" if detail else ""
            lines.append(f"  [{status}] {name}{suffix}")
        return "\n".join(lines)


def _load_schema(name: str) -> dict:
    schema_path = SCHEMA_DIR / name
    with open(schema_path) as f:
        return json.load(f)


def validate_output_directory(
    output_dir: Path | str,
    *,
    tool: str | None = None,
    expected_residues: int | None = None,
    with_report: bool = False,
) -> ValidationResult:
    """Validate a normalized prediction output directory.

    Args:
        output_dir: Path to the output directory.
        tool: Expected tool name in metadata.json (optional).
        expected_residues: Expected length of per_residue_plddt array (optional).
        with_report: Also validate report.html presence.

    Returns:
        ValidationResult with all checks.
    """
    result = ValidationResult()
    output_dir = Path(output_dir)

    if not output_dir.is_dir():
        result.failed("output_dir_exists", f"Not a directory: {output_dir}")
        return result
    result.passed("output_dir_exists")

    # --- model_1.pdb ---
    pdb = output_dir / "model_1.pdb"
    if pdb.exists():
        size = pdb.stat().st_size
        if size < 100:
            result.failed("model_pdb_size", f"Too small: {size} bytes")
        else:
            result.passed("model_pdb_size", f"{size} bytes")

        content = pdb.read_text()
        atom_count = sum(1 for line in content.splitlines() if line.startswith("ATOM"))
        if atom_count == 0:
            result.failed("model_pdb_atoms", "No ATOM records found")
        else:
            result.passed("model_pdb_atoms", f"{atom_count} ATOM records")
    else:
        result.failed("model_pdb_exists", "model_1.pdb not found")

    # --- model_1.cif ---
    cif = output_dir / "model_1.cif"
    if cif.exists():
        size = cif.stat().st_size
        if size < 100:
            result.failed("model_cif_size", f"Too small: {size} bytes")
        else:
            result.passed("model_cif_size", f"{size} bytes")
    else:
        result.warned("model_cif_exists", "model_1.cif not found (optional)")

    # --- confidence.json ---
    conf_path = output_dir / "confidence.json"
    if conf_path.exists():
        try:
            with open(conf_path) as f:
                conf_data = json.load(f)

            schema = _load_schema("confidence.schema.json")
            jsonschema.validate(conf_data, schema)
            result.passed("confidence_schema", "Validates against JSON schema")

            plddt = conf_data.get("plddt_mean")
            if plddt is not None:
                result.passed("confidence_plddt", f"pLDDT mean = {plddt:.2f}")

            residues = conf_data.get("per_residue_plddt", [])
            if expected_residues is not None and len(residues) != expected_residues:
                result.failed(
                    "confidence_residue_count",
                    f"Expected {expected_residues}, got {len(residues)}",
                )
            elif len(residues) > 0:
                result.passed("confidence_residue_count", f"{len(residues)} residues")

            atoms = conf_data.get("per_atom_plddt")
            if atoms is not None:
                if len(atoms) < len(residues):
                    result.failed(
                        "confidence_atom_count",
                        f"per_atom_plddt ({len(atoms)}) shorter than per_residue_plddt ({len(residues)})",
                    )
                else:
                    ratio = len(atoms) / len(residues) if residues else 0
                    result.passed(
                        "confidence_atom_count",
                        f"{len(atoms)} atoms ({ratio:.1f} atoms/residue)",
                    )

        except json.JSONDecodeError as e:
            result.failed("confidence_json_parse", str(e))
        except jsonschema.ValidationError as e:
            result.failed("confidence_schema", e.message)
    else:
        result.failed("confidence_exists", "confidence.json not found")

    # --- metadata.json ---
    meta_path = output_dir / "metadata.json"
    if meta_path.exists():
        try:
            with open(meta_path) as f:
                meta_data = json.load(f)

            schema = _load_schema("metadata.schema.json")
            jsonschema.validate(meta_data, schema)
            result.passed("metadata_schema", "Validates against JSON schema")

            if tool and meta_data.get("tool") != tool:
                result.failed(
                    "metadata_tool",
                    f"Expected '{tool}', got '{meta_data.get('tool')}'",
                )
            elif meta_data.get("tool"):
                result.passed("metadata_tool", meta_data["tool"])

            runtime = meta_data.get("runtime_seconds")
            if runtime is not None and runtime > 0:
                result.passed("metadata_runtime", f"{runtime:.1f}s")
            elif runtime is not None:
                result.warned("metadata_runtime", f"Unexpected runtime: {runtime}")

        except json.JSONDecodeError as e:
            result.failed("metadata_json_parse", str(e))
        except jsonschema.ValidationError as e:
            result.failed("metadata_schema", e.message)
    else:
        result.failed("metadata_exists", "metadata.json not found")

    # --- raw_output/ ---
    raw_dirs = [output_dir / "raw_output", output_dir / "raw"]
    raw_found = False
    for raw in raw_dirs:
        if raw.is_dir() and any(raw.iterdir()):
            result.passed("raw_output_exists", str(raw.name))
            raw_found = True
            break
    if not raw_found:
        result.warned("raw_output_exists", "No raw_output/ or raw/ directory found")

    # --- report.html (optional) ---
    if with_report:
        report = output_dir / "report" / "report.html"
        if not report.exists():
            report = output_dir / "report.html"
        if report.exists():
            size = report.stat().st_size
            if size < 10_000:
                result.warned("report_size", f"Report seems small: {size} bytes")
            else:
                result.passed("report_size", f"{size} bytes")
            content = report.read_text(errors="replace")[:500]
            if "<html" in content.lower():
                result.passed("report_html_valid", "Contains <html> tag")
            else:
                result.warned("report_html_valid", "No <html> tag found")
        else:
            result.failed("report_exists", "report.html not found")

    return result


def assert_valid_output(output_dir: Path | str, **kwargs) -> ValidationResult:
    """Validate output directory and raise AssertionError on failure."""
    result = validate_output_directory(output_dir, **kwargs)
    if not result.ok:
        failures = "\n".join(f"  - {n}: {d}" for n, d in result.failures)
        raise AssertionError(f"Output validation failed:\n{failures}\n\n{result.summary()}")
    return result


# ---------------------------------------------------------------------------
# results.json (summary + sha256 manifest) -- written by predict_structure.results
# ---------------------------------------------------------------------------


def _sha256(path: Path, buf_size: int = 64 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(buf_size):
            h.update(chunk)
    return h.hexdigest()


def validate_results_json(output_dir: Path | str) -> ValidationResult:
    """Validate results.json against schema + verify sha256 manifest matches.

    Asserts:
      - File exists at output_dir/results.json
      - JSON validates against tests/acceptance/schemas/results.schema.json
      - Each outputs[*] entry's sha256 + size match the on-disk file
      - raw_dir entry has size=null + sha256=null
      - results.json itself is NOT in the manifest (self-reference would
        break hash stability)
    """
    output_dir = Path(output_dir)
    result = ValidationResult()

    results_path = output_dir / "results.json"
    if not results_path.is_file():
        result.failed("results_exists", f"{results_path} not found")
        return result

    try:
        data = json.loads(results_path.read_text())
    except json.JSONDecodeError as e:
        result.failed("results_json_parse", str(e))
        return result
    result.passed("results_exists")

    try:
        schema = _load_schema("results.schema.json")
        jsonschema.validate(data, schema)
        result.passed("results_schema")
    except FileNotFoundError:
        result.warned("results_schema", "results.schema.json not present")
    except jsonschema.ValidationError as e:
        result.failed("results_schema", e.message)

    paths_seen: set[str] = set()
    for entry in data.get("outputs", []):
        rel = entry["path"]
        paths_seen.add(rel)
        if rel == "results.json":
            result.failed("results_self_reference", "manifest lists itself")
            continue
        if entry["role"] == "raw_dir":
            if entry["size"] is not None or entry["sha256"] is not None:
                result.failed("raw_dir_entry",
                              f"{rel} should have null size+sha256")
            continue
        target = output_dir / rel
        if not target.is_file():
            result.failed("manifest_file_missing",
                          f"{rel} listed but missing on disk")
            continue
        actual_size = target.stat().st_size
        if entry["size"] != actual_size:
            result.failed("manifest_size",
                          f"{rel}: declared {entry['size']}, actual {actual_size}")
            continue
        actual_hash = _sha256(target)
        if entry["sha256"] != actual_hash:
            result.failed("manifest_sha256",
                          f"{rel}: declared {entry['sha256'][:12]}..., "
                          f"actual {actual_hash[:12]}...")
            continue
    if paths_seen:
        result.passed("manifest_files", f"{len(paths_seen)} entries verified")

    return result


def assert_valid_results_json(output_dir: Path | str) -> ValidationResult:
    """Validate results.json and raise AssertionError on failure."""
    result = validate_results_json(output_dir)
    if not result.ok:
        failures = "\n".join(f"  - {n}: {d}" for n, d in result.failures)
        raise AssertionError(
            f"results.json validation failed:\n{failures}\n\n{result.summary()}"
        )
    return result
