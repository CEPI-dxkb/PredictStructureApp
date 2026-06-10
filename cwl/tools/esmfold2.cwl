cwlVersion: v1.2
class: CommandLineTool

label: "ESMFold2 Structure Prediction"
doc: |
  Runs the predict_structure ESMFold2 runner inside the all-in-one container.
  Input is the JSON spec produced by the ESMFold2 adapter (prepare_input),
  not a FASTA — ESMFold2 ships only a Python API, so execution goes through
  predict_structure.runners.esmfold2.

requirements:
  InlineJavascriptRequirement: {}
  InitialWorkDirRequirement:
    listing:
      - $(inputs.spec)
  EnvVarRequirement:
    envDef:
      HF_HOME: $(inputs.model_cache_dir)
  NetworkAccess:
    networkAccess: true
  ResourceRequirement:
    coresMin: 8
    ramMin: 32768

hints:
  DockerRequirement:
    dockerPull: folding_prod.sif
    dockerImageId: /scout/containers/folding_prod.sif
  gowe:Execution:
    worker_group: esmfold2
  gowe:ResourceData:
    datasets:
      - id: esmfold2
        path: /scout/wf/gowe/cache/esmfold2
        size: 12GB
        mode: prestage

baseCommand: [/opt/conda-esmfold2/bin/python, -m, predict_structure.runners.esmfold2]

inputs:
  spec:
    type: File
    inputBinding:
      prefix: --spec
    doc: "ESMFold2 input spec (JSON) written by the adapter"

  output_dir:
    type: string
    default: output
    inputBinding:
      prefix: --output-dir
    doc: "Output directory"

  num_loops:
    type: int?
    inputBinding:
      prefix: --num-loops
    doc: "ESMFold2 num_loops (recycling iterations)"

  num_sampling_steps:
    type: int?
    inputBinding:
      prefix: --num-sampling-steps
    doc: "Diffusion sampling steps"

  num_diffusion_samples:
    type: int?
    inputBinding:
      prefix: --num-diffusion-samples
    doc: "Number of diffusion samples"

  checkpoint:
    type: string?
    inputBinding:
      prefix: --checkpoint
    doc: "HF checkpoint id or path (default biohub/ESMFold2)"

  seed:
    type: int?
    inputBinding:
      prefix: --seed
    doc: "Random seed"

  cpu_only:
    type: boolean?
    inputBinding:
      prefix: --cpu-only
    doc: "Run on CPU only (forces fp32; GPU strongly preferred)"

  model_cache_dir:
    type: string
    default: /scout/wf/gowe/cache/hf
    doc: "Local directory for model weights (HF_HOME)"

outputs:
  predictions:
    type: Directory
    outputBinding:
      glob: $(inputs.output_dir)

stdout: esmfold2.log
stderr: esmfold2.err

$namespaces:
  cwltool: http://commonwl.org/cwltool#
  gowe: https://github.com/wilke/GoWe#
