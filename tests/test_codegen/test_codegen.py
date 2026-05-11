import pytest
from slip.lexer import Lexer
from slip.parser import Parser
from slip.semantic import SemanticAnalyzer
from slip.codegen import CodeGenerator
from slip.ir import HDLModule


def compile_source(source: str) -> dict[str, str]:
    tokens = Lexer(source, "test.slip").tokenize()
    modules = Parser(tokens, "test.slip").parse()
    ir_modules = SemanticAnalyzer().analyze(modules)
    return CodeGenerator().generate(ir_modules)


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
        sv = compile_source("module m (clk) { Other #(.W(8)) inst1 { .clk(clk) }; }")
        text = sv["m"]
        assert "Other" in text
        assert "inst1" in text
        assert ".W(8)" in text
        assert ".clk(clk)" in text
