"""Tests for Slip v1.2 features: localparam, `_` dangling, `'0`/`'1`, constant validation."""

import pytest
from pathlib import Path

from slip.lexer import Lexer, TokenType
from slip.parser import Parser
from slip.semantic import SemanticAnalyzer
from slip.semantic.gen_expand import expand_module
from slip.semantic.symbol_collector import collect
from slip.semantic.expr_serializer import expr_to_sv
from slip.slang_integration import reflect_module
from slip.codegen import CodeGenerator
from slip.errors.semantic import SlipSemanticError

from conftest import FIXTURES, IP_DIR, compile_source as _compile


# ════════════════════════════════════════════════════════════════
# A. localparam
# ════════════════════════════════════════════════════════════════

class TestLocalparamParsing:
    def test_single_localparam(self):
        tokens = Lexer("module top { localparam W = 8; }", "t.slip").tokenize()
        unit = Parser(tokens, "t.slip").parse()
        mods = unit.modules
        from slip.ast.statements import LocalParamDecl
        lps = [s for s in mods[0].body if isinstance(s, LocalParamDecl)]
        assert len(lps) == 1
        assert lps[0].name == "W"

    def test_comma_separated_localparams(self):
        tokens = Lexer("module top { localparam A = 1, B = 2; }", "t.slip").tokenize()
        unit = Parser(tokens, "t.slip").parse()
        mods = unit.modules
        from slip.ast.statements import LocalParamDecl, BlockStmt
        # Comma-separated returns a BlockStmt wrapping multiple LocalParamDecl
        body = mods[0].body
        assert len(body) == 1
        assert isinstance(body[0], BlockStmt)
        lps = body[0].statements
        assert len(lps) == 2
        assert lps[0].name == "A"
        assert lps[1].name == "B"

    def test_localparam_expression(self):
        tokens = Lexer("module top { localparam W = 4 * 2; }", "t.slip").tokenize()
        unit = Parser(tokens, "t.slip").parse()
        mods = unit.modules
        from slip.ast.statements import LocalParamDecl
        lp = [s for s in mods[0].body if isinstance(s, LocalParamDecl)][0]
        assert lp.name == "W"


class TestLocalparamCodegen:
    def test_localparam_emitted_in_sv(self):
        sv = _compile("module top (clk) { logic clk; localparam W = 8; logic [W-1:0] data; assign data = 0; }")
        text = sv["top"]
        assert "localparam W = 8" in text

    def test_localparam_not_in_header(self):
        sv = _compile("module top (clk) { logic clk; localparam W = 8; }")
        text = sv["top"]
        assert "parameter" not in text
        assert "localparam W = 8" in text

    def test_localparam_with_param(self):
        sv = _compile(
            "module top #(param DEPTH = 4) (clk) {\n"
            "  logic clk;\n"
            "  localparam HALF = DEPTH / 2;\n"
            "  logic [HALF-1:0] cnt;\n"
            "  assign cnt = 0;\n"
            "}\n"
        )
        text = sv["top"]
        assert "parameter DEPTH = 4" in text
        assert "localparam HALF = DEPTH / 2" in text


class TestLocalparamGenExpand:
    def test_localparam_in_if_condition(self):
        sv = _compile(
            "module top (clk) {\n"
            "  logic clk;\n"
            "  localparam ENABLE = 1;\n"
            "  `if (ENABLE) {\n"
            "    logic flag;\n"
            "    assign flag = 1;\n"
            "  }\n"
            "}\n"
        )
        text = sv["top"]
        assert "logic flag" in text
        assert "assign flag = 1" in text

    def test_localparam_in_if_false(self):
        sv = _compile(
            "module top (clk) {\n"
            "  logic clk;\n"
            "  localparam DISABLE = 0;\n"
            "  `if (DISABLE) {\n"
            "    logic flag;\n"
            "    assign flag = 1;\n"
            "  }\n"
            "}\n"
        )
        text = sv["top"]
        assert "flag" not in text

    def test_localparam_in_for_bound(self):
        sv = _compile(
            "module top (clk) {\n"
            "  logic clk;\n"
            "  localparam N = 3;\n"
            "  `for (`i = 0; `i < N; `i = `i + 1) {\n"
            "    logic [7:0] data_`i;\n"
            "    assign data_`i = `i;\n"
            "  }\n"
            "}\n"
        )
        text = sv["top"]
        assert "logic [7:0] data_0" in text
        assert "logic [7:0] data_1" in text
        assert "logic [7:0] data_2" in text
        assert "assign data_0 = 0" in text
        assert "assign data_2 = 2" in text

    def test_localparam_symbol_collection(self):
        tokens = Lexer(
            "module top (clk) { logic clk; localparam W = 8; logic [W-1:0] d; assign d = 0; }",
            "t.slip"
        ).tokenize()
        unit = Parser(tokens, "t.slip").parse()
        mods = unit.modules
        syms = collect(mods[0])
        assert "W" in syms.localparams
        assert "W" not in syms.signals


# ════════════════════════════════════════════════════════════════
# B. localparam override check (Feature 5)
# ════════════════════════════════════════════════════════════════

class TestLocalparamOverrideCheck:
    def test_override_param_ok(self):
        source = (
            "module inner #(param W = 8) (clk) { logic clk; }\n"
            "module top (clk) {\n"
            "  logic clk;\n"
            "  inner #(.W(16)) u1 { .clk };\n"
            "}\n"
        )
        _compile(source)  # should not raise

    def test_override_localparam_error(self):
        source = (
            "module inner (clk) { logic clk; localparam W = 8; }\n"
            "module top (clk) {\n"
            "  logic clk;\n"
            "  inner #(.W(16)) u1 { .clk };\n"
            "}\n"
        )
        with pytest.raises(SlipSemanticError, match="cannot override localparam"):
            _compile(source)


# ════════════════════════════════════════════════════════════════
# C. Reflection is_local (Feature 6)
# ════════════════════════════════════════════════════════════════

class TestReflectionIsLocal:
    def test_param_is_not_local(self):
        info = reflect_module(IP_DIR / "prim_fifo.sv", "prim_fifo")
        width_p = [p for p in info.params if p.name == "Width"][0]
        assert width_p.is_local is False

    def test_localparam_is_local(self):
        info = reflect_module(IP_DIR / "ip_with_localparam.sv", "ip_with_localparam")
        half_p = [p for p in info.params if p.name == "HALF_W"][0]
        assert half_p.is_local is True
        width_p = [p for p in info.params if p.name == "WIDTH"][0]
        assert width_p.is_local is False

    def test_override_ip_localparam_error(self):
        source = (
            "module top (clk, din, dout) {\n"
            "  logic clk;\n"
            "  logic [7:0] din;\n"
            "  logic [3:0] dout;\n"
            "  ip_with_localparam #(.WIDTH(8), .HALF_W(2)) u1 {\n"
            "    .clk, .din, .dout(dout), .valid\n"
            "  };\n"
            "}\n"
        )
        with pytest.raises(SlipSemanticError, match="cannot override localparam"):
            _compile(source, [IP_DIR])


# ════════════════════════════════════════════════════════════════
# D. `_` dangling marker (Feature 2)
# ════════════════════════════════════════════════════════════════

class TestDanglingMarker:
    def test_dangling_input_omitted_in_sv(self):
        source = (
            "module inner (clk, rst_n, data) {\n"
            "  logic clk; logic rst_n; logic [7:0] data;\n"
            "  assign data = 0;\n"
            "}\n"
            "module top (clk) {\n"
            "  logic clk;\n"
            "  inner u1 { .clk, .rst_n(_), .data };\n"
            "}\n"
        )
        sv = _compile(source)
        text = sv["top"]
        assert ".clk(clk)" in text
        assert ".data(data)" in text
        assert ".rst_n" not in text

    def test_dangling_output_omitted(self):
        source = (
            "module inner (clk, data, valid) {\n"
            "  logic clk; logic [7:0] data; logic valid;\n"
            "  assign data = 0; assign valid = 1;\n"
            "}\n"
            "module top (clk) {\n"
            "  logic clk;\n"
            "  inner u1 { .clk, .data, .valid(_) };\n"
            "}\n"
        )
        sv = _compile(source)
        text = sv["top"]
        assert ".valid" not in text
        assert ".clk(clk)" in text

    def test_dangling_not_in_symbols(self):
        tokens = Lexer(
            "module top (clk) { logic clk; inner u1 { .clk, .rst(_) }; }",
            "t.slip"
        ).tokenize()
        unit = Parser(tokens, "t.slip").parse()
        mods = unit.modules
        syms = collect(mods[0])
        assert "_" not in syms.all_refs


# ════════════════════════════════════════════════════════════════
# E. `'0` / `'1` constants (Feature 3)
# ════════════════════════════════════════════════════════════════

class TestTickConstants:
    def test_tick_zero_token(self):
        tokens = Lexer("'0", "t.slip").tokenize()
        assert tokens[0].type == TokenType.TICK_ZERO
        assert tokens[0].value == "'0"

    def test_tick_one_token(self):
        tokens = Lexer("'1", "t.slip").tokenize()
        assert tokens[0].type == TokenType.TICK_ONE
        assert tokens[0].value == "'1"

    def test_tick_two_not_merged(self):
        tokens = Lexer("'2", "t.slip").tokenize()
        assert tokens[0].type == TokenType.TICK
        assert tokens[1].type == TokenType.INT_LITERAL

    def test_verilog_literal_not_merged(self):
        tokens = Lexer("8'hFF", "t.slip").tokenize()
        assert tokens[0].type == TokenType.INT_LITERAL
        assert tokens[0].value == "8'hFF"

    def test_tick_zero_in_connection(self):
        source = (
            "module inner (clk, rst_n) { logic clk; logic rst_n; }\n"
            "module top (clk) {\n"
            "  logic clk;\n"
            "  inner u1 { .clk, .rst_n('0) };\n"
            "}\n"
        )
        sv = _compile(source)
        text = sv["top"]
        assert ".rst_n('0)" in text

    def test_tick_one_in_connection(self):
        source = (
            "module inner (clk, en) { logic clk; logic en; }\n"
            "module top (clk) {\n"
            "  logic clk;\n"
            "  inner u1 { .clk, .en('1) };\n"
            "}\n"
        )
        sv = _compile(source)
        text = sv["top"]
        assert ".en('1)" in text

    def test_tick_in_if_condition_error(self):
        source = (
            "module top (clk) {\n"
            "  logic clk;\n"
            "  `if ('1) { logic x; assign x = 0; }\n"
            "}\n"
        )
        with pytest.raises(SlipSemanticError, match="cannot be evaluated"):
            _compile(source)


# ════════════════════════════════════════════════════════════════
# F. Constant validation (Feature 4)
# ════════════════════════════════════════════════════════════════

class TestConstantValidation:
    def test_bare_zero_rejected(self):
        source = (
            "module inner (clk, rst) { logic clk; logic rst; }\n"
            "module top (clk) {\n"
            "  logic clk;\n"
            "  inner u1 { .clk, .rst(0) };\n"
            "}\n"
        )
        with pytest.raises(SlipSemanticError, match="bare integer"):
            _compile(source)

    def test_bare_one_rejected(self):
        source = (
            "module inner (clk, en) { logic clk; logic en; }\n"
            "module top (clk) {\n"
            "  logic clk;\n"
            "  inner u1 { .clk, .en(1) };\n"
            "}\n"
        )
        with pytest.raises(SlipSemanticError, match="bare integer"):
            _compile(source)

    def test_width_prefixed_ok(self):
        source = (
            "module inner (clk, rst) { logic clk; logic rst; }\n"
            "module top (clk) {\n"
            "  logic clk;\n"
            "  inner u1 { .clk, .rst(1'b0) };\n"
            "}\n"
        )
        sv = _compile(source)
        assert ".rst(1'b0)" in sv["top"]

    def test_tick_zero_ok(self):
        source = (
            "module inner (clk, rst) { logic clk; logic rst; }\n"
            "module top (clk) {\n"
            "  logic clk;\n"
            "  inner u1 { .clk, .rst('0) };\n"
            "}\n"
        )
        sv = _compile(source)
        assert ".rst('0)" in sv["top"]

    def test_hex_literal_ok(self):
        source = (
            "module inner (clk, data) { logic clk; logic [7:0] data; }\n"
            "module top (clk) {\n"
            "  logic clk;\n"
            "  inner u1 { .clk, .data(8'hFF) };\n"
            "}\n"
        )
        sv = _compile(source)
        assert ".data(8'hFF)" in sv["top"]
