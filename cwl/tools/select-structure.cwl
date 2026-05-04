cwlVersion: v1.2
class: ExpressionTool

label: "Select Structure from Predictions Directory"
doc: |
  Selects the first structure file (.pdb or .cif) from a predictions
  directory.  Prefers .pdb; falls back to .cif if no PDB is found.
  Bridges the predict step (Directory output) to the report step
  (File input).

requirements:
  InlineJavascriptRequirement: {}
  LoadListingRequirement:
    loadListing: shallow_listing

inputs:
  predictions:
    type: Directory
    doc: "Predictions directory from a structure prediction tool"

expression: |
  ${
    var pdb = null;
    var cif = null;
    for (var i = 0; i < inputs.predictions.listing.length; i++) {
      var f = inputs.predictions.listing[i];
      if (f.class !== "File") continue;
      if (!pdb && f.basename.endsWith(".pdb")) pdb = f;
      if (!cif && f.basename.endsWith(".cif")) cif = f;
      if (pdb) break;
    }
    var hit = pdb || cif;
    if (!hit) throw "No .pdb or .cif file found in predictions directory";
    return {"structure": hit};
  }

outputs:
  structure:
    type: File
    doc: "First structure file found (PDB preferred, CIF fallback)"
