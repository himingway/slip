import pytest
from slip.lexer import Lexer
from slip.parser import Parser
from slip.semantic import SemanticAnalyzer
from slip.codegen import CodeGenerator
from slip.ir import HDLModule

from conftest import compile_source


class TestCodeGeneration:
    def test_simple_assign(self):
        sv = compile_source("module m (a, b, y) { assign y = a & b; }")
        text = sv["m"]
        assert "module m" in text
        assert "assign" in text
        assert "endmodule" in text
        assert "a & b" in text

    def test_module_with_params(self):
        sv = compile_source("module m #(param W = 8) (a, b, y) { assign y = a + b; }")
        text = sv["m"]
        assert "parameter W = 8" in text

    def test_seq_block(self):
        source = (
            "module counter (clk, rst_n, count) { "
            "seq (clk, neg: rst_n) { "
            "if (!rst_n) { count = 0; } else { count = count + 1; } "
            "} }"
        )
        sv = compile_source(source)
        text = sv["counter"]
        assert "always_ff" in text
        assert "posedge clk" in text
        assert "negedge rst_n" in text
        assert "<=" in text  # nonblocking assignments

    def test_signal_decl(self):
        sv = compile_source("module m (a, b, y) { logic [7:0] a; logic [7:0] b; logic [7:0] y; assign y = a + b; }")
        text = sv["m"]
        assert "logic" in text

    def test_instance(self):
        sv = compile_source(
            "module Other #(param W = 8) (clk) { logic clk; } "
            "module m (clk) { Other #(.W(8)) inst1 { .clk(clk) }; }"
        )
        text = sv["m"]
        assert "Other" in text
        assert "inst1" in text
        assert ".W(8)" in text
        assert ".clk(clk)" in text


class TestStaleOutputWarning:
    """Stale .sv files in the output directory are surfaced, not silent."""

    def test_stale_file_warns(self, tmp_path):
        import warnings
        from conftest import parse_source
        from slip.semantic import SemanticAnalyzer
        from slip.codegen import CodeGenerator

        (tmp_path / "old_module.sv").write_text("module old_module; endmodule\n")
        modules = parse_source("module m (y) { logic y; assign y = 1'b0; }")
        ir = SemanticAnalyzer().analyze(modules)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            CodeGenerator().generate(ir, output_dir=tmp_path)
        assert any("not produced by this run" in str(x.message) for x in w)

    def test_no_warning_when_clean(self, tmp_path):
        import warnings
        from conftest import parse_source
        from slip.semantic import SemanticAnalyzer
        from slip.codegen import CodeGenerator

        modules = parse_source("module m (y) { logic y; assign y = 1'b0; }")
        ir = SemanticAnalyzer().analyze(modules)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            CodeGenerator().generate(ir, output_dir=tmp_path)
        assert not any("not produced by this run" in str(x.message) for x in w)
