cwlVersion: v1.2
class: ExpressionTool

label: "Select PAE JSON from a Normalized Output Directory"
doc: |
  Picks ``predictions/pae.json`` out of the unified output directory so the
  report step can be handed a File. Returns null when the tool produced no
  PAE matrix (ESMFold, Chai), which is why the downstream ``pae`` input is
  optional. Needs deep_listing: pae.json lives one level down, under
  predictions/.

requirements:
  InlineJavascriptRequirement: {}
  LoadListingRequirement:
    loadListing: deep_listing

inputs:
  predictions:
    type: Directory
    doc: "Normalized output directory from a structure prediction tool"

expression: |
  ${
    var listing = inputs.predictions.listing || [];
    for (var i = 0; i < listing.length; i++) {
      var entry = listing[i];
      if (entry.class === "File" && entry.basename === "pae.json") {
        return {"pae": entry};
      }
      if (entry.class === "Directory" && entry.basename === "predictions") {
        var sub = entry.listing || [];
        for (var j = 0; j < sub.length; j++) {
          if (sub[j].class === "File" && sub[j].basename === "pae.json") {
            return {"pae": sub[j]};
          }
        }
      }
    }
    return {"pae": null};
  }

outputs:
  pae:
    type: File?
    doc: "predictions/pae.json, or null when the tool emits no PAE"
