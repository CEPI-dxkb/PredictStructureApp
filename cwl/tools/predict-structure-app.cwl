cwlVersion: v1.2
class: CommandLineTool

label: "Predict Structure (BV-BRC AppService wrapper)"
doc: |
  Wraps the full BV-BRC App-PredictStructure.pl service script as a
  single CWL tool. Unlike the multi-step protein-structure-prediction
  workflow (predict → extract → report → merge), this tool runs
  everything in one invocation: input validation, prediction,
  characterization report (protein_compare), results.json + ro-crate
  finalization.

  Inputs mirror the basic PredictStructure.json app spec. The tool
  generates a params.json from CWL inputs via InitialWorkDirRequirement,
  sets up the environment, and invokes the Perl AppScript. Workspace
  upload is skipped (PREDICT_STRUCTURE_SKIP_UPLOAD=1) — CWL collects
  the output directory directly.

  Output directory (unified layout):
    output/
    ├── model_1.pdb        ├── report.html       ├── results.json
    ├── inputs/            ├── predictions/       ├── reports/
    ├── metadata/          └── raw/

requirements:
  InlineJavascriptRequirement: {}
  InitialWorkDirRequirement:
    listing:
      # Stage input files so the Perl's local-copy fallback in
      # download_workspace_file finds them by path.
      - entryname: staged/protein.fasta
        entry: |
          ${ return inputs.protein ? inputs.protein : null; }
      - entryname: staged/dna.fasta
        entry: |
          ${ return inputs.dna ? inputs.dna : null; }
      - entryname: staged/rna.fasta
        entry: |
          ${ return inputs.rna ? inputs.rna : null; }
      - entryname: staged/msa_file
        entry: |
          ${ return inputs.msa ? inputs.msa : null; }
      # Generate params.json from CWL inputs
      - entryname: params.json
        entry: |
          ${
            var params = {
              tool: inputs.tool,
              output_path: "/cwl/output"
            };
            if (inputs.protein) {
              params.input_file = "staged/protein.fasta";
            }
            if (inputs.dna) {
              params.dna_file = "staged/dna.fasta";
            }
            if (inputs.rna) {
              params.rna_file = "staged/rna.fasta";
            }
            if (inputs.msa) {
              params.msa_file = "staged/msa_file";
            }
            if (inputs.ligand && inputs.ligand.length > 0) {
              params.ligand = inputs.ligand;
            }
            if (inputs.smiles && inputs.smiles.length > 0) {
              params.smiles = inputs.smiles;
            }
            if (inputs.debug) {
              params.debug = true;
            }
            return JSON.stringify(params, null, 2);
          }
  EnvVarRequirement:
    envDef:
      - envName: P3_WORKDIR
        envValue: "."
      - envName: PREDICT_STRUCTURE_SKIP_UPLOAD
        envValue: "1"
      - envName: HF_HOME
        envValue: /local_databases/cache
  DockerRequirement:
    dockerPull: folding_prod.sif
    dockerImageId: /scout/containers/folding_prod.sif
  ResourceRequirement:
    coresMin: 8
    ramMin: 65536
    ramMax: 204800
  NetworkAccess:
    networkAccess: true

hints:
  cwltool:CUDARequirement:
    cudaVersionMin: "11.8"
    cudaDeviceCountMin: 1
    cudaDeviceCountMax: 1
  gowe:Execution:
    executor: worker
    gpu: true
  gowe:ResourceData:
    datasets:
      - id: boltz
        path: /local_databases/boltz
        size: 50GB
        mode: cache
      - id: chai
        path: /local_databases/chai
        size: 30GB
        mode: cache
      - id: openfold
        path: /local_databases/openfold
        size: 10GB
        mode: cache
      - id: esmfold
        path: /local_databases/esmfold
        size: 20GB
        mode: cache

baseCommand:
  - perl
  - /build/dev_container/modules/PredictStructureApp/service-scripts/App-PredictStructure.pl

arguments:
  - position: 1
    valueFrom: ""
  - position: 2
    valueFrom: /build/dev_container/modules/PredictStructureApp/app_specs/PredictStructure.json
  - position: 3
    valueFrom: params.json

# ===================================================================
#  Inputs (mirrors basic PredictStructure.json app spec)
# ===================================================================

inputs:
  tool:
    type:
      type: enum
      symbols: [auto, boltz, openfold, chai, alphafold, esmfold]
    default: auto
    doc: "Prediction tool. 'auto' picks best from inputs (see docs/tool-selection.md)."

  protein:
    type: File?
    doc: "Protein FASTA file. Multi-chain via multiple sequences in one file."

  dna:
    type: File?
    doc: "DNA FASTA file. Tools: Boltz-2, OpenFold 3, Chai-1."

  rna:
    type: File?
    doc: "RNA FASTA file. Tools: Boltz-2, OpenFold 3, Chai-1."

  ligand:
    type: string[]?
    doc: "Ligand CCD codes (e.g. ATP, NAG). Glycans use CCD codes here too."

  smiles:
    type: string[]?
    doc: "SMILES strings for arbitrary small molecules."

  msa:
    type: File?
    doc: "Pre-computed MSA (.a3m, .sto). Required for Boltz / OpenFold / Chai."

  debug:
    type: boolean?
    default: false
    doc: "Enable debug logging (P3_DEBUG=1, --verbose)"

# ===================================================================
#  Outputs (unified layout)
# ===================================================================

outputs:
  output_dir:
    type: Directory
    outputBinding:
      glob: output
    doc: |
      Full prediction output directory (unified layout):
      model_1.pdb + report.html + results.json at top, plus
      inputs/ predictions/ reports/ metadata/ raw/ subdirs.

  best_model:
    type: File?
    outputBinding:
      glob: output/model_1.pdb
    doc: "Top-level rank-1 PDB (user-facing copy)"

  report:
    type: File?
    outputBinding:
      glob: output/report.html
    doc: "HTML characterization report (user-facing copy)"

  results:
    type: File?
    outputBinding:
      glob: output/results.json
    doc: "results.json v2.0 (CWL-style outputs map + UI summary)"

  metadata:
    type: File?
    outputBinding:
      glob: output/metadata/metadata.json
    doc: "Canonical run-trace metadata (v1.1)"

stdout: predict-structure-app.log
stderr: predict-structure-app.err

$namespaces:
  cwltool: http://commonwl.org/cwltool#
  gowe: https://gowe.bv-brc.org/cwl#

$schemas:
  - https://schema.org/version/latest/schemaorg-current-https.rdf
