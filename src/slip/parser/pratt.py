from __future__ import annotations

from slip.ast.base import SourceLocation
from slip.ast.expressions import (
    BinaryExpr,
    CallExpr,
    CastExpr,
    ConcatExpr,
    Expr,
    IdentExpr,
    IndexExpr,
    IntLiteralExpr,
    MethodCallExpr,
    ParenExpr,
    ReplicationExpr,
    StringLiteralExpr,
    TernaryExpr,
    TickConstExpr,
    TickIdentExpr,
    UnaryExpr,
)
from slip.errors.syntax import SlipSyntaxError
from slip.lexer.token import Token, TokenType

# Binding power pairs: (left_bp, right_bp)
# Higher = tighter binding. Right-associative: right_bp < left_bp.
INFIX_BP: dict[TokenType, tuple[int, int]] = {
    TokenType.QUESTION: (2, 1),       # ternary, right-assoc
    TokenType.PIPE_PIPE: (4, 5),      # ||
    TokenType.AMP_AMP: (6, 7),        # &&
    TokenType.PIPE: (8, 9),           # | bitwise
    TokenType.CARET: (10, 11),        # ^
    TokenType.AMP: (12, 13),          # & bitwise
    TokenType.LT_LT: (14, 15),       # <<
    TokenType.GT_GT: (14, 15),       # >>
    TokenType.LT_LT_LT: (14, 15),   # <<<
    TokenType.GT_GT_GT: (14, 15),   # >>>
    TokenType.LT: (16, 17),           # <
    TokenType.GT: (16, 17),           # >
    TokenType.LE: (16, 17),           # <=
    TokenType.GT_EQ: (16, 17),       # >=
    TokenType.EQ_EQ: (18, 19),       # ==
    TokenType.BANG_EQ: (18, 19),     # !=
    TokenType.EQ_EQ_EQ: (18, 19),   # ===
    TokenType.BANG_EQ_EQ: (18, 19), # !==
    TokenType.PLUS: (20, 21),         # +
    TokenType.MINUS: (20, 21),       # -
    TokenType.STAR: (22, 23),         # *
    TokenType.SLASH: (22, 23),       # /
    TokenType.PERCENT: (22, 23),     # %
    TokenType.STAR_STAR: (25, 24),   # ** (right-assoc: higher than *)
    TokenType.INSIDE: (4, 5),        # inside (low precedence, above assignment)
}

# Postfix operators (left bp only)
POSTFIX_BP: dict[TokenType, int] = {
    TokenType.LBRACK: 26,   # indexing a[i]
    TokenType.LPAREN: 26,   # function call f(...)
    TokenType.TICK: 26,     # replication {n{expr}} -- handled in concatenation
    TokenType.DOT: 26,      # method call expr.method(args)
}

# Prefix operator binding power
PREFIX_BP = 24

PREFIX_OPS = {
    TokenType.PLUS, TokenType.MINUS, TokenType.BANG,
    TokenType.TILDE, TokenType.AMP, TokenType.PIPE, TokenType.CARET,
}


class PrattParser:
    def __init__(self, tokens: list[Token], pos: int, filename: str):
        self._tokens = tokens
        self._pos = pos
        self._filename = filename

    @property
    def pos(self) -> int:
        return self._pos

    def peek(self) -> Token:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return self._tokens[-1]  # EOF

    def advance(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _loc(self, tok: Token) -> SourceLocation:
        return SourceLocation(self._filename, tok.line, tok.col)

    def parse_expression(self, min_bp: int = 0) -> Expr:
        left = self._parse_prefix()

        while True:
            tok = self.peek()

            # Infix binary operators
            if tok.type in INFIX_BP:
                l_bp, r_bp = INFIX_BP[tok.type]
                if l_bp < min_bp:
                    break
                op_tok = self.advance()

                # Ternary ? :
                if op_tok.type == TokenType.QUESTION:
                    true_expr = self.parse_expression(0)
                    colon = self.advance()
                    if colon.type != TokenType.COLON:
                        raise SlipSyntaxError(
                            self._filename, colon.line, colon.col,
                            f"expected ':' in ternary expression, got '{colon.value}'"
                        )
                    false_expr = self.parse_expression(r_bp)
                    left = TernaryExpr(self._loc(tok), left, true_expr, false_expr)
                else:
                    right = self.parse_expression(r_bp)
                    left = BinaryExpr(self._loc(tok), op_tok.value, left, right)
                continue

            # Postfix: indexing [expr] or slice [expr:expr]
            if tok.type == TokenType.LBRACK and POSTFIX_BP.get(TokenType.LBRACK, 0) >= min_bp:
                self.advance()  # consume [

                # Check for omitted start (e.g., s[:3])
                if self.peek().type == TokenType.COLON:
                    # Omitted start: s[:expr] or s[:]
                    index = None
                else:
                    index = self.parse_expression(0)

                if self.peek().type == TokenType.COLON:
                    self.advance()  # consume :
                    # Check for omitted end (e.g., s[3:])
                    if self.peek().type == TokenType.RBRACK:
                        high = None
                    else:
                        high = self.parse_expression(0)
                    right_brack = self.advance()
                    if right_brack.type != TokenType.RBRACK:
                        raise SlipSyntaxError(
                            self._filename, right_brack.line, right_brack.col,
                            f"expected ']', got '{right_brack.value}'"
                        )
                    left = IndexExpr(self._loc(tok), left, index, high, is_slice=True)
                else:
                    # Single index: s[expr]
                    right_brack = self.advance()
                    if right_brack.type != TokenType.RBRACK:
                        raise SlipSyntaxError(
                            self._filename, right_brack.line, right_brack.col,
                            f"expected ']', got '{right_brack.value}'"
                        )
                    left = IndexExpr(self._loc(tok), left, index)
                continue

            # Postfix: function call f(args)
            if tok.type == TokenType.LPAREN and POSTFIX_BP.get(TokenType.LPAREN, 0) >= min_bp:
                self.advance()  # consume (
                args: list[Expr] = []
                if self.peek().type != TokenType.RPAREN:
                    args.append(self.parse_expression(0))
                    while self.peek().type == TokenType.COMMA:
                        self.advance()
                        args.append(self.parse_expression(0))
                rparen = self.advance()
                if rparen.type != TokenType.RPAREN:
                    raise SlipSyntaxError(
                        self._filename, rparen.line, rparen.col,
                        f"expected ')', got '{rparen.value}'"
                    )
                if isinstance(left, IdentExpr):
                    left = CallExpr(left.loc, left.name, tuple(args))
                else:
                    raise SlipSyntaxError(
                        self._filename, tok.line, tok.col,
                        "function call target must be an identifier"
                    )
                continue

            # Postfix: method call expr.method(args)
            if tok.type == TokenType.DOT and POSTFIX_BP.get(TokenType.DOT, 0) >= min_bp:
                self.advance()  # consume .
                method_tok = self.advance()
                if method_tok.type != TokenType.IDENT:
                    raise SlipSyntaxError(
                        self._filename, method_tok.line, method_tok.col,
                        f"expected method name after '.', got '{method_tok.value}'"
                    )
                # Expect (args)
                lparen = self.advance()
                if lparen.type != TokenType.LPAREN:
                    raise SlipSyntaxError(
                        self._filename, lparen.line, lparen.col,
                        f"expected '(' after method name, got '{lparen.value}'"
                    )
                method_args: list[Expr] = []
                if self.peek().type != TokenType.RPAREN:
                    method_args.append(self.parse_expression(0))
                    while self.peek().type == TokenType.COMMA:
                        self.advance()
                        method_args.append(self.parse_expression(0))
                rparen = self.advance()
                if rparen.type != TokenType.RPAREN:
                    raise SlipSyntaxError(
                        self._filename, rparen.line, rparen.col,
                        f"expected ')', got '{rparen.value}'"
                    )
                left = MethodCallExpr(self._loc(tok), obj=left, method=method_tok.value, args=tuple(method_args))
                continue

            break

        return left

    def _parse_prefix(self) -> Expr:
        tok = self.peek()

        # Unary prefix operators
        if tok.type in PREFIX_OPS:
            self.advance()
            operand = self.parse_expression(PREFIX_BP)
            return UnaryExpr(self._loc(tok), tok.value, operand)

        # Parenthesized expression
        if tok.type == TokenType.LPAREN:
            self.advance()
            expr = self.parse_expression(0)
            rparen = self.advance()
            if rparen.type != TokenType.RPAREN:
                raise SlipSyntaxError(
                    self._filename, rparen.line, rparen.col,
                    f"expected ')', got '{rparen.value}'"
                )
            return ParenExpr(self._loc(tok), expr)

        # Concatenation {a, b} or replication {n{expr}}
        if tok.type == TokenType.LBRACE:
            self.advance()
            parts: list[Expr] = []
            if self.peek().type != TokenType.RBRACE:
                parts.append(self.parse_expression(0))
                # Check for replication: {n{expr}}
                if self.peek().type == TokenType.LBRACE:
                    self.advance()  # consume inner {
                    inner = self.parse_expression(0)
                    rbrace_inner = self.advance()
                    if rbrace_inner.type != TokenType.RBRACE:
                        raise SlipSyntaxError(
                            self._filename, rbrace_inner.line, rbrace_inner.col,
                            f"expected '}}' in replication, got '{rbrace_inner.value}'"
                        )
                    rbrace = self.advance()
                    if rbrace.type != TokenType.RBRACE:
                        raise SlipSyntaxError(
                            self._filename, rbrace.line, rbrace.col,
                            f"expected '}}', got '{rbrace.value}'"
                        )
                    return ReplicationExpr(self._loc(tok), count=parts[0], inner=inner)
                while self.peek().type == TokenType.COMMA:
                    self.advance()
                    parts.append(self.parse_expression(0))
            rbrace = self.advance()
            if rbrace.type != TokenType.RBRACE:
                raise SlipSyntaxError(
                    self._filename, rbrace.line, rbrace.col,
                    f"expected '}}', got '{rbrace.value}'"
                )
            return ConcatExpr(self._loc(tok), tuple(parts))

        # signed' / unsigned' cast
        if tok.type == TokenType.SIGNED or (tok.type == TokenType.IDENT and tok.value == "unsigned"):
            cast_name = tok.value
            next_tok = self._tokens[self._pos + 1] if self._pos + 1 < len(self._tokens) else None
            if next_tok and next_tok.type == TokenType.TICK:
                self.advance()  # consume signed/unsigned
                self.advance()  # consume '
                lparen = self.advance()
                if lparen.type != TokenType.LPAREN:
                    raise SlipSyntaxError(
                        self._filename, lparen.line, lparen.col,
                        f"expected '(' after {cast_name}', got '{lparen.value}'"
                    )
                inner = self.parse_expression(0)
                rparen = self.advance()
                if rparen.type != TokenType.RPAREN:
                    raise SlipSyntaxError(
                        self._filename, rparen.line, rparen.col,
                        f"expected ')', got '{rparen.value}'"
                    )
                return CastExpr(self._loc(tok), f"{cast_name}'", inner)

        # Width cast: INT_LITERAL'(expr) e.g. 8'(x + 1)
        if tok.type == TokenType.INT_LITERAL:
            next_tok = self._tokens[self._pos + 1] if self._pos + 1 < len(self._tokens) else None
            if next_tok and next_tok.type == TokenType.TICK:
                cast_width = tok.value
                self.advance()  # consume INT_LITERAL
                self.advance()  # consume '
                lparen = self.advance()
                if lparen.type != TokenType.LPAREN:
                    raise SlipSyntaxError(
                        self._filename, lparen.line, lparen.col,
                        f"expected '(' after {cast_width}', got '{lparen.value}'"
                    )
                inner = self.parse_expression(0)
                rparen = self.advance()
                if rparen.type != TokenType.RPAREN:
                    raise SlipSyntaxError(
                        self._filename, rparen.line, rparen.col,
                        f"expected ')', got '{rparen.value}'"
                    )
                return CastExpr(self._loc(tok), f"{cast_width}'", inner)

        # Tick identifier (meta-variable like `i)
        if tok.type == TokenType.TICK_IDENT:
            self.advance()
            return TickIdentExpr(self._loc(tok), name=tok.value[1:])

        # Identifier (reject bare 'unsigned' without tick)
        if tok.type == TokenType.IDENT:
            if tok.value == "unsigned":
                raise SlipSyntaxError(
                    self._filename, tok.line, tok.col,
                    "expected 'unsigned\\'' (cast), got bare 'unsigned'"
                )
            self.advance()
            return IdentExpr(self._loc(tok), tok.value)

        # Integer literal
        if tok.type == TokenType.INT_LITERAL:
            self.advance()
            return IntLiteralExpr(self._loc(tok), tok.value)

        # Tick constants '0 and '1
        if tok.type in (TokenType.TICK_ZERO, TokenType.TICK_ONE):
            self.advance()
            return TickConstExpr(self._loc(tok), raw=tok.value)

        # String literal
        if tok.type == TokenType.STRING_LITERAL:
            self.advance()
            return StringLiteralExpr(self._loc(tok), tok.value)

        raise SlipSyntaxError(
            self._filename, tok.line, tok.col,
            f"unexpected token '{tok.value}' in expression"
        )
