"""Tests for the 'inside' operator (FEAT-002)."""

import pytest

from slip.ast.expressions import BinaryExpr, ConcatExpr, IdentExpr, IntLiteralExpr
from slip.lexer import Lexer, TokenType
from slip.parser import Parser
from conftest import compile_source, parse_module, validate_sv


class TestInsideLexer:
    def test_inside_keyword_lexer(self):
        """Verify 'inside' is tokenized as INSIDE."""
        tokens = Lexer("inside").tokenize()
        assert tokens[0].type == TokenType.INSIDE
        assert tokens[0].value == "inside"

    def test_inside_in_expression(self):
        """Verify 'inside' tokenizes correctly in context."""
        tokens = Lexer("x inside {1, 2, 3}").tokenize()
        types = [t.type for t in tokens]
        assert TokenType.IDENT in types
        assert TokenType.INSIDE in types
        assert TokenType.LBRACE in types
        assert TokenType.INT_LITERAL in types


class TestInsideParser:
    def test_inside_basic_parse(self):
        """Parse 'x inside {1, 2, 3}'."""
        mod = parse_module("module m (x, y) { assign y = x inside {1, 2, 3}; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == "inside"
        assert isinstance(stmt.value.left, IdentExpr)
        assert stmt.value.left.name == "x"
        assert isinstance(stmt.value.right, ConcatExpr)
        assert len(stmt.value.right.parts) == 3

    def test_inside_single_element(self):
        """Parse 'x inside {42}'."""
        mod = parse_module("module m (x, y) { assign y = x inside {42}; }")
        stmt = mod.body[0]
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == "inside"
        assert isinstance(stmt.value.right, ConcatExpr)
        assert len(stmt.value.right.parts) == 1

    def test_inside_with_comparison(self):
        """Parse 'a == b inside {1, 2}' - inside has lower precedence than ==."""
        mod = parse_module("module m (a, b, y) { assign y = a == b inside {1, 2}; }")
        stmt = mod.body[0]
        # Inside has lower precedence than ==, so this parses as (a == b) inside {1, 2}
        assert isinstance(stmt.value, BinaryExpr)
        assert stmt.value.op == "inside"
        assert isinstance(stmt.value.left, BinaryExpr)
        assert stmt.value.left.op == "=="


class TestInsideCodegen:
    def test_inside_codegen(self):
        """Verify 'inside' appears in SV output."""
        sv = compile_source("module m (x, y) { assign y = x inside {1, 2, 3}; }")
        output = list(sv.values())[0]
        assert "inside" in output
        assert "{1, 2, 3}" in output

    def test_inside_in_if(self):
        """Use inside in an if condition."""
        source = """
        module m (x, y) {
            comb {
                if (x inside {1, 2, 3}) {
                    y = 1;
                } else {
                    y = 0;
                }
            }
        }
        """
        sv = compile_source(source)
        output = list(sv.values())[0]
        assert "inside" in output
        assert "{1, 2, 3}" in output


class TestInsideSemantics:
    def test_inside_compile_time_eval(self):
        """Test compile-time evaluation of inside with constants."""
        from slip.ast.base import SourceLocation
        from slip.semantic.gen_expand import _eval_int

        loc = SourceLocation("test.slip", 1, 1)
        # Create: 2 inside {1, 2, 3}
        left = IntLiteralExpr(loc, "2")
        set_parts = (
            IntLiteralExpr(loc, "1"),
            IntLiteralExpr(loc, "2"),
            IntLiteralExpr(loc, "3"),
        )
        right = ConcatExpr(loc, parts=set_parts)
        expr = BinaryExpr(loc, "inside", left, right)
        result = _eval_int(expr, {}, loc)
        assert result == 1  # True (2 is in {1, 2, 3})

    def test_inside_compile_time_eval_false(self):
        """Test compile-time evaluation of inside when value is not in set."""
        from slip.ast.base import SourceLocation
        from slip.semantic.gen_expand import _eval_int

        loc = SourceLocation("test.slip", 1, 1)
        # Create: 5 inside {1, 2, 3}
        left = IntLiteralExpr(loc, "5")
        set_parts = (
            IntLiteralExpr(loc, "1"),
            IntLiteralExpr(loc, "2"),
            IntLiteralExpr(loc, "3"),
        )
        right = ConcatExpr(loc, parts=set_parts)
        expr = BinaryExpr(loc, "inside", left, right)
        result = _eval_int(expr, {}, loc)
        assert result == 0  # False (5 is not in {1, 2, 3})


class TestInsidePyslang:
    def test_pyslang_valid_inside(self):
        """Validate generated SV with pyslang (if available)."""
        pyslang = pytest.importorskip("pyslang")
        sv = compile_source("module m (x, y) { assign y = x inside {1, 2, 3}; }")
        output = list(sv.values())[0]
        errors = validate_sv(output, allow_missing_modules=True)
        assert errors == [], f"pyslang errors: {errors}"
