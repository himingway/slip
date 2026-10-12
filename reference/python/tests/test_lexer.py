import pytest
from slip.lexer import Lexer, Token, TokenType


class TestSingleTokens:
    def test_keywords(self):
        tokens = Lexer("module param logic signed assign seq pos neg if else for").tokenize()
        expected = [
            TokenType.MODULE, TokenType.PARAM, TokenType.LOGIC, TokenType.SIGNED,
            TokenType.ASSIGN, TokenType.SEQ, TokenType.POS, TokenType.NEG,
            TokenType.IF, TokenType.ELSE, TokenType.FOR,
        ]
        for tok, exp in zip(tokens, expected):
            assert tok.type == exp

    def test_multi_char_operators(self):
        tokens = Lexer("<= >= == != << >> && || =>").tokenize()
        expected = [
            TokenType.LE, TokenType.GT_EQ, TokenType.EQ_EQ, TokenType.BANG_EQ,
            TokenType.LT_LT, TokenType.GT_GT, TokenType.AMP_AMP, TokenType.PIPE_PIPE,
            TokenType.ARROW,
        ]
        for tok, exp in zip(tokens, expected):
            assert tok.type == exp

    def test_single_char_operators(self):
        tokens = Lexer("= + - * / % ! ~ & | ^ < > ? ' @").tokenize()
        expected = [
            TokenType.EQ, TokenType.PLUS, TokenType.MINUS, TokenType.STAR,
            TokenType.SLASH, TokenType.PERCENT, TokenType.BANG, TokenType.TILDE,
            TokenType.AMP, TokenType.PIPE, TokenType.CARET, TokenType.LT,
            TokenType.GT, TokenType.QUESTION, TokenType.TICK, TokenType.AT,
        ]
        for tok, exp in zip(tokens, expected):
            assert tok.type == exp

    def test_delimiters(self):
        tokens = Lexer("{ } [ ] ( ) ; : , . #").tokenize()
        expected = [
            TokenType.LBRACE, TokenType.RBRACE, TokenType.LBRACK, TokenType.RBRACK,
            TokenType.LPAREN, TokenType.RPAREN, TokenType.SEMICOLON, TokenType.COLON,
            TokenType.COMMA, TokenType.DOT, TokenType.HASH,
        ]
        for tok, exp in zip(tokens, expected):
            assert tok.type == exp


class TestLiterals:
    def test_integer_decimal(self):
        tokens = Lexer("42 0 1234").tokenize()
        for tok in tokens[:3]:
            assert tok.type == TokenType.INT_LITERAL
        assert tokens[0].value == "42"

    def test_integer_verilog(self):
        tokens = Lexer("8'hFF 16'd1234 32'b1010").tokenize()
        assert tokens[0].value == "8'hFF"
        assert tokens[1].value == "16'd1234"
        assert tokens[2].value == "32'b1010"

    def test_string(self):
        tokens = Lexer('"hello world"').tokenize()
        assert tokens[0].type == TokenType.STRING_LITERAL
        assert tokens[0].value == '"hello world"'

    def test_identifier(self):
        tokens = Lexer("my_signal clk rst_n").tokenize()
        assert tokens[0].type == TokenType.IDENT
        assert tokens[0].value == "my_signal"
        assert tokens[1].type == TokenType.IDENT
        assert tokens[1].value == "clk"
        assert tokens[2].type == TokenType.IDENT
        assert tokens[2].value == "rst_n"


class TestComments:
    def test_line_comment(self):
        tokens = Lexer("a // comment\nb").tokenize()
        assert tokens[0].value == "a"
        assert tokens[1].value == "b"
        assert len(tokens) == 3  # a, b, EOF

    def test_block_comment(self):
        tokens = Lexer("a /* comment */ b").tokenize()
        assert tokens[0].value == "a"
        assert tokens[1].value == "b"

    def test_nested_block_comment(self):
        tokens = Lexer("a /* outer /* inner */ still outer */ b").tokenize()
        assert tokens[0].value == "a"
        assert tokens[1].value == "b"


class TestPositionTracking:
    def test_line_col(self):
        tokens = Lexer("a\n  b\nc").tokenize()
        assert tokens[0].line == 1 and tokens[0].col == 1
        assert tokens[1].line == 2 and tokens[1].col == 3
        assert tokens[2].line == 3 and tokens[2].col == 1


class TestErrors:
    def test_unrecognized_char(self):
        from slip.errors.syntax import SlipSyntaxError
        with pytest.raises(SlipSyntaxError):
            Lexer("\\invalid").tokenize()

    def test_unterminated_string(self):
        from slip.errors.syntax import SlipSyntaxError
        with pytest.raises(SlipSyntaxError):
            Lexer('"unterminated').tokenize()


class TestFullProgram:
    def test_simple_module(self):
        source = "module foo (a, b) { assign a = b; }"
        tokens = Lexer(source).tokenize()
        types = [t.type for t in tokens]
        assert types[0] == TokenType.MODULE
        assert types[1] == TokenType.IDENT  # foo
        assert types[-1] == TokenType.EOF
