cwlVersion: v1.2
class: CommandLineTool

label: "Batch Protein Structure Comparison"
doc: |
  Runs protein_compare batch to compare multiple predicted structures
  pairwise. Calculates TM-score, RMSD, secondary structure agreement,
  and contact map similarity for all pairs.

  Designed to receive an array of PDB/mmCIF files from scattered
  predict-structure runs (one per tool) and produce a comparison report.

requirements:
  InlineJavascriptRequirement: {}

hints:
  DockerRequirement:
    dockerPull: folding_compare_prod.sif
    dockerImageId: /scout/containers/folding_compare_prod.sif
  ResourceRequirement:
    coresMin: 1
    ramMin: 4096

baseCommand: [python, -m, protein_compare, batch]

inputs:
  structures:
    type: File[]
    inputBinding:
      position: 1
    doc: "Structure files to compare (PDB or mmCIF)"

  output_csv:
    type: string
    default: results.csv
    inputBinding:
      prefix: -o
    doc: "Output CSV file with pairwise comparison metrics"

  output_html:
    type: string?
    default: report.html
    inputBinding:
      prefix: --html
    doc: "HTML comparison report"

  output_json:
    type: string?
    default: results.json
    inputBinding:
      prefix: --json
    doc: "JSON comparison results"

  confidence_weighted:
    type: boolean
    default: true
    inputBinding:
      prefix: --confidence-weighted
    doc: "Use pLDDT-weighted RMSD"

  jobs:
    type: int?
    inputBinding:
      prefix: --jobs
    doc: "Number of parallel comparison jobs (-1 for all CPUs)"

outputs:
  comparison_csv:
    type: File
    outputBinding:
      glob: $(inputs.output_csv)
    doc: "CSV with pairwise TM-score, RMSD, etc."

  comparison_html:
    type: File?
    outputBinding:
      glob: $(inputs.output_html)
    doc: "HTML comparison report"

  comparison_json:
    type: File?
    outputBinding:
      glob: $(inputs.output_json)
    doc: "JSON comparison results"

stdout: protein-compare-batch.log
stderr: protein-compare-batch.err
