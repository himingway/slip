"""Integration tests for mixed .sv + .slip projects.

Tests the full ip_dirs pipeline: Slip compiles a .slip file that
instantiates an external SystemVerilog module via regex port mapping.
The external module's ports are discovered via slang reflection.
"""

import pytest
from pathlib import Path

from slip.lexer import Lexer
from slip.parser import Parser
from slip.semantic import SemanticAnalyzer
from slip.slang_integration import reflect_module, ModuleInfo
from slip.codegen import CodeGenerator
from slip.errors.semantic import SlipSemanticError

from conftest import FIXTURES, IP_DIR, compile_from_path as compile_with_ip, compile_source


# ════════════════════════════════════════════════════════════════
# A. Slang reflection of external SV modules
# ════════════════════════════════════════════════════════════════

class TestReflection:
    def test_reflect_prim_fifo(self):
        info = reflect_module(IP_DIR / "prim_fifo.sv", "prim_fifo")
        assert isinstance(info, ModuleInfo)
        port_names = [p.name for p in info.ports]
        assert "clk" in port_names
        assert "rst_n" in port_names
        assert "wren" in port_names
        assert "wdata" in port_names
        assert "rdata" in port_names
        assert "full" in port_names
        assert "empty" in port_names

    def test_reflect_prim_fifo_params(self):
        info = reflect_module(IP_DIR / "prim_fifo.sv", "prim_fifo")
        param_names = [p.name for p in info.params]
        assert "Depth" in param_names
        assert "Width" in param_names

    def test_reflect_prim_fifo_directions(self):
        info = reflect_module(IP_DIR / "prim_fifo.sv", "prim_fifo")
        dirs = {p.name: p.direction for p in info.ports}
        # pyslang returns direction as enum string like "argumentdirection.in"
        assert "in" in dirs["clk"]
        assert "in" in dirs["wdata"]
        assert "out" in dirs["rdata"]
        assert "out" in dirs["full"]
        assert "out" in dirs["empty"]

    def test_reflect_prim_sync_reset(self):
        info = reflect_module(IP_DIR / "prim_sync_reset.sv", "prim_sync_reset")
        port_names = [p.name for p in info.ports]
        assert "clk" in port_names
        assert "rst_n_async" in port_names
        assert "rst_n_sync" in port_names

    def test_reflect_prim_obuf(self):
        info = reflect_module(IP_DIR / "prim_obuf.sv", "prim_obuf")
        port_names = [p.name for p in info.ports]
        assert "oe" in port_names
        assert "din" in port_names
        assert "dout" in port_names

    def test_reflect_nonexistent_module(self):
        with pytest.raises(ValueError, match="not found"):
            reflect_module(IP_DIR / "prim_fifo.sv", "nonexistent")

    def test_reflect_nonexistent_file(self):
        with pytest.raises(Exception):
            reflect_module(IP_DIR / "no_such_file.sv", "foo")


# ════════════════════════════════════════════════════════════════
# B. Instance regex + IP reflection pipeline
# ════════════════════════════════════════════════════════════════

class TestIPInstanceResolve:
    def test_fifo_user_resolves_via_ip(self):
        sv = compile_with_ip(FIXTURES / "ip_top_fifo_user.slip", [IP_DIR])
        assert "fifo_user" in sv
        text = sv["fifo_user"]
        # Named connections
        assert ".clk(clk)" in text
        assert ".rst_n(rst_n)" in text
        assert ".wren(wr_en)" in text
        assert ".rdata(dout)" in text
        assert ".full(full)" in text
        assert ".empty(empty)" in text
        # Regex-mapped: wdata → fifo_wdata
        assert ".wdata(fifo_wdata)" in text

    def test_reset_wrap_resolves_via_ip(self):
        sv = compile_with_ip(FIXTURES / "ip_top_reset_wrap.slip", [IP_DIR])
        assert "reset_wrap" in sv
        text = sv["reset_wrap"]
        assert ".clk(clk)" in text
        assert ".rst_n_async(rst_n_async)" in text
        # Regex: rst_n_sync → rst_n_sync (same-name via regex)
        assert ".rst_n_sync(rst_n_sync)" in text

    def test_bus_wrap_no_regex_resolves_via_ip(self):
        sv = compile_with_ip(FIXTURES / "ip_top_bus_wrap.slip", [IP_DIR])
        assert "bus_wrap" in sv
        text = sv["bus_wrap"]
        assert ".oe(oe)" in text
        assert ".din(din)" in text
        assert ".dout(dout)" in text
        assert ".Width(W)" in text

    def test_missing_ip_dir_error(self):
        with pytest.raises(SlipSemanticError, match="cannot resolve"):
            compile_with_ip(FIXTURES / "ip_top_fifo_user.slip", [])

    def test_wrong_ip_dir_error(self):
        """IP dir with no .sv files at all raises error."""
        empty_dir = FIXTURES / "no_sv_here"
        empty_dir.mkdir(exist_ok=True)
        try:
            with pytest.raises(SlipSemanticError, match="cannot resolve"):
                compile_with_ip(FIXTURES / "ip_top_fifo_user.slip", [empty_dir])
        finally:
            empty_dir.rmdir()


# ════════════════════════════════════════════════════════════════
# C. SV output validation
# ════════════════════════════════════════════════════════════════

class TestIPSvOutput:
    def test_fifo_user_sv_structure(self):
        sv = compile_with_ip(FIXTURES / "ip_top_fifo_user.slip", [IP_DIR])["fifo_user"]
        # Check module header
        assert "module fifo_user" in sv
        assert "parameter" in sv  # has params
        # Check signal declarations
        assert "logic [WIDTH - 1:0] din" in sv or "logic [W" not in sv
        assert "logic wr_en" in sv
        assert "logic [WIDTH - 1:0] fifo_wdata" in sv
        # Check instance
        assert "prim_fifo" in sv
        assert "u_fifo" in sv
        assert ".Depth(DEPTH)" in sv
        assert ".Width(WIDTH)" in sv

    def test_reset_wrap_sv_structure(self):
        sv = compile_with_ip(FIXTURES / "ip_top_reset_wrap.slip", [IP_DIR])["reset_wrap"]
        assert "prim_sync_reset" in sv
        assert "u_rst_sync" in sv

    def test_bus_wrap_sv_has_params(self):
        sv = compile_with_ip(FIXTURES / "ip_top_bus_wrap.slip", [IP_DIR])["bus_wrap"]
        assert "prim_obuf" in sv
        assert "u_buf" in sv


# ════════════════════════════════════════════════════════════════
# D. Mixed source: Slip module instantiating SV IP + Slip module
# ════════════════════════════════════════════════════════════════

class TestMixedSourceIntegration:
    def test_slip_module_and_sv_ip_together(self):
        """Slip source defines a local module AND instantiates an SV IP."""
        source = (
            "module local_buf (clk, din, dout) {\n"
            "  logic clk;\n"
            "  logic [7:0] din;\n"
            "  logic [7:0] dout;\n"
            "  assign dout = din;\n"
            "}\n"
            "module top (clk, rst_n, din, dout) {\n"
            "  logic clk;\n"
            "  logic rst_n;\n"
            "  logic [7:0] din;\n"
            "  logic [7:0] dout;\n"
            "  logic rst_n_sync;\n"
            "\n"
            "  prim_sync_reset u_rst {\n"
            "    .clk,\n"
            "    .rst_n_async(rst_n),\n"
            '    "rst_n_(.+)" => "rst_n_\\1"\n'
            "  };\n"
            "\n"
            "  local_buf u_buf {\n"
            "    .clk,\n"
            "    .din(din),\n"
            "    .dout(dout)\n"
            "  };\n"
            "}\n"
        )
        tokens = Lexer(source, "test.slip").tokenize()
        modules = Parser(tokens, "test.slip").parse()
        ir = SemanticAnalyzer().analyze(modules, [IP_DIR])
        sv = CodeGenerator().generate(ir)

        top = sv["top"]
        # SV IP instance resolved via reflection
        assert "prim_sync_reset" in top
        assert ".rst_n_sync(rst_n_sync)" in top
        # Local Slip module instance resolved via module_index
        assert "local_buf" in top
        assert ".din(din)" in top

    def test_slip_module_used_as_target_before_ip(self):
        """When target exists in same design, IP dirs are not consulted."""
        source = (
            "module my_ip (clk, data) {\n"
            "  logic clk;\n"
            "  logic [7:0] data;\n"
            "  assign data = 0;\n"
            "}\n"
            "module top (clk) {\n"
            "  logic clk;\n"
            r'  my_ip u1 { .clk, "d(.+)" => "my_d\1" };' "\n"
            "}\n"
        )
        tokens = Lexer(source, "test.slip").tokenize()
        modules = Parser(tokens, "test.slip").parse()
        ir = SemanticAnalyzer().analyze(modules, [IP_DIR])
        sv = CodeGenerator().generate(ir)
        top = sv["top"]
        assert ".data(my_data)" in top


# ════════════════════════════════════════════════════════════════
# E. CLI end-to-end with -ip flag
# ════════════════════════════════════════════════════════════════

class TestIPCLI:
    def test_build_fifo_user(self, tmp_path):
        from slip.cli._pipeline import run_build
        result = run_build(FIXTURES / "ip_top_fifo_user.slip", tmp_path, [IP_DIR])
        assert (tmp_path / "fifo_user.sv").exists()
        sv = (tmp_path / "fifo_user.sv").read_text()
        assert "prim_fifo" in sv
        assert ".wdata(fifo_wdata)" in sv

    def test_build_reset_wrap(self, tmp_path):
        from slip.cli._pipeline import run_build
        result = run_build(FIXTURES / "ip_top_reset_wrap.slip", tmp_path, [IP_DIR])
        assert (tmp_path / "reset_wrap.sv").exists()
        sv = (tmp_path / "reset_wrap.sv").read_text()
        assert "prim_sync_reset" in sv

    def test_build_bus_wrap(self, tmp_path):
        from slip.cli._pipeline import run_build
        result = run_build(FIXTURES / "ip_top_bus_wrap.slip", tmp_path, [IP_DIR])
        assert (tmp_path / "bus_wrap.sv").exists()

    def test_check_fifo_user(self):
        from slip.cli._pipeline import run_check
        run_check(FIXTURES / "ip_top_fifo_user.slip", [IP_DIR])

    def test_check_reset_wrap(self):
        from slip.cli._pipeline import run_check
        run_check(FIXTURES / "ip_top_reset_wrap.slip", [IP_DIR])

    def test_build_without_ip_fails(self, tmp_path):
        from slip.cli._pipeline import run_build
        with pytest.raises(SlipSemanticError, match="cannot resolve"):
            run_build(FIXTURES / "ip_top_fifo_user.slip", tmp_path, [])

    def test_check_without_ip_fails(self):
        from slip.cli._pipeline import run_check
        with pytest.raises(SlipSemanticError, match="cannot resolve"):
            run_check(FIXTURES / "ip_top_fifo_user.slip", [])


# ════════════════════════════════════════════════════════════════
# F. Implicit signal creation from reflected width
# ════════════════════════════════════════════════════════════════

class TestIPImplicitSignals:
    def test_fifo_implicit_signal_has_width(self):
        """fifo_wdata is created implicitly by regex and should have width info."""
        tokens = Lexer(
            (FIXTURES / "ip_top_fifo_user.slip").read_text(),
            "test.slip"
        ).tokenize()
        modules = Parser(tokens, "test.slip").parse()
        ir = SemanticAnalyzer().analyze(modules, [IP_DIR])
        fifo_user = [m for m in ir if m.name == "fifo_user"][0]
        sig_names = {s.name: s for s in fifo_user.signals}
        assert "fifo_wdata" in sig_names

    def test_regex_creates_signal_for_unconnected_input(self):
        """When a port is not in scope, an implicit signal is created."""
        source = (
            "module top (clk, rst_n) {\n"
            "  logic clk;\n"
            "  logic rst_n;\n"
            "  prim_sync_reset u_rst {\n"
            "    .clk,\n"
            "    .rst_n_async(rst_n),\n"
            r'    "rst_n_(.+)" => "sync_\1"' "\n"
            "  };\n"
            "}\n"
        )
        tokens = Lexer(source, "test.slip").tokenize()
        modules = Parser(tokens, "test.slip").parse()
        ir = SemanticAnalyzer().analyze(modules, [IP_DIR])
        top = [m for m in ir if m.name == "top"][0]
        sig_names = [s.name for s in top.signals]
        assert "sync_sync" in sig_names


# ════════════════════════════════════════════════════════════════
# G. Define-macro IP: `define expressions in port widths
# ════════════════════════════════════════════════════════════════

class TestDefineMacroIP:
    def test_reflect_define_ip_widths(self):
        """pyslang resolves `define macros for port widths."""
        info = reflect_module(IP_DIR / "defined_ip.sv", "defined_ip")
        widths = {p.name: p.width for p in info.ports}
        assert widths["addr"] == "[7:0]"
        assert widths["wdata"] == "[31:0]"
        assert widths["rdata"] == "[31:0]"
        assert widths["clk"] is None
        assert widths["valid"] is None

    def test_reflect_define_ip_directions(self):
        """Directions are normalized to input/output."""
        info = reflect_module(IP_DIR / "defined_ip.sv", "defined_ip")
        dirs = {p.name: p.direction for p in info.ports}
        assert dirs["clk"] == "input"
        assert dirs["wdata"] == "input"
        assert dirs["rdata"] == "output"
        assert dirs["valid"] == "output"

    def test_define_ip_implicit_signal_width(self):
        """Implicit signal from regex gets correct SV bracket width."""
        tokens = Lexer(
            (FIXTURES / "ip_top_defined_ip.slip").read_text(),
            "test.slip"
        ).tokenize()
        modules = Parser(tokens, "test.slip").parse()
        ir = SemanticAnalyzer().analyze(modules, [IP_DIR])
        top = [m for m in ir if m.name == "define_user"][0]
        sig = {s.name: s for s in top.signals}
        assert "my_data" in sig
        assert sig["my_data"].type_.width_sv == "[31:0]"

    def test_define_ip_sv_output_valid(self):
        """Full pipeline generates valid SV with define-macro IP."""
        sv = compile_with_ip(FIXTURES / "ip_top_defined_ip.slip", [IP_DIR])
        assert "define_user" in sv
        text = sv["define_user"]
        assert "defined_ip" in text
        assert ".clk(clk)" in text
        assert ".rdata(data_out)" in text
        assert ".wdata(my_data)" in text
        assert ".valid(valid)" in text

    def test_define_ip_regex_creates_wide_signal(self):
        """Regex-created implicit signal has correct width in SV output."""
        sv = compile_with_ip(FIXTURES / "ip_top_defined_ip.slip", [IP_DIR])
        text = sv["define_user"]
        assert "logic [31:0] my_data" in text


# ════════════════════════════════════════════════════════════════
# H. Filelist end-to-end tests (-f flag)
# ════════════════════════════════════════════════════════════════

class TestFilelistEndToEnd:
    """End-to-end tests using VCS filelist format."""

    def test_build_with_filelist(self, tmp_path):
        """Build using -f filelist instead of -ip directory."""
        from slip.cli._pipeline import run_build
        fl = IP_DIR / "test.f"
        result = run_build(FIXTURES / "ip_top_fifo_user.slip", tmp_path, [], filelists=[fl])
        assert (tmp_path / "fifo_user.sv").exists()
        sv = (tmp_path / "fifo_user.sv").read_text()
        assert "prim_fifo" in sv
        assert ".wdata(fifo_wdata)" in sv

    def test_check_with_filelist(self):
        """Check using -f filelist."""
        from slip.cli._pipeline import run_check
        fl = IP_DIR / "test.f"
        run_check(FIXTURES / "ip_top_fifo_user.slip", [], filelists=[fl])

    def test_filelist_and_ip_dirs_combined(self):
        """Filelist and -ip directory work together."""
        from slip.cli._pipeline import run_check
        # test.f has prim_fifo and prim_obuf; IP_DIR also has them + others
        fl = IP_DIR / "test.f"
        # Should succeed — filelist provides prim_fifo, dir provides the rest
        run_check(FIXTURES / "ip_top_fifo_user.slip", [IP_DIR], filelists=[fl])

    def test_filelist_with_nested_f(self):
        """Nested -f references work end-to-end."""
        from slip.cli._pipeline import run_check
        fl = IP_DIR / "test_main.f"
        # test_main.f -> test_sub.f (prim_sync_reset) + defined_ip
        run_check(FIXTURES / "ip_top_reset_wrap.slip", [], filelists=[fl])

    def test_compile_source_with_filelist(self):
        """compile_source helper supports filelists parameter."""
        source = (
            "module top (clk, rst_n) {\n"
            "  logic clk;\n"
            "  logic rst_n;\n"
            "  prim_sync_reset u_rst {\n"
            "    .clk,\n"
            "    .rst_n_async(rst_n),\n"
            r'    "rst_n_(.+)" => "rst_n_\1"' "\n"
            "  };\n"
            "}\n"
        )
        fl = IP_DIR / "test_sub.f"
        sv = compile_source(source, filelists=[fl])
        assert "top" in sv
        assert "prim_sync_reset" in sv["top"]
        assert ".rst_n_sync(rst_n_sync)" in sv["top"]
