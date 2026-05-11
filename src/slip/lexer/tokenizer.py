import re
from dataclasses import dataclass, field

from slip.errors.syntax import SlipSyntaxError
from slip.lexer.token import Token, TokenType

# Keyword map
_KEYWORDS: dict[str, TokenType] = {
    "module": TokenType.MODULE,
    "param": TokenType.PARAM,
    "localparam": TokenType.LOCALPARAM,
    "logic": TokenType.LOGIC,
    "signed": TokenType.SIGNED,
    "assign": TokenType.ASSIGN,
    "seq": TokenType.SEQ,
    "comb": TokenType.COMB,
    "pos": TokenType.POS,
    "neg": TokenType.NEG,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "for": TokenType.FOR,
}

# Regex rules: (pattern, token_type_or_None)
# Order matters: longest match first for multi-char operators.
_REGEX_RULES: list[tuple[re.Pattern, TokenType | None]] = [
    # Multi-char operators (must come before single-char prefixes)
    (re.compile(r"=>"), TokenType.ARROW),
    (re.compile(r"<="), TokenType.LE),
    (re.compile(r">="), TokenType.GT_EQ),
    (re.compile(r"=="), TokenType.EQ_EQ),
    (re.compile(r"!="), TokenType.BANG_EQ),
    (re.compile(r"<<"), TokenType.LT_LT),
    (re.compile(r">>"), TokenType.GT_GT),
    (re.compile(r"&&"), TokenType.AMP_AMP),
    (re.compile(r"\|\|"), TokenType.PIPE_PIPE),
    # Single-char operators and delimiters
    (re.compile(r"="), TokenType.EQ),
    (re.compile(r"<"), TokenType.LT),
    (re.compile(r">"), TokenType.GT),
    (re.compile(r"\+"), TokenType.PLUS),
    (re.compile(r"-"), TokenType.MINUS),
    (re.compile(r"\*"), TokenType.STAR),
    (re.compile(r"/"), TokenType.SLASH),
    (re.compile(r"%"), TokenType.PERCENT),
    (re.compile(r"!"), TokenType.BANG),
    (re.compile(r"~"), TokenType.TILDE),
    (re.compile(r"&"), TokenType.AMP),
    (re.compile(r"\|"), TokenType.PIPE),
    (re.compile(r"\^"), TokenType.CARET),
    (re.compile(r"\?"), TokenType.QUESTION),
    (re.compile(r"'"), TokenType.TICK),
    (re.compile(r"`"), TokenType.BACKTICK),
    (re.compile(r"@"), TokenType.AT),
    (re.compile(r"\{"), TokenType.LBRACE),
    (re.compile(r"}"), TokenType.RBRACE),
    (re.compile(r"\["), TokenType.LBRACK),
    (re.compile(r"]"), TokenType.RBRACK),
    (re.compile(r"\("), TokenType.LPAREN),
    (re.compile(r"\)"), TokenType.RPAREN),
    (re.compile(r";"), TokenType.SEMICOLON),
    (re.compile(r":"), TokenType.COLON),
    (re.compile(r","), TokenType.COMMA),
    (re.compile(r"\."), TokenType.DOT),
    (re.compile(r"#"), TokenType.HASH),
]

# Integer literal: Verilog-style with optional width/radix, or plain decimal
_INT_LITERAL_RE = re.compile(
    r"\d+'[bBdDhHoO][0-9a-fA-F_xXzZ]+"
    r"|"
    r"[0-9][0-9_]*"
)

_IDENT_RE = re.compile(r"\$?[a-zA-Z_][a-zA-Z0-9_]*")

# Post-lex merging: BACKTICK + keyword → compound token
_TICK_KEYWORD_MAP: dict[TokenType, TokenType] = {
    TokenType.FOR: TokenType.TICK_FOR,
    TokenType.IF: TokenType.TICK_IF,
    TokenType.ELSE: TokenType.TICK_ELSE,
}


def _merge_tick_keywords(tokens: list[Token]) -> list[Token]:
    """Merge BACKTICK + FOR/IF/ELSE into TICK_FOR/TICK_IF/TICK_ELSE."""
    result: list[Token] = []
    i = 0
    while i < len(tokens):
        if (
            i + 1 < len(tokens)
            and tokens[i].type == TokenType.BACKTICK
            and tokens[i + 1].type in _TICK_KEYWORD_MAP
        ):
            merged_type = _TICK_KEYWORD_MAP[tokens[i + 1].type]
            merged_value = f"`{tokens[i + 1].value}"
            result.append(Token(merged_type, merged_value, tokens[i].line, tokens[i].col))
            i += 2
        else:
            result.append(tokens[i])
            i += 1
    return result


# Post-lex merging: TICK + INT_LITERAL(0/1) → TICK_ZERO/TICK_ONE
_TICK_MERGE = {"0": TokenType.TICK_ZERO, "1": TokenType.TICK_ONE}


def _merge_tick_constants(tokens: list[Token]) -> list[Token]:
    """Merge TICK + INT_LITERAL('0'/'1') into TICK_ZERO/TICK_ONE."""
    result: list[Token] = []
    i = 0
    while i < len(tokens):
        if (
            i + 1 < len(tokens)
            and tokens[i].type == TokenType.TICK
            and tokens[i + 1].type == TokenType.INT_LITERAL
            and tokens[i + 1].value in _TICK_MERGE
        ):
            merged_type = _TICK_MERGE[tokens[i + 1].value]
            result.append(Token(merged_type, f"'{tokens[i + 1].value}",
                                tokens[i].line, tokens[i].col))
            i += 2
        else:
            result.append(tokens[i])
            i += 1
    return result


def _merge_tick_idents(tokens: list[Token]) -> list[Token]:
    """Merge BACKTICK + IDENT into TICK_IDENT for meta-variables like `i."""
    result: list[Token] = []
    i = 0
    while i < len(tokens):
        if (
            i + 1 < len(tokens)
            and tokens[i].type == TokenType.BACKTICK
            and tokens[i + 1].type == TokenType.IDENT
        ):
            result.append(Token(TokenType.TICK_IDENT, f"`{tokens[i + 1].value}",
                                tokens[i].line, tokens[i].col))
            i += 2
        else:
            result.append(tokens[i])
            i += 1
    return result


def _merge_template_idents(tokens: list[Token]) -> list[Token]:
    """Merge IDENT + TICK_IDENT into IDENT for template identifiers like data_`i."""
    result: list[Token] = []
    i = 0
    while i < len(tokens):
        if (
            i + 1 < len(tokens)
            and tokens[i].type == TokenType.IDENT
            and tokens[i + 1].type == TokenType.TICK_IDENT
        ):
            result.append(Token(TokenType.IDENT,
                                tokens[i].value + tokens[i + 1].value,
                                tokens[i].line, tokens[i].col))
            i += 2
        else:
            result.append(tokens[i])
            i += 1
    return result


class Lexer:
    def __init__(self, source: str, filename: str = "<input>"):
        self._source = source
        self._filename = filename
        self._pos = 0
        self._line = 1
        self._col = 1

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while self._pos < len(self._source):
            self._skip_whitespace()
            if self._pos >= len(self._source):
                break

            # Comments
            if self._source[self._pos:self._pos + 2] == "//":
                self._skip_line_comment()
                continue
            if self._source[self._pos:self._pos + 2] == "/*":
                self._skip_block_comment()
                continue

            # String literal
            if self._source[self._pos] == '"':
                tokens.append(self._read_string())
                continue

            # Integer literal (must be checked before identifiers that start with digit)
            m = _INT_LITERAL_RE.match(self._source, self._pos)
            if m and (self._pos == 0 or not self._source[self._pos - 1].isalpha()):
                val = m.group()
                tok = Token(TokenType.INT_LITERAL, val, self._line, self._col)
                self._advance(len(val))
                tokens.append(tok)
                continue

            # Identifier / keyword
            m = _IDENT_RE.match(self._source, self._pos)
            if m:
                val = m.group()
                tt = _KEYWORDS.get(val, TokenType.IDENT)
                tok = Token(tt, val, self._line, self._col)
                self._advance(len(val))
                tokens.append(tok)
                continue

            # Operators and punctuation (regex rules)
            matched = False
            for pattern, tt in _REGEX_RULES:
                m = pattern.match(self._source, self._pos)
                if m:
                    val = m.group()
                    tok = Token(tt, val, self._line, self._col)
                    self._advance(len(val))
                    tokens.append(tok)
                    matched = True
                    break
            if matched:
                continue

            # Unrecognized character
            ch = self._source[self._pos]
            raise SlipSyntaxError(
                self._filename, self._line, self._col,
                f"unexpected character '{ch}'"
            )

        tokens.append(Token(TokenType.EOF, "", self._line, self._col))
        return _merge_template_idents(_merge_tick_idents(_merge_tick_constants(_merge_tick_keywords(tokens))))

    def _advance(self, n: int):
        for i in range(n):
            if self._pos + i < len(self._source) and self._source[self._pos + i] == '\n':
                self._line += 1
                self._col = 1
            else:
                self._col += 1
        self._pos += n

    def _skip_whitespace(self):
        while self._pos < len(self._source) and self._source[self._pos] in " \t\r\n":
            if self._source[self._pos] == '\n':
                self._line += 1
                self._col = 1
            else:
                self._col += 1
            self._pos += 1

    def _skip_line_comment(self):
        while self._pos < len(self._source) and self._source[self._pos] != '\n':
            self._pos += 1
            self._col += 1

    def _skip_block_comment(self):
        self._pos += 2  # skip /*
        self._col += 2
        depth = 1
        while self._pos < len(self._source) and depth > 0:
            if self._source[self._pos:self._pos + 2] == "/*":
                depth += 1
                self._pos += 2
                self._col += 2
            elif self._source[self._pos:self._pos + 2] == "*/":
                depth -= 1
                self._pos += 2
                self._col += 2
            else:
                if self._source[self._pos] == '\n':
                    self._line += 1
                    self._col = 1
                else:
                    self._col += 1
                self._pos += 1
        if depth > 0:
            raise SlipSyntaxError(
                self._filename, self._line, self._col,
                "unterminated block comment"
            )

    def _read_string(self) -> Token:
        line, col = self._line, self._col
        self._pos += 1  # skip opening "
        self._col += 1
        chars: list[str] = ['"']
        while self._pos < len(self._source) and self._source[self._pos] != '"':
            ch = self._source[self._pos]
            if ch == '\\' and self._pos + 1 < len(self._source):
                chars.append(ch)
                self._pos += 1
                self._col += 1
                ch = self._source[self._pos]
            chars.append(ch)
            if ch == '\n':
                self._line += 1
                self._col = 1
            else:
                self._col += 1
            self._pos += 1
        if self._pos >= len(self._source):
            raise SlipSyntaxError(self._filename, line, col, "unterminated string literal")
        chars.append('"')
        self._pos += 1
        self._col += 1
        return Token(TokenType.STRING_LITERAL, "".join(chars), line, col)
