#!/usr/bin/env python3
"""Expand ${WS_HOME} / ${WS_USER} placeholders in a service-script params file.

Phase 3 service-params templates use bash-style placeholders so they
can be committed without baking in a particular workspace user. This
script reads a token and substitutes the real values.

Usage:
    python scripts/instantiate_params.py <input.json> [--out PATH]

By default writes to stdout. Pass --out to write to a file.

Token resolution order:
    1. --token PATH
    2. $PATRIC_TOKEN_PATH
    3. ~/.patric_token

Placeholders:
    ${WS_USER}  ->  <user>@<domain>   (e.g. awilke@bvbrc)
    ${WS_HOME}  ->  /<user>@<domain>/home

Example:
    # Manual flow: expand a tier params file then hand it to App-PredictStructure.pl
    python scripts/instantiate_params.py \\
        test_data/service_params/tier1_boltz.json \\
        --out /tmp/params.json

    apptainer exec ... folding_prod.sif perl <script.pl> ... /tmp/params.json
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def parse_ws_user(token_text: str) -> str:
    """Extract '<user>@<domain>' from a .patric_token string.

    Token format: 'un=<user>@<domain>|tokenid=...'.
    """
    for part in token_text.split("|"):
        if part.startswith("un="):
            return part[3:]
    raise ValueError("Could not find 'un=' field in token")


def expand_ws_placeholders(text: str, token_text: str) -> str:
    """Replace ${WS_HOME} / ${WS_USER} in `text` using values from `token_text`."""
    user = parse_ws_user(token_text)
    home = f"/{user}/home"
    return text.replace("${WS_HOME}", home).replace("${WS_USER}", user)


def _resolve_token_path(cli_path: str | None) -> Path:
    if cli_path:
        return Path(cli_path)
    env = os.environ.get("PATRIC_TOKEN_PATH")
    if env:
        return Path(env)
    return Path.home() / ".patric_token"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n", 2)[2] if len(__doc__.split("\n\n", 2)) > 2 else "",
    )
    parser.add_argument("input", type=Path,
                        help="Params JSON template with ${WS_*} placeholders")
    parser.add_argument("--out", type=Path, default=None,
                        help="Write expanded JSON here (default: stdout)")
    parser.add_argument("--token", type=str, default=None,
                        help="Path to .patric_token (default: $PATRIC_TOKEN_PATH or ~/.patric_token)")
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 2

    token_path = _resolve_token_path(args.token)
    if not token_path.is_file():
        print(f"ERROR: token not found: {token_path}", file=sys.stderr)
        print("Set PATRIC_TOKEN_PATH or pass --token PATH.", file=sys.stderr)
        return 2

    text = args.input.read_text()
    token = token_path.read_text().strip()
    expanded = expand_ws_placeholders(text, token)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(expanded)
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(expanded)
    return 0


if __name__ == "__main__":
    sys.exit(main())
