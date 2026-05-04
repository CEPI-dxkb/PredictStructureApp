cwlVersion: v1.2
class: CommandLineTool

label: "OpenFold 3 Structure Prediction"
doc: |
  Runs run_openfold predict inside the all-in-one container.
  Inputs match the native OpenFold 3 CLI flags.

requirements:
  InitialWorkDirRequirement:
    listing:
      - $(inputs.query_json)
  NetworkAccess:
    networkAccess: true
  ResourceRequirement:
    coresMin: 8
    ramMin: 65536
    ramMax: 98304

hints:
  DockerRequirement:
    dockerPull: folding_prod.sif
    dockerImageId: /scout/containers/folding_prod.sif
  cwltool:CUDARequirement:
    cudaVersionMin: "12.1"
    cudaDeviceCountMin: 1
    cudaDeviceCountMax: 1
  gowe:Execution:
    executor: worker
  gowe:ResourceData:
    datasets:
      - id: openfold
        path: /local_databases/openfold
        size: 10GB
        mode: cache

baseCommand: [/opt/conda-openfold/bin/run_openfold, predict]

inputs:
  query_json:
    type: File
    inputBinding:
      prefix: --query-json
    doc: "Input JSON query file"

  output_dir:
    type: string
    default: output
    inputBinding:
      prefix: --output-dir
    doc: "Output directory"

  num_diffusion_samples:
    type: int?
    inputBinding:
      prefix: --num-diffusion-samples
    doc: "Number of diffusion samples per query"

  num_model_seeds:
    type: int?
    inputBinding:
      prefix: --num-model-seeds
    doc: "Number of independent model seeds"

  use_msa_server:
    type: boolean?
    inputBinding:
      prefix: --use-msa-server
    doc: "Use ColabFold MSA server"

  use_templates:
    type: boolean?
    inputBinding:
      prefix: --use-templates
    doc: "Use template structures"

  inference_ckpt_name:
    type: string?
    inputBinding:
      prefix: --inference-ckpt-name
    doc: "Model checkpoint name"

  model_cache_dir:
    type: string?
    default: /local_databases/openfold
    inputBinding:
      prefix: --inference-ckpt-path
    doc: "Local directory for model weights"

outputs:
  predictions:
    type: Directory
    outputBinding:
      glob: $(inputs.output_dir)

stdout: openfold.log
stderr: openfold.err

$namespaces:
  cwltool: http://commonwl.org/cwltool#
  gowe: https://github.com/wilke/GoWe#
