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

from conftest import FIXTURES, compile_source, parse_module, validate_sv


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


# ────────────────────────────────────────────────────────────────
# Constant folding
# ────────────────────────────────────────────────────────────────

class TestConstantFolding:
    def test_fold_subtraction_with_zero(self):
        # W - `i - 1 when i=0 → should produce "W - 1" not "W - 0 - 1"
        sv = compile_source(
            "module m #(param W = 8) (y) { "
            "logic [W-1:0] y; "
            "`for (`i = 0; `i < 1; `i = `i + 1) { "
            "assign y = y >> (W - 1 - `i); "
            "} }"
        )
        text = sv["m"]
        assert "- 0" not in text
        assert "- 1" in text

    def test_fold_multiplication(self):
        # `i * 2 when i=3 → should produce "6"
        sv = compile_source(
            "module m (y) { "
            "`for (`i = 3; `i < 4; `i = `i + 1) { "
            "assign y = `i * 2; "
            "} }"
        )
        text = sv["m"]
        assert "6" in text

    def test_fold_addition(self):
        # `i + 1 when i=3 → should produce "4"
        sv = compile_source(
            "module m (y) { "
            "`for (`i = 3; `i < 4; `i = `i + 1) { "
            "assign y = `i + 1; "
            "} }"
        )
        text = sv["m"]
        assert "4" in text

    def test_fold_index(self):
        # data[`i] when i=3 → should produce "data[3]"
        sv = compile_source(
            "module m (y) { "
            "logic [7:0] data_0; logic [7:0] data_1; "
            "logic [7:0] data_2; logic [7:0] data_3; "
            "`for (`i = 0; `i < 4; `i = `i + 1) { "
            "assign data_`i = `i; "
            "} "
            "assign y = data_3; "
            "} "
        )
        text = sv["m"]
        assert "data_3" in text

    @pytest.mark.parametrize("width", [4, 8, 16])
    def test_fold_pipeline_param_width(self, width):
        # W - 1 - `i: when i=0 → W - 1, when i=1 → W - 2
        src = (
            "module m #(param W = " + str(width) + ") (y) { "
            "logic [W-1:0] y; "
            "`for (`i = 0; `i < 2; `i = `i + 1) { "
            "assign y = y >> (W - 1 - `i); "
            "} }"
        )
        sv = compile_source(src)
        text = sv["m"]
        assert "- 0" not in text


# ────────────────────────────────────────────────────────────────
# Template identifiers in instance names and connections
# ────────────────────────────────────────────────────────────────

class TestTemplateIdentInInstances:
    def test_instance_name_expansion(self):
        """u_stage_`i should expand to u_stage_0, u_stage_1, etc."""
        src = (
            "module inner (clk, data) { logic clk; logic data; } "
            "module m (clk) { "
            "logic clk; "
            "`for (`i = 0; `i < 3; `i = `i + 1) { "
            "inner u_stage_`i { .clk, .data(_) }; "
            "} }"
        )
        sv = compile_source(src)
        text = sv["m"]
        assert "u_stage_0" in text
        assert "u_stage_1" in text
        assert "u_stage_2" in text

    def test_instance_connection_expansion(self):
        """sd_`i in connections should expand to sd_0, sd_1, etc."""
        src = (
            "module inner (clk, data_out) { logic clk; logic data_out; } "
            "module m (clk, dout) { "
            "logic clk; logic [7:0] dout; "
            "`for (`i = 0; `i < 3; `i = `i + 1) { "
            "logic [7:0] sd_`i; "
            "inner u_`i { .clk, .data_out(sd_`i) }; "
            "} "
            "assign dout = sd_2; "
            "}"
        )
        sv = compile_source(src)
        text = sv["m"]
        assert "sd_0" in text
        assert "sd_1" in text
        assert "sd_2" in text
        assert "data_out(sd_0)" in text
        assert "data_out(sd_1)" in text
        assert "data_out(sd_2)" in text

    def test_template_ident_multi_var(self):
        """a`i_`j should expand correctly for nested loops."""
        src = (
            "module inner (clk, data) { logic clk; logic data; } "
            "module m (clk) { "
            "logic clk; "
            "`for (`i = 0; `i < 2; `i = `i + 1) { "
            "`for (`j = 0; `j < 2; `j = `j + 1) { "
            "inner u_`i_`j { .clk, .data(_) }; "
            "} } }"
        )
        sv = compile_source(src)
        text = sv["m"]
        assert "u_0_0" in text
        assert "u_0_1" in text
        assert "u_1_0" in text
        assert "u_1_1" in text

    def test_regex_mapping_with_template_var(self):
        """Regex replacement string with `i should be expanded per iteration."""
        src = (
            "module inner (clk, data_in, data_out) { "
            "logic clk; logic [7:0] data_in; logic [7:0] data_out; } "
            "module m (clk) { "
            "logic clk; "
            "`for (`i = 0; `i < 3; `i = `i + 1) { "
            "logic [7:0] bus_`i_in; logic [7:0] bus_`i_out; "
            "inner u_`i { .clk, \"data_(.*)\" => \"bus_`i_\\1\" }; "
            "} }"
        )
        sv = compile_source(src)
        text = sv["m"]
        # Each instance should get its own bus_N_in / bus_N_out
        assert "bus_0_in" in text
        assert "bus_0_out" in text
        assert "bus_1_in" in text
        assert "bus_1_out" in text
        assert "bus_2_in" in text
        assert "bus_2_out" in text
        # All instances should be present
        assert "u_0" in text
        assert "u_1" in text
        assert "u_2" in text
