cwlVersion: v1.2
class: Workflow

label: "Multi-Tool Structure Prediction Comparison"
doc: |
  Runs Boltz, OpenFold, Chai, and ESMFold on the same input, extracts
  the best structure from each, renames them by tool, and compares all
  pairwise using protein_compare batch.

  Output files are named model_1.<tool>.pdb for clear identification
  in the comparison report.

requirements:
  InlineJavascriptRequirement: {}
  MultipleInputFeatureRequirement: {}

inputs:
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
    doc: "Ligand identifiers (CCD codes)"
  smiles:
    type:
      - "null"
      - type: array
        items: string
    doc: "SMILES strings for small molecules"

  # --- Shared prediction options ---
  output_dir:
    type: string
    default: output
    doc: "Output directory"
  num_samples:
    type: int?
    doc: "Number of structure samples"
  num_recycles:
    type: int?
    doc: "Number of recycling iterations"
  seed:
    type: int?
    doc: "Random seed"
  msa:
    type: File?
    doc: "Precomputed MSA file (.a3m, .sto)"
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

  # --- Comparison options ---
  report_name:
    type: string
    default: comparison
    doc: "Comparison report name"
  confidence_weighted:
    type: boolean
    default: true
    doc: "Use pLDDT-weighted RMSD in comparison"

steps:
  # --- Predict with each tool ---

  predict_boltz:
    run: ../tools/predict-structure.cwl
    in:
      tool: { default: boltz }
      protein: protein
      dna: dna
      rna: rna
      ligand: ligand
      smiles: smiles
      output_dir: output_dir
      num_samples: num_samples
      num_recycles: num_recycles
      seed: seed
      msa: msa
      device: device
      output_format: output_format
    out: [predictions, results]

  predict_openfold:
    run: ../tools/predict-structure.cwl
    in:
      tool: { default: openfold }
      protein: protein
      dna: dna
      rna: rna
      ligand: ligand
      smiles: smiles
      output_dir: output_dir
      num_samples: num_samples
      num_recycles: num_recycles
      seed: seed
      msa: msa
      device: device
      output_format: output_format
    out: [predictions, results]

  predict_chai:
    run: ../tools/predict-structure.cwl
    in:
      tool: { default: chai }
      protein: protein
      dna: dna
      rna: rna
      ligand: ligand
      smiles: smiles
      output_dir: output_dir
      num_samples: num_samples
      num_recycles: num_recycles
      seed: seed
      msa: msa
      device: device
      output_format: output_format
    out: [predictions, results]

  predict_esmfold:
    run: ../tools/predict-structure.cwl
    in:
      tool: { default: esmfold }
      protein: protein
      dna: dna
      rna: rna
      ligand: ligand
      smiles: smiles
      output_dir: output_dir
      num_samples: num_samples
      num_recycles: num_recycles
      seed: seed
      msa: msa
      device: device
      output_format: output_format
    out: [predictions, results]

  # --- Extract structures ---

  extract_boltz:
    run: ../tools/select-structure.cwl
    in:
      predictions: predict_boltz/predictions
    out: [structure]

  extract_openfold:
    run: ../tools/select-structure.cwl
    in:
      predictions: predict_openfold/predictions
    out: [structure]

  extract_chai:
    run: ../tools/select-structure.cwl
    in:
      predictions: predict_chai/predictions
    out: [structure]

  extract_esmfold:
    run: ../tools/select-structure.cwl
    in:
      predictions: predict_esmfold/predictions
    out: [structure]

  # --- Rename with tool suffix ---

  rename_boltz:
    run: ../tools/rename-structure.cwl
    in:
      structure: extract_boltz/structure
      tool: { default: boltz }
    out: [renamed]

  rename_openfold:
    run: ../tools/rename-structure.cwl
    in:
      structure: extract_openfold/structure
      tool: { default: openfold }
    out: [renamed]

  rename_chai:
    run: ../tools/rename-structure.cwl
    in:
      structure: extract_chai/structure
      tool: { default: chai }
    out: [renamed]

  rename_esmfold:
    run: ../tools/rename-structure.cwl
    in:
      structure: extract_esmfold/structure
      tool: { default: esmfold }
    out: [renamed]

  # --- Compare all structures ---

  compare:
    run: ../tools/protein-compare-batch.cwl
    in:
      structures:
        source:
          - rename_boltz/renamed
          - rename_openfold/renamed
          - rename_chai/renamed
          - rename_esmfold/renamed
        linkMerge: merge_flattened
      output_csv:
        default: results.csv
      output_html:
        valueFrom: $(inputs.report_name + ".html")
      output_json:
        valueFrom: $(inputs.report_name + ".json")
      confidence_weighted: confidence_weighted
    out: [comparison_csv, comparison_html, comparison_json]

  aggregate_results:
    run: ../tools/aggregate-results.cwl
    in:
      per_tool_results:
        source:
          - predict_boltz/results
          - predict_openfold/results
          - predict_chai/results
          - predict_esmfold/results
        linkMerge: merge_flattened
        pickValue: all_non_null
    out: [aggregated_results]

outputs:
  predictions:
    type: Directory[]
    outputSource:
      - predict_boltz/predictions
      - predict_openfold/predictions
      - predict_chai/predictions
      - predict_esmfold/predictions
    linkMerge: merge_flattened
    doc: "Prediction output directories (one per tool)"

  structures:
    type: File[]
    outputSource:
      - rename_boltz/renamed
      - rename_openfold/renamed
      - rename_chai/renamed
      - rename_esmfold/renamed
    linkMerge: merge_flattened
    doc: "Renamed structure files (model_1.boltz.pdb, etc.)"

  comparison_report:
    type: File?
    outputSource: compare/comparison_html
    doc: "HTML comparison report"

  comparison_csv:
    type: File
    outputSource: compare/comparison_csv
    doc: "CSV with pairwise TM-score, RMSD, etc."

  comparison_json:
    type: File?
    outputSource: compare/comparison_json
    doc: "JSON comparison results"

  results:
    type: File
    outputSource: aggregate_results/aggregated_results
    doc: "Aggregated multi-tool results.json (summary of all per-tool runs)"
