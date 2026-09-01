"""Tests for App-PredictStructure.pl behaviours that unit tests can reach.

The service script is Perl, so these extract the relevant sub and execute
it, rather than asserting on source text alone where behaviour is testable.
"""
import os
import subprocess
from pathlib import Path

class TestPeekFileLinesShellSafety:
    """_peek_file_lines must not build a shell string from a workspace path.

    $source is submitter-chosen (input_file / dna_file / rna_file /
    msa_file). The previous implementation interpolated it into
    "p3-cat '$source' ... | head", so a single quote in the workspace
    object name escaped the quoting and the remainder ran as the service
    user. Demonstrated with a harmless payload before the fix.
    """

    SCRIPT = Path(__file__).parent.parent / "service-scripts" / "App-PredictStructure.pl"

    def test_no_shell_interpolation_of_the_path(self):
        src = self.SCRIPT.read_text()
        block = src[src.index("sub _peek_file_lines"):]
        block = block[:block.index("\nsub ")]
        # Comments may legitimately mention the old shell form; only the
        # executable lines matter here.
        code = "\n".join(l for l in block.splitlines()
                         if not l.lstrip().startswith("#"))
        assert "`" not in code, "backticks run a shell; use list-form open"
        assert "p3-cat '$source'" not in code
        assert 'open(my $ph, "-|", "p3-cat", $source)' in block, \
            "workspace path must be passed as an argv element, not a shell string"

    def test_injection_payload_does_not_execute(self, tmp_path):
        """Run the real sub with a hostile path and a stub p3-cat."""
        stub = tmp_path / "bin"
        stub.mkdir()
        (stub / "p3-cat").write_text("#!/bin/sh\nexit 0\n")
        (stub / "p3-cat").chmod(0o755)
        marker = tmp_path / "PWNED"
        hostile = f"/ws/home/x'; touch {marker}; echo '.fasta"

        src = self.SCRIPT.read_text()
        sub = src[src.index("sub _peek_file_lines"):]
        sub = sub[:sub.index("\nsub ")]
        harness = sub + '\nmy @l = _peek_file_lines($ARGV[0], 5);\n'

        env = dict(os.environ, PATH=f"{stub}:{os.environ['PATH']}")
        subprocess.run(["perl", "-e", harness, hostile],
                       capture_output=True, text=True, timeout=60, env=env)
        assert not marker.exists(), "shell injection executed the payload"
