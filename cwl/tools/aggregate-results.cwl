cwlVersion: v1.2
class: CommandLineTool

label: "Aggregate per-tool results.json into a multi-tool summary"
doc: |
  Wraps `predict-structure aggregate-results` to combine per-tool
  results.json files (emitted by each predict-structure.cwl run) into a
  single top-level results.json describing a multi-tool comparison.

  Output schema (see docs/OUTPUT_NORMALIZATION.md §5):
    {
      "schema_version": "1.0",
      "kind": "multi-tool",
      "timestamp": "...",
      "runs": [ <per-tool results.json> ... ]
    }

requirements:
  InlineJavascriptRequirement: {}

baseCommand: [predict-structure, aggregate-results]

inputs:
  per_tool_results:
    type: File[]
    doc: "Per-tool results.json files to aggregate"
    inputBinding:
      prefix: "--in"
      position: 1
  output_name:
    type: string
    default: "results.json"
    doc: "Filename of the aggregated summary"
    inputBinding:
      prefix: "-o"
      position: 2

outputs:
  aggregated_results:
    type: File
    outputBinding:
      glob: "$(inputs.output_name)"
    doc: "Aggregated multi-tool results.json"
