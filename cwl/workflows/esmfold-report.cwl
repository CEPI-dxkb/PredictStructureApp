cwlVersion: v1.2
class: Workflow

label: "ESMFold Predict + Report Workflow"
doc: |
  Three-step workflow: predict structure with ESMFold via predict-structure,
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
  num_recycles:
    type: int?
    doc: "Number of recycling iterations"
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
      tool:
        default: esmfold
      protein: protein
      output_dir: output_dir
      num_recycles: num_recycles
      device: device
      output_format: output_format
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
