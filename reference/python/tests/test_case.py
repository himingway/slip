"""Tests for case/casez/casex statements."""

import pytest

from slip.lexer import Lexer, TokenType
from slip.parser import Parser
from slip.ast import CaseStmt, CaseItem, AssignStmt, CombBlock
from slip.semantic.gen_expand import expand_module
from slip.semantic import SemanticAnalyzer
from slip.codegen import CodeGenerator
from slip.errors.syntax import SlipSyntaxError

from conftest import compile_source, parse_module


# ────────────────────────────────────────────────────────────────
# Lexer
# ────────────────────────────────────────────────────────────────

class TestCaseLexer:
    def test_case_keyword(self):
        tokens = Lexer("case").tokenize()
        assert tokens[0].type == TokenType.CASE

    def test_casez_keyword(self):
        tokens = Lexer("casez").tokenize()
        assert tokens[0].type == TokenType.CASEZ

    def test_casex_keyword(self):
        tokens = Lexer("casex").tokenize()
        assert tokens[0].type == TokenType.CASEX

    def test_default_keyword(self):
        tokens = Lexer("default").tokenize()
        assert tokens[0].type == TokenType.DEFAULT


# ────────────────────────────────────────────────────────────────
# Parser
# ────────────────────────────────────────────────────────────────

class TestCaseParsing:
    def test_parse_simple_case(self):
        mod = parse_module(
            "module m (y) { comb { "
            "case (sel) { "
            "  0: { assign y = a; } "
            "  1: { assign y = b; } "
            "} } }"
        )
        comb = mod.body[0]
        assert isinstance(comb, CombBlock)
        case = comb.body.statements[0]
        assert isinstance(case, CaseStmt)
        assert case.kind == "case"
        assert len(case.items) == 2

    def test_parse_casez(self):
        mod = parse_module(
            "module m (y) { comb { "
            "casez (sel) { "
            "  4'b1???: { assign y = 1; } "
            "} } }"
        )
        case = mod.body[0].body.statements[0]
        assert isinstance(case, CaseStmt)
        assert case.kind == "casez"

    def test_parse_casex(self):
        mod = parse_module(
            "module m (y) { comb { "
            "casex (sel) { "
            "  4'b1xxx: { assign y = 1; } "
            "} } }"
        )
        case = mod.body[0].body.statements[0]
        assert isinstance(case, CaseStmt)
        assert case.kind == "casex"

    def test_parse_case_with_default(self):
        mod = parse_module(
            "module m (y) { comb { "
            "case (sel) { "
            "  0: { assign y = a; } "
            "  default: { assign y = 0; } "
            "} } }"
        )
        case = mod.body[0].body.statements[0]
        assert isinstance(case, CaseStmt)
        assert len(case.items) == 2
        assert case.items[1].patterns == ()  # default has empty patterns

    def test_parse_case_multi_pattern(self):
        mod = parse_module(
            "module m (y) { comb { "
            "case (sel) { "
            "  0, 1: { assign y = a; } "
            "  default: { assign y = 0; } "
            "} } }"
        )
        case = mod.body[0].body.statements[0]
        assert isinstance(case, CaseStmt)
        assert len(case.items[0].patterns) == 2

    def test_parse_case_single_stmt(self):
        mod = parse_module(
            "module m (y) { comb { "
            "case (sel) { "
            "  0: assign y = a; "
            "  default: assign y = 0; "
            "} } }"
        )
        case = mod.body[0].body.statements[0]
        assert isinstance(case, CaseStmt)
        assert len(case.items) == 2

    def test_parse_case_syntax_error(self):
        with pytest.raises(SlipSyntaxError):
            parse_module(
                "module m (y) { comb { case sel { } } }"
            )


# ────────────────────────────────────────────────────────────────
# Codegen
# ────────────────────────────────────────────────────────────────

class TestCaseCodegen:
    def test_case_generates_sv(self):
        sv = compile_source(
            "module m (y, sel) { "
            "comb { "
            "case (sel) { "
            "  0: { assign y = 1; } "
            "  1: { assign y = 0; } "
            "} } }"
        )
        text = sv["m"]
        assert "case (sel)" in text
        assert "endcase" in text
        assert "default" not in text

    def test_case_default_sv(self):
        sv = compile_source(
            "module m (y, sel) { "
            "comb { "
            "case (sel) { "
            "  0: { assign y = 1; } "
            "  default: { assign y = 0; } "
            "} } }"
        )
        text = sv["m"]
        assert "default" in text
        assert "endcase" in text

    def test_casez_sv(self):
        sv = compile_source(
            "module m (y, sel) { "
            "comb { "
            "casez (sel) { "
            "  4'b1???: { assign y = 1; } "
            "  default: { assign y = 0; } "
            "} } }"
        )
        text = sv["m"]
        assert "casez (sel)" in text
        assert "endcase" in text

    def test_casex_sv(self):
        sv = compile_source(
            "module m (y, sel) { "
            "comb { "
            "casex (sel) { "
            "  4'b1???: { assign y = 1; } "
            "  default: { assign y = 0; } "
            "} } }"
        )
        text = sv["m"]
        assert "casex (sel)" in text
        assert "endcase" in text

    def test_case_in_seq(self):
        sv = compile_source(
            "module m (clk, y) { "
            "seq (clk) { "
            "case (y) { "
            "  0: { assign y = 1; } "
            "  1: { assign y = 0; } "
            "} } }"
        )
        text = sv["m"]
        assert "always_ff" in text
        assert "case (y)" in text
        # seq block converts to nonblocking
        assert "<=" in text

    def test_case_multi_pattern_sv(self):
        sv = compile_source(
            "module m (y, sel) { "
            "comb { "
            "case (sel) { "
            "  0, 1: { assign y = 1; } "
            "  default: { assign y = 0; } "
            "} } }"
        )
        text = sv["m"]
        assert "0, 1: begin" in text

    def test_pyslang_valid_case(self):
        from pyslang import SyntaxTree, Compilation
        sv = compile_source(
            "module m (y, sel) { "
            "logic [1:0] sel; "
            "comb { "
            "case (sel) { "
            "  0: { assign y = 1; } "
            "  1: { assign y = 0; } "
            "  default: { assign y = 0; } "
            "} } }"
        )["m"]
        tree = SyntaxTree.fromText(sv)
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert len(errors) == 0, f"SV errors: {[str(d) for d in errors]}"

    def test_pyslang_valid_casez(self):
        from pyslang import SyntaxTree, Compilation
        sv = compile_source(
            "module m (y, sel) { "
            "logic [3:0] sel; "
            "comb { "
            "casez (sel) { "
            "  4'b1???: { assign y = 1; } "
            "  default: { assign y = 0; } "
            "} } }"
        )["m"]
        tree = SyntaxTree.fromText(sv)
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert len(errors) == 0, f"SV errors: {[str(d) for d in errors]}"
