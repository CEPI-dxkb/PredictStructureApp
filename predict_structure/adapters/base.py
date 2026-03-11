"""Abstract base adapter for structure prediction tools."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseAdapter(ABC):
    """Base class for tool-specific adapters.

    Each adapter implements four methods that handle the full prediction lifecycle:
    1. prepare_input  — convert universal FASTA/MSA to tool-native format
    2. build_command   — construct the CLI invocation for the tool
    3. run             — execute the prediction (delegates to a backend)
    4. normalize_output — standardize output to unified directory layout

    Subclasses: BoltzAdapter, ChaiAdapter, AlphaFoldAdapter, ESMFoldAdapter
    """

    #: Short tool identifier used in CLI dispatch (e.g. "boltz", "chai", "alphafold", "esmfold")
    tool_name: str = ""

    #: Whether this tool supports MSA input
    supports_msa: bool = True

    #: Whether this tool requires a GPU
    requires_gpu: bool = True

    @abstractmethod
    def prepare_input(
        self,
        input_path: Path,
        output_dir: Path,
        *,
        msa_path: Path | None = None,
        **kwargs: Any,
    ) -> Path:
        """Convert universal input (FASTA + optional MSA) to tool-native format.

        Args:
            input_path: Path to input FASTA or tool-native file.
            output_dir: Working directory for prepared files.
            msa_path: Optional MSA file (.a3m, .sto, .pqt).

        Returns:
            Path to the prepared input file in tool-native format.
        """
        ...

    @abstractmethod
    def build_command(
        self,
        input_path: Path,
        output_dir: Path,
        *,
        num_samples: int = 1,
        num_recycles: int = 3,
        seed: int | None = None,
        device: str = "gpu",
        **kwargs: Any,
    ) -> list[str]:
        """Construct the CLI command for the native tool.

        Args:
            input_path: Prepared input file (from prepare_input).
            output_dir: Where the tool should write results.
            num_samples: Number of structure samples to generate.
            num_recycles: Number of recycling iterations.
            seed: Random seed for reproducibility.
            device: Compute device ("gpu" or "cpu").

        Returns:
            Command as a list of strings (for subprocess).
        """
        ...

    @abstractmethod
    def run(self, command: list[str], **kwargs: Any) -> int:
        """Execute the prediction command.

        Args:
            command: CLI command from build_command.

        Returns:
            Process return code (0 = success).
        """
        ...

    @abstractmethod
    def normalize_output(self, raw_output_dir: Path, output_dir: Path) -> Path:
        """Standardize tool output to unified directory layout.

        Expected output structure:
            output_dir/
            ├── model_1.pdb
            ├── model_1.cif
            ├── confidence.json   # {plddt_mean, ptm, per_residue_plddt[]}
            ├── metadata.json     # {tool, params, runtime, version}
            └── raw/              # Original tool output (unmodified)

        Args:
            raw_output_dir: Directory containing native tool output.
            output_dir: Target directory for normalized output.

        Returns:
            Path to the normalized output directory.
        """
        ...

    def preflight(self) -> dict[str, Any]:
        """Return resource requirements for BV-BRC preflight check.

        Returns:
            Dict with cpu, memory, runtime, storage, and optional policy_data.
        """
        return {
            "cpu": 8,
            "memory": "64G",
            "runtime": 7200,
            "storage": "50G",
        }
