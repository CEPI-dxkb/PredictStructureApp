cwlVersion: v1.2
class: CommandLineTool

label: "Merge predict-structure output with characterization reports"
doc: |
  Stages the predict-structure output directory plus the protein-compare
  report files into one workspace, then runs `predict-structure
  finalize-results` to refresh results.json + ro-crate-metadata.json so
  the manifest lists the freshly-added reports.

  Output is a single Directory matching the BV-BRC service-script layout:
  - top level: model_1.pdb, report.html, results.json
  - predictions/, reports/, inputs/, metadata/, raw/

requirements:
  InlineJavascriptRequirement: {}
  InitialWorkDirRequirement:
    listing:
      # Stage every entry from the predict-structure output Directory at
      # the top of the working dir.
      - entry: $(inputs.predictions)
        entryname: "."
      # Tool-side report.html / .json / .pdf land under reports/. Each is
      # optional; the JS expression returns null when the input is unset.
      - entry: |
          ${ return inputs.report_html ? inputs.report_html : null; }
        entryname: "reports/report.html"
      - entry: |
          ${ return inputs.report_json ? inputs.report_json : null; }
        entryname: "reports/report.json"
      - entry: |
          ${ return inputs.report_pdf ? inputs.report_pdf : null; }
        entryname: "reports/report.pdf"
      # Top-level user-facing copy of the HTML report.
      - entry: |
          ${ return inputs.report_html ? inputs.report_html : null; }
        entryname: "report.html"

hints:
  DockerRequirement:
    dockerPull: folding_prod.sif
    dockerImageId: /scout/containers/folding_prod.sif

baseCommand: [predict-structure, finalize-results]

arguments:
  - position: 1
    valueFrom: "."

inputs:
  predictions:
    type: Directory
    doc: "Output directory from predict-structure.cwl"

  report_html:
    type: File?
    doc: "HTML report from protein-compare.cwl (optional)"

  report_json:
    type: File?
    doc: "JSON metrics from protein-compare.cwl (optional)"

  report_pdf:
    type: File?
    doc: "PDF report from protein-compare.cwl (optional)"

outputs:
  merged:
    type: Directory
    outputBinding:
      glob: "."
    doc: "Unified output directory matching the BV-BRC workspace upload layout"

stdout: merge-output.log
stderr: merge-output.err
