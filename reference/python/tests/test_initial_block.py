"""Tests for the `initial` block: initialization logic."""

import pytest

from slip.lexer import Lexer, TokenType
from slip.parser import Parser
from slip.ast import CombBlock, InitialBlock, SeqBlock, AssignStmt, IfStmt
from slip.semantic import SemanticAnalyzer
from slip.codegen import CodeGenerator

from conftest import FIXTURES, compile_source, parse_source, validate_sv


# ────────────────────────────────────────────────────────────────
# Lexer
# ────────────────────────────────────────────────────────────────

class TestInitialLexer:
    def test_initial_keyword(self):
        tokens = Lexer("initial").tokenize()
        assert tokens[0].type == TokenType.INITIAL
        assert tokens[0].value == "initial"


# ────────────────────────────────────────────────────────────────
# Parser
# ────────────────────────────────────────────────────────────────

class TestInitialParser:
    def test_initial_block_basic(self):
        modules = parse_source("module m (y) { initial { y = 1; } }")
        stmt = modules[0].body[0]
        assert isinstance(stmt, InitialBlock)
        assert len(stmt.body.statements) == 1

    def test_initial_block_no_clock_no_reset(self):
        modules = parse_source("module m (y) { initial { y = 0; } }")
        stmt = modules[0].body[0]
        assert isinstance(stmt, InitialBlock)
        assert not hasattr(stmt, 'clock')
        assert not hasattr(stmt, 'reset')

    def test_initial_with_if(self):
        modules = parse_source(
            "module m (sel, a, b, y) { initial { if (sel) y = a; else y = b; } }"
        )
        stmt = modules[0].body[0]
        assert isinstance(stmt, InitialBlock)
        assert isinstance(stmt.body.statements[0], IfStmt)

    def test_initial_vs_comb_distinct(self):
        modules = parse_source(
            "module m (y) { "
            "initial { y = 0; } "
            "comb { y = 1; } "
            "}"
        )
        assert isinstance(modules[0].body[0], InitialBlock)
        assert isinstance(modules[0].body[1], CombBlock)

    def test_initial_vs_seq_distinct(self):
        modules = parse_source(
            "module m (clk, y) { "
            "initial { y = 0; } "
            "seq (clk) { y = 1; } "
            "}"
        )
        assert isinstance(modules[0].body[0], InitialBlock)
        assert isinstance(modules[0].body[1], SeqBlock)


# ────────────────────────────────────────────────────────────────
# Semantic: blocking assignments stay blocking in initial
# ────────────────────────────────────────────────────────────────

class TestInitialSemantic:
    def test_blocking_stays_blocking(self):
        """Initial block assignments should NOT be converted to nonblocking."""
        modules = parse_source("module m (y) { initial { y = 1; } }")
        ir = SemanticAnalyzer().analyze(modules)
        block = ir[0].logic_blocks[0]
        assert block.kind == "initial"
        assert len(block.body) == 1
        assign = block.body[0]
        assert assign.is_nonblocking is False

    def test_initial_driver_analysis(self):
        """Initial block assignments should mark targets as drivers."""
        modules = parse_source("module m (a, y) { initial { y = a; } }")
        ir = SemanticAnalyzer().analyze(modules)
        port_names = [p.name for p in ir[0].ports]
        assert "y" in port_names
        y_port = [p for p in ir[0].ports if p.name == "y"][0]
        assert y_port.direction == "output"

    def test_initial_reader_analysis(self):
        """Initial block expressions should mark identifiers as readers."""
        modules = parse_source("module m (a, y) { initial { y = a; } }")
        ir = SemanticAnalyzer().analyze(modules)
        a_port = [p for p in ir[0].ports if p.name == "a"][0]
        assert a_port.direction == "input"


# ────────────────────────────────────────────────────────────────
# Codegen: initial begin ... end generation
# ────────────────────────────────────────────────────────────────

class TestInitialCodegen:
    def test_initial_begin_output(self):
        sv = compile_source("module m (y) { initial { y = 1; } }")
        assert "initial begin" in sv["m"]
        assert "always_ff" not in sv["m"]
        assert "always_comb" not in sv["m"]

    def test_no_sensitivity_list(self):
        sv = compile_source("module m (a, y) { initial { y = a; } }")
        assert "@(" not in sv["m"]

    def test_blocking_assignment_output(self):
        sv = compile_source("module m (a, y) { initial { y = a; } }")
        # Should use = not <=
        assert "y = a;" in sv["m"]
        assert "y <= a;" not in sv["m"]

    def test_initial_with_if_else(self):
        sv = compile_source(
            "module mux (sel, a, b, y) { "
            "initial { if (sel) y = a; else y = b; } "
            "}"
        )
        assert "initial begin" in sv["mux"]
        assert "if (sel)" in sv["mux"]
        assert "y = a;" in sv["mux"]
        assert "y = b;" in sv["mux"]

    def test_pyslang_valid(self):
        sv = compile_source(
            "module init_basic (y) { "
            "initial { y = 0; } "
            "}"
        )["init_basic"]
        errors = validate_sv(sv)
        assert len(errors) == 0


# ────────────────────────────────────────────────────────────────
# Mixed initial + comb + seq in same module
# ────────────────────────────────────────────────────────────────

class TestMixedInitialCombSeq:
    def test_all_three_blocks_present(self):
        sv = compile_source(
            "module m (clk, rst_n, a, b, init_val, reg_out, comb_out) { "
            "initial { reg_out = 0; } "
            "comb { comb_out = a & b; } "
            "seq (clk, neg: rst_n) { "
            "if (!rst_n) { reg_out = 0; } else { reg_out = reg_out + 1; } "
            "} }"
        )
        text = sv["m"]
        assert "initial begin" in text
        assert "always_comb begin" in text
        assert "always_ff" in text
        assert text.count("initial begin") == 1
        assert text.count("always_comb begin") == 1
        assert text.count("always_ff") == 1

    def test_initial_uses_blocking_seq_uses_nonblocking(self):
        sv = compile_source(
            "module m (clk, a, y_init, y_seq) { "
            "initial { y_init = a + 1; } "
            "seq (clk) { y_seq = a; } "
            "}"
        )
        text = sv["m"]
        # initial section
        initial_section = text.split("initial begin")[1].split("end")[0]
        assert "y_init = a + 1;" in initial_section
        assert "y_init <=" not in initial_section
        # seq section
        seq_section = text.split("always_ff")[1].split("endmodule")[0]
        assert "y_seq <= a;" in seq_section

    def test_pyslang_mixed_valid(self):
        sv = compile_source(
            "module m (clk, rst_n, a, b, y_i, y_c, y_s) { "
            "initial { y_i = 0; } "
            "comb { y_c = a & b; } "
            "seq (clk, neg: rst_n) { "
            "if (!rst_n) { y_s = 0; } else { y_s = y_s + 1; } "
            "} }"
        )["m"]
        errors = validate_sv(sv)
        assert len(errors) == 0
