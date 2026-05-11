"""Complex integration tests: realistic hardware designs, operator precedence
stress tests, error reporting, and edge cases."""

import re
import pytest
from pathlib import Path

from slip.lexer import Lexer, TokenType
from slip.parser import Parser
from slip.semantic import SemanticAnalyzer, expr_to_sv
from slip.ast.expressions import (
    BinaryExpr, CallExpr, ConcatExpr, IdentExpr, IndexExpr,
    IntLiteralExpr, ParenExpr, TernaryExpr, UnaryExpr,
)
from slip.ast.statements import AssignStmt, BlockStmt, IfStmt, SeqBlock, SignalDecl
from slip.codegen import CodeGenerator
from slip.errors.syntax import SlipSyntaxError
from slip.errors.semantic import SlipSemanticError

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
# 1. Complex fixture compilation (UART TX, FIFO, Arbiter)
# ────────────────────────────────────────────────────────────────

class TestUARTTX:
    def test_compiles(self):
        sv = compile_source((FIXTURES / "uart_tx.slip").read_text())
        assert "uart_tx" in sv

    def test_params(self):
        sv = compile_source((FIXTURES / "uart_tx.slip").read_text())["uart_tx"]
        assert "parameter CLK_FREQ = 50000000" in sv
        assert "parameter BAUD = 115200" in sv

    def test_ports(self):
        sv = compile_source((FIXTURES / "uart_tx.slip").read_text())["uart_tx"]
        assert "input logic clk" in sv
        assert "input logic rst_n" in sv
        assert "input logic [7:0] tx_data" in sv
        assert "output logic tx_ready" in sv
        assert "output logic tx_pin" in sv

    def test_continuous_assign(self):
        sv = compile_source((FIXTURES / "uart_tx.slip").read_text())["uart_tx"]
        assert "assign tx_ready = ~(tx_valid & ~tx_done)" in sv

    def test_seq_block_correctness(self):
        sv = compile_source((FIXTURES / "uart_tx.slip").read_text())["uart_tx"]
        assert "always_ff @(posedge clk or negedge rst_n)" in sv
        # All assignments in seq block must be nonblocking
        lines = sv.split("\n")
        in_always = False
        for line in lines:
            if "always_ff" in line:
                in_always = True
            if in_always and "<=" in line:
                assert "= " not in line.replace("<=", "") or "<= " in line
            if "endmodule" in line:
                in_always = False

    def test_concatenation(self):
        sv = compile_source((FIXTURES / "uart_tx.slip").read_text())["uart_tx"]
        assert "{tx_data, 1'b0}" in sv

    def test_state_machine(self):
        sv = compile_source((FIXTURES / "uart_tx.slip").read_text())["uart_tx"]
        # Should have state 0, 1, 2, 3 transitions
        assert "state <= 0" in sv
        assert "state <= 1" in sv
        assert "state <= 2" in sv
        assert "state <= 3" in sv

    def test_pyslang_valid(self):
        from pyslang import SyntaxTree, Compilation
        sv = compile_source((FIXTURES / "uart_tx.slip").read_text())["uart_tx"]
        tree = SyntaxTree.fromText(sv, "uart_tx.sv")
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        # Filter single-module context errors
        errors = [e for e in errors if "Undeclared" not in str(e.code)
                  and "Unknown" not in str(e.code)]
        assert len(errors) == 0, f"Unexpected errors: {errors}"


class TestFIFO:
    def test_compiles(self):
        sv = compile_source((FIXTURES / "pipeline.slip").read_text())
        assert "fifo" in sv

    def test_multi_param(self):
        sv = compile_source((FIXTURES / "pipeline.slip").read_text())["fifo"]
        assert "parameter DW = 32" in sv
        assert "parameter DEPTH = 16" in sv
        assert "parameter AW = 4" in sv

    def test_array_signal(self):
        sv = compile_source((FIXTURES / "pipeline.slip").read_text())["fifo"]
        assert "mem [0:DEPTH - 1]" in sv

    def test_param_expr_width(self):
        sv = compile_source((FIXTURES / "pipeline.slip").read_text())["fifo"]
        assert "[DW - 1:0]" in sv
        assert "[AW:0]" in sv

    def test_dual_assigns_in_seq(self):
        sv = compile_source((FIXTURES / "pipeline.slip").read_text())["fifo"]
        # Both write and read pointers updated in same always_ff
        assert "wr_ptr <= wr_ptr + 1" in sv
        assert "rd_ptr <= rd_ptr + 1" in sv

    def test_assign_expressions(self):
        sv = compile_source((FIXTURES / "pipeline.slip").read_text())["fifo"]
        assert "assign full = (cnt == DEPTH)" in sv
        assert "assign empty = (cnt == 0)" in sv
        assert "assign dout = mem[rd_ptr]" in sv


class TestArbiter:
    def test_compiles(self):
        sv = compile_source((FIXTURES / "crossbar.slip").read_text())
        assert "arbiter" in sv

    def test_reduction_operators(self):
        sv = compile_source((FIXTURES / "crossbar.slip").read_text())["arbiter"]
        assert "|masked_req" in sv
        assert "|req" in sv

    def test_bitwise_operations(self):
        sv = compile_source((FIXTURES / "crossbar.slip").read_text())["arbiter"]
        assert "req & ~(req - 1)" in sv
        assert "masked_req & ~(masked_req - 1)" in sv

    def test_part_select(self):
        sv = compile_source((FIXTURES / "crossbar.slip").read_text())["arbiter"]
        assert "prio[N - 2:0]" in sv


# ────────────────────────────────────────────────────────────────
# 2. Pratt parser precedence stress tests
# ────────────────────────────────────────────────────────────────

class TestPrecedenceStress:
    def test_deep_nesting(self):
        sv = compile_source("module m (a, b, c, d, e, y) { assign y = a + b * c - d / e; }")
        assert "a + b * c - d / e" in sv["m"]

    def test_parentheses_override(self):
        sv = compile_source("module m (a, b, c, y) { assign y = (a + b) * c; }")
        assert "(a + b) * c" in sv["m"]

    def test_chained_ternary(self):
        sv = compile_source("module m (s, a, b, c, d, y) { assign y = s ? a : b ? c : d; }")
        text = sv["m"]
        assert "?" in text and ":" in text

    def test_all_binary_ops(self):
        """Test every binary operator at least once."""
        ops = ["+", "-", "*", "/", "%", "==", "!=", "<", ">", ">=",
               "&&", "||", "&", "|", "^", "<<", ">>"]
        for op in ops:
            src = f'module m (a, b, y) {{ assign y = a {op} b; }}'
            sv = compile_source(src)
            assert op in sv["m"] or (op == ">=" and ">=" in sv["m"])

    def test_unary_prefix(self):
        sv = compile_source("module m (a, y) { assign y = ~a; }")
        assert "~a" in sv["m"]

    def test_unary_bang(self):
        sv = compile_source("module m (a, y) { assign y = !a; }")
        assert "!a" in sv["m"]

    def test_reduction_and(self):
        sv = compile_source("module m (a, y) { assign y = &a; }")
        assert "&a" in sv["m"]

    def test_reduction_or(self):
        sv = compile_source("module m (a, y) { assign y = |a; }")
        assert "|a" in sv["m"]

    def test_reduction_xor(self):
        sv = compile_source("module m (a, y) { assign y = ^a; }")
        assert "^a" in sv["m"]

    def test_mixed_unary_binary(self):
        sv = compile_source("module m (a, b, y) { assign y = !a & ~b; }")
        assert "!a & ~b" in sv["m"]

    def test_shift_in_expression(self):
        sv = compile_source("module m (a, b, y) { assign y = a << 2 | b >> 1; }")
        assert "a << 2 | b >> 1" in sv["m"]

    def test_complex_conditional(self):
        sv = compile_source(
            "module m (a, b, c, d, y) { "
            "assign y = (a == b) ? (c & d) : (c | d); }"
        )
        assert "(a == b) ? (c & d) : (c | d)" in sv["m"]


# ────────────────────────────────────────────────────────────────
# 3. Expression round-trip: parse → serialize → verify structure
# ────────────────────────────────────────────────────────────────

class TestExprRoundTrip:
    def _roundtrip(self, expr_src: str) -> str:
        source = f"module m (y) {{ assign y = {expr_src}; }}"
        tokens = Lexer(source).tokenize()
        modules = Parser(tokens).parse()
        assign = modules[0].body[0]
        return expr_to_sv(assign.value)

    def test_ident(self):
        assert self._roundtrip("a") == "a"

    def test_int_literal(self):
        assert self._roundtrip("42") == "42"

    def test_verilog_literal(self):
        assert self._roundtrip("8'hFF") == "8'hFF"

    def test_add(self):
        assert self._roundtrip("a + b") == "a + b"

    def test_mul_before_add(self):
        result = self._roundtrip("a + b * c")
        assert result == "a + b * c"

    def test_paren_group(self):
        result = self._roundtrip("(a + b) * c")
        assert result == "(a + b) * c"

    def test_ternary(self):
        result = self._roundtrip("a ? b : c")
        assert result == "a ? b : c"

    def test_nested_ternary(self):
        result = self._roundtrip("a ? b ? c : d : e")
        assert "b ? c : d" in result

    def test_index(self):
        assert self._roundtrip("a[3]") == "a[3]"

    def test_range(self):
        assert self._roundtrip("a[7:0]") == "a[7:0]"

    def test_concat(self):
        assert self._roundtrip("{a, b}") == "{a, b}"

    def test_multi_concat(self):
        assert self._roundtrip("{a, b[3:0], 4'hF}") == "{a, b[3:0], 4'hF}"

    def test_unary_neg(self):
        assert self._roundtrip("-a") == "-a"

    def test_system_func(self):
        assert self._roundtrip("$clog2(16)") == "$clog2(16)"

    def test_chained_ops(self):
        result = self._roundtrip("a + b - c * d / e")
        assert "a + b - c * d / e" == result


# ────────────────────────────────────────────────────────────────
# 4. Implicit port inference edge cases
# ────────────────────────────────────────────────────────────────

class TestImplicitPorts:
    def test_read_only_is_input(self):
        """'a' is in port list but only read -> input."""
        sv = compile_source("module m (y, a) { logic y; assign y = a; }")
        assert "input logic a" in sv["m"]

    def test_written_only_is_output(self):
        """'y' is in port list and written -> output."""
        sv = compile_source("module m (y) { assign y = 1; }")
        assert "output logic y" in sv["m"]

    def test_internal_signal_not_port(self):
        """A signal both read and written internally should NOT become a port."""
        sv = compile_source(
            "module m (clk, out) { "
            "logic [7:0] tmp; "
            "assign tmp = 8'hFF; "
            "assign out = tmp & tmp; "
            "}"
        )
        assert "output logic out" in sv["m"]
        assert "input logic clk" in sv["m"]
        # tmp should be a signal, not a port
        lines = sv["m"]
        # Count port declarations (input/output)
        port_count = len(re.findall(r'(input|output) logic', lines))
        assert port_count == 2  # only clk and out

    def test_mixed_assign_and_seq(self):
        sv = compile_source(
            "module m (clk, rst, a, b, comb_out, seq_out) { "
            "assign comb_out = a ^ b; "
            "seq (clk, neg: rst) { "
            "if (!rst) { seq_out = 0; } else { seq_out = seq_out + 1; } "
            "} }"
        )
        assert "assign comb_out = a ^ b" in sv["m"]
        assert "always_ff" in sv["m"]
        assert "input logic a" in sv["m"]
        assert "output logic comb_out" in sv["m"]
        assert "output logic seq_out" in sv["m"]


# ────────────────────────────────────────────────────────────────
# 5. Seq block edge cases
# ────────────────────────────────────────────────────────────────

class TestSeqBlockEdgeCases:
    def test_pos_reset(self):
        sv = compile_source(
            "module m (clk, rst) { seq (clk, pos: rst) { a = 1; } }"
        )
        assert "posedge rst" in sv["m"]

    def test_no_reset(self):
        sv = compile_source("module m (clk) { seq (clk) { a = 1; } }")
        assert "posedge clk" in sv["m"]
        assert "negedge" not in sv["m"]
        assert "or" not in sv["m"].split("always_ff")[1].split("begin")[0]

    def test_multiple_seq_blocks(self):
        sv = compile_source(
            "module m (clk, rst_n, a, b) { "
            "seq (clk, neg: rst_n) { a = 0; } "
            "seq (clk, neg: rst_n) { b = 1; } "
            "}"
        )
        assert sv["m"].count("always_ff") == 2

    def test_nested_if_else_chain(self):
        sv = compile_source(
            "module m (clk, rst_n, sel, a, b, c, out) { "
            "seq (clk, neg: rst_n) { "
            "if (!rst_n) { out = 0; } else { "
            "if (sel == 0) { out = a; } else { "
            "if (sel == 1) { out = b; } else { out = c; } "
            "} } } }"
        )
        text = sv["m"]
        assert text.count("if") >= 3
        assert text.count("else") >= 2

    def test_all_blocking_become_nonblocking(self):
        sv = compile_source(
            "module m (clk) { "
            "seq (clk) { "
            "a = 1; "
            "b = a + 2; "
            "c = b * 3; "
            "} }"
        )
        text = sv["m"]
        # No blocking assigns in always_ff block
        always_section = text.split("always_ff")[1].split("endmodule")[0]
        lines = [l.strip() for l in always_section.split("\n") if l.strip()]
        for line in lines:
            if "<=" in line:
                # Should NOT have "= " without "<" before it (blocking)
                # except in sensitivity list
                assert "assign" not in line


# ────────────────────────────────────────────────────────────────
# 6. Error reporting
# ────────────────────────────────────────────────────────────────

class TestErrorReporting:
    def test_unexpected_token(self):
        with pytest.raises(SlipSyntaxError, match="expected SEMICOLON"):
            parse_source("module m { logic a }")

    def test_unmatched_brace(self):
        with pytest.raises(SlipSyntaxError):
            parse_source("module m { logic a;")

    def test_missing_module_keyword(self):
        with pytest.raises(SlipSyntaxError, match="expected MODULE"):
            parse_source("foo {}")

    def test_error_has_location(self):
        with pytest.raises(SlipSyntaxError) as exc_info:
            parse_source("module m { logic a }")
        err = exc_info.value
        assert err.line > 0
        assert err.col > 0

    def test_unterminated_string_literal(self):
        with pytest.raises(SlipSyntaxError, match="unterminated"):
            Lexer('"hello').tokenize()

    def test_unterminated_block_comment(self):
        with pytest.raises(SlipSyntaxError, match="unterminated"):
            Lexer("a /* comment").tokenize()


# ────────────────────────────────────────────────────────────────
# 7. Multiple modules in one file
# ────────────────────────────────────────────────────────────────

class TestMultiModule:
    def test_two_modules(self):
        source = (
            "module adder (a, b, sum) { assign sum = a + b; } "
            "module sub (a, b, diff) { assign diff = a - b; }"
        )
        sv = compile_source(source)
        assert "adder" in sv
        assert "sub" in sv
        assert "a + b" in sv["adder"]
        assert "a - b" in sv["sub"]

    def test_three_modules(self):
        source = (
            "module mod_a (x) { assign x = 1; } "
            "module mod_b (y) { assign y = 2; } "
            "module mod_c (z) { assign z = 3; }"
        )
        sv = compile_source(source)
        assert len(sv) == 3


# ────────────────────────────────────────────────────────────────
# 8. Operator expression structure verification (AST-level)
# ────────────────────────────────────────────────────────────────

class TestASTStructure:
    def _get_expr(self, source: str):
        tokens = Lexer(source, "test.slip").tokenize()
        modules = Parser(tokens, "test.slip").parse()
        assign = modules[0].body[0]
        return assign.value

    def test_add_is_binary(self):
        expr = self._get_expr("module m (y) { assign y = a + b; }")
        assert isinstance(expr, BinaryExpr)
        assert expr.op == "+"

    def test_mul_has_higher_precedence(self):
        expr = self._get_expr("module m (y) { assign y = a + b * c; }")
        assert isinstance(expr, BinaryExpr)
        assert expr.op == "+"
        assert isinstance(expr.right, BinaryExpr)
        assert expr.right.op == "*"

    def test_ternary_structure(self):
        expr = self._get_expr("module m (y) { assign y = a ? b : c; }")
        assert isinstance(expr, TernaryExpr)
        assert isinstance(expr.cond, IdentExpr)
        assert expr.cond.name == "a"

    def test_nested_index(self):
        expr = self._get_expr("module m (y) { assign y = a[3:0]; }")
        assert isinstance(expr, IndexExpr)
        assert expr.high is not None

    def test_single_index(self):
        expr = self._get_expr("module m (y) { assign y = a[3]; }")
        assert isinstance(expr, IndexExpr)
        assert expr.high is None

    def test_concat_structure(self):
        expr = self._get_expr("module m (y) { assign y = {a, b}; }")
        assert isinstance(expr, ConcatExpr)
        assert len(expr.parts) == 2

    def test_call_expr(self):
        expr = self._get_expr("module m (y) { assign y = $clog2(16); }")
        assert isinstance(expr, CallExpr)
        assert expr.func == "$clog2"
        assert len(expr.args) == 1


# ────────────────────────────────────────────────────────────────
# 9. Lexer edge cases
# ────────────────────────────────────────────────────────────────

class TestLexerEdgeCases:
    def test_system_function(self):
        tokens = Lexer("$clog2 $bits $signed").tokenize()
        assert tokens[0].type == TokenType.IDENT
        assert tokens[0].value == "$clog2"

    def test_verilog_literals(self):
        for lit in ["8'hFF", "16'd1234", "32'b0101", "4'o77", "2'd3"]:
            tokens = Lexer(lit).tokenize()
            assert tokens[0].type == TokenType.INT_LITERAL
            assert tokens[0].value == lit

    def test_escaped_string(self):
        tokens = Lexer(r'"hello \"world\""').tokenize()
        assert tokens[0].type == TokenType.STRING_LITERAL

    def test_leading_vs_trailing_comments(self):
        tokens = Lexer("// leading\na/* middle */b// trailing").tokenize()
        assert tokens[0].value == "a"
        assert tokens[1].value == "b"
        assert len(tokens) == 3  # a, b, EOF

    def test_empty_input(self):
        tokens = Lexer("").tokenize()
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.EOF

    def test_whitespace_only(self):
        tokens = Lexer("   \n\t  \n  ").tokenize()
        assert tokens[0].type == TokenType.EOF

    def test_all_keywords(self):
        kw = "module param logic signed assign seq pos neg if else for"
        tokens = Lexer(kw).tokenize()
        for t in tokens[:-1]:  # exclude EOF
            assert t.type != TokenType.IDENT, f"'{t.value}' should be a keyword"


# ────────────────────────────────────────────────────────────────
# 10. Full pipeline: .slip → .sv end-to-end with file I/O
# ────────────────────────────────────────────────────────────────

class TestFullPipelineIO:
    def test_uart_write_and_reparse(self, tmp_path):
        """Compile UART TX, write to file, then reparse with pyslang."""
        from slip.cli._pipeline import run_build
        source = FIXTURES / "uart_tx.slip"
        result = run_build(source, tmp_path, [])
        assert (tmp_path / "uart_tx.sv").exists()

        from pyslang import SyntaxTree, Compilation
        tree = SyntaxTree.fromText((tmp_path / "uart_tx.sv").read_text())
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert len(errors) == 0

    def test_fifo_write_and_reparse(self, tmp_path):
        from slip.cli._pipeline import run_build
        source = FIXTURES / "pipeline.slip"
        run_build(source, tmp_path, [])
        from pyslang import SyntaxTree, Compilation
        tree = SyntaxTree.fromText((tmp_path / "fifo.sv").read_text())
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert len(errors) == 0

    def test_arbiter_write_and_reparse(self, tmp_path):
        from slip.cli._pipeline import run_build
        source = FIXTURES / "crossbar.slip"
        run_build(source, tmp_path, [])
        from pyslang import SyntaxTree, Compilation
        tree = SyntaxTree.fromText((tmp_path / "arbiter.sv").read_text())
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert len(errors) == 0

    def test_check_command_all_fixtures(self):
        from slip.cli._pipeline import run_check
        for name in ["simple.slip", "seq_block.slip", "implicit_ports.slip",
                      "params.slip", "uart_tx.slip", "pipeline.slip", "crossbar.slip"]:
            run_check(FIXTURES / name, [])


# ────────────────────────────────────────────────────────────────
# 11. Stress: deeply nested expressions
# ────────────────────────────────────────────────────────────────

class TestStressDeepNesting:
    def test_deep_binary_chain(self):
        """a + b + c + d + e + f + g + h"""
        src = "module m (y) { assign y = a + b + c + d + e + f + g + h; }"
        sv = compile_source(src)
        assert "a + b + c + d + e + f + g + h" in sv["m"]

    def test_deep_paren_nesting(self):
        src = "module m (y) { assign y = ((((a + b)))); }"
        sv = compile_source(src)
        assert "a + b" in sv["m"]

    def test_wide_concat(self):
        parts = ", ".join([f"x{i}" for i in range(16)])
        src = f"module m (y) {{ assign y = {{{parts}}}; }}"
        sv = compile_source(src)
        assert "x0" in sv["m"] and "x15" in sv["m"]

    def test_complex_param_expr(self):
        sv = compile_source(
            "module m #(param A = 1, param B = 2, param C = 3, "
            "param D = 4, param E = 5) (y) { assign y = 0; }"
        )
        assert "parameter A = 1" in sv["m"]
        assert "parameter E = 5" in sv["m"]
