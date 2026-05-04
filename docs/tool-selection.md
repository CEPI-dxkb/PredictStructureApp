# Tool Auto-Selection Decision Tree

When `predict-structure auto` is called, the tool is selected based on
entity types, device, and MSA availability.

## Decision Tree

```
predict-structure auto
│
├─ device = cpu AND protein-only?
│  ├─ YES → ESMFold available? → YES → ESMFold ✓
│  │                           → NO  → (fall through to GPU path)
│  └─ NO  ↓
│
│  For each tool in priority order:
│  Boltz → OpenFold → Chai → AlphaFold → ESMFold
│
├─ Boltz
│  ├─ Has non-protein entities (DNA/RNA/ligand/SMILES)?
│  │  └─ OK (Boltz supports all entity types)
│  ├─ Has protein AND no MSA available?
│  │  └─ SKIP (Boltz needs MSA file or server for protein)
│  ├─ Tool installed?
│  │  └─ NO → SKIP
│  └─ YES → Boltz ✓
│
├─ OpenFold
│  ├─ Has non-protein entities?
│  │  └─ OK (OpenFold supports all entity types)
│  ├─ Tool installed?
│  │  └─ NO → SKIP
│  └─ YES → OpenFold ✓
│
├─ Chai
│  ├─ Has non-protein entities?
│  │  └─ OK (Chai supports protein/DNA/RNA/ligand, not SMILES)
│  ├─ Has protein AND no MSA available?
│  │  └─ SKIP (Chai needs MSA file or server for protein)
│  ├─ Tool installed?
│  │  └─ NO → SKIP
│  └─ YES → Chai ✓
│
├─ AlphaFold
│  ├─ Has non-protein entities?
│  │  └─ SKIP (AlphaFold is protein-only)
│  ├─ Tool installed AND database dir exists?
│  │  └─ NO → SKIP
│  └─ YES → AlphaFold ✓
│
├─ ESMFold
│  ├─ Has non-protein entities?
│  │  └─ SKIP (ESMFold is protein-only)
│  ├─ Tool installed?
│  │  └─ NO → SKIP
│  └─ YES → ESMFold ✓
│
└─ No tool found → ERROR
```

## Selection Summary

```
                    Boltz    OpenFold   Chai    AlphaFold   ESMFold
Priority:             1         2        3         4          5
Protein:              ✓         ✓        ✓         ✓          ✓
DNA/RNA:              ✓         ✓        ✓         ✗          ✗
Ligand:               ✓         ✓        ✓         ✗          ✗
SMILES:               ✓         ✓        ✗         ✗          ✗
Needs MSA (protein):  ✓*        ✗        ✓*        ✗**        ✗
CPU mode:             ✗         ✗        ✗         ✗          ✓
```

`*` Skipped during auto-select when no MSA source available (file or server).
    Can still run in single-sequence mode when called directly.

`**` AlphaFold runs its own MSA pipeline from databases; doesn't need external MSA.

## Common Scenarios

| Input | MSA | Device | Selected |
|-------|-----|--------|----------|
| protein | none | gpu | OpenFold |
| protein | file | gpu | Boltz |
| protein | none | cpu | ESMFold |
| protein + DNA | none | gpu | OpenFold |
| protein + ligand | none | gpu | OpenFold |
| protein + ligand | file | gpu | Boltz |
| DNA only | none | gpu | Boltz |

## Code Reference

`predict_structure/cli.py` → `_auto_select_tool()`
