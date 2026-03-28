"""Execution backends for structure prediction tools."""

from __future__ import annotations

from predict_structure.backends.apptainer import ApptainerBackend
from predict_structure.backends.cwl import CWLBackend
from predict_structure.backends.docker import DockerBackend
from predict_structure.backends.subprocess import SubprocessBackend

BACKENDS: dict[str, type] = {
    "docker": DockerBackend,
    "subprocess": SubprocessBackend,
    "cwl": CWLBackend,
    "apptainer": ApptainerBackend,
}


def get_backend(name: str, **kwargs):
    """Return a backend instance by name.

    Args:
        name: "docker", "subprocess", "cwl", or "apptainer".
        **kwargs: Passed to backend constructor.

    Returns:
        Configured backend instance.

    Raises:
        ValueError: If name is not recognized.
    """
    cls = BACKENDS.get(name)
    if cls is None:
        raise ValueError(f"Unknown backend '{name}'. Choose from: {list(BACKENDS)}")
    return cls(**kwargs)


__all__ = [
    "ApptainerBackend", "CWLBackend", "DockerBackend", "SubprocessBackend",
    "BACKENDS", "get_backend",
]
