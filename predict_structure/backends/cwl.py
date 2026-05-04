"""CWL execution backend — unified and per-tool CWL dispatch."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

import yaml

from predict_structure.config import get_cwl_path, get_shared_sif

# Docker image used in per-tool CWL definitions (for singularity cache setup)
_CWL_DOCKER_IMAGE = "dxkb/predict-structure-all:latest-gpu"

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Native CWL input-name mapping per tool (legacy per-tool CWL definitions)
#
# Each entry maps a native CLI flag (as produced by the adapter's
# build_command) to the CWL input name in the per-tool .cwl definition.
# Flags not listed are passed through with underscored names.
# A value of None means "skip this flag".
# ---------------------------------------------------------------------------

_BOLTZ_MAP: dict[str, str | None] = {
    "--out_dir": "output_dir",
    "--diffusion_samples": "diffusion_samples",
    "--recycling_steps": "recycling_steps",
    "--sampling_steps": "sampling_steps",
    "--output_format": "output_format",
    "--write_full_pae": "write_full_pae",
    "--accelerator": "accelerator",
    "--use_msa_server": "use_msa_server",
    "--msa_server_url": "msa_server_url",
    "--use_potentials": "use_potentials",
}

_CHAI_MAP: dict[str, str | None] = {
    "--num-diffn-samples": "num_diffn_samples",
    "--num-trunk-recycles": "num_trunk_recycles",
    "--num-diffn-timesteps": "num_diffn_timesteps",
    "--num-trunk-samples": "num_trunk_samples",
    "--seed": "seed",
    "--device": "device",
    "--msa-directory": "msa_directory",
    "--use-msa-server": "use_msa_server",
    "--msa-server-url": "msa_server_url",
    "--no-use-esm-embeddings": None,  # boolean negation handled separately
    "--use-templates-server": "use_templates_server",
    "--constraint-path": "constraint_path",
    "--template-hits-path": "template_hits_path",
    "--recycle-msa-subsample": "recycle_msa_subsample",
    "--no-low-memory": None,  # boolean negation
}

_ALPHAFOLD_MAP: dict[str, str | None] = {
    "--fasta_paths": None,  # handled as input_file
    "--output_dir": "output_dir",
    "--data_dir": "data_dir",
    "--model_preset": "model_preset",
    "--db_preset": "db_preset",
    "--max_template_date": "max_template_date",
    "--random_seed": "random_seed",
    "--use_gpu_relax": "use_gpu_relax",
    "--use_precomputed_msas": "use_precomputed_msas",
    # Database sub-paths are derived from data_dir inside the container,
    # so we skip them in the job YAML.
    "--uniref90_database_path": None,
    "--mgnify_database_path": None,
    "--template_mmcif_dir": None,
    "--obsolete_pdbs_path": None,
    "--small_bfd_database_path": None,
    "--bfd_database_path": None,
    "--uniref30_database_path": None,
    "--pdb70_database_path": None,
    "--pdb_seqres_database_path": None,
    "--uniprot_database_path": None,
}

_ESMFOLD_MAP: dict[str, str | None] = {
    "-i": None,  # handled as input_file
    "-o": "output_dir",
    "--num-recycles": "num_recycles",
    "--chunk-size": "chunk_size",
    "--max-tokens-per-batch": "max_tokens_per_batch",
    "--cpu-only": "cpu_only",
    "--fp16": "fp16",
}

_TOOL_MAPS: dict[str, dict[str, str | None]] = {
    "boltz": _BOLTZ_MAP,
    "chai": _CHAI_MAP,
    "alphafold": _ALPHAFOLD_MAP,
    "esmfold": _ESMFOLD_MAP,
}

# CWL input name for the input file per tool
_INPUT_FILE_KEY: dict[str, str] = {
    "boltz": "input_file",
    "chai": "input_fasta",
    "alphafold": "fasta_paths",
    "esmfold": "sequences",
}

# CWL input name for the output directory per tool
_OUTPUT_DIR_KEY: dict[str, str] = {
    "boltz": "output_dir",
    "chai": "output_directory",
    "alphafold": "output_dir",
    "esmfold": "output_dir",
}

# Boolean flags per tool (presence = true)
_BOOLEAN_FLAGS_PER_TOOL: dict[str, set[str]] = {
    "boltz": {"--use_msa_server", "--use_potentials", "--write_full_pae"},
    "chai": {"--use-msa-server", "--use-templates-server", "--no-use-esm-embeddings", "--no-low-memory"},
    "alphafold": set(),
    "esmfold": {"--cpu-only", "--fp16"},
}

# Integer-valued flags per tool
_INT_FLAGS_PER_TOOL: dict[str, set[str]] = {
    "boltz": {"--diffusion_samples", "--recycling_steps", "--sampling_steps"},
    "chai": {"--num-diffn-samples", "--num-trunk-recycles", "--num-diffn-timesteps", "--num-trunk-samples", "--seed", "--recycle-msa-subsample"},
    "alphafold": {"--random_seed"},
    "esmfold": {"--num-recycles", "--chunk-size", "--max-tokens-per-batch"},
}

# Flags whose value is = appended (e.g. --use_gpu_relax=true)
_EQUALS_FLAGS = {"--use_gpu_relax", "--use_precomputed_msas"}

# ---------------------------------------------------------------------------
# Mapping from CLI extra_kwargs keys to CWL input names
# (used by build_unified_job for the unified predict-structure.cwl)
# ---------------------------------------------------------------------------

_EXTRA_TO_CWL: dict[str, str] = {
    "boltz_use_potentials": "use_potentials",
    "esm_fp16": "fp16",
    "esm_chunk_size": "chunk_size",
    "esm_max_tokens": "max_tokens_per_batch",
    # These already match CWL input names:
    # sampling_steps, use_msa_server, msa_server_url
    # af2_data_dir, af2_model_preset, af2_db_preset, af2_max_template_date
}

# Keys whose CWL type is Directory (need {class: Directory, path: ...})
_DIRECTORY_KEYS = {"af2_data_dir"}


class CWLBackend:
    """Run predictions via CWL tool definitions.

    Supports two modes:

    1. **Unified** (``build_unified_job`` / ``run_unified``):
       Maps CLI parameters directly to the unified ``predict-structure.cwl``
       inputs.  No per-tool flag parsing needed.

    2. **Legacy** (``_build_job_yaml`` / ``run``):
       Parses native tool commands from ``adapter.build_command()`` and maps
       them to per-tool CWL input names.  Kept for backward compatibility.
    """

    DEFAULT_RUNNER = "cwltool"

    def __init__(
        self,
        cwl_tool: str | Path | None = None,
        runner: str | None = None,
        use_singularity: bool = False,
    ):
        self._cwl_tool_override = str(cwl_tool) if cwl_tool else None
        self._runner = runner or self.DEFAULT_RUNNER
        self._use_singularity = use_singularity

    def _resolve_cwl_tool(self, tool_name: str | None) -> str:
        """Resolve the CWL tool definition path for a given tool."""
        if self._cwl_tool_override:
            return self._cwl_tool_override
        if tool_name:
            path = get_cwl_path(tool_name)
            if path.exists():
                return str(path)
            logger.warning("CWL tool not found at %s", path)
            return str(path)
        raise ValueError("No tool_name provided to resolve CWL tool definition.")

    def _build_cwl_cmd(
        self,
        cwl_tool: str,
        job_path: str,
        outdir: str | None = None,
    ) -> list[str]:
        """Build the cwltool command line."""
        cmd = [self._runner]
        if self._use_singularity:
            cmd.append("--singularity")
        if outdir:
            cmd.extend(["--outdir", outdir])
        cmd.extend([cwl_tool, job_path])
        return cmd

    def _setup_singularity_cache(self) -> str | None:
        """Create a singularity cache dir with a symlink to the configured SIF.

        Returns the cache directory path, or None if no SIF is configured.
        """
        sif = get_shared_sif()
        if not sif or not sif.exists():
            return None

        cache_dir = Path(tempfile.mkdtemp(prefix="cwl-sif-cache-"))
        # cwltool normalizes docker image names: / → _  (colon kept)
        normalized = _CWL_DOCKER_IMAGE.replace("/", "_")
        symlink = cache_dir / (normalized + ".sif")
        symlink.symlink_to(sif)
        logger.info("Singularity cache: %s → %s", symlink, sif)
        return str(cache_dir)

    def _write_and_run(
        self,
        job: dict,
        cwl_tool: str,
        *,
        output_dir: str | None = None,
        timeout: int | None = None,
    ) -> int:
        """Write a job YAML and invoke cwltool."""
        if output_dir:
            job_dir = Path(output_dir)
        else:
            job_dir = Path(tempfile.mkdtemp(prefix="cwl-job-"))
        job_dir.mkdir(parents=True, exist_ok=True)
        job_path = job_dir / "job.yml"
        job_path.write_text(yaml.dump(job, default_flow_style=False))

        cwl_cmd = self._build_cwl_cmd(cwl_tool, str(job_path), outdir=output_dir)
        logger.info("Running: %s", " ".join(cwl_cmd))

        # Set up environment for singularity cache and data bind mounts
        run_env = None
        if self._use_singularity:
            run_env = dict(os.environ)
            cache_dir = self._setup_singularity_cache()
            if cache_dir:
                run_env["CWL_SINGULARITY_CACHE"] = cache_dir
                logger.info("CWL_SINGULARITY_CACHE=%s", cache_dir)
            # Bind-mount data directories so tools can access weights/caches
            from predict_structure.config import get_data_root
            data_root = get_data_root()
            if data_root.exists():
                run_env["SINGULARITY_BIND"] = f"{data_root}:{data_root}"
                logger.info("SINGULARITY_BIND=%s", run_env["SINGULARITY_BIND"])

        result = subprocess.run(cwl_cmd, env=run_env, timeout=timeout)
        return result.returncode

    def _format_job(
        self,
        job: dict,
        cwl_tool: str,
        *,
        output_dir: str | None = None,
    ) -> list[str]:
        """Format a job YAML and return debug output lines."""
        job_yaml = yaml.dump(job, default_flow_style=False, sort_keys=False).rstrip()

        if output_dir is not None:
            job_path = Path(output_dir) / "job.yml"
            job_path.parent.mkdir(parents=True, exist_ok=True)
            job_path.write_text(job_yaml + "\n")
            cwl_cmd_str = " ".join(self._build_cwl_cmd(cwl_tool, str(job_path)))
        else:
            cwl_cmd_str = " ".join(self._build_cwl_cmd(cwl_tool, "job.yml"))

        lines = [cwl_cmd_str]
        lines.append("# --- job.yml ---")
        for line in job_yaml.splitlines():
            lines.append(f"# {line}")
        return lines

    # -----------------------------------------------------------------------
    # Unified CWL interface (predict-structure.cwl with entity inputs)
    # -----------------------------------------------------------------------

    def build_unified_job(
        self,
        tool_name: str,
        entity_inputs: dict,
        *,
        output_dir: str,
        num_samples: int = 1,
        num_recycles: int = 3,
        seed: int | None = None,
        device: str = "gpu",
        msa: str | None = None,
        output_format: str = "pdb",
        **extra_kwargs,
    ) -> dict:
        """Build a CWL job dict for the unified predict-structure.cwl tool.

        Args:
            tool_name: Tool subcommand (boltz, chai, alphafold, esmfold, auto).
            entity_inputs: Raw CLI entity options — ``{"protein": ("/path",), ...}``.
            output_dir: Output directory path.
            num_samples: Number of structure samples.
            num_recycles: Recycling iterations.
            seed: Random seed (None = not set).
            device: Compute device (gpu/cpu).
            msa: MSA file path (None = not set).
            output_format: Output format (pdb/mmcif).
            **extra_kwargs: Tool-specific options from CLI subcommands.

        Returns:
            CWL job dict ready for YAML serialization.
        """
        job: dict = {
            "tool": tool_name,
            "output_dir": output_dir,
            "num_samples": num_samples,
            "num_recycles": num_recycles,
            "device": device,
            "output_format": output_format,
        }

        # Entity file inputs (protein, dna, rna → File arrays)
        for entity_type in ("protein", "dna", "rna"):
            paths = entity_inputs.get(entity_type, ())
            if paths:
                job[entity_type] = [
                    {"class": "File", "path": str(Path(p).resolve())}
                    for p in paths
                ]

        # Inline entity inputs (ligand, smiles, glycan → string arrays)
        for entity_type in ("ligand", "smiles", "glycan"):
            values = entity_inputs.get(entity_type, ())
            if values:
                job[entity_type] = list(values)

        # Optional shared options
        if seed is not None:
            job["seed"] = seed
        if msa:
            job["msa"] = {"class": "File", "path": str(Path(msa).resolve())}

        # Tool-specific options
        for k, v in extra_kwargs.items():
            if v is None or v is False:
                continue
            # Map CLI extra name to CWL input name
            cwl_key = _EXTRA_TO_CWL.get(k, k)
            # Directory-typed inputs
            if cwl_key in _DIRECTORY_KEYS:
                job[cwl_key] = {"class": "Directory", "path": str(Path(v).resolve())}
            else:
                job[cwl_key] = v

        return job

    def run_unified(
        self,
        job: dict,
        *,
        tool_name: str | None = None,
        output_dir: str | None = None,
        timeout: int | None = None,
        **kwargs,
    ) -> int:
        """Run a unified CWL job (from build_unified_job).

        Returns:
            Exit code from the CWL runner.
        """
        cwl_tool = self._resolve_cwl_tool(tool_name)
        return self._write_and_run(
            job, cwl_tool, output_dir=output_dir, timeout=timeout,
        )

    def format_unified_command(
        self,
        job: dict,
        *,
        tool_name: str | None = None,
        output_dir: str | None = None,
    ) -> list[str]:
        """Format a unified CWL job for debug output."""
        cwl_tool = self._resolve_cwl_tool(tool_name)
        return self._format_job(job, cwl_tool, output_dir=output_dir)

    # -----------------------------------------------------------------------
    # Legacy per-tool CWL interface (adapter command → per-tool .cwl)
    # -----------------------------------------------------------------------

    def format_command(
        self,
        command: list[str],
        **kwargs,
    ) -> list[str]:
        """Write a CWL job YAML and return the cwltool command line."""
        tool_name = kwargs.get("tool_name")
        output_dir = kwargs.get("output_dir")
        cwl_tool = self._resolve_cwl_tool(tool_name)
        job = self._build_job_yaml(command, tool_name)
        return self._format_job(job, cwl_tool, output_dir=output_dir)

    def run(
        self,
        command: list[str],
        *,
        tool_name: str | None = None,
        gpu: bool = True,
        timeout: int | None = None,
        **kwargs,
    ) -> int:
        """Build a CWL job YAML from a native command and invoke the runner.

        Args:
            command: Native tool command list from adapter.build_command().
            tool_name: Tool name (boltz, chai, alphafold, esmfold).
            gpu: Whether GPU is requested (encoded in CWL hints).
            timeout: Max seconds for the CWL runner.

        Returns:
            Exit code from the CWL runner.
        """
        cwl_tool = self._resolve_cwl_tool(tool_name)
        job = self._build_job_yaml(command, tool_name)
        output_dir = kwargs.get("output_dir")
        return self._write_and_run(
            job, cwl_tool, output_dir=output_dir, timeout=timeout,
        )

    def _build_job_yaml(
        self,
        command: list[str],
        tool_name: str | None,
    ) -> dict:
        """Parse a native tool command into a CWL job dict.

        Uses per-tool flag maps to translate native CLI flags into the
        CWL input names defined in each tool's ``.cwl`` definition.
        """
        flag_map = _TOOL_MAPS.get(tool_name or "", {})
        bool_flags = _BOOLEAN_FLAGS_PER_TOOL.get(tool_name or "", set())
        int_flags = _INT_FLAGS_PER_TOOL.get(tool_name or "", set())
        input_key = _INPUT_FILE_KEY.get(tool_name or "", "input_file")
        output_key = _OUTPUT_DIR_KEY.get(tool_name or "", "output_dir")

        job: dict = {}

        # Find input file and output dir from positional/flag args
        input_file, output_dir = self._find_io_paths(command, tool_name)
        if input_file:
            job[input_key] = {"class": "File", "path": str(input_file)}
        if output_dir:
            # CWL runs in a sandboxed workdir — use relative output path
            job[output_key] = "output"

        # Parse flags
        i = 0
        while i < len(command):
            arg = command[i]

            # Handle --flag=value syntax (e.g. --use_gpu_relax=true)
            if "=" in arg and arg.startswith("--"):
                flag, val = arg.split("=", 1)
                cwl_name = flag_map.get(flag)
                if cwl_name is None:
                    i += 1
                    continue
                if val.lower() in ("true", "false"):
                    job[cwl_name] = val.lower() == "true"
                else:
                    job[cwl_name] = val
                i += 1
                continue

            if arg.startswith("-"):
                cwl_name = flag_map.get(arg)

                # Explicitly skipped
                if cwl_name is None and arg in flag_map:
                    # Skip flag + its value if it has one
                    if arg not in bool_flags and i + 1 < len(command) and not command[i + 1].startswith("-"):
                        i += 2
                    else:
                        i += 1
                    continue

                # Unknown flag — skip
                if cwl_name is None:
                    if arg in bool_flags:
                        i += 1
                    elif i + 1 < len(command) and not command[i + 1].startswith("-"):
                        i += 2
                    else:
                        i += 1
                    continue

                # Boolean flag
                if arg in bool_flags:
                    job[cwl_name] = True
                    i += 1
                    continue

                # Flag with value
                if i + 1 < len(command):
                    val = command[i + 1]
                    if arg in int_flags:
                        job[cwl_name] = int(val)
                    elif cwl_name == output_key:
                        # CWL runs in sandboxed workdir — use relative path
                        job[cwl_name] = "output"
                    else:
                        job[cwl_name] = val
                    i += 2
                else:
                    i += 1
            else:
                i += 1

        return job

    @staticmethod
    def _find_io_paths(
        command: list[str],
        tool_name: str | None,
    ) -> tuple[Path | None, Path | None]:
        """Extract input file and output directory from a native command."""
        input_file: Path | None = None
        output_dir: Path | None = None

        if tool_name == "boltz":
            # boltz predict <input> --out_dir <output>
            for i, arg in enumerate(command):
                if arg == "--out_dir" and i + 1 < len(command):
                    output_dir = Path(command[i + 1])
            # Input is first positional after "predict"
            for i, arg in enumerate(command):
                if arg == "predict" and i + 1 < len(command):
                    input_file = Path(command[i + 1])
                    break

        elif tool_name == "chai":
            # chai-lab fold <input> <output>
            # command may use full paths: /opt/conda-chai/bin/chai-lab fold ...
            _chai_skip = {"chai-lab", "fold"}
            positionals = []
            i = 0
            while i < len(command):
                if command[i].startswith("-"):
                    # Skip flag + value
                    i += 2 if (i + 1 < len(command) and not command[i + 1].startswith("-")) else 1
                    continue
                basename = Path(command[i]).name
                if basename not in _chai_skip:
                    positionals.append(command[i])
                i += 1
            if len(positionals) >= 1:
                input_file = Path(positionals[0])
            if len(positionals) >= 2:
                output_dir = Path(positionals[1])

        elif tool_name == "alphafold":
            # python /app/alphafold/run_alphafold.py --fasta_paths <input> --output_dir <output>
            for i, arg in enumerate(command):
                if arg == "--fasta_paths" and i + 1 < len(command):
                    input_file = Path(command[i + 1])
                elif arg == "--output_dir" and i + 1 < len(command):
                    output_dir = Path(command[i + 1])

        elif tool_name == "esmfold":
            # esm-fold-hf -i <input> -o <output>
            for i, arg in enumerate(command):
                if arg == "-i" and i + 1 < len(command):
                    input_file = Path(command[i + 1])
                elif arg == "-o" and i + 1 < len(command):
                    output_dir = Path(command[i + 1])

        return input_file, output_dir
