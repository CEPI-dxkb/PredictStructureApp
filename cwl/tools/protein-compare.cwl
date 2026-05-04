cwlVersion: v1.2
class: CommandLineTool

label: "Protein Structure Characterization Report"
doc: |
  Runs protein_compare characterize to generate an HTML/PDF report
  for a predicted protein structure. Consumes normalized output
  from predict-structure (model_1.pdb, confidence.json).

requirements:
  InlineJavascriptRequirement: {}
  InitialWorkDirRequirement:
    listing:
      - $(inputs.structure)

hints:
  DockerRequirement:
    dockerPull: folding_compare_prod.sif
    dockerImageId: /scout/containers/folding_compare_prod.sif
  ResourceRequirement:
    coresMin: 1
    ramMin: 4096

baseCommand: [python, -m, protein_compare, characterize]

inputs:
  structure:
    type: File
    inputBinding:
      position: 1
    doc: "Input PDB or mmCIF structure file"

  output_name:
    type: string
    default: report
    inputBinding:
      prefix: -o
    doc: "Output report name (without extension)"

  format:
    type:
      - "null"
      - type: enum
        symbols: [html, pdf, json, both, all]
    default: all
    inputBinding:
      prefix: --format
    doc: "Report format (html, pdf, json, both, or all)"

  pae:
    type: File?
    inputBinding:
      prefix: --pae
    doc: "PAE JSON file (AlphaFold/Boltz)"

  chai_scores:
    type: File?
    inputBinding:
      prefix: --chai-scores
    doc: "Chai scores NPZ file"

  msa:
    type: File?
    inputBinding:
      prefix: --msa
    doc: "MSA parquet file for depth visualization"

outputs:
  report:
    type: File?
    outputBinding:
      glob: $(inputs.output_name + ".html")
    doc: "HTML characterization report"

  report_pdf:
    type: File?
    outputBinding:
      glob: $(inputs.output_name + ".pdf")
    doc: "PDF characterization report"

  report_json:
    type: File?
    outputBinding:
      glob: $(inputs.output_name + ".json")
    doc: "JSON characterization data"

stdout: protein-compare.log
stderr: protein-compare.err
