"""Corner case tests for the lexer."""

import pytest

from slip.lexer import Lexer, TokenType
from slip.errors.syntax import SlipSyntaxError


def _token_types(source: str) -> list[TokenType]:
    return [t.type for t in Lexer(source).tokenize()]


def _token_values(source: str) -> list[str]:
    return [t.value for t in Lexer(source).tokenize() if t.type != TokenType.EOF]


class TestBlockComments:
    def test_nested_block_comments(self):
        tokens = _token_types("module /* /* inner */ outer */ m {}")
        assert TokenType.MODULE in tokens
        assert TokenType.IDENT in tokens

    def test_unterminated_block_comment(self):
        with pytest.raises(SlipSyntaxError, match="unterminated block comment"):
            Lexer("module /* unclosed").tokenize()

    def test_block_comment_with_newlines(self):
        tokens = _token_types("module /* line1\nline2 */ m {}")
        assert TokenType.MODULE in tokens


class TestStringLiterals:
    def test_escape_sequences(self):
        tokens = _token_values(r'"hello \"world\""')
        assert any('"' in v for v in tokens)

    def test_backslash_escape(self):
        tokens = _token_values(r'"path\\to\\file"')
        assert any("\\\\" in v for v in tokens)

    def test_unterminated_string(self):
        with pytest.raises(SlipSyntaxError, match="unterminated string"):
            Lexer('"unterminated').tokenize()


class TestVerilogLiterals:
    def test_hex_literal(self):
        tokens = _token_values("8'hFF")
        assert "8'hFF" in tokens

    def test_binary_literal(self):
        tokens = _token_values("4'b1010")
        assert "4'b1010" in tokens

    def test_octal_literal(self):
        tokens = _token_values("8'o377")
        assert "8'o377" in tokens

    def test_decimal_with_width(self):
        tokens = _token_values("32'd100")
        assert "32'd100" in tokens

    def test_underscore_in_literal(self):
        tokens = _token_values("32'd1_000_000")
        assert "32'd1_000_000" in tokens

    def test_hex_with_underscore(self):
        tokens = _token_values("16'hFF_FF")
        assert "16'hFF_FF" in tokens


class TestLineComments:
    def test_line_comment_ignored(self):
        tokens = _token_types("module // this is a comment\nm {}")
        assert TokenType.MODULE in tokens
        assert TokenType.IDENT in tokens


class TestTickMerging:
    def test_tick_for(self):
        tokens = _token_types("`for")
        assert TokenType.TICK_FOR in tokens

    def test_tick_if(self):
        tokens = _token_types("`if")
        assert TokenType.TICK_IF in tokens

    def test_tick_else(self):
        tokens = _token_types("`else")
        assert TokenType.TICK_ELSE in tokens

    def test_tick_ident(self):
        tokens = _token_types("`i")
        assert TokenType.TICK_IDENT in tokens

    def test_tick_zero(self):
        tokens = _token_types("'0")
        assert TokenType.TICK_ZERO in tokens

    def test_tick_one(self):
        tokens = _token_types("'1")
        assert TokenType.TICK_ONE in tokens

    def test_template_ident(self):
        tokens = _token_values("data_`i")
        assert "data_`i" in tokens


class TestOperators:
    def test_arrow(self):
        tokens = _token_types("=>")
        assert TokenType.ARROW in tokens

    def test_less_equal(self):
        tokens = _token_types("<=")
        assert TokenType.LE in tokens

    def test_not_equal(self):
        tokens = _token_types("!=")
        assert TokenType.BANG_EQ in tokens

    def test_left_shift(self):
        tokens = _token_types("<<")
        assert TokenType.LT_LT in tokens

    def test_right_shift(self):
        tokens = _token_types(">>")
        assert TokenType.GT_GT in tokens


class TestPositionTracking:
    def test_line_tracking(self):
        tokens = Lexer("a\nb\nc").tokenize()
        assert tokens[0].line == 1  # a
        assert tokens[1].line == 2  # b
        assert tokens[2].line == 3  # c

    def test_col_tracking(self):
        tokens = Lexer("a b c").tokenize()
        assert tokens[0].col == 1  # a
        assert tokens[1].col == 3  # b
        assert tokens[2].col == 5  # c


class TestUnrecognizedCharacter:
    def test_unrecognized_char(self):
        with pytest.raises(SlipSyntaxError, match="unexpected character"):
            Lexer("module m { \\ }").tokenize()
