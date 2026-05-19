import os, tempfile, pytest
from trace_io import export_sltrace, import_sltrace

SPANS = [{"name": "foo", "addr": 0x1000, "start_us": 0.0, "end_us": 1.0, "duration_us": 1.0, "depth": 0, "ipsr": 0}]
MARKS = [{"name": "m", "t_us": 0.5, "ipsr": 0}]
META  = {"cpu_mhz": 192.0, "total_us": 1.0}

ELF_BYTES = b"\x7fELF" + b"\x00" * 60  # minimal fake ELF header


def test_roundtrip_with_elf(tmp_path):
    elf = tmp_path / "fw.elf"
    elf.write_bytes(ELF_BYTES)
    out = str(tmp_path / "trace.sltrace")
    export_sltrace(out, SPANS, meta=META, marks=MARKS, elf_path=str(elf))
    spans, marks, prs, meta, elf_bytes, elf_name = import_sltrace(out)
    assert spans == SPANS
    assert marks == MARKS
    assert prs == []
    assert meta["cpu_mhz"] == 192.0
    assert elf_bytes == ELF_BYTES
    assert elf_name == "fw.elf"


def test_roundtrip_without_elf(tmp_path):
    out = str(tmp_path / "trace.sltrace")
    export_sltrace(out, SPANS, meta=META)
    spans, marks, prs, meta, elf_bytes, elf_name = import_sltrace(out)
    assert spans == SPANS
    assert elf_bytes is None
    assert elf_name is None


def test_metadata_fields(tmp_path):
    out = str(tmp_path / "trace.sltrace")
    export_sltrace(out, SPANS, meta=META, marks=MARKS, wrapped=True)
    _, _, _, meta, _, _ = import_sltrace(out)
    assert meta["span_count"] == 1
    assert meta["mark_count"] == 1
    assert meta["wrapped"] is True
    assert "exported_at" in meta


def test_is_zip(tmp_path):
    import zipfile
    out = str(tmp_path / "trace.sltrace")
    export_sltrace(out, SPANS, meta=META)
    assert zipfile.is_zipfile(out)
    with zipfile.ZipFile(out) as zf:
        assert "trace.json" in zf.namelist()
