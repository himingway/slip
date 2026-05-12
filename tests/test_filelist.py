"""Tests for VCS-format filelist parser."""

import pytest
from pathlib import Path

from slip.slang_integration.filelist import FilelistData, parse_filelist

FIXTURES = Path(__file__).parent / "fixtures" / "ip"


class TestFilelistParser:
    """Test parsing VCS-format filelist files."""

    def test_basic_filelist(self):
        """Parse a basic filelist with files, defines, and incdirs."""
        fl = parse_filelist(FIXTURES / "test.f")
        assert len(fl.files) == 2
        assert fl.files[0].name == "prim_fifo.sv"
        assert fl.files[1].name == "prim_obuf.sv"
        assert "TEST_MACRO=42" in fl.defines
        assert len(fl.incdirs) == 1

    def test_nested_filelist(self):
        """Parse filelist with -f reference to sub-filelist."""
        fl = parse_filelist(FIXTURES / "test_main.f")
        assert len(fl.files) == 2
        assert fl.files[0].name == "prim_sync_reset.sv"
        assert fl.files[1].name == "defined_ip.sv"

    def test_comments_ignored(self):
        """Comments are ignored."""
        fl = parse_filelist(FIXTURES / "test.f")
        # test.f has comments, verify they don't affect parsing
        assert len(fl.files) == 2

    def test_empty_lines_ignored(self):
        """Empty lines are ignored."""
        content = "// comment\n\n./file.sv\n\n"
        tmp = Path("/tmp/test_empty.f")
        tmp.write_text(content)
        fl = parse_filelist(tmp)
        assert len(fl.files) == 1
        tmp.unlink()

    def test_define_format(self):
        """Define can be MACRO or MACRO=value."""
        tmp = Path("/tmp/test_defines.f")
        tmp.write_text("+define+FOO\n+define+BAR=100\n")
        fl = parse_filelist(tmp)
        assert "FOO" in fl.defines
        assert "BAR=100" in fl.defines
        tmp.unlink()

    def test_multiple_incdirs(self):
        """Multiple +incdir+ paths separated by +."""
        tmp = Path("/tmp/test_incdir.f")
        tmp.write_text("+incdir+./dir1+./dir2\n")
        fl = parse_filelist(tmp)
        assert len(fl.incdirs) == 2
        tmp.unlink()

    def test_dedup_files(self):
        """Duplicate file paths are deduplicated."""
        tmp = Path("/tmp/test_dedup.f")
        tmp.write_text("./file.sv\n./file.sv\n")
        fl = parse_filelist(tmp)
        assert len(fl.files) == 1
        tmp.unlink()

    def test_file_not_found(self):
        """Missing filelist raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            parse_filelist(Path("/nonexistent/filelist.f"))

    def test_circular_reference(self):
        """Circular -f reference raises ValueError."""
        tmp1 = Path("/tmp/test_circ1.f")
        tmp2 = Path("/tmp/test_circ2.f")
        tmp1.write_text(f"-f {tmp2}\n")
        tmp2.write_text(f"-f {tmp1}\n")
        with pytest.raises(ValueError, match="circular"):
            parse_filelist(tmp1)
        tmp1.unlink()
        tmp2.unlink()

    def test_other_plus_options_skipped(self):
        """Other +options are silently skipped."""
        tmp = Path("/tmp/test_plus.f")
        tmp.write_text("+some_option\n./file.sv\n")
        fl = parse_filelist(tmp)
        assert len(fl.files) == 1
        tmp.unlink()

    def test_other_minus_flags_skipped(self):
        """Other -flags are silently skipped."""
        tmp = Path("/tmp/test_minus.f")
        tmp.write_text("-some_flag\n./file.sv\n")
        fl = parse_filelist(tmp)
        assert len(fl.files) == 1
        tmp.unlink()

    def test_relative_paths_resolved(self):
        """Relative paths are resolved relative to filelist location."""
        tmp_dir = Path("/tmp/test_filelist_dir")
        tmp_dir.mkdir(exist_ok=True)
        fl_path = tmp_dir / "test.f"
        fl_path.write_text("./sub/file.sv\n")
        fl = parse_filelist(fl_path)
        assert fl.files[0].is_absolute()
        assert "sub" in str(fl.files[0])
        fl_path.unlink()
        tmp_dir.rmdir()

    def test_absolute_paths_preserved(self):
        """Absolute paths are used as-is."""
        tmp = Path("/tmp/test_abs.f")
        tmp.write_text("/absolute/path/file.sv\n")
        fl = parse_filelist(tmp)
        assert str(fl.files[0]) == "/absolute/path/file.sv"
        tmp.unlink()
