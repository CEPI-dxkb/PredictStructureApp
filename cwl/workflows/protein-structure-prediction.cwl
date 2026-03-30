cwlVersion: v1.2
class: Workflow

label: "Protein Structure Prediction Workflow"
doc: |
  Three-step workflow: predict structure with predict-structure,
  extract the first PDB file, and generate a characterization
  report with protein-compare.

requirements:
  InlineJavascriptRequirement: {}

inputs:
  # --- Tool selection ---
  tool:
    type:
      type: enum
      symbols: [boltz, chai, alphafold, esmfold, auto]
    doc: "Prediction tool to use"

  # --- Entity inputs ---
  protein:
    type:
      - "null"
      - type: array
        items: File
    doc: "Protein FASTA file(s)"
  dna:
    type:
      - "null"
      - type: array
        items: File
    doc: "DNA FASTA file(s)"
  rna:
    type:
      - "null"
      - type: array
        items: File
    doc: "RNA FASTA file(s)"
  ligand:
    type:
      - "null"
      - type: array
        items: string
    doc: "Ligand identifiers (e.g. ATP, CCD codes)"
  smiles:
    type:
      - "null"
      - type: array
        items: string
    doc: "SMILES strings for small molecules"
  glycan:
    type:
      - "null"
      - type: array
        items: string
    doc: "Glycan identifiers"

  # --- Shared options ---
  output_dir:
    type: string
    default: output
    doc: "Output directory for predictions"
  num_samples:
    type: int?
    doc: "Number of structure samples (Boltz, Chai)"
  num_recycles:
    type: int?
    doc: "Number of recycling iterations"
  seed:
    type: int?
    doc: "Random seed"
  msa:
    type: File?
    doc: "Precomputed MSA file (.a3m, .sto, .pqt)"
  device:
    type:
      - "null"
      - type: enum
        symbols: [gpu, cpu]
    default: gpu
    doc: "Compute device"
  output_format:
    type:
      - "null"
      - type: enum
        symbols: [pdb, mmcif]
    default: pdb
    doc: "Output structure format"

  # --- Boltz / Chai options ---
  sampling_steps:
    type: int?
    doc: "Diffusion sampling steps (Boltz, Chai)"
  use_msa_server:
    type: boolean?
    doc: "Use remote MSA server (Boltz, Chai)"
  msa_server_url:
    type: string?
    doc: "Custom MSA server URL"
  use_potentials:
    type: boolean?
    doc: "Enable potential terms (Boltz only)"

  # --- AlphaFold options ---
  af2_model_preset:
    type: string?
    doc: "AlphaFold2 model preset (monomer, monomer_casp14, multimer)"
  af2_db_preset:
    type: string?
    doc: "AlphaFold2 database preset (full_dbs, reduced_dbs)"
  af2_max_template_date:
    type: string?
    doc: "Maximum template date (YYYY-MM-DD)"

  # --- ESMFold options ---
  fp16:
    type: boolean?
    doc: "Half-precision inference (ESMFold)"
  chunk_size:
    type: int?
    doc: "Chunk size for long sequences (ESMFold)"
  max_tokens_per_batch:
    type: int?
    doc: "Max tokens per batch (ESMFold)"

  # --- Report options ---
  report_name:
    type: string
    default: report
    doc: "Output report name (without extension)"
  report_format:
    type: string?
    default: html
    doc: "Report format (html or pdf)"

steps:
  predict:
    run: ../tools/predict-structure.cwl
    in:
      tool: tool
      protein: protein
      dna: dna
      rna: rna
      ligand: ligand
      smiles: smiles
      glycan: glycan
      output_dir: output_dir
      num_samples: num_samples
      num_recycles: num_recycles
      seed: seed
      msa: msa
      device: device
      output_format: output_format
      sampling_steps: sampling_steps
      use_msa_server: use_msa_server
      msa_server_url: msa_server_url
      use_potentials: use_potentials
      af2_model_preset: af2_model_preset
      af2_db_preset: af2_db_preset
      af2_max_template_date: af2_max_template_date
      fp16: fp16
      chunk_size: chunk_size
      max_tokens_per_batch: max_tokens_per_batch
    out: [predictions]

  extract:
    run: ../tools/select-structure.cwl
    in:
      predictions: predict/predictions
    out: [structure]

  report:
    run: ../tools/protein-compare.cwl
    in:
      structure: extract/structure
      output_name: report_name
      format: report_format
    out: [report]

outputs:
  predictions:
    type: Directory
    outputSource: predict/predictions
    doc: "Full predictions directory"
  structure:
    type: File
    outputSource: extract/structure
    doc: "Extracted PDB structure file"
  characterization_report:
    type: File
    outputSource: report/report
    doc: "Characterization report (HTML or PDF)"
