cwlVersion: v1.2
class: CommandLineTool

label: "AlphaFold 2 Structure Prediction"
doc: |
  Runs AlphaFold 2 inside the all-in-one container.
  Database sub-paths are derived from data_dir automatically.

requirements:
  InlineJavascriptRequirement: {}
  InitialWorkDirRequirement:
    listing:
      - $(inputs.fasta_paths)
  NetworkAccess:
    networkAccess: true
  ResourceRequirement:
    coresMin: 8
    ramMin: 65536
    ramMax: 98304

hints:
  DockerRequirement:
    dockerPull: folding_prod.sif
  cwltool:CUDARequirement:
    cudaVersionMin: "11.8"
    cudaDeviceCountMin: 1
    cudaDeviceCountMax: 1
  gowe:Execution:
    executor: worker
  gowe:ResourceData:
    datasets:
      - id: alphafold
        path: /local_databases/alphafold/databases
        size: 2TB
        mode: prestage

baseCommand: [/opt/conda-alphafold/bin/python, /app/alphafold/run_alphafold.py]

inputs:
  fasta_paths:
    type: File
    inputBinding:
      prefix: --fasta_paths
    doc: "Input FASTA file"

  output_dir:
    type: string
    default: output
    inputBinding:
      prefix: --output_dir
    doc: "Output directory"

  data_dir:
    type: string
    default: /local_databases/alphafold/databases
    inputBinding:
      prefix: --data_dir
    doc: "AlphaFold database directory (~2TB)"

  model_preset:
    type: string?
    default: monomer
    inputBinding:
      prefix: --model_preset
    doc: "Model preset (monomer, monomer_casp14, multimer)"

  db_preset:
    type: string?
    default: reduced_dbs
    inputBinding:
      prefix: --db_preset
    doc: "Database preset (reduced_dbs, full_dbs)"

  max_template_date:
    type: string?
    default: "2022-01-01"
    inputBinding:
      prefix: --max_template_date
    doc: "Maximum template date (YYYY-MM-DD)"

  random_seed:
    type: int?
    inputBinding:
      prefix: --random_seed
    doc: "Random seed"

  use_gpu_relax:
    type: boolean?
    default: false
    doc: "Use GPU for relaxation"

  use_precomputed_msas:
    type: boolean?
    doc: "Use precomputed MSAs"

# Database sub-paths derived from data_dir
arguments:
  - prefix: --uniref90_database_path
    valueFrom: $(inputs.data_dir + "/uniref90/uniref90.fasta")
  - prefix: --mgnify_database_path
    valueFrom: $(inputs.data_dir + "/mgnify/mgy_clusters_2022_05.fa")
  - prefix: --template_mmcif_dir
    valueFrom: $(inputs.data_dir + "/pdb_mmcif/mmcif_files")
  - prefix: --obsolete_pdbs_path
    valueFrom: $(inputs.data_dir + "/pdb_mmcif/obsolete.dat")
  # reduced_dbs → small_bfd
  - valueFrom: |-
      ${
        if (inputs.db_preset === "reduced_dbs" || !inputs.db_preset) {
          return "--small_bfd_database_path=" + inputs.data_dir + "/small_bfd/bfd-first_non_consensus_sequences.fasta";
        }
        return null;
      }
  # full_dbs → bfd + uniref30
  - valueFrom: |-
      ${
        if (inputs.db_preset === "full_dbs") {
          return "--bfd_database_path=" + inputs.data_dir + "/bfd/bfd_metaclust_clu_complete_id30_c90_final_seq.sorted_opt";
        }
        return null;
      }
  - valueFrom: |-
      ${
        if (inputs.db_preset === "full_dbs") {
          return "--uniref30_database_path=" + inputs.data_dir + "/uniref30/UniRef30_2021_03";
        }
        return null;
      }
  # monomer → pdb70
  - valueFrom: |-
      ${
        var preset = inputs.model_preset || "monomer";
        if (preset.indexOf("monomer") === 0) {
          return "--pdb70_database_path=" + inputs.data_dir + "/pdb70/pdb70";
        }
        return null;
      }
  # multimer → pdb_seqres + uniprot
  - valueFrom: |-
      ${
        if (inputs.model_preset === "multimer") {
          return "--pdb_seqres_database_path=" + inputs.data_dir + "/pdb_seqres/pdb_seqres.txt";
        }
        return null;
      }
  - valueFrom: |-
      ${
        if (inputs.model_preset === "multimer") {
          return "--uniprot_database_path=" + inputs.data_dir + "/uniprot/uniprot.fasta";
        }
        return null;
      }
  # use_gpu_relax (absl boolean: --use_gpu_relax or --nouse_gpu_relax)
  - valueFrom: |-
      ${
        if (inputs.use_gpu_relax !== null && inputs.use_gpu_relax !== undefined) {
          return inputs.use_gpu_relax ? "--use_gpu_relax" : "--nouse_gpu_relax";
        }
        return null;
      }
  # use_precomputed_msas (absl boolean)
  - valueFrom: |-
      ${
        if (inputs.use_precomputed_msas !== null && inputs.use_precomputed_msas !== undefined) {
          return inputs.use_precomputed_msas ? "--use_precomputed_msas" : "--nouse_precomputed_msas";
        }
        return null;
      }

outputs:
  predictions:
    type: Directory
    outputBinding:
      glob: $(inputs.output_dir)

stdout: alphafold.log
stderr: alphafold.err

$namespaces:
  cwltool: http://commonwl.org/cwltool#
  gowe: https://github.com/wilke/GoWe#
