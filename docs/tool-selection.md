# Auto Tool Selection

When the user picks `tool: auto` (the BV-BRC form default), the unified
CLI selects a concrete tool based on the entity inputs and the device.
This page documents that decision so a UI can mirror it: as the user
toggles inputs (DNA, ligand, MSA file, …), the form can show which tool
will actually run.

## Inputs that drive selection

From the basic [app spec](../app_specs/PredictStructure.json):

| Form field | Variable | Notes |
|---|---|---|
| `input_file` | `protein` | Protein FASTA. Multi-chain via multiple sequences in one file. |
| `dna_file` | `dna` | DNA FASTA. |
| `rna_file` | `rna` | RNA FASTA. |
| `ligand` | `ligand` | List of CCD codes (incl. glycans NAG / MAN). |
| `smiles` | `smiles` | List of SMILES strings. |
| `msa_file` | `msa` | Pre-computed MSA (.a3m / .sto). |
| (implicit) | `device` | The Perl AppScript sets `cpu` for ESMFold, `gpu` otherwise. The form does not expose this. |

Two **derived** signals matter:

```
non_protein  =  dna  OR  rna  OR  ligand  OR  smiles
msa_present  =  msa_file is set
```

## BV-BRC policy assumed

In the AppScript path, **external MSA servers are disabled**. The Perl
never passes `--use-msa-server`, so the `use_msa_server` arm of the
underlying selector is always false. Direct CLI / CWL invocations may
still set `--use-msa-server`; this doc focuses on the BV-BRC form.

## Decision tree

```
auto-select(protein, dna, rna, ligand, smiles, msa, device)

  ┌─ device == cpu  AND  protein-only?
  │     └─→ ESMFold
  │
  ├─ For each tool in priority order: boltz, openfold, chai, esmfold, alphafold
  │
  │     ┌─ tool ∈ {alphafold, esmfold}  AND  non_protein?
  │     │     └─ SKIP  (AF2 / ESMFold are protein-only)
  │     │
  │     ├─ tool ∈ {boltz, openfold, chai}  AND  protein  AND  NOT msa_present?
  │     │     └─ SKIP  (would otherwise produce a dummy single-sequence MSA;
  │     │              external MSA servers disabled by BV-BRC policy)
  │     │
  │     ├─ tool == alphafold  AND  AlphaFold DB dir not on disk?
  │     │     └─ SKIP
  │     │
  │     ├─ tool not installed?
  │     │     └─ SKIP
  │     │
  │     └─→ select this tool
  │
  └─ No tool eligible → ERROR ("No prediction tool found")
```

## Outcomes by input combination

Assumes all five tools are installed and AlphaFold databases are on disk
(true on the production BV-BRC SIF). `device` is taken to be `gpu` —
the Perl only auto-flips to `cpu` for ESMFold itself.

| protein | dna/rna/lig/smi | msa_file | → Auto picks | Why |
|:-:|:-:|:-:|---|---|
| ✓ | — | — | **ESMFold** | Fast single-sequence (~5 min); fallback AlphaFold (hours, local DB MSA) |
| ✓ | — | ✓ | **Boltz** | MSA available, highest priority |
| ✓ | ✓ (any) | — | **ERROR** | Boltz/OpenFold/Chai require MSA for protein; AF/ESMFold can't handle DNA/RNA/ligand |
| ✓ | ✓ (any) | ✓ | **Boltz** | MSA + multi-entity → diffusion tool, Boltz first |
| — | DNA/RNA only | — | **Boltz** | No protein → no MSA gate; Boltz first |
| — | DNA/RNA only | ✓ | **Boltz** | Same |
| — | ligand or SMILES only (no biopolymer) | any | **ERROR** in practice | Tools require at least one chain |
| ✓ (only) | — | — | **AlphaFold** only if ESMFold unavailable AND AF DBs present | Last resort |

### Three failure modes the UI should surface

1. **Protein + (DNA/RNA/ligand/SMILES) without `msa_file`** — no tool
   matches. The UI can light this up the moment the user adds a
   non-protein input without an MSA, prompting "Boltz / OpenFold / Chai
   require an uploaded MSA — provide `msa_file` or remove the
   non-protein input to use AlphaFold."

2. **No inputs at all** — Perl errors before invocation.

3. **Specific tool chosen explicitly + no MSA** — when the user picks
   `tool: boltz | openfold | chai` directly (overriding `auto`) without
   an MSA file, the AppScript hard-errors with:
   *"$tool requires an MSA upload (msa_file). External MSA servers are
   disabled by BV-BRC policy. For MSA-free prediction use esmfold; for
   local-database MSA use alphafold."*

## Capability matrix

```
                     Boltz   OpenFold   Chai    ESMFold     AlphaFold
Priority (auto):       1        2         3         4            5
Protein:               ✓        ✓         ✓         ✓            ✓
DNA:                   ✓        ✓         ✓         —            —
RNA:                   ✓        ✓         ✓         —            —
Ligand (CCD):          ✓        ✓         ✓         —            —
SMILES:                ✓        ✓         ✓         —            —
Glycan (CCD):          ✓        ✓         ✓         —            —
Needs MSA (protein):  yes      yes       yes        no           no
   ↳ source:          file     file      file   (none, single-seq)  local DBs
CPU practical:         —        —         —         ✓            —
Multi-chain:           ✓        ✓         ✓    single-chain   ✓ (multimer preset)
```

Notes:
- **Glycans use ligand CCD codes** (NAG, MAN, BMA, …); there is no
  separate glycan input. See [`app_specs/README.md`](../app_specs/README.md).
- **AlphaFold's MSA is built from on-disk databases** (jackhmmer /
  hhsearch); no external HTTP call. This is the only "compute MSA on the
  fly" option in the BV-BRC stack.
- **OpenFold's recycle count** isn't exposed via the form's `num_recycles`;
  it's set in the runner YAML. The form's `num_recycles` affects Boltz,
  Chai, and ESMFold.

## UI guidance pseudocode

```js
function recommendedTool({protein, dna, rna, ligand, smiles, msa_file}) {
    const hasNonProtein = dna || rna || (ligand?.length) || (smiles?.length);
    const hasProtein = !!protein;

    if (!hasProtein && !hasNonProtein) {
        return { tool: null, hint: "Provide at least one input." };
    }

    // Single-sequence path (protein-only, no MSA)
    if (hasProtein && !hasNonProtein && !msa_file) {
        return {
            tool: "esmfold",
            fallback: "alphafold",
            hint: "ESMFold selected — fast single-sequence prediction (~5 min). " +
                  "AlphaFold (hours) is the fallback if ESMFold is unavailable."
        };
    }

    // Need MSA for protein with anything (or for protein-only with MSA)
    if (hasProtein && msa_file) {
        return {
            tool: "boltz",
            fallbacks: ["openfold", "chai", "esmfold", "alphafold"],
            hint: "Boltz selected — diffusion tool with highest priority when MSA is available."
        };
    }

    // Protein + non-protein, no MSA — auto cannot pick anything
    if (hasProtein && hasNonProtein && !msa_file) {
        return {
            tool: null,
            error: "Boltz / OpenFold / Chai require an MSA file when a " +
                   "protein chain is present. Upload msa_file, or remove " +
                   "the DNA/RNA/ligand/SMILES inputs to use AlphaFold."
        };
    }

    // Non-protein only (DNA / RNA / ligand etc.)
    if (!hasProtein && hasNonProtein) {
        return {
            tool: "boltz",
            fallbacks: ["openfold", "chai"],
            hint: "DNA/RNA/ligand-only complex — diffusion tools (Boltz first)."
        };
    }
}
```

## Code reference

The decision logic lives in
[`predict_structure/cli.py:_auto_select_tool`](../predict_structure/cli.py).
Any change here should keep this doc, the auto-select function, and the
acceptance test
[`tests/acceptance/test_phase2_auto_selection.py`](../tests/acceptance/test_phase2_auto_selection.py)
in sync.
