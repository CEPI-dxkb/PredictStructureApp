# Output Normalization Design

How PredictStructureApp normalizes outputs from Boltz-2, OpenFold 3, Chai-1,
AlphaFold 2, and ESMFold into a uniform schema.

Audience: reviewer / computational biologist familiar with structure prediction
tools. Covers design decisions, tool-specific quirks, and where information is
preserved vs. transformed.

## 1. Unified Output Layout

Every prediction -- whether executed via the CWL workflow or the BV-BRC
app-script -- produces this identical directory:

```
output/
├── model_1.pdb               # Predicted structure (always PDB)
├── model_1.cif               # Predicted structure (always mmCIF)
├── confidence.json           # {plddt_mean, ptm, per_residue_plddt[], per_atom_plddt[]?}
├── metadata.json             # {tool, params, runtime_seconds, version, timestamp}
├── results.json              # Summary + file manifest (sha256/size) -- see §5
├── ro-crate-metadata.json    # RO-Crate 1.1 Process Run Crate provenance -- see §6
├── report/                   # Characterization report (optional, see §7)
│   ├── report.html
│   ├── report.json
│   └── report.pdf
└── raw/                      # Original tool output, unmodified
```

### Rationale

- **Both PDB and mmCIF**: Different consumers prefer different formats. PDB is
  ubiquitous; mmCIF is the standard for structures with >99,999 atoms and
  is what AF3-class tools emit natively.
- **Single model selected**: We pick the *best* sample (by tool's ranking
  metric) as `model_1`. We do not currently preserve alternate samples.
- **`results.json` at top level**: a stable, schema-validated contract for
  the *next* step in a pipeline. It denormalizes scalar metrics
  (`plddt_mean`, `ptm`) and lists every artifact with sha256 + size + role
  so downstream consumers don't have to scan the dir.
- **`ro-crate-metadata.json`**: FAIR/archival provenance surface; follows
  the Process Run Crate 0.5 profile. Best-effort -- skipped with a log
  warning if the `rocrate` package isn't installed.
- **`report/` subdir**: reports from `protein_compare characterize` move
  here so `report.json` doesn't collide with `results.json` at the top
  level. Absent if characterization was skipped or failed.
- **`raw/`**: Keeps the tool-native output for forensic/reproducibility
  use. `results.json` treats it as a single opaque entry (no sha256).

## 2. `confidence.json` Schema

```json
{
  "plddt_mean": 82.3,
  "ptm": 0.89,                          // null if tool doesn't report it
  "per_residue_plddt": [45.2, ...],     // length = N residues
  "per_atom_plddt": [45.1, 43.2, ...]   // optional, length = M atoms (M >= N)
}
```

All pLDDT values are on the **0-100 scale** regardless of the tool's native
scale. pTM is on the 0-1 scale.

JSON Schema: `tests/acceptance/schemas/confidence.schema.json`.

## 3. pLDDT Extraction Per Tool

Each tool produces pLDDT in different forms; we extract both per-residue and
(optionally) per-atom values. The canonical source for each is chosen to
preserve as much accuracy as possible.

### 3.1 Boltz-2

**Native outputs:**
- `predictions/*/plddt_*_model_0.npz` -- per-residue pLDDT (shape `(N,)`)
- `model_0.cif` -- B-factors are per-atom
- `confidence_*.json` -- summary scalars (no array)

**Our extraction:**
- `per_residue_plddt` <- NPZ array (scale 0-1 → 0-100 if needed)
- `per_atom_plddt` <- `model_1.pdb` ATOM B-factors
- `plddt_mean` <- mean of NPZ
- `ptm` <- from JSON summary

**Rationale:** NPZ is the tool's canonical per-residue source. PDB B-factors
give us true per-atom resolution.

### 3.2 OpenFold 3

**Native outputs:**
- `*_confidences.json` -- key `plddt` is **per-atom** array (shape `(M,)`)
  where M ≈ 7 × N for proteins (AF3-style atomization)
- `*_confidences_aggregated.json` -- summary scalars (`avg_plddt`, `ptm`, `iptm`, ...)
- `*_model.cif` -- B-factors are per-atom
- `*_model.pdb` (if requested) -- B-factors are per-atom

**Our extraction:**
- `per_residue_plddt` <- `model_1.pdb` **CA B-factors** (one per residue)
- `per_atom_plddt` <- `model_1.pdb` all-atom B-factors
- `plddt_mean` <- `avg_plddt` from aggregated JSON
- `ptm` <- `ptm` from aggregated JSON

**Rationale:** OpenFold 3's per-atom JSON array cannot be meaningfully
reshaped to per-residue without mapping each atom index to its residue.
The CA atom's pLDDT is the standard per-residue convention (used by
AlphaFold, ESMFold, UniProt). We verified that `model_1.pdb` encodes the
same per-atom pLDDT as the JSON (via B-factors), so both arrays come from
the same source.

**Documented upstream:** OpenFold 3 docs
[`inference.md`](https://github.com/aqlaboratory/openfold-3/blob/main/docs/source/inference.md)
state: "Per-atom confidence scores (plddt, pae, pde)" for confidences.json,
and "per-atom pLDDT in B-factor" for PDB output.

### 3.3 Chai-1

**Native outputs:**
- `pred.model_idx_*.cif` -- B-factors are per-atom
- `scores.model_idx_*.npz` -- summary scalars (`ptm`, `iptm`, `ranking_score`, ...)
- No per-residue or per-atom array in JSON/NPZ

**Our extraction:**
- `per_residue_plddt` <- `model_1.pdb` CA B-factors
- `per_atom_plddt` <- `model_1.pdb` all-atom B-factors
- `plddt_mean` <- mean of CA B-factors
- `ptm` <- from NPZ

**Rationale:** PDB is the only source of per-residue/atom pLDDT in Chai's
output, so we use CA B-factors for residue-level and all-atom for atom-level.

### 3.4 AlphaFold 2

**Native outputs:**
- `ranked_*.pdb` -- B-factors are **per-residue** (same value copied to every
  atom in a residue; AF2 doesn't atomize)
- `ranking_debug.json` -- ranking scores per model
- `result_model_*.pkl` -- internal features (we don't parse these)

**Our extraction:**
- `per_residue_plddt` <- `model_1.pdb` CA B-factors
- `per_atom_plddt` <- `model_1.pdb` all-atom B-factors (values replicated
  across a residue's atoms; no new information beyond per-residue)
- `plddt_mean` <- mean of CA B-factors; also compared against
  `ranking_debug.plddts[best_model]` as a sanity check
- `ptm` <- from pickle (if available) -- not always populated

**Rationale:** Consistent with other tools. Per-atom values for AF2 are
informational only -- they duplicate the per-residue values but keep the
array shape aligned with `model_1.pdb` ATOM records.

### 3.5 ESMFold

**Native outputs:**
- Single PDB file -- B-factors are **per-residue** (ESMFold doesn't
  atomize; values copied to all atoms in residue)
- No pTM, no confidence JSON

**Our extraction:**
- `per_residue_plddt` <- `model_1.pdb` CA B-factors (scale 0-1 → 0-100 if needed)
- `per_atom_plddt` <- `model_1.pdb` all-atom B-factors (same scaling)
- `plddt_mean` <- mean of per-residue
- `ptm` <- `null`

**Rationale:** Same as AF2. Scale conversion handles ESMFold's 0-1 output
convention.

## 4. Per-residue vs. Per-atom Trade-offs

### What we lose by converting to per-residue

For AF3-style tools (Boltz, Chai, OpenFold 3), each residue has 4-14 heavy
atoms, each with its own pLDDT. Using only the CA atom's value:
- Discards side-chain confidence (tips of long side chains often differ
  significantly from backbone)
- Matches the standard visualization convention (pLDDT on the sequence)
- Matches AF2/ESMFold/UniProt conventions (so consumers don't need
  tool-specific branching)

### What we preserve via `per_atom_plddt`

The optional `per_atom_plddt` array gives consumers the full atomic
resolution when available. Atom order matches the PDB ATOM record order so
consumers can zip it directly.

### Consumer detection of granularity

```python
import json
from Bio.PDB import PDBParser

conf = json.load(open("confidence.json"))
n_res = len(conf["per_residue_plddt"])
n_atom = len(conf.get("per_atom_plddt", []))

if n_atom == 0:
    print("Per-residue only (older output)")
elif n_atom == n_res:
    print("Only CA atoms included (unusual)")
else:
    # Check if values within a residue are identical -> AF2/ESMFold
    # Check if values within a residue differ -> Boltz/Chai/OpenFold
    ratio = n_atom / n_res
    print(f"{ratio:.1f} atoms/residue")
```

## 5. Scale Conversion

Different tools use different numeric ranges:

| Tool | Native scale | Our output |
|------|--------------|-----------|
| Boltz-2 | 0-1 or 0-100 (varies by output) | 0-100 |
| OpenFold 3 | 0-100 | 0-100 |
| Chai-1 | 0-100 | 0-100 |
| AlphaFold 2 | 0-100 | 0-100 |
| ESMFold | 0-1 | 0-100 (multiplied by 100) |

**Detection heuristic**: if `max(values) <= 1.0`, multiply by 100.

This is applied in `normalize_boltz_output` (NPZ case) and
`normalize_esmfold_output` (B-factor case).

## 6. Hetatm Handling

When extracting `per_atom_plddt`, we **skip HETATM records**:

- Ligands, waters, metals: not part of the predicted chain
- Biopython filter: `residue.id[0] != " "` (hetfield)

This keeps `per_atom_plddt` aligned with ATOM records only. Consumers
parsing `model_1.pdb` ATOM lines will get a 1:1 correspondence with the
`per_atom_plddt` array.

Edge case: for protein+ligand predictions (Boltz/Chai/OpenFold), the ligand
atoms are written as HETATM in our normalized PDB and excluded from
`per_atom_plddt`. If a consumer needs ligand confidence, they must parse
the `raw/` tool output directly.

## 7. Best-Sample Selection

When a tool produces multiple samples (Boltz `--diffusion_samples`,
Chai `--num-diffn-samples`, OpenFold `--num-diffusion-samples`), we pick
the single best and write it as `model_1.pdb`:

| Tool | Ranking signal |
|------|----------------|
| Boltz-2 | `model_0` (tool outputs in rank order) |
| Chai-1 | `model_idx_0` (tool outputs in rank order) |
| OpenFold 3 | `sample_ranking_score` from `*_confidences_aggregated.json` |
| AlphaFold 2 | `ranking_debug.order[0]` -> prefers `ranked_0.pdb`, then relaxed, then unrelaxed |
| ESMFold | Deterministic; single output |

Alternate samples are in `raw/` for inspection.

## 8. Known Issues & Limitations

### 8.1 Per-atom values for AF2/ESMFold are replicated

AF2 and ESMFold don't produce true per-atom pLDDT. The `per_atom_plddt`
array duplicates the per-residue value across each residue's atoms. This is
cosmetic (no new information) but keeps the schema uniform.

### 8.2 Ligand pLDDT not in `per_atom_plddt`

See section 6. If ligand confidence is needed, parse the tool's raw output.

### 8.3 Multi-chain handling

For multi-chain predictions (multimer), `per_residue_plddt` concatenates
all chains in the order they appear in the PDB. We do not currently emit
per-chain boundaries in `confidence.json`. Consumers can recover chain
boundaries by parsing `model_1.pdb` headers or the ATOM chain_id column.

### 8.4 Alternate samples discarded

We select the best model only. Users who want all samples must run with
`--num-samples N` and inspect `raw/`.

### 8.5 Confidence metrics beyond pLDDT and pTM

Tool-specific metrics (PAE, PDE, iPTM, chain_ptm, ranking_score, etc.) are
**not** in the unified schema. They are preserved in `raw/` and consumed
by downstream reporters (e.g. `protein_compare characterize --pae ...`).

## 9. Validation

### Unit tests (`tests/test_normalizers.py`)

Mock inputs for each tool, assert:
- PDB and CIF exist
- `confidence.json` matches schema
- `plddt_mean`, `ptm`, `per_residue_plddt` populated correctly
- `per_atom_plddt` optional -- absent by default, present when passed
- Length invariant: `len(per_atom_plddt) >= len(per_residue_plddt)`

### Acceptance tests (`tests/acceptance/validators.py`)

For real tool runs, `validate_output_directory()` checks:
- Schema validation (JSON Schema draft 2020-12)
- pLDDT values in 0-100 range
- Per-residue count matches expected for test fixtures (e.g. crambin = 46)
- Per-atom count >= per-residue count when present
- Reports atoms/residue ratio for diagnostic visibility

## 10. Summary Table for Reviewers

| Decision | Alternatives considered | Rationale |
|----------|------------------------|-----------|
| CA B-factor for `per_residue_plddt` | Mean over residue's atom pLDDTs | Standard convention across AF2/ESMFold/UniProt; reviewers expect CA values |
| Both PDB and mmCIF | One format only | Different consumers; ESMFold only emits PDB, OpenFold prefers mmCIF |
| Always scale to 0-100 | Keep native scale | Mixing scales confuses downstream; 0-100 is the norm |
| Optional `per_atom_plddt` | Always include, or omit for AF2/ESMFold | Uniform schema when present, backwards compat when absent; replicated values for AF2/ESMFold are honest (match PDB) |
| Skip HETATM | Include all atoms | Ligand confidence is metadata, not chain confidence |
| Single best model as `model_1` | Write all samples | Consumers want one answer; alternates in `raw/` |
| JSON Schema validation | Free-form | Catches regressions, schema-first design |

## 5. `results.json` -- Summary + File Manifest

Written by `predict_structure.results.write_results_json` after
normalization. Denormalizes canonical scalars from `metadata.json` /
`confidence.json` and adds a sha256/size manifest of every artifact.

```json
{
  "schema_version": "1.0",
  "tool": "boltz",
  "version": "0.2.0",
  "tool_version": "2.1.1",
  "status": "success",
  "timestamp": "2026-04-24T12:34:56+00:00",
  "runtime_seconds": 842.3,
  "inputs": [{"kind": "protein", "source": "input.fasta"}],
  "command": ["predict-structure", "boltz", "--protein", "input.fasta", "-o", "."],
  "container_image": "folding_prod.sif",
  "backend": "subprocess",
  "metrics": {
    "plddt_mean": 82.14,
    "ptm": 0.78,
    "num_residues": 312,
    "num_atoms": 2487
  },
  "outputs": [
    {"path": "model_1.pdb", "size": 24518, "sha256": "...", "role": "structure"},
    {"path": "confidence.json", "size": 8412, "sha256": "...", "role": "confidence"},
    {"path": "report/report.html", "size": 91240, "sha256": "...", "role": "report"},
    {"path": "raw", "size": null, "sha256": null, "role": "raw_dir"}
  ]
}
```

JSON Schema: `tests/acceptance/schemas/results.schema.json`.

### Design

- **Denormalized but non-duplicating**: scalars (`plddt_mean`, `ptm`) are
  copied for quick access; arrays (`per_residue_plddt`, `per_atom_plddt`)
  stay canonical in `confidence.json`.
- **Stable path ordering**: `outputs` is sorted by `path` so diffs across
  runs are reviewable.
- **`raw/` as opaque entry**: we don't hash tool-native files (they're
  large and tool-specific); consumers who need them dig in.
- **Self-exclusion**: `results.json` does not list itself (would force
  circular-hash logic).
- **`role` taxonomy**: `structure`, `confidence`, `metadata`, `summary`,
  `provenance`, `report`, `raw_dir`, `auxiliary`.

## 6. `ro-crate-metadata.json` -- Process Run Crate Provenance

Written best-effort by `predict_structure.results.write_ro_crate` via the
`rocrate` Python package. Skipped (with a log warning) if the package is
not installed; install via `pip install predict-structure[provenance]`.

The crate follows the RO-Crate 1.1 + Workflow Run Crate **Process Run
Crate 0.5** profile:

- Root `Dataset` -- naming, description, publication date.
- `SoftwareApplication` for `predict-structure` (this package) and for
  the underlying tool (Boltz/Chai/OpenFold/AlphaFold/ESMFold).
- `CreateAction` entity -- describes the actual run: `instrument` = the
  tool, `agent` = `predict-structure`, `object` = input files, `result` =
  output files (every entry from `results.json.outputs`),
  `actionStatus` = Completed/Failed, a textual `description` holding the
  command line, and a `containerImage` property with the SIF path/digest.
- `File` entities for every output with `contentSize` + `sha256`.

Populated entirely from `results.json` so the provenance record stays
consistent with the manifest. Opt out via `--no-emit-rocrate`.

## 7. Report Relocation (`report/` subdir)

`protein_compare characterize -o <prefix>` emits `<prefix>.html`,
`<prefix>.json`, `<prefix>.pdf`. With the unified layout, any top-level
`report.{html,json,pdf}` is relocated into `output/report/` by
`predict_structure.normalizers.move_reports_to_subdir`. This:

- Prevents a `report.json` vs `results.json` collision at the top level.
- Keeps the top level uniformly machine-readable (only JSON + structure
  files + the `raw/` + `report/` dirs).
- Matches the CWL multi-tool workflow convention of grouping auxiliary
  artifacts.

The BV-BRC app-script calls `predict-structure finalize-results <dir>`
after `run_report()` so the relocation and manifest regeneration happen
together and the `results.json` outputs array contains the freshly
generated reports.

## 8. CLI Integration

- **Prediction subcommands** (`predict-structure boltz`, `chai`, etc.):
  `--emit-rocrate/--no-emit-rocrate` controls whether the RO-Crate is
  written. Default: emit.
- **`predict-structure finalize-results <dir>`**: regenerates
  `results.json` + RO-Crate on an existing output dir. Used by the Perl
  service script after report generation.
- **`predict-structure aggregate-results --in a.json b.json -o out.json`**:
  combines per-tool `results.json` files into a multi-tool summary.
  Used by the CWL multi-tool workflow.

## 11. Code Pointers

| File | Purpose |
|------|---------|
| `predict_structure/normalizers.py` | All tool-specific normalization + shared helpers |
| `predict_structure/normalizers.py:write_confidence_json` | Schema-aligned JSON emitter |
| `predict_structure/normalizers.py:move_reports_to_subdir` | Relocate report.* into report/ |
| `predict_structure/normalizers.py:_extract_ca_bfactors` | Per-residue pLDDT extraction |
| `predict_structure/normalizers.py:_extract_all_atom_bfactors` | Per-atom pLDDT extraction (skips HETATM) |
| `predict_structure/results.py:write_results_json` | Summary manifest writer |
| `predict_structure/results.py:write_ro_crate` | RO-Crate Process Run Crate writer |
| `predict_structure/cli.py:_finalize_output` | Post-normalization hook (meta → reports → results → crate) |
| `predict_structure/cli.py:finalize_results` / `aggregate_results` | Standalone provenance subcommands |
| `tests/acceptance/schemas/confidence.schema.json` | Confidence JSON Schema |
| `tests/acceptance/schemas/results.schema.json` | Results JSON Schema |
| `tests/acceptance/validators.py` | Acceptance-test validation |
| `tests/test_normalizers.py` | Unit tests for each tool's normalizer |
| `tests/test_results.py` | Unit tests for results.json + RO-Crate writers |
