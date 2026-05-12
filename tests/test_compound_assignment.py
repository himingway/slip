"""Tests for compound assignment operators (+=, -=, *=, etc.)."""

import pytest

from slip.ast.expressions import BinaryExpr, IdentExpr
from slip.ast.statements import AssignStmt
from slip.lexer.token import TokenType

from conftest import compile_source, parse_module, parse_source, validate_sv


# ── Lexer tests ─────────────────────────────────────────────────────


class TestCompoundAssignmentLexer:
    """Compound assignment tokens are produced correctly by the lexer."""

    @pytest.mark.parametrize(
        "source,expected_type",
        [
            ("+=", TokenType.PLUS_EQ),
            ("-=", TokenType.MINUS_EQ),
            ("*=", TokenType.STAR_EQ),
            ("/=", TokenType.SLASH_EQ),
            ("%=", TokenType.PERCENT_EQ),
            ("&=", TokenType.AMP_EQ),
            ("|=", TokenType.PIPE_EQ),
            ("^=", TokenType.CARET_EQ),
            ("<<=", TokenType.LT_LT_EQ),
            (">>=", TokenType.GT_GT_EQ),
            ("<<<=", TokenType.LT_LT_LT_EQ),
            (">>>=", TokenType.GT_GT_GT_EQ),
        ],
    )
    def test_token_type(self, source, expected_type):
        from slip.lexer import Lexer

        tokens = Lexer(source, "test.slip").tokenize()
        # First non-EOF token should match
        non_eof = [t for t in tokens if t.type != TokenType.EOF]
        assert len(non_eof) == 1
        assert non_eof[0].type == expected_type
        assert non_eof[0].value == source

    def test_compound_not_confused_with_shift(self):
        """<<= should not be lexed as << followed by =."""
        from slip.lexer import Lexer

        tokens = Lexer("<<=", "test.slip").tokenize()
        non_eof = [t for t in tokens if t.type != TokenType.EOF]
        assert len(non_eof) == 1
        assert non_eof[0].type == TokenType.LT_LT_EQ

    def test_compound_not_confused_with_le(self):
        """<= should still be LE, not confused with <<=."""
        from slip.lexer import Lexer

        tokens = Lexer("<=", "test.slip").tokenize()
        non_eof = [t for t in tokens if t.type != TokenType.EOF]
        assert len(non_eof) == 1
        assert non_eof[0].type == TokenType.LE

    def test_shift_still_works(self):
        """Plain shift operators should not be affected."""
        from slip.lexer import Lexer

        tokens = Lexer("<< >>", "test.slip").tokenize()
        non_eof = [t for t in tokens if t.type != TokenType.EOF]
        assert non_eof[0].type == TokenType.LT_LT
        assert non_eof[1].type == TokenType.GT_GT


# ── Parser / desugaring tests ───────────────────────────────────────


class TestCompoundAssignmentParser:
    """Compound assignments are desugared to plain assignments at parse time."""

    def test_plus_eq_desugars(self):
        mod = parse_module("module m { a += 1; }")
        stmt = mod.body[0]
        assert isinstance(stmt, AssignStmt)
        assert stmt.target.name == "a"
        assert not stmt.is_nonblocking
        # Value should be BinaryExpr(a, +, 1)
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == "+"
        assert isinstance(stmt.value.left, IdentExpr)
        assert stmt.value.left.name == "a"

    def test_minus_eq_desugars(self):
        mod = parse_module("module m { a -= 2; }")
        stmt = mod.body[0]
        assert isinstance(stmt, AssignStmt)
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == "-"

    @pytest.mark.parametrize(
        "op,expected_base",
        [
            ("+=", "+"),
            ("-=", "-"),
            ("*=", "*"),
            ("/=", "/"),
            ("%=", "%"),
            ("&=", "&"),
            ("|=", "|"),
            ("^=", "^"),
            ("<<=", "<<"),
            (">>=", ">>"),
            ("<<<=", "<<<"),
            (">>>=", ">>>"),
        ],
    )
    def test_all_compound_operators(self, op, expected_base):
        source = f"module m {{ a {op} 1; }}"
        mod = parse_module(source)
        stmt = mod.body[0]
        assert isinstance(stmt, AssignStmt)
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == expected_base
        assert isinstance(stmt.value.left, IdentExpr)
        assert stmt.value.left.name == "a"

    def test_compound_with_expression(self):
        """a += b + c should desugar to a = a + (b + c)."""
        mod = parse_module("module m { a += b + c; }")
        stmt = mod.body[0]
        assert isinstance(stmt, AssignStmt)
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == "+"
        # Left is IdentExpr("a"), right is BinaryExpr("b + c")
        assert isinstance(stmt.value.left, IdentExpr)
        assert stmt.value.left.name == "a"
        assert isinstance(stmt.value.right, BinaryExpr)
        assert stmt.value.right.op == "+"


# ── Codegen tests ───────────────────────────────────────────────────


class TestCompoundAssignmentCodegen:
    """Compound assignments generate correct SystemVerilog output."""

    def test_plus_eq_generates_expanded_sv(self):
        sv = compile_source("module m { a += 1; }")
        sv_text = sv["m"]
        assert "a = a + 1" in sv_text

    def test_minus_eq_generates_expanded_sv(self):
        sv = compile_source("module m { a -= 1; }")
        sv_text = sv["m"]
        assert "a = a - 1" in sv_text

    def test_compound_in_seq_block(self):
        """Compound assignment inside seq block should get non-blocking (<=)."""
        sv = compile_source(
            "module m { seq (clk) { count += 1; } }"
        )
        sv_text = sv["m"]
        # The desugared form is count = count + 1, but inside seq it becomes <=
        assert "count <= count + 1" in sv_text

    def test_compound_in_seq_with_reset(self):
        sv = compile_source(
            "module m { seq (clk, pos: rst) { count += 1; } }"
        )
        sv_text = sv["m"]
        assert "count <= count + 1" in sv_text

    @pytest.mark.parametrize(
        "op,expected_op",
        [
            ("+=", "+"),
            ("-=", "-"),
            ("*=", "*"),
            ("/=", "/"),
            ("%=", "%"),
            ("&=", "&"),
            ("|=", "|"),
            ("^=", "^"),
            ("<<=", "<<"),
            (">>=", ">>"),
            ("<<<=", "<<<"),
            (">>>=", ">>>"),
        ],
    )
    def test_all_compound_operators_codegen(self, op, expected_op):
        source = f"module m {{ a {op} 1; }}"
        sv = compile_source(source)
        sv_text = sv["m"]
        assert f"a = a {expected_op} 1" in sv_text


# ── pyslang validation ──────────────────────────────────────────────


class TestCompoundAssignmentValidation:
    """Generated SV from compound assignments validates with pyslang."""

    def test_plus_eq_valid_sv(self):
        sv = compile_source("module m { logic [7:0] a; a += 1; }")
        sv_text = sv["m"]
        errors = validate_sv(sv_text, allow_missing_modules=True)
        # Filter out undeclared identifier errors for 'a' if any
        assert errors == []

    def test_compound_in_seq_valid_sv(self):
        sv = compile_source(
            "module m { logic [7:0] count; seq (clk) { count += 1; } }"
        )
        sv_text = sv["m"]
        errors = validate_sv(sv_text, allow_missing_modules=True)
        assert errors == []
