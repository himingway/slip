"""Tests for metaprogramming: `for / `if / `else expansion."""

import pytest
from pathlib import Path

from slip.lexer import Lexer, TokenType
from slip.parser import Parser
from slip.ast import GenForStmt, GenIfStmt, SignalDecl, AssignStmt
from slip.semantic.gen_expand import expand_module
from slip.semantic import SemanticAnalyzer
from slip.codegen import CodeGenerator
from slip.errors.semantic import SlipSemanticError

FIXTURES = Path(__file__).parent / "fixtures"


def parse_module(source: str):
    tokens = Lexer(source, "test.slip").tokenize()
    modules = Parser(tokens, "test.slip").parse()
    return modules[0]


def compile_source(source: str) -> dict[str, str]:
    tokens = Lexer(source, "test.slip").tokenize()
    modules = Parser(tokens, "test.slip").parse()
    ir = SemanticAnalyzer().analyze(modules)
    return CodeGenerator().generate(ir)


# ────────────────────────────────────────────────────────────────
# Lexer: token merging
# ────────────────────────────────────────────────────────────────

class TestTickTokenMerging:
    def test_tick_for(self):
        tokens = Lexer("`for").tokenize()
        assert tokens[0].type == TokenType.TICK_FOR
        assert tokens[0].value == "`for"

    def test_tick_if(self):
        tokens = Lexer("`if").tokenize()
        assert tokens[0].type == TokenType.TICK_IF
        assert tokens[0].value == "`if"

    def test_tick_else(self):
        tokens = Lexer("`else").tokenize()
        assert tokens[0].type == TokenType.TICK_ELSE
        assert tokens[0].value == "`else"

    def test_tick_ident(self):
        tokens = Lexer("`i").tokenize()
        assert tokens[0].type == TokenType.TICK_IDENT
        assert tokens[0].value == "`i"

    def test_tick_alone_stays(self):
        tokens = Lexer("'").tokenize()
        assert tokens[0].type == TokenType.TICK

    def test_tick_ident_no_merge(self):
        tokens = Lexer("`foo").tokenize()
        assert tokens[0].type == TokenType.TICK_IDENT
        assert tokens[0].value == "`foo"

    def test_position_preserved(self):
        tokens = Lexer("  `for").tokenize()
        assert tokens[0].line == 1
        assert tokens[0].col == 3

    def test_template_ident_merge(self):
        tokens = Lexer("data_`i").tokenize()
        assert tokens[0].type == TokenType.IDENT
        assert tokens[0].value == "data_`i"


# ────────────────────────────────────────────────────────────────
# Parser: GenForStmt / GenIfStmt
# ────────────────────────────────────────────────────────────────

class TestGenParsing:
    def test_parse_gen_for(self):
        mod = parse_module(
            "module m { `for (`i = 0; `i < 4; `i = `i + 1) { logic x; } }"
        )
        stmt = mod.body[0]
        assert isinstance(stmt, GenForStmt)
        assert stmt.var == "i"

    def test_parse_gen_if(self):
        mod = parse_module(
            "module m { `if (1) { logic x; } }"
        )
        stmt = mod.body[0]
        assert isinstance(stmt, GenIfStmt)

    def test_parse_gen_if_else(self):
        mod = parse_module(
            "module m { `if (0) { logic a; } `else { logic b; } }"
        )
        stmt = mod.body[0]
        assert isinstance(stmt, GenIfStmt)
        assert stmt.else_body is not None

    def test_gen_for_with_param_bound(self):
        mod = parse_module(
            "module m #(param N = 4) { `for (`i = 0; `i < N; `i = `i + 1) { logic x; } }"
        )
        stmt = mod.body[0]
        assert isinstance(stmt, GenForStmt)


# ────────────────────────────────────────────────────────────────
# Expansion: `for
# ────────────────────────────────────────────────────────────────

class TestGenForExpansion:
    def test_for_expand_count(self):
        mod = parse_module(
            "module m { `for (`i = 0; `i < 3; `i = `i + 1) { logic x; } }"
        )
        expanded = expand_module(mod)
        assert len(expanded.body) == 3
        assert all(isinstance(s, SignalDecl) for s in expanded.body)

    def test_for_substitution(self):
        mod = parse_module(
            "module m (y) { `for (`i = 0; `i < 2; `i = `i + 1) { assign y = `i; } }"
        )
        expanded = expand_module(mod)
        assert len(expanded.body) == 2
        # First assign: y = 0
        a0 = expanded.body[0]
        assert isinstance(a0, AssignStmt)
        assert a0.value.raw == "0"
        a1 = expanded.body[1]
        assert a1.value.raw == "1"

    def test_for_with_param(self):
        mod = parse_module(
            "module m #(param N = 4) { `for (`i = 0; `i < N; `i = `i + 1) { logic x; } }"
        )
        expanded = expand_module(mod)
        assert len(expanded.body) == 4

    def test_for_zero_iterations(self):
        mod = parse_module(
            "module m { `for (`i = 0; `i < 0; `i = `i + 1) { logic x; } }"
        )
        expanded = expand_module(mod)
        assert len(expanded.body) == 0

    def test_nested_for(self):
        mod = parse_module(
            "module m { "
            "`for (`i = 0; `i < 2; `i = `i + 1) { "
            "  `for (`j = 0; `j < 2; `j = `j + 1) { logic x; } "
            "} }"
        )
        expanded = expand_module(mod)
        assert len(expanded.body) == 4

    def test_for_step_var_mismatch(self):
        mod = parse_module(
            "module m { `for (`i = 0; `i < 4; `j = `j + 1) { logic x; } }"
        )
        with pytest.raises(SlipSemanticError, match="step variable"):
            expand_module(mod)

    def test_for_non_evaluable_bound(self):
        mod = parse_module(
            "module m (x) { `for (`i = 0; `i < x; `i = `i + 1) { logic z; } }"
        )
        with pytest.raises(SlipSemanticError, match="compile time"):
            expand_module(mod)


# ────────────────────────────────────────────────────────────────
# Expansion: `if
# ────────────────────────────────────────────────────────────────

class TestGenIfExpansion:
    def test_if_true(self):
        mod = parse_module("module m { `if (1) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 1
        assert isinstance(expanded.body[0], SignalDecl)

    def test_if_false(self):
        mod = parse_module("module m { `if (0) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 0

    def test_if_else_true(self):
        mod = parse_module(
            "module m { `if (1) { logic a; } `else { logic b; } }"
        )
        expanded = expand_module(mod)
        assert len(expanded.body) == 1
        assert expanded.body[0].name == "a"

    def test_if_else_false(self):
        mod = parse_module(
            "module m { `if (0) { logic a; } `else { logic b; } }"
        )
        expanded = expand_module(mod)
        assert len(expanded.body) == 1
        assert expanded.body[0].name == "b"

    def test_if_with_param(self):
        mod = parse_module(
            "module m #(param ENABLE = 1) { `if (ENABLE) { logic x; } }"
        )
        expanded = expand_module(mod)
        assert len(expanded.body) == 1


# ────────────────────────────────────────────────────────────────
# Expansion: inside blocks
# ────────────────────────────────────────────────────────────────

class TestGenInBlocks:
    def test_for_inside_seq(self):
        mod = parse_module(
            "module m (clk) { seq (clk) { "
            "`for (`i = 0; `i < 2; `i = `i + 1) { assign y = `i; } "
            "} }"
        )
        expanded = expand_module(mod)
        seq = expanded.body[0]
        assert len(seq.body.statements) == 2

    def test_for_inside_comb(self):
        mod = parse_module(
            "module m (y) { comb { "
            "`for (`i = 0; `i < 3; `i = `i + 1) { assign y = `i; } "
            "} }"
        )
        expanded = expand_module(mod)
        comb = expanded.body[0]
        assert len(comb.body.statements) == 3


# ────────────────────────────────────────────────────────────────
# Codegen: full pipeline
# ────────────────────────────────────────────────────────────────

class TestGenCodegen:
    def test_for_produces_assigns(self):
        sv = compile_source(
            "module m (y) { `for (`i = 0; `i < 3; `i = `i + 1) { assign y = `i; } }"
        )
        assert "m" in sv
        text = sv["m"]
        assert text.count("assign") == 3

    def test_if_selects_branch(self):
        sv = compile_source(
            "module m (y) { `if (1) { assign y = 1; } }"
        )
        assert "assign y = 1;" in sv["m"]

    def test_if_removes_false_branch(self):
        sv = compile_source(
            "module m (y) { `if (0) { assign y = 1; } }"
        )
        assert "assign" not in sv["m"]

    def test_for_with_param_sv(self):
        sv = compile_source(
            "module m #(param N = 2) (y) { "
            "`for (`i = 0; `i < N; `i = `i + 1) { assign y = `i; } "
            "}"
        )
        assert sv["m"].count("assign") == 2

    def test_pyslang_valid_for(self):
        from pyslang import SyntaxTree, Compilation
        sv = compile_source(
            "module m (y) { `for (`i = 0; `i < 2; `i = `i + 1) { assign y = `i; } }"
        )["m"]
        tree = SyntaxTree.fromText(sv)
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert len(errors) == 0


# ────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────

class TestGenFixtures:
    def test_gen_for_fixture_compiles(self):
        sv = compile_source((FIXTURES / "gen_for.slip").read_text())
        assert "gen_for_test" in sv

    def test_gen_for_fixture_has_assigns(self):
        sv = compile_source((FIXTURES / "gen_for.slip").read_text())["gen_for_test"]
        assert sv.count("assign") == 4

    def test_gen_if_fixture_compiles(self):
        sv = compile_source((FIXTURES / "gen_if.slip").read_text())
        assert "gen_if_test" in sv

    def test_gen_if_fixture_comb_branch(self):
        sv = compile_source((FIXTURES / "gen_if.slip").read_text())["gen_if_test"]
        assert "always_comb" in sv
        assert "always_ff" not in sv


# ────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────

class TestGenCLI:
    def test_build_gen_for(self, tmp_path):
        from slip.cli._pipeline import run_build
        result = run_build(FIXTURES / "gen_for.slip", tmp_path, [])
        assert (tmp_path / "gen_for_test.sv").exists()

    def test_check_gen_for(self):
        from slip.cli._pipeline import run_check
        run_check(FIXTURES / "gen_for.slip", [])
