"""Tests for the `comb` block: combinational logic syntax sugar."""

import pytest
from pathlib import Path

from slip.lexer import Lexer, TokenType
from slip.parser import Parser
from slip.ast import CombBlock, SeqBlock, AssignStmt, IfStmt
from slip.semantic import SemanticAnalyzer
from slip.codegen import CodeGenerator

FIXTURES = Path(__file__).parent / "fixtures"


def compile_source(source: str) -> dict[str, str]:
    tokens = Lexer(source, "test.slip").tokenize()
    modules = Parser(tokens, "test.slip").parse()
    ir = SemanticAnalyzer().analyze(modules)
    return CodeGenerator().generate(ir)


def parse_source(source: str):
    tokens = Lexer(source, "test.slip").tokenize()
    return Parser(tokens, "test.slip").parse()


# ────────────────────────────────────────────────────────────────
# Lexer
# ────────────────────────────────────────────────────────────────

class TestCombLexer:
    def test_comb_keyword(self):
        tokens = Lexer("comb").tokenize()
        assert tokens[0].type == TokenType.COMB
        assert tokens[0].value == "comb"


# ────────────────────────────────────────────────────────────────
# Parser
# ────────────────────────────────────────────────────────────────

class TestCombParser:
    def test_comb_block_basic(self):
        modules = parse_source("module m (y) { comb { y = 1; } }")
        stmt = modules[0].body[0]
        assert isinstance(stmt, CombBlock)
        assert len(stmt.body.statements) == 1

    def test_comb_block_no_clock_no_reset(self):
        modules = parse_source("module m (y) { comb { y = 0; } }")
        stmt = modules[0].body[0]
        assert isinstance(stmt, CombBlock)
        assert not hasattr(stmt, 'clock')
        assert not hasattr(stmt, 'reset')

    def test_comb_with_if(self):
        modules = parse_source(
            "module m (sel, a, b, y) { comb { if (sel) y = a; else y = b; } }"
        )
        stmt = modules[0].body[0]
        assert isinstance(stmt, CombBlock)
        assert isinstance(stmt.body.statements[0], IfStmt)

    def test_comb_with_nested_if(self):
        modules = parse_source(
            "module m (a, b, c, y) { comb { "
            "if (a) { y = 1; } else { if (b) { y = 2; } else { y = 3; } } "
            "} }"
        )
        stmt = modules[0].body[0]
        assert isinstance(stmt, CombBlock)
        inner_if = stmt.body.statements[0].else_body.statements[0]
        assert isinstance(inner_if, IfStmt)

    def test_comb_vs_seq_distinct(self):
        modules = parse_source(
            "module m (clk, y) { "
            "comb { y = 1; } "
            "seq (clk) { y = 0; } "
            "}"
        )
        assert isinstance(modules[0].body[0], CombBlock)
        assert isinstance(modules[0].body[1], SeqBlock)


# ────────────────────────────────────────────────────────────────
# Semantic: blocking assignments stay blocking in comb
# ────────────────────────────────────────────────────────────────

class TestCombSemantic:
    def test_blocking_stays_blocking(self):
        """Comb block assignments should NOT be converted to nonblocking."""
        modules = parse_source("module m (y) { comb { y = 1; } }")
        ir = SemanticAnalyzer().analyze(modules)
        block = ir[0].logic_blocks[0]
        assert len(block.body) == 1
        assign = block.body[0]
        assert assign.is_nonblocking is False

    def test_seq_blocking_becomes_nonblocking(self):
        """Seq block assignments should still be corrected."""
        modules = parse_source("module m (clk, y) { seq (clk) { y = 1; } }")
        ir = SemanticAnalyzer().analyze(modules)
        block = ir[0].logic_blocks[0]
        assert block.body[0].is_nonblocking is True

    def test_comb_driver_analysis(self):
        """Comb block assignments should mark targets as drivers."""
        modules = parse_source("module m (a, y) { comb { y = a; } }")
        ir = SemanticAnalyzer().analyze(modules)
        port_names = [p.name for p in ir[0].ports]
        assert "y" in port_names
        y_port = [p for p in ir[0].ports if p.name == "y"][0]
        assert y_port.direction == "output"

    def test_comb_reader_analysis(self):
        """Comb block expressions should mark identifiers as readers."""
        modules = parse_source("module m (a, y) { comb { y = a; } }")
        ir = SemanticAnalyzer().analyze(modules)
        a_port = [p for p in ir[0].ports if p.name == "a"][0]
        assert a_port.direction == "input"


# ────────────────────────────────────────────────────────────────
# Codegen: always_comb generation
# ────────────────────────────────────────────────────────────────

class TestCombCodegen:
    def test_always_comb_output(self):
        sv = compile_source("module m (y) { comb { y = 1; } }")
        assert "always_comb begin" in sv["m"]
        assert "always_ff" not in sv["m"]

    def test_no_sensitivity_list(self):
        sv = compile_source("module m (a, y) { comb { y = a; } }")
        assert "@(" not in sv["m"]  # no sensitivity list

    def test_blocking_assignment_output(self):
        sv = compile_source("module m (a, y) { comb { y = a; } }")
        # Should use = not <=
        assert "y = a;" in sv["m"]
        assert "y <= a;" not in sv["m"]

    def test_mux_if_else(self):
        sv = compile_source(
            "module mux (sel, a, b, y) { "
            "comb { if (sel) y = a; else y = b; } "
            "}"
        )
        assert "always_comb begin" in sv["mux"]
        assert "if (sel)" in sv["mux"]
        assert "y = a;" in sv["mux"]
        assert "y = b;" in sv["mux"]

    def test_pyslang_valid(self):
        from pyslang import SyntaxTree, Compilation
        sv = compile_source(
            "module mux (sel, a, b, y) { "
            "comb { if (sel) y = a; else y = b; } "
            "}"
        )["mux"]
        tree = SyntaxTree.fromText(sv, "mux.sv")
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert len(errors) == 0


# ────────────────────────────────────────────────────────────────
# Mixed comb + seq in same module
# ────────────────────────────────────────────────────────────────

class TestMixedCombSeq:
    def test_both_blocks_present(self):
        sv = compile_source(
            "module m (clk, rst_n, a, b, reg_out, comb_out) { "
            "comb { comb_out = a & b; } "
            "seq (clk, neg: rst_n) { "
            "if (!rst_n) { reg_out = 0; } else { reg_out = reg_out + 1; } "
            "} }"
        )
        text = sv["m"]
        assert "always_comb" in text
        assert "always_ff" in text
        assert text.count("always_comb") == 1
        assert text.count("always_ff") == 1

    def test_comb_uses_blocking_seq_uses_nonblocking(self):
        sv = compile_source(
            "module m (clk, a, y_comb, y_seq) { "
            "comb { y_comb = a + 1; } "
            "seq (clk) { y_seq = a; } "
            "}"
        )
        text = sv["m"]
        # comb section
        comb_section = text.split("always_comb")[1].split("end")[0]
        assert "y_comb = a + 1;" in comb_section
        assert "y_comb <=" not in comb_section
        # seq section
        seq_section = text.split("always_ff")[1].split("endmodule")[0]
        assert "y_seq <= a;" in seq_section

    def test_pyslang_mixed_valid(self):
        from pyslang import SyntaxTree, Compilation
        sv = compile_source(
            "module m (clk, rst_n, a, b, y_c, y_s) { "
            "comb { y_c = a & b; } "
            "seq (clk, neg: rst_n) { "
            "if (!rst_n) { y_s = 0; } else { y_s = y_s + 1; } "
            "} }"
        )["m"]
        tree = SyntaxTree.fromText(sv)
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert len(errors) == 0


# ────────────────────────────────────────────────────────────────
# Fixture: comb_mux.slip
# ────────────────────────────────────────────────────────────────

class TestCombMuxFixture:
    def test_compiles(self):
        sv = compile_source((FIXTURES / "comb_mux.slip").read_text())
        assert "mux" in sv

    def test_output(self):
        sv = compile_source((FIXTURES / "comb_mux.slip").read_text())["mux"]
        assert "always_comb begin" in sv
        assert "if (sel)" in sv
        assert "y = a;" in sv
        assert "y = b;" in sv

    def test_ports(self):
        sv = compile_source((FIXTURES / "comb_mux.slip").read_text())["mux"]
        assert "input logic sel" in sv
        assert "input logic [7:0] a" in sv
        assert "input logic [7:0] b" in sv
        assert "output logic [7:0] y" in sv

    def test_pyslang_valid(self):
        from pyslang import SyntaxTree, Compilation
        sv = compile_source((FIXTURES / "comb_mux.slip").read_text())["mux"]
        tree = SyntaxTree.fromText(sv)
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert len(errors) == 0


# ────────────────────────────────────────────────────────────────
# Fixture: comb_priority_encoder.slip
# ────────────────────────────────────────────────────────────────

class TestCombPriorityEncoderFixture:
    def test_compiles(self):
        sv = compile_source((FIXTURES / "comb_priority_encoder.slip").read_text())
        assert "priority_encoder" in sv

    def test_nested_if_structure(self):
        sv = compile_source((FIXTURES / "comb_priority_encoder.slip").read_text())["priority_encoder"]
        assert "always_comb" in sv
        assert "req[0]" in sv
        assert "req[3]" in sv

    def test_blocking_assignments(self):
        sv = compile_source((FIXTURES / "comb_priority_encoder.slip").read_text())["priority_encoder"]
        # No nonblocking assignments
        always_section = sv.split("always_comb")[1].split("endmodule")[0]
        assert "<=" not in always_section

    def test_pyslang_valid(self):
        from pyslang import SyntaxTree, Compilation
        sv = compile_source((FIXTURES / "comb_priority_encoder.slip").read_text())["priority_encoder"]
        tree = SyntaxTree.fromText(sv)
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert len(errors) == 0


# ────────────────────────────────────────────────────────────────
# End-to-end CLI
# ────────────────────────────────────────────────────────────────

class TestCombCLI:
    def test_build_mux(self, tmp_path):
        from slip.cli._pipeline import run_build
        result = run_build(FIXTURES / "comb_mux.slip", tmp_path, [])
        assert (tmp_path / "mux.sv").exists()
        assert "always_comb" in result["mux"]

    def test_build_priority_encoder(self, tmp_path):
        from slip.cli._pipeline import run_build
        result = run_build(FIXTURES / "comb_priority_encoder.slip", tmp_path, [])
        assert (tmp_path / "priority_encoder.sv").exists()

    def test_check_mux(self):
        from slip.cli._pipeline import run_check
        run_check(FIXTURES / "comb_mux.slip", [])

    def test_check_priority_encoder(self):
        from slip.cli._pipeline import run_check
        run_check(FIXTURES / "comb_priority_encoder.slip", [])
