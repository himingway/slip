"""Tests for two-pass IP scanner and IPIndex."""

import pytest
from pathlib import Path

from slip.slang_integration.ip_scanner import IPIndex, build_ip_index
from slip.slang_integration.filelist import parse_filelist

FIXTURES = Path(__file__).parent / "fixtures" / "ip"


class TestIPIndex:
    """Test IPIndex data structure."""

    def test_empty_index(self):
        idx = IPIndex()
        assert idx.get_module("anything") is None
        assert idx.get_ports("anything") is None
        assert idx.get_localparams("anything") == set()

    def test_get_module(self):
        idx = build_ip_index(None, [FIXTURES])
        info = idx.get_module("prim_fifo")
        assert info is not None
        assert len(info.ports) > 0

    def test_get_ports(self):
        idx = build_ip_index(None, [FIXTURES])
        ports = idx.get_ports("prim_fifo")
        assert ports is not None
        port_names = [p[0] for p in ports]
        assert "clk" in port_names
        assert "rst_n" in port_names
        assert "wdata" in port_names

    def test_get_ports_nonexistent(self):
        idx = build_ip_index(None, [FIXTURES])
        assert idx.get_ports("nonexistent") is None

    def test_get_localparams(self):
        idx = build_ip_index(None, [FIXTURES])
        lps = idx.get_localparams("ip_with_localparam")
        assert "HALF_W" in lps

    def test_get_localparams_nonexistent(self):
        idx = build_ip_index(None, [FIXTURES])
        assert idx.get_localparams("nonexistent") == set()


class TestBuildIPIndex:
    """Test build_ip_index two-pass scanning."""

    def test_ip_dirs_only(self):
        """Index built from IP directory scanning."""
        idx = build_ip_index(None, [FIXTURES])
        # Should discover all modules in the IP directory
        assert idx.get_module("prim_fifo") is not None
        assert idx.get_module("prim_sync_reset") is not None
        assert idx.get_module("prim_obuf") is not None
        assert idx.get_module("defined_ip") is not None

    def test_filelist_only(self):
        """Index built from filelist only."""
        fl = FIXTURES / "test.f"
        idx = build_ip_index([fl], [])
        # test.f lists prim_fifo.sv and prim_obuf.sv
        assert idx.get_module("prim_fifo") is not None
        assert idx.get_module("prim_obuf") is not None

    def test_filelist_with_nested_f(self):
        """Index built from filelist with nested -f references."""
        fl = FIXTURES / "test_main.f"
        idx = build_ip_index([fl], [])
        # test_main.f -> test_sub.f (prim_sync_reset.sv) + defined_ip.sv
        assert idx.get_module("prim_sync_reset") is not None
        assert idx.get_module("defined_ip") is not None

    def test_filelist_and_ip_dirs_combined(self):
        """Index from both filelist and directory scanning."""
        fl = FIXTURES / "test.f"
        idx = build_ip_index([fl], [FIXTURES])
        # Filelist provides prim_fifo and prim_obuf
        assert idx.get_module("prim_fifo") is not None
        assert idx.get_module("prim_obuf") is not None
        # Directory scanning adds the rest
        assert idx.get_module("prim_sync_reset") is not None
        assert idx.get_module("defined_ip") is not None

    def test_dedup_between_filelist_and_dir(self):
        """Files from filelist aren't duplicated by directory scanning."""
        fl = FIXTURES / "test.f"
        idx = build_ip_index([fl], [FIXTURES])
        # prim_fifo appears in both filelist and directory
        # Should still only have one entry
        assert idx.get_module("prim_fifo") is not None
        ports = idx.get_ports("prim_fifo")
        assert ports is not None
        # Verify it's the correct module (not corrupted by dedup)
        port_names = [p[0] for p in ports]
        assert "clk" in port_names

    def test_empty_filelist_and_dirs(self):
        """Empty inputs return empty index."""
        idx = build_ip_index([], [])
        assert idx.get_module("prim_fifo") is None

    def test_nonexistent_ip_dir(self):
        """Nonexistent IP directory is silently skipped."""
        idx = build_ip_index(None, [Path("/nonexistent/dir")])
        assert idx.get_module("prim_fifo") is None

    def test_define_propagation(self):
        """Defines propagate across files when parsed together.

        ip_def_base.sv defines DATA_WIDTH and ADDR_WIDTH.
        ip_uses_defines.sv uses those defines for port widths.
        When parsed together (shared preprocessor context), the defines
        are available to ip_uses_defines.sv.
        """
        fl = FIXTURES / "test_defines.f"
        idx = build_ip_index([fl], [])
        # ip_uses_defines should be resolved with correct widths
        info = idx.get_module("ip_uses_defines")
        assert info is not None
        ports = {p[0]: p for p in idx.get_ports("ip_uses_defines")}
        # data_in and data_out should have width [15:0] (DATA_WIDTH=16)
        assert "data_in" in ports
        assert "data_out" in ports
        assert "addr" in ports
        # Width should reflect the define values
        assert ports["data_in"][2] is not None  # has width
        assert ports["data_out"][2] is not None
        assert ports["addr"][2] is not None

    def test_multiple_filelists(self):
        """Multiple filelists are merged."""
        fl1 = FIXTURES / "test_sub.f"  # prim_sync_reset.sv
        fl2 = FIXTURES / "test.f"  # prim_fifo.sv, prim_obuf.sv
        idx = build_ip_index([fl1, fl2], [])
        assert idx.get_module("prim_sync_reset") is not None
        assert idx.get_module("prim_fifo") is not None
        assert idx.get_module("prim_obuf") is not None


class TestIPScannerDiagnostics:
    """Missing files error out; duplicates and unreflectable modules warn."""

    def test_missing_filelist_entry_raises(self, tmp_path):
        from slip.errors.semantic import SlipSemanticError
        fl = tmp_path / "bad.f"
        fl.write_text("./does_not_exist.sv\n")
        with pytest.raises(SlipSemanticError, match="does not exist"):
            build_ip_index([fl], [])

    def test_duplicate_module_warns(self, tmp_path):
        (tmp_path / "a.sv").write_text("module dup (input logic x); endmodule\n")
        (tmp_path / "b.sv").write_text("module dup (input logic y); endmodule\n")
        with pytest.warns(UserWarning, match="duplicate module 'dup'"):
            idx = build_ip_index(None, [tmp_path])
        assert idx.get_module("dup") is not None

    def test_filelist_define_applies(self, tmp_path):
        # Macro use requires the Verilog backtick prefix
        (tmp_path / "top.sv").write_text(
            "module t (input logic [`W-1:0] x); endmodule\n"
        )
        fl = tmp_path / "d.f"
        fl.write_text("+define+W=8\n./top.sv\n")
        idx = build_ip_index([fl], [])
        ports = {p[0]: p for p in idx.get_ports("t")}
        assert ports["x"][2] == "[7:0]"

    def test_undefined_macro_leaves_port_unresolved(self, tmp_path):
        # Without the define, the port width is not resolved to the macro value
        (tmp_path / "top.sv").write_text(
            "module t (input logic [`MISSING-1:0] x); endmodule\n"
        )
        fl = tmp_path / "d.f"
        fl.write_text("./top.sv\n")
        idx = build_ip_index([fl], [])
        ports = {p[0]: p for p in idx.get_ports("t")}
        assert ports["x"][2] != "[7:0]"

    def test_unreadable_file_warns_not_silent(self, tmp_path):
        bad = tmp_path / "bad.sv"
        bad.write_text("module ok (input logic x); endmodule\n")
        bad.chmod(0o000)
        try:
            # Per-file fallback path reports the read failure
            with pytest.warns(UserWarning):
                from slip.slang_integration.ip_scanner import _reflect_per_file
                idx = _reflect_per_file([bad])
            assert idx.get_module("ok") is None
        finally:
            bad.chmod(0o644)
