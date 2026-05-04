"""Helpers for Phase 3 workspace tests.

Shared by `test_phase3_workspace.py` (pure workspace ops) and
`test_phase3_appscript_workspace.py` (service script + workspace roundtrips).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime


def parse_ws_user(token_text: str) -> str:
    """Extract the workspace user (e.g. 'awilke@bvbrc') from a .patric_token.

    Token format: 'un=<user>@<domain>|tokenid=...'
    Returns: '<user>@<domain>' (e.g. 'awilke@bvbrc').
    """
    for part in token_text.split("|"):
        if part.startswith("un="):
            return part[3:]
    raise ValueError("Could not find 'un=' field in token")


def ws_home(token_text: str) -> str:
    """Return the workspace home path for the token's user."""
    return f"/{parse_ws_user(token_text)}/home"


def ws_apptests(token_text: str) -> str:
    """Return the dedicated folder under home for app-script tests.

    All Phase 3 workspace tests write under this folder so test artifacts
    are isolated from the user's own workspace content. The folder persists
    across runs; individual tests clean up their own sub-folders.
    """
    return f"{ws_home(token_text)}/AppTests"


def ensure_ws_dirs(container, token: str, *paths: str) -> None:
    """Create workspace directories, idempotent. Creates each path in order
    so parents exist before children (p3-mkdir has no -p flag)."""
    for path in paths:
        container.exec(
            ["p3-mkdir", path],
            gpu=False,
            env={"KB_AUTH_TOKEN": token},
            timeout=30,
        )


def make_output_path(container, token: str, tool: str, testname: str) -> str:
    """Build a unique, conventional workspace path for a test's output.

    Convention: {AppTests}/{tool}/{testname}-{YYYYMMDD-HHMMSS}/

    Creates {AppTests} and {AppTests}/{tool} if missing (the timestamped
    leaf is intentionally NOT created -- the service script or test does
    that so p3-cp creates it fresh with the right contents).
    """
    apptests = ws_apptests(token)
    tool_dir = f"{apptests}/{tool}"
    ensure_ws_dirs(container, token, apptests, tool_dir)
    # Timestamp + 8-hex UUID suffix so parallel pytest workers don't
    # collide when starting in the same wall-clock second.
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{tool_dir}/{testname}-{ts}-{uuid.uuid4().hex[:8]}"


def upload_test_input(
    container,
    token: str,
    local_host_dir,
    filename: str,
    testname: str,
) -> str:
    """Upload a test input FASTA from the host to a staging workspace path.

    The staging path is in a sibling `_inputs/` dir so it does NOT pre-create
    the test's output dir (which would cause p3-cp to nest results under
    `output/` on upload). Layout:
        {AppTests}/_inputs/{testname}-{ts}-{filename}

    Args:
        container: ApptainerRunner fixture.
        token: workspace auth token.
        local_host_dir: host path mounted as /data inside the container.
        filename: basename of the FASTA inside local_host_dir.
        testname: used in the staged filename for cleanup + identification.

    Returns:
        Full workspace path to the uploaded file.
    """
    apptests = ws_apptests(token)
    inputs_dir = f"{apptests}/_inputs"
    ensure_ws_dirs(container, token, apptests, inputs_dir)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    ws_path = f"{inputs_dir}/{testname}-{ts}-{suffix}-{filename}"
    result = container.exec(
        ["p3-cp", f"/data/{filename}", f"ws:{ws_path}"],
        gpu=False,
        env={"KB_AUTH_TOKEN": token},
        binds={str(local_host_dir): "/data"},
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Input upload failed: {result.stderr}")
    return ws_path


def expand_ws_placeholders(text: str, token_text: str) -> str:
    """Expand ``${WS_HOME}`` / ``${WS_USER}`` placeholders in a string.

    Used by the Phase 3 service-script params files so the canonical
    ``output_path`` doesn't have to hard-code a particular workspace
    user. Generator emits e.g.::

        "output_path": "${WS_HOME}/AppTests/tier1_boltz_test"

    At test-time / run-time the placeholder is replaced with the real
    workspace path derived from the token.

    Supported placeholders:
      ${WS_USER}  ->  ``<user>@<domain>``  (e.g. ``awilke@bvbrc``)
      ${WS_HOME}  ->  ``/<user>@<domain>/home``
    """
    user = parse_ws_user(token_text)
    home = ws_home(token_text)
    return text.replace("${WS_HOME}", home).replace("${WS_USER}", user)


def cleanup_ws(container, token: str, path: str) -> None:
    """Recursively delete a workspace path, unless PREDICT_STRUCTURE_KEEP_WORKSPACE=1.

    When keep mode is on, logs the path (captured in pytest -s / log) so the
    artifacts can be inspected with `p3-ls` / `p3-cp` after the run.
    """
    if os.environ.get("PREDICT_STRUCTURE_KEEP_WORKSPACE", "").lower() in ("1", "true", "yes"):
        print(f"\n[keep-workspace] Leaving artifacts in workspace: {path}")
        return
    container.exec(
        ["p3-rm", "-r", path],
        gpu=False,
        env={"KB_AUTH_TOKEN": token},
        timeout=30,
    )
