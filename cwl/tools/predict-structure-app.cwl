cwlVersion: v1.2
class: CommandLineTool

label: "Predict Structure (BV-BRC App)"
doc: |
  BV-BRC protein structure prediction app. Dispatched via the BV-BRC
  AppService runtime (executor: bvbrc), which handles workspace file
  staging, SLURM scheduling, and result upload.

  The app runs App-PredictStructure.pl end-to-end: input validation,
  prediction (Boltz-2 / OpenFold 3 / Chai-1 / AlphaFold 2 / ESMFold),
  characterization report (protein_compare), and results finalization
  (results.json v2.0 + ro-crate-metadata.json).

  Inputs mirror the basic PredictStructure.json app spec. GoWe
  translates CWL inputs to BV-BRC params.json for the AppService.

  Output directory (unified layout):
    output/
    ├── model_1.pdb        ├── report.html       ├── results.json
    ├── inputs/            ├── predictions/       ├── reports/
    ├── metadata/          └── raw/

$namespaces:
  cwltool: http://commonwl.org/cwltool#
  gowe: "https://github.com/wilke/GoWe#"

hints:
  DockerRequirement:
    dockerPull: folding_prod.sif
    dockerImageId: /scout/containers/folding_prod.sif
  cwltool:CUDARequirement:
    cudaVersionMin: "11.8"
    cudaDeviceCountMin: 1
    cudaDeviceCountMax: 1
  gowe:Execution:
    bvbrc_app_id: PredictStructure
    executor: bvbrc
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

requirements:
  ResourceRequirement:
    coresMin: 8
    ramMin: 65536
    ramMax: 204800
  NetworkAccess:
    networkAccess: true

baseCommand: [App-PredictStructure]

# ===================================================================
#  Inputs (mirrors basic PredictStructure.json app spec)
# ===================================================================

inputs:
  tool:
    type:
      type: enum
      symbols: [auto, boltz, openfold, chai, alphafold, esmfold]
    default: auto
    doc: |
      Prediction tool. 'auto' picks best from inputs:
        with MSA → Boltz > OpenFold > Chai > ESMFold > AlphaFold
        no MSA   → ESMFold > AlphaFold

  protein:
    type: File?
    doc: "Protein FASTA file. Multi-chain via multiple sequences."

  dna:
    type: File?
    doc: "DNA FASTA file. Tools: Boltz-2, OpenFold 3, Chai-1."

  rna:
    type: File?
    doc: "RNA FASTA file. Tools: Boltz-2, OpenFold 3, Chai-1."

  ligand:
    type: string[]?
    doc: "Ligand CCD codes (e.g. ATP, NAG). Glycans use CCD codes."

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

  output_path:
    type: string?
    doc: "Workspace output folder (BV-BRC). Set by the UI or GoWe --output-destination."

# ===================================================================
#  Outputs (unified layout)
# ===================================================================

outputs:
  output_dir:
    type: Directory
    outputBinding:
      glob: output
    doc: |
      Full prediction output directory. Top-level: model_1.pdb,
      report.html, results.json. Subdirs: inputs/, predictions/,
      reports/, metadata/, raw/.

  best_model:
    type: File?
    outputBinding:
      glob: output/model_1.pdb
    doc: "Rank-1 PDB structure"

  report:
    type: File?
    outputBinding:
      glob: output/report.html
    doc: "HTML characterization report"

  results:
    type: File?
    outputBinding:
      glob: output/results.json
    doc: "results.json v2.0 (CWL-style outputs map)"

  metadata:
    type: File?
    outputBinding:
      glob: output/metadata/metadata.json
    doc: "Canonical run-trace metadata (v1.1)"

stdout: predict-structure-app.log
stderr: predict-structure-app.err
