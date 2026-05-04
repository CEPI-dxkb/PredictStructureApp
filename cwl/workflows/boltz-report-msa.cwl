cwlVersion: v1.2
class: Workflow

label: "Boltz-2 Predict + Report Workflow"
doc: |
  Three-step workflow: predict structure with Boltz-2 via predict-structure,
  extract the first PDB file, and generate a characterization report.

requirements:
  InlineJavascriptRequirement: {}

inputs:
  protein:
    type:
      - "null"
      - type: array
        items: File
    doc: "Protein FASTA file(s)"
  output_dir:
    type: string
    default: output
    doc: "Output directory for predictions"
  num_samples:
    type: int?
    doc: "Number of diffusion samples"
  num_recycles:
    type: int?
    doc: "Number of recycling iterations"
  seed:
    type: int?
    doc: "Random seed"
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
  use_msa_server:
    type: boolean?
    default: true
    doc: "Use remote MSA server for alignment generation"
  report_name:
    type: string
    default: report
    doc: "Output report name (without extension)"
  report_format:
    type:
      - "null"
      - type: enum
        symbols: [html, pdf, json, both, all]
    default: all
    doc: "Report format (html, pdf, json, both, or all)"

steps:
  predict:
    run: ../tools/predict-structure.cwl
    in:
      tool:
        default: boltz
      protein: protein
      output_dir: output_dir
      num_samples: num_samples
      num_recycles: num_recycles
      seed: seed
      device: device
      output_format: output_format
      use_msa_server: use_msa_server
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
    out: [report, report_json]

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
    doc: "HTML characterization report"
  characterization_json:
    type: File
    outputSource: report/report_json
    doc: "JSON characterization data"
