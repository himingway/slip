from __future__ import annotations

from slip.ast.base import SourceLocation
from slip.ast.expressions import Expr, IdentExpr, IntLiteralExpr
from slip.ast.instance import Connection, InstanceStmt, NamedParam
from slip.ast.metaprogram import GenForStmt, GenIfStmt
from slip.ast.module import Module, Param, PortItem
from slip.ast.statements import (
    AssignStmt,
    BlockStmt,
    CombBlock,
    ForStmt,
    IfStmt,
    LocalParamDecl,
    LValue,
    SeqBlock,
    SignalDecl,
    Statement,
)
from slip.errors.syntax import SlipSyntaxError
from slip.lexer.token import Token, TokenType
from slip.parser.pratt import PrattParser


class Parser:
    def __init__(self, tokens: list[Token], filename: str = "<input>"):
        self._tokens = tokens
        self._pos = 0
        self._filename = filename

    def _loc(self, tok: Token) -> SourceLocation:
        return SourceLocation(self._filename, tok.line, tok.col)

    def peek(self, offset: int = 0) -> Token:
        idx = self._pos + offset
        if idx < len(self._tokens):
            return self._tokens[idx]
        return self._tokens[-1]

    def advance(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def expect(self, tt: TokenType) -> Token:
        tok = self.advance()
        if tok.type != tt:
            raise SlipSyntaxError(
                self._filename, tok.line, tok.col,
                f"expected {tt.name}, got '{tok.value}'"
            )
        return tok

    def parse(self) -> list[Module]:
        modules: list[Module] = []
        while self.peek().type != TokenType.EOF:
            modules.append(self._parse_module())
        return modules

    def _parse_module(self) -> Module:
        tok = self.expect(TokenType.MODULE)
        name_tok = self.expect(TokenType.IDENT)
        name = name_tok.value

        # Parameters
        params: list[Param] = []
        if self.peek().type == TokenType.HASH and self.peek(1).type == TokenType.LPAREN:
            self.advance()  # #
            self.advance()  # (
            params = self._parse_parameter_list()
            self.expect(TokenType.RPAREN)

        # Ports
        ports: list[PortItem] = []
        if self.peek().type == TokenType.LPAREN:
            self.advance()  # (
            ports = self._parse_port_list()
            self.expect(TokenType.RPAREN)

        # Body
        self.expect(TokenType.LBRACE)
        body = self._parse_statements_until(TokenType.RBRACE)
        self.expect(TokenType.RBRACE)

        return Module(
            self._loc(tok),
            name=name,
            params=tuple(params),
            ports=tuple(ports),
            body=tuple(body),
        )

    def _parse_parameter_list(self) -> list[Param]:
        params: list[Param] = []
        if self.peek().type == TokenType.RPAREN:
            return params
        params.append(self._parse_param_decl())
        while self.peek().type == TokenType.COMMA:
            self.advance()
            params.append(self._parse_param_decl())
        return params

    def _parse_param_decl(self) -> Param:
        self.expect(TokenType.PARAM)
        name_tok = self.expect(TokenType.IDENT)
        self.expect(TokenType.EQ)
        default = self._parse_expr()
        return Param(self._loc(name_tok), name=name_tok.value, default=default)

    def _parse_localparam_decl(self) -> Statement:
        tok = self.advance()  # consume LOCALPARAM
        decls = [self._parse_single_localparam()]
        while self.peek().type == TokenType.COMMA:
            self.advance()
            decls.append(self._parse_single_localparam())
        self.expect(TokenType.SEMICOLON)
        if len(decls) == 1:
            return decls[0]
        return BlockStmt(self._loc(tok), statements=tuple(decls))

    def _parse_single_localparam(self) -> LocalParamDecl:
        name_tok = self.expect(TokenType.IDENT)
        self.expect(TokenType.EQ)
        value = self._parse_expr()
        return LocalParamDecl(self._loc(name_tok), name=name_tok.value, value=value)

    def _parse_port_list(self) -> list[PortItem]:
        ports: list[PortItem] = []
        if self.peek().type == TokenType.RPAREN:
            return ports
        ports.append(self._parse_port_item())
        while self.peek().type == TokenType.COMMA:
            self.advance()
            ports.append(self._parse_port_item())
        return ports

    def _parse_port_item(self) -> PortItem:
        name_tok = self.expect(TokenType.IDENT)
        width = None
        if self.peek().type == TokenType.LBRACK:
            self.advance()
            width = self._parse_expr()
            self.expect(TokenType.RBRACK)
        return PortItem(self._loc(name_tok), name=name_tok.value, width=width)

    def _parse_statements_until(self, end: TokenType) -> list[Statement]:
        stmts: list[Statement] = []
        while self.peek().type != end:
            stmts.append(self._parse_statement())
        return stmts

    def _parse_statement(self) -> Statement:
        tok = self.peek()

        if tok.type == TokenType.LOGIC or (tok.type == TokenType.SIGNED):
            return self._parse_signal_decl()
        if tok.type == TokenType.ASSIGN:
            return self._parse_assign_stmt()
        if tok.type == TokenType.SEQ:
            return self._parse_seq_block()
        if tok.type == TokenType.COMB:
            return self._parse_comb_block()
        if tok.type == TokenType.IF:
            return self._parse_if_stmt()
        if tok.type == TokenType.FOR:
            return self._parse_for_stmt()
        if tok.type == TokenType.LOCALPARAM:
            return self._parse_localparam_decl()
        if tok.type == TokenType.TICK_FOR:
            return self._parse_gen_for_stmt()
        if tok.type == TokenType.TICK_IF:
            return self._parse_gen_if_stmt()
        # Instance: IDENT followed by IDENT or #(
        if tok.type == TokenType.IDENT and (
            self.peek(1).type == TokenType.IDENT
            or (self.peek(1).type == TokenType.HASH and self.peek(2).type == TokenType.LPAREN)
        ):
            return self._parse_instance_stmt()
        # Bare assignment: IDENT = expr; or IDENT[...] = expr;
        if tok.type == TokenType.IDENT and (
            self.peek(1).type == TokenType.EQ
            or self.peek(1).type == TokenType.LE
            or self.peek(1).type == TokenType.LBRACK
        ):
            return self._parse_bare_assign_stmt()
        # Bare signal declaration without 'logic' keyword: ident ;
        if tok.type == TokenType.IDENT:
            return self._parse_signal_decl()

        raise SlipSyntaxError(
            self._filename, tok.line, tok.col,
            f"unexpected token '{tok.value}' at statement level"
        )

    def _parse_signal_decl(self) -> SignalDecl:
        tok = self.peek()
        is_signed = False
        width = None

        if tok.type == TokenType.SIGNED:
            is_signed = True
            self.advance()
            tok = self.peek()

        if tok.type == TokenType.LOGIC:
            self.advance()
            tok = self.peek()

        # Optional width [expr:expr] or [expr]
        if tok.type == TokenType.LBRACK:
            self.advance()
            first = self._parse_expr()
            if self.peek().type == TokenType.COLON:
                self.advance()
                second = self._parse_expr()
                # For width, store as a range expression wrapped in a binary expr
                from slip.ast.expressions import BinaryExpr
                width = BinaryExpr(first.loc, ":", first, second)
            else:
                width = first
            self.expect(TokenType.RBRACK)
            tok = self.peek()

        name_tok = self.expect(TokenType.IDENT)

        # Optional array range [expr:expr]
        array_range = None
        if self.peek().type == TokenType.LBRACK:
            self.advance()
            high = self._parse_expr()
            self.expect(TokenType.COLON)
            low = self._parse_expr()
            self.expect(TokenType.RBRACK)
            array_range = (high, low)

        self.expect(TokenType.SEMICOLON)
        return SignalDecl(
            self._loc(tok) if tok.type != TokenType.IDENT else self._loc(name_tok),
            is_signed=is_signed,
            width=width,
            name=name_tok.value,
            array_range=array_range,
        )

    def _parse_assign_stmt(self) -> AssignStmt:
        tok = self.advance()  # consume 'assign'
        target = self._parse_lvalue()
        eq = self.advance()
        if eq.type not in (TokenType.EQ, TokenType.LE):
            raise SlipSyntaxError(
                self._filename, eq.line, eq.col,
                f"expected '=' or '<=' in assignment, got '{eq.value}'"
            )
        is_nb = eq.type == TokenType.LE
        value = self._parse_expr()
        self.expect(TokenType.SEMICOLON)
        return AssignStmt(self._loc(tok), target=target, value=value, is_nonblocking=is_nb)

    def _parse_bare_assign_stmt(self) -> AssignStmt:
        """Parse a bare assignment without 'assign' keyword: IDENT = expr;"""
        tok = self.peek()
        target = self._parse_lvalue()
        eq = self.advance()
        if eq.type not in (TokenType.EQ, TokenType.LE):
            raise SlipSyntaxError(
                self._filename, eq.line, eq.col,
                f"expected '=' or '<=' in assignment, got '{eq.value}'"
            )
        is_nb = eq.type == TokenType.LE
        value = self._parse_expr()
        self.expect(TokenType.SEMICOLON)
        return AssignStmt(self._loc(tok), target=target, value=value, is_nonblocking=is_nb)

    def _parse_lvalue(self) -> LValue:
        name_tok = self.expect(TokenType.IDENT)
        indices: list = []
        while self.peek().type == TokenType.LBRACK:
            self.advance()
            idx = self._parse_expr()
            if self.peek().type == TokenType.COLON:
                self.advance()
                high = self._parse_expr()
                self.expect(TokenType.RBRACK)
                indices.append((idx, high))
            else:
                self.expect(TokenType.RBRACK)
                indices.append(idx)
        return LValue(self._loc(name_tok), name=name_tok.value, indices=tuple(indices))

    def _parse_seq_block(self) -> SeqBlock:
        tok = self.advance()  # consume 'seq'
        self.expect(TokenType.LPAREN)
        clock_tok = self.expect(TokenType.IDENT)
        clock = clock_tok.value
        reset = None
        if self.peek().type == TokenType.COMMA:
            self.advance()
            edge_tok = self.advance()
            if edge_tok.type not in (TokenType.POS, TokenType.NEG):
                raise SlipSyntaxError(
                    self._filename, edge_tok.line, edge_tok.col,
                    f"expected 'pos' or 'neg' in seq reset, got '{edge_tok.value}'"
                )
            self.expect(TokenType.COLON)
            rst_tok = self.expect(TokenType.IDENT)
            reset = (edge_tok.value, rst_tok.value)
        self.expect(TokenType.RPAREN)
        body = self._parse_block()
        return SeqBlock(self._loc(tok), clock=clock, reset=reset, body=body)

    def _parse_comb_block(self) -> CombBlock:
        tok = self.advance()  # consume 'comb'
        body = self._parse_block()
        return CombBlock(self._loc(tok), body=body)

    def _parse_if_stmt(self) -> IfStmt:
        tok = self.advance()  # consume 'if'
        self.expect(TokenType.LPAREN)
        cond = self._parse_expr()
        self.expect(TokenType.RPAREN)
        then_body = self._parse_stmt_or_block()
        else_body = None
        if self.peek().type == TokenType.ELSE:
            self.advance()
            else_body = self._parse_stmt_or_block()
        return IfStmt(self._loc(tok), cond=cond, then_body=then_body, else_body=else_body)

    def _parse_for_stmt(self) -> ForStmt:
        tok = self.advance()  # consume 'for'
        self.expect(TokenType.LPAREN)
        var_tok = self.expect(TokenType.IDENT)
        self.expect(TokenType.EQ)
        init = self._parse_expr()
        self.expect(TokenType.SEMICOLON)
        cond = self._parse_expr()
        self.expect(TokenType.SEMICOLON)
        step_var_tok = self.expect(TokenType.IDENT)
        self.expect(TokenType.EQ)
        step = self._parse_expr()
        self.expect(TokenType.RPAREN)
        body = self._parse_block()
        return ForStmt(
            self._loc(tok),
            var=var_tok.value,
            init=init,
            cond=cond,
            step_var=step_var_tok.value,
            step=step,
            body=body,
        )

    def _parse_gen_for_stmt(self) -> GenForStmt:
        tok = self.advance()  # consume `for
        self.expect(TokenType.LPAREN)
        var_tok = self.expect(TokenType.TICK_IDENT)
        self.expect(TokenType.EQ)
        init = self._parse_expr()
        self.expect(TokenType.SEMICOLON)
        cond = self._parse_expr()
        self.expect(TokenType.SEMICOLON)
        step_var_tok = self.expect(TokenType.TICK_IDENT)
        self.expect(TokenType.EQ)
        step = self._parse_expr()
        self.expect(TokenType.RPAREN)
        body = self._parse_block()
        return GenForStmt(
            self._loc(tok),
            var=var_tok.value[1:],  # strip backtick
            init=init,
            cond=cond,
            step_var=step_var_tok.value[1:],  # strip backtick
            step=step,
            body=body,
        )

    def _parse_gen_if_stmt(self) -> GenIfStmt:
        tok = self.advance()  # consume `if
        self.expect(TokenType.LPAREN)
        cond = self._parse_expr()
        self.expect(TokenType.RPAREN)
        then_body = self._parse_block()
        else_body = None
        if self.peek().type == TokenType.TICK_ELSE:
            self.advance()
            else_body = self._parse_block()
        return GenIfStmt(self._loc(tok), cond=cond, then_body=then_body, else_body=else_body)

    def _parse_instance_stmt(self) -> InstanceStmt:
        module_tok = self.advance()
        module_name = module_tok.value

        params: list[NamedParam] = []
        if self.peek().type == TokenType.HASH and self.peek(1).type == TokenType.LPAREN:
            self.advance()  # #
            self.advance()  # (
            params = self._parse_named_params()
            self.expect(TokenType.RPAREN)

        inst_tok = self.expect(TokenType.IDENT)
        self.expect(TokenType.LBRACE)
        connections = self._parse_connections()
        self.expect(TokenType.RBRACE)
        self.expect(TokenType.SEMICOLON)

        return InstanceStmt(
            self._loc(module_tok),
            module_name=module_name,
            params=tuple(params),
            inst_name=inst_tok.value,
            connections=tuple(connections),
        )

    def _parse_named_params(self) -> list[NamedParam]:
        params: list[NamedParam] = []
        if self.peek().type == TokenType.RPAREN:
            return params
        params.append(self._parse_named_param())
        while self.peek().type == TokenType.COMMA:
            self.advance()
            params.append(self._parse_named_param())
        return params

    def _parse_named_param(self) -> NamedParam:
        self.expect(TokenType.DOT)
        name_tok = self.expect(TokenType.IDENT)
        self.expect(TokenType.LPAREN)
        value = self._parse_expr()
        self.expect(TokenType.RPAREN)
        return NamedParam(self._loc(name_tok), name=name_tok.value, value=value)

    def _parse_connections(self) -> list[Connection]:
        conns: list[Connection] = []
        if self.peek().type == TokenType.RBRACE:
            return conns
        conns.append(self._parse_connection())
        while self.peek().type == TokenType.COMMA:
            self.advance()
            if self.peek().type == TokenType.RBRACE:
                break
            conns.append(self._parse_connection())
        return conns

    def _parse_connection(self) -> Connection:
        # Regex: STRING => STRING
        if self.peek().type == TokenType.STRING_LITERAL:
            port_re_tok = self.advance()
            self.expect(TokenType.ARROW)
            sig_re_tok = self.expect(TokenType.STRING_LITERAL)
            return Connection(
                self._loc(port_re_tok),
                port_regex=port_re_tok.value[1:-1],
                signal_regex=sig_re_tok.value[1:-1],
            )
        # Named: .port(signal)
        self.expect(TokenType.DOT)
        name_tok = self.expect(TokenType.IDENT)
        signal = None
        if self.peek().type == TokenType.LPAREN:
            self.advance()
            signal = self._parse_expr()
            self.expect(TokenType.RPAREN)
        return Connection(
            self._loc(name_tok),
            port=name_tok.value,
            signal=signal,
        )

    def _parse_block(self) -> BlockStmt:
        self.expect(TokenType.LBRACE)
        stmts = self._parse_statements_until(TokenType.RBRACE)
        self.expect(TokenType.RBRACE)
        return BlockStmt(SourceLocation(self._filename, 0, 0), statements=tuple(stmts))

    def _parse_stmt_or_block(self) -> BlockStmt:
        if self.peek().type == TokenType.LBRACE:
            return self._parse_block()
        stmt = self._parse_statement()
        return BlockStmt(SourceLocation(self._filename, 0, 0), statements=(stmt,))

    def _parse_expr(self) -> Expr:
        pratt = PrattParser(self._tokens, self._pos, self._filename)
        expr = pratt.parse_expression()
        self._pos = pratt.pos
        return expr
