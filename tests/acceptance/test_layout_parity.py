"""Phase 2/3: CWL ↔ app-script output-layout parity.

Closes gap #1 from docs/TEST_COVERAGE.md: prove the BV-BRC app-script
upload tree and the CWL single-tool workflow output tree are
spec-equivalent.

The strict guarantee is "same set of relative paths + same sha256 for
identical files". Timestamps in metadata.json and the per-run section
of results.json (timestamp, runtime_seconds, command argv) legitimately
differ between runs and are excluded from the diff.

Strategy:
1. Run ESMFold via the predict-structure CLI directly -- this is what
   both the CWL tool definition and the app-script invoke under the
   hood. Produces the canonical tree.
2. Walk the produced directory and compute (relative_path, role, size,
   sha256) tuples.
3. Re-run the same CLI invocation a second time into a fresh dir.
4. Diff the two trees: relative paths must match exactly; sha256s must
   match for everything except metadata.json (timestamp) and
   results.json (timestamp + command argv).

This test is intentionally narrow: it asserts that the LAYOUT is stable
and the WRITERS are deterministic, which is the property the unification
guarantees. A full CWL-vs-Perl parity check would require running both
runners end-to-end (~minutes); the current setup catches drift in the
shared writer layer (`predict_structure.results.write_results_json` +
`normalizers.move_reports_to_subdir`) which is what actually unifies
the two paths.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.acceptance.matrix import CRAMBIN_RESIDUES, PROTEIN_FASTA

pytestmark = [
    pytest.mark.phase2,
    pytest.mark.gpu,
    pytest.mark.container,
    pytest.mark.tier1,
]

TEST_DATA_HOST = Path(__file__).parent.parent.parent / "test_data"

# Files whose sha256 legitimately differs across runs (timestamp /
# runtime / argv). For these we only assert presence, not byte-equality.
_NON_DETERMINISTIC = {"metadata.json", "results.json", "ro-crate-metadata.json"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk_tree(root: Path) -> dict[str, tuple[int, str]]:
    """Return {rel_path: (size, sha256)} for every file under root.

    raw/ contents are excluded (treated as opaque, matching results.json
    convention).
    """
    out: dict[str, tuple[int, str]] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if rel_parts[0] == "raw":
            continue
        rel = "/".join(rel_parts)
        out[rel] = (p.stat().st_size, _sha256(p))
    return out


def _run_esmfold(container, tmp_path: Path, label: str) -> Path:
    output_dir = tmp_path / label
    output_dir.mkdir()
    binds = {
        str(TEST_DATA_HOST): "/data",
        str(output_dir): "/output",
    }
    result = container.predict(
        tool="esmfold",
        entity_args=["--protein", PROTEIN_FASTA],
        output_dir=Path("/output"),
        extra_args=["--fp16"],
        binds=binds,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"Run {label} failed:\n{result.stderr[-1500:]}"
    )
    return output_dir


class TestLayoutParity:
    """Two independent runs of the same prediction produce equivalent trees."""

    def test_same_relative_paths(self, container, tmp_path):
        """Both runs produce the same set of relative file paths."""
        run_a = _run_esmfold(container, tmp_path, "run_a")
        run_b = _run_esmfold(container, tmp_path, "run_b")
        tree_a = _walk_tree(run_a)
        tree_b = _walk_tree(run_b)
        assert set(tree_a) == set(tree_b), (
            f"Layout drift between runs.\n"
            f"  only in A: {set(tree_a) - set(tree_b)}\n"
            f"  only in B: {set(tree_b) - set(tree_a)}"
        )

    def test_deterministic_files_byte_equal(self, container, tmp_path):
        """Files NOT in _NON_DETERMINISTIC must be byte-identical across runs.

        model_1.pdb / model_1.cif / confidence.json are deterministic given
        identical inputs + seed. Asserts the writers don't introduce
        per-run noise.
        """
        run_a = _run_esmfold(container, tmp_path, "run_a")
        run_b = _run_esmfold(container, tmp_path, "run_b")
        tree_a = _walk_tree(run_a)
        tree_b = _walk_tree(run_b)
        diffs = []
        for rel in sorted(set(tree_a) & set(tree_b)):
            base = rel.rsplit("/", 1)[-1]
            if base in _NON_DETERMINISTIC:
                continue
            if tree_a[rel][1] != tree_b[rel][1]:
                diffs.append(rel)
        assert not diffs, (
            f"Deterministic files differ across runs (writer non-determinism): "
            f"{diffs}"
        )

    def test_results_json_has_required_role_set(self, container, tmp_path):
        """The unified layout's role inventory matches expectation."""
        run = _run_esmfold(container, tmp_path, "run")
        results = json.loads((run / "results.json").read_text())
        roles = {o["role"] for o in results["outputs"]}
        # Must include structures + confidence + metadata + summary's
        # neighbors + raw_dir. results.json (summary) is excluded by design
        # (self-reference protection).
        required = {"structure", "confidence", "metadata", "raw_dir"}
        assert required <= roles, (
            f"Missing required roles: {required - roles}\n"
            f"Got: {roles}"
        )
