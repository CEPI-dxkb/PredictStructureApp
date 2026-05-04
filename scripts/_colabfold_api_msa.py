#!/usr/bin/env python3
"""Fetch an A3M MSA from the ColabFold MMseqs2 web service.

Used as a fallback when colabfold_search isn't installed locally and the
SIF doesn't ship it either. Direct REST calls to api.colabfold.com.

Usage:
    python scripts/_colabfold_api_msa.py <input.fasta> <output.a3m>
"""

from __future__ import annotations

import io
import sys
import tarfile
import time
from pathlib import Path

import requests

API_BASE = "https://api.colabfold.com"
POLL_INTERVAL = 10  # seconds
MAX_WAIT = 1800  # 30 min hard cap


def _fasta_query(fasta_path: Path) -> str:
    """Return a single-sequence FASTA string for the API.

    The ColabFold API expects ONE query sequence per ticket. We strip
    any inline newlines / multi-chain content and use only the first
    record's sequence.
    """
    seq_lines: list[str] = []
    with fasta_path.open() as fh:
        in_first = False
        for line in fh:
            if line.startswith(">"):
                if in_first:
                    break
                in_first = True
                seq_lines.append(line.rstrip())
            else:
                if in_first:
                    seq_lines.append(line.rstrip())
    return "\n".join(seq_lines)


def submit(query_fasta: str) -> str:
    print(f"  -> submitting query ({len(query_fasta.splitlines())} lines)")
    resp = requests.post(
        f"{API_BASE}/ticket/msa",
        data={"q": query_fasta, "mode": "env"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    ticket = data.get("id")
    if not ticket:
        raise RuntimeError(f"unexpected submit response: {data}")
    print(f"  -> ticket: {ticket}")
    return ticket


def poll(ticket: str) -> None:
    deadline = time.time() + MAX_WAIT
    last_status = None
    while time.time() < deadline:
        r = requests.get(f"{API_BASE}/ticket/{ticket}", timeout=30)
        r.raise_for_status()
        status = r.json().get("status")
        if status != last_status:
            print(f"  -> status: {status}")
            last_status = status
        if status == "COMPLETE":
            return
        if status == "ERROR":
            raise RuntimeError(f"ColabFold API returned ERROR for {ticket}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"ticket {ticket} not complete after {MAX_WAIT}s")


def download(ticket: str, out_path: Path) -> None:
    """Download the result tarball, extract the a3m, write to out_path."""
    print("  -> downloading result tarball")
    r = requests.get(
        f"{API_BASE}/result/download/{ticket}",
        timeout=120,
        stream=True,
    )
    r.raise_for_status()
    blob = io.BytesIO(r.content)
    with tarfile.open(fileobj=blob) as tar:
        # Look for the env / uniref a3m. Prefer 'uniref.a3m' (most
        # commonly named) but fall back to any *.a3m.
        candidates = [m for m in tar.getmembers() if m.name.endswith(".a3m")]
        if not candidates:
            raise RuntimeError(
                f"no .a3m in tarball; members: {[m.name for m in tar.getmembers()]}"
            )
        # Prefer uniref.a3m -> bfd.mgnify30.smag30.a3m -> first
        priority = ["uniref.a3m", "bfd.mgnify30.smag30.a3m"]
        chosen = None
        for p in priority:
            for m in candidates:
                if m.name.endswith(p):
                    chosen = m
                    break
            if chosen:
                break
        if chosen is None:
            chosen = candidates[0]
        print(f"  -> extracting {chosen.name}")
        f = tar.extractfile(chosen)
        if f is None:
            raise RuntimeError(f"failed to extract {chosen.name}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # ColabFold tarballs sometimes pad with a trailing NUL byte that
        # downstream tools (e.g. boltz a3m parser) reject as
        # KeyError: '\x00'. Strip trailing whitespace/nulls and ensure
        # the file ends with a single newline.
        body = f.read().rstrip(b"\x00 \t\r\n")
        out_path.write_bytes(body + b"\n")
        print(f"  -> wrote {out_path} ({out_path.stat().st_size} bytes)")


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    fasta = Path(sys.argv[1])
    out = Path(sys.argv[2])
    if not fasta.is_file():
        print(f"ERROR: {fasta} not found", file=sys.stderr)
        return 1

    print(f"\n=== Generating MSA for {fasta} -> {out} ===")
    query = _fasta_query(fasta)
    ticket = submit(query)
    poll(ticket)
    download(ticket, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
