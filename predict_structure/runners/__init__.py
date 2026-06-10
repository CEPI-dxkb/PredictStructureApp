"""In-process runners for tools that ship only a Python API (no upstream CLI).

Each runner exposes a small ``argparse`` entry point that the matching adapter
invokes via ``tools.yml`` ``command``. The runner loads a JSON spec written by
the adapter, calls the model's Python API, and writes the raw output the
adapter's ``normalize_output`` expects.
"""
