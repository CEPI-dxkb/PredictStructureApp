cwlVersion: v1.2
class: CommandLineTool

label: "ESMFold Structure Prediction"
doc: |
  Runs esm-fold-hf inside the all-in-one container.
  Inputs match the native esm-fold-hf CLI flags.

requirements:
  InlineJavascriptRequirement: {}
  InitialWorkDirRequirement:
    listing:
      - $(inputs.sequences)
  EnvVarRequirement:
    envDef:
      HF_HOME: $(inputs.model_cache_dir)
  ResourceRequirement:
    coresMin: 8
    ramMin: 32768

hints:
  DockerRequirement:
    dockerPull: folding_260327.3.sif
  gowe:Execution:
    worker_group: esmfold
  gowe:ResourceData:
    datasets:
      - id: esmfold
        path: /scout/wf/gowe/cache/esmfold
        size: 3GB
        mode: prestage

baseCommand: [/opt/conda-esmfold/bin/esm-fold-hf]

inputs:
  sequences:
    type: File
    inputBinding:
      prefix: -i
    doc: "Input FASTA file"

  output_dir:
    type: string
    default: output
    inputBinding:
      prefix: -o
    doc: "Output directory"

  num_recycles:
    type: int?
    inputBinding:
      prefix: --num-recycles
    doc: "Number of recycling iterations"

  chunk_size:
    type: int?
    inputBinding:
      prefix: --chunk-size
    doc: "Chunk size for long sequences"

  max_tokens_per_batch:
    type: int?
    inputBinding:
      prefix: --max-tokens-per-batch
    doc: "Maximum tokens per batch"

  cpu_only:
    type: boolean?
    inputBinding:
      prefix: --cpu-only
    doc: "Run on CPU only"

  fp16:
    type: boolean?
    inputBinding:
      prefix: --fp16
    doc: "Use half-precision inference"

  model_cache_dir:
    type: string
    default: /scout/wf/gowe/cache/hf
    doc: "Local directory for model weights (HF_HOME)"

outputs:
  predictions:
    type: Directory
    outputBinding:
      glob: $(inputs.output_dir)

stdout: esmfold.log
stderr: esmfold.err

$namespaces:
  cwltool: http://commonwl.org/cwltool#
  gowe: https://github.com/wilke/GoWe#
