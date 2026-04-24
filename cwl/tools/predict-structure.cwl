cwlVersion: v1.2
class: CommandLineTool

label: "Unified Protein Structure Prediction"
doc: |
  Dispatches to Boltz-2, OpenFold 3, Chai-1, AlphaFold 2, or ESMFold via the
  predict-structure CLI inside a single all-in-one container.

  Tool selection is a CWL enum input that maps to a CLI subcommand.
  Entity inputs (protein, DNA, RNA, ligand, SMILES) use repeatable
  flags, matching the CLI's explicit entity model.

  When run with cwltool --singularity, the DockerRequirement image
  is automatically converted to a SIF.  Pre-built SIF files can be
  used via CWL_SINGULARITY_CACHE or --singularity-cache.

  Defaults
  --------
  num_samples:          1
  num_recycles:         3
  output_format:        pdb
  device:               gpu
  sampling_steps:       200      (Boltz, Chai)
  af2_model_preset:     monomer  (AlphaFold)
  af2_db_preset:        reduced_dbs (AlphaFold)
  af2_max_template_date: 2022-01-01 (AlphaFold)

requirements:
  InlineJavascriptRequirement: {}
  DockerRequirement:
    dockerPull: folding_prod.sif
    dockerImageId: /scout/containers/folding_prod.sif
  ResourceRequirement:
    coresMin: 8
    ramMin: 65536
    ramMax: 98304
  InitialWorkDirRequirement:
    listing: |
      ${
        var files = [];
        if (inputs.protein) {
          inputs.protein.forEach(function(f) { files.push(f); });
        }
        if (inputs.dna) {
          inputs.dna.forEach(function(f) { files.push(f); });
        }
        if (inputs.rna) {
          inputs.rna.forEach(function(f) { files.push(f); });
        }
        if (inputs.msa) {
          files.push(inputs.msa);
        }
        if (inputs.constraint_path) {
          files.push(inputs.constraint_path);
        }
        if (inputs.template_hits_path) {
          files.push(inputs.template_hits_path);
        }
        return files;
      }
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

baseCommand: [predict-structure]

arguments:
  - valueFrom: "--backend"
    position: 98
  - valueFrom: "subprocess"
    position: 99

# ===================================================================
#  Inputs
# ===================================================================

inputs:

  # --- Tool selection (becomes CLI subcommand) ----------------------

  tool:
    type:
      type: enum
      symbols: [boltz, openfold, chai, alphafold, esmfold, auto]
    inputBinding:
      position: -100
    doc: "Prediction tool to use (maps to CLI subcommand)"

  # --- Entity inputs (repeatable flags) -----------------------------

  protein:
    type:
      - "null"
      - type: array
        items: File
        inputBinding:
          prefix: --protein
          position: 2
    doc: "Protein FASTA file(s) — repeatable for multi-chain"

  dna:
    type:
      - "null"
      - type: array
        items: File
        inputBinding:
          prefix: --dna
          position: 2
    doc: "DNA FASTA file(s) — repeatable"

  rna:
    type:
      - "null"
      - type: array
        items: File
        inputBinding:
          prefix: --rna
          position: 2
    doc: "RNA FASTA file(s) — repeatable"

  ligand:
    type:
      - "null"
      - type: array
        items: string
        inputBinding:
          prefix: --ligand
          position: 2
    doc: "Ligand CCD code(s) — repeatable"

  smiles:
    type:
      - "null"
      - type: array
        items: string
        inputBinding:
          prefix: --smiles
          position: 2
    doc: "SMILES string(s) — repeatable"

  glycan:
    type:
      - "null"
      - type: array
        items: string
        inputBinding:
          prefix: --glycan
          position: 2
    doc: "Glycan specification(s) — repeatable"

  # --- Global options -----------------------------------------------

  output_dir:
    type: string?
    default: "output"
    inputBinding:
      prefix: --output-dir
      position: 3
    doc: "Output directory for prediction results [default: output]"

  num_samples:
    type: int?
    default: 1
    inputBinding:
      prefix: --num-samples
      position: 2
    doc: "Number of structure samples to generate (Boltz, Chai) [default: 1]"

  num_recycles:
    type: int?
    default: 3
    inputBinding:
      prefix: --num-recycles
      position: 2
    doc: "Number of recycling iterations [default: 3]"

  seed:
    type: int?
    inputBinding:
      prefix: --seed
      position: 2
    doc: "Random seed for reproducibility [default: none]"

  msa:
    type: File?
    inputBinding:
      prefix: --msa
      position: 2
    doc: "Pre-computed MSA file (.a3m, .sto, .pqt)"

  output_format:
    type:
      - "null"
      - type: enum
        symbols: [pdb, mmcif]
    default: pdb
    inputBinding:
      prefix: --output-format
      position: 2
    doc: "Output structure format [default: pdb]"

  # --- Execution options --------------------------------------------

  device:
    type:
      - "null"
      - type: enum
        symbols: [gpu, cpu]
    default: gpu
    inputBinding:
      prefix: --device
      position: 2
    doc: "Compute device [default: gpu]"

  # --- Boltz-2 / Chai-1 options ------------------------------------

  sampling_steps:
    type: int?
    default: 200
    inputBinding:
      prefix: --sampling-steps
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "boltz" || inputs.tool === "chai") {
            return self;
          }
          return null;
        }
    doc: "Diffusion sampling steps (Boltz, Chai) [default: 200]"

  use_msa_server:
    type: boolean?
    default: false
    inputBinding:
      prefix: --use-msa-server
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "boltz" || inputs.tool === "chai") {
            return self;
          }
          return null;
        }
    doc: "Use remote MSA server for alignment generation (Boltz, Chai) [default: false]"

  msa_server_url:
    type: string?
    inputBinding:
      prefix: --msa-server-url
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "boltz" || inputs.tool === "chai") {
            return self;
          }
          return null;
        }
    doc: "Custom MSA server URL; implies use_msa_server (Boltz, Chai)"

  # --- Boltz-2 only ------------------------------------------------

  use_potentials:
    type: boolean?
    default: false
    inputBinding:
      prefix: --use-potentials
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "boltz") {
            return self;
          }
          return null;
        }
    doc: "Enable inference-time potentials (Boltz only) [default: false]"

  # --- Chai-1 only ------------------------------------------------

  no_esm_embeddings:
    type: boolean?
    default: false
    inputBinding:
      prefix: --no-esm-embeddings
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "chai") {
            return self;
          }
          return null;
        }
    doc: "Disable ESM2 language model embeddings (Chai only) [default: false]"

  use_templates_server:
    type: boolean?
    default: false
    inputBinding:
      prefix: --use-templates-server
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "chai") {
            return self;
          }
          return null;
        }
    doc: "Use PDB template server (Chai only) [default: false]"

  constraint_path:
    type: File?
    inputBinding:
      prefix: --constraint-path
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "chai") {
            return self;
          }
          return null;
        }
    doc: "Constraint JSON file (Chai only)"

  template_hits_path:
    type: File?
    inputBinding:
      prefix: --template-hits-path
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "chai") {
            return self;
          }
          return null;
        }
    doc: "Pre-computed template hits file (Chai only)"

  num_trunk_samples:
    type: int?
    default: 1
    inputBinding:
      prefix: --num-trunk-samples
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "chai") {
            return self;
          }
          return null;
        }
    doc: "Trunk samples per prediction (Chai only) [default: 1]"

  recycle_msa_subsample:
    type: int?
    default: 0
    inputBinding:
      prefix: --recycle-msa-subsample
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "chai") {
            return self;
          }
          return null;
        }
    doc: "MSA subsample per recycle (Chai only) [default: 0 = all]"

  no_low_memory:
    type: boolean?
    default: false
    inputBinding:
      prefix: --no-low-memory
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "chai") {
            return self;
          }
          return null;
        }
    doc: "Disable low-memory mode (Chai only) [default: false]"

  # --- AlphaFold 2 options -----------------------------------------

  af2_data_dir:
    type: Directory?
    inputBinding:
      prefix: --af2-data-dir
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "alphafold") {
            if (self) { return self; }
            return "/local_databases/alphafold/databases";
          }
          return null;
        }
    doc: "AlphaFold2 database directory [default: /local_databases/alphafold/databases]"

  af2_model_preset:
    type: string?
    default: "monomer"
    inputBinding:
      prefix: --af2-model-preset
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "alphafold") {
            return self;
          }
          return null;
        }
    doc: "AlphaFold2 model preset (monomer, monomer_casp14, multimer) [default: monomer]"

  af2_db_preset:
    type: string?
    default: "reduced_dbs"
    inputBinding:
      prefix: --af2-db-preset
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "alphafold") {
            return self;
          }
          return null;
        }
    doc: "AlphaFold2 database preset (full_dbs, reduced_dbs) [default: reduced_dbs]"

  af2_max_template_date:
    type: string?
    default: "2022-01-01"
    inputBinding:
      prefix: --af2-max-template-date
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "alphafold") {
            return self;
          }
          return null;
        }
    doc: "Maximum template date for AlphaFold2 (YYYY-MM-DD) [default: 2022-01-01]"

  # --- ESMFold options ----------------------------------------------

  fp16:
    type: boolean?
    default: false
    inputBinding:
      prefix: --fp16
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "esmfold") {
            return self;
          }
          return null;
        }
    doc: "Use half-precision (FP16) inference (ESMFold only) [default: false]"

  chunk_size:
    type: int?
    inputBinding:
      prefix: --chunk-size
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "esmfold") {
            return self;
          }
          return null;
        }
    doc: "Chunk size for long sequences (ESMFold only)"

  max_tokens_per_batch:
    type: int?
    inputBinding:
      prefix: --max-tokens-per-batch
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "esmfold") {
            return self;
          }
          return null;
        }
    doc: "Maximum tokens per batch (ESMFold only)"

  # --- OpenFold 3 options -------------------------------------------

  num_diffusion_samples:
    type: int?
    inputBinding:
      prefix: --num-diffusion-samples
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "openfold") {
            return self;
          }
          return null;
        }
    doc: "Number of diffusion samples (OpenFold only)"

  num_model_seeds:
    type: int?
    inputBinding:
      prefix: --num-model-seeds
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "openfold") {
            return self;
          }
          return null;
        }
    doc: "Number of independent model seeds (OpenFold only)"

  use_templates:
    type: boolean?
    inputBinding:
      prefix: --use-templates
      position: 2
      valueFrom: |
        ${
          if (inputs.tool === "openfold") {
            return self;
          }
          return null;
        }
    doc: "Use template structures (OpenFold only) [default: true]"

# ===================================================================
#  Outputs
# ===================================================================

outputs:
  predictions:
    type: Directory
    outputBinding:
      glob: $(inputs.output_dir)
    doc: "Directory containing all prediction outputs"

  structure_files:
    type: File[]?
    outputBinding:
      glob: |
        ${
          if (inputs.output_format === "mmcif") {
            return inputs.output_dir + "/**/*.cif";
          }
          return inputs.output_dir + "/**/*.pdb";
        }
    doc: "Predicted structure files (PDB or mmCIF)"

  metadata:
    type: File?
    outputBinding:
      glob: "$(inputs.output_dir)/metadata.json"
    doc: "Prediction metadata (tool, parameters, runtime, version)"

  confidence:
    type: File?
    outputBinding:
      glob: "$(inputs.output_dir)/confidence.json"
    doc: "Confidence scores (pLDDT, pTM, per-residue)"

  results:
    type: File?
    outputBinding:
      glob: "$(inputs.output_dir)/results.json"
    doc: "Summary + file manifest (sha256, size) for downstream pipelines"

  ro_crate:
    type: File?
    outputBinding:
      glob: "$(inputs.output_dir)/ro-crate-metadata.json"
    doc: "RO-Crate 1.1 Process Run Crate provenance (best-effort)"

  reports:
    type: Directory?
    outputBinding:
      glob: "$(inputs.output_dir)/report"
    doc: "Characterization reports (report.html/json/pdf) from protein_compare"

stdout: predict-structure.log
stderr: predict-structure.err

s:author:
  - class: s:Person
    s:name: BV-BRC Team
    s:email: help@bv-brc.org

s:license: https://spdx.org/licenses/MIT

$namespaces:
  cwltool: http://commonwl.org/cwltool#
  s: https://schema.org/

$schemas:
  - https://schema.org/version/latest/schemaorg-current-https.rdf
