cwlVersion: v1.2
class: ExpressionTool

label: "Rename Structure File with Tool Suffix"
doc: |
  Renames a structure file to include the tool name as a suffix,
  e.g. model_1.pdb → model_1.boltz.pdb. This allows protein_compare
  batch to distinguish structures from different tools in its output.

requirements:
  InlineJavascriptRequirement: {}

inputs:
  structure:
    type: File
    doc: "Structure file to rename"
  tool:
    type: string
    doc: "Tool name to insert as suffix (e.g. boltz, chai)"

expression: |
  ${
    var name = inputs.structure.basename;
    var dot = name.lastIndexOf(".");
    var stem = dot > 0 ? name.substring(0, dot) : name;
    var ext = dot > 0 ? name.substring(dot) : "";
    var newName = stem + "." + inputs.tool + ext;
    return {"renamed": {
      "class": "File",
      "location": inputs.structure.location,
      "basename": newName
    }};
  }

outputs:
  renamed:
    type: File
    doc: "Structure file with tool suffix in name"
