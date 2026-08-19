# Archived app specs

Kept for forensics, not for use. Nothing here is registered with BV-BRC —
the live spec is [`../PredictStructure.json`](../PredictStructure.json).

## `app_spec_root_orphan_20260818.json`

An untracked copy of the app spec that sat at the **repo root** as
`app_spec.json` until 2026-08-18. It was referenced by nothing (only a
docstring example in `tests/acceptance/conftest.py` mentions the bare
filename as a generic CLI argument) and its content predated several
merged changes:

- `tool` enum has no `esmfold2`
- no `text_input` parameter
- `ligand` still documents the 1-3 character CCD rule (corrected to 1-3
  or exactly 5 in #48)
- `tool` description still says `auto` can fall through to AlphaFold
  (retired from auto in #90)

Archived rather than deleted so that if the **next container build**
misbehaves, this file can be diffed against the live spec to check
whether a stale copy is implicated — the same failure mode as #110
(container shipped a June deployed spec beside the current checkout
copy) and #98 (stale runner copy in a second conda env).
