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
    dockerPull: folding_compare_260329.sif
    dockerImageId: /scout/containers/folding_compare_260329.sif
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
    type: string?
    default: html
    inputBinding:
      prefix: --format
    doc: "Report format (html or pdf)"

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
    type: File
    outputBinding:
      glob: $(inputs.output_name + "." + inputs.format)

stdout: protein-compare.log
stderr: protein-compare.err
