"""Tests for the MSA input-format precheck."""

from __future__ import annotations

import pytest

from predict_structure.msa_check import (
    MsaFormatError,
    _sniff_format,
    check_msa_input,
)


def _write(tmp_path, name, content):
    p = tmp_path / name
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content)
    return p


# ---------- format sniffer ----------

def test_sniff_a3m_with_insertions(tmp_path):
    p = _write(tmp_path, "x.a3m",
               ">q\nMKEL\n>UniRef100_X 1 1.0 1e-5 1 4 4 1 4 4\nm-kel\n")
    assert _sniff_format(p) == "a3m"


def test_sniff_a3m_multiple_records(tmp_path):
    p = _write(tmp_path, "x.a3m", ">a\nMKEL\n>b\nMKEL\n")
    assert _sniff_format(p) == "a3m"


def test_sniff_single_seq_fasta(tmp_path):
    p = _write(tmp_path, "x.fasta", ">q\nMKEL\n")
    assert _sniff_format(p) == "fasta"


def test_sniff_stockholm(tmp_path):
    p = _write(tmp_path, "x.sto", "# STOCKHOLM 1.0\nq MKEL\n//\n")
    assert _sniff_format(p) == "stockholm"


def test_sniff_parquet(tmp_path):
    p = _write(tmp_path, "x.pqt", b"PAR1" + b"\x00" * 100)
    assert _sniff_format(p) == "parquet"


def test_sniff_empty(tmp_path):
    p = _write(tmp_path, "x.a3m", "")
    assert _sniff_format(p) == "empty"


def test_sniff_binary(tmp_path):
    p = _write(tmp_path, "x.a3m", bytes(range(256)) * 4)
    assert _sniff_format(p) == "binary"


# ---------- check_msa_input ----------

def test_none_msa_is_noop():
    check_msa_input(None, "chai")  # must not raise


def test_chai_accepts_a3m(tmp_path):
    p = _write(tmp_path, "good.a3m", ">a\nMKEL\n>b\nm-kel\n")
    check_msa_input(p, "chai")


def test_chai_accepts_parquet(tmp_path):
    p = _write(tmp_path, "good.pqt", b"PAR1" + b"\x00" * 64)
    check_msa_input(p, "chai")


def test_chai_rejects_single_seq_fasta(tmp_path):
    p = _write(tmp_path, "one.fasta", ">q\nMKEL\n")
    with pytest.raises(MsaFormatError, match="single-sequence"):
        check_msa_input(p, "chai")


def test_chai_rejects_stockholm(tmp_path):
    p = _write(tmp_path, "aln.sto", "# STOCKHOLM 1.0\nq MKEL\n//\n")
    with pytest.raises(MsaFormatError, match="chai accepts only"):
        check_msa_input(p, "chai")


def test_chai_rejects_empty(tmp_path):
    p = _write(tmp_path, "e.a3m", "")
    with pytest.raises(MsaFormatError, match="empty"):
        check_msa_input(p, "chai")


def test_chai_rejects_binary(tmp_path):
    p = _write(tmp_path, "b.a3m", bytes(range(256)) * 4)
    with pytest.raises(MsaFormatError, match="binary"):
        check_msa_input(p, "chai")


def test_missing_file_raises(tmp_path):
    with pytest.raises(MsaFormatError, match="does not exist"):
        check_msa_input(tmp_path / "nope.a3m", "chai")


def test_alphafold_accepts_stockholm(tmp_path):
    p = _write(tmp_path, "aln.sto", "# STOCKHOLM 1.0\nq MKEL\n//\n")
    check_msa_input(p, "alphafold")


def test_boltz_rejects_stockholm(tmp_path):
    p = _write(tmp_path, "aln.sto", "# STOCKHOLM 1.0\nq MKEL\n//\n")
    with pytest.raises(MsaFormatError, match="boltz accepts only"):
        check_msa_input(p, "boltz")


def test_esmfold_warns_but_passes(tmp_path, caplog):
    p = _write(tmp_path, "aln.a3m", ">a\nM\n>b\nM\n")
    import logging
    with caplog.at_level(logging.WARNING):
        check_msa_input(p, "esmfold")
    assert any("ignores MSA" in r.message for r in caplog.records)


def test_directory_input_for_alphafold(tmp_path):
    d = tmp_path / "msa_dir"
    d.mkdir()
    (d / "uniref90_hits.a3m").write_text(">a\nMKEL\n>b\nMKEL\n")
    check_msa_input(d, "alphafold")


def test_directory_input_rejected_for_boltz(tmp_path):
    d = tmp_path / "msa_dir"
    d.mkdir()
    (d / "aln.a3m").write_text(">a\nMKEL\n>b\nMKEL\n")
    with pytest.raises(MsaFormatError, match="not a directory"):
        check_msa_input(d, "boltz")


def test_directory_without_matching_files(tmp_path):
    d = tmp_path / "msa_dir"
    d.mkdir()
    (d / "stray.txt").write_text("nothing useful")
    with pytest.raises(MsaFormatError, match="no .* files"):
        check_msa_input(d, "alphafold")


def test_a3m_content_with_txt_suffix_warns_but_passes(tmp_path, caplog):
    p = _write(tmp_path, "aln.txt", ">a\nMKEL\n>b\nm-kel\n")
    import logging
    with caplog.at_level(logging.WARNING):
        check_msa_input(p, "chai")
    assert any("suffix" in r.message and "proceeding" in r.message
               for r in caplog.records)
