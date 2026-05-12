from __future__ import annotations

import re

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
    ParenExpr,
    ReplicationExpr,
    StringLiteralExpr,
    TernaryExpr,
    TickConstExpr,
    TickIdentExpr,
    UnaryExpr,
)
from slip.ast.instance import Connection, InstanceStmt, NamedParam
from slip.ast.metaprogram import GenForStmt, GenIfStmt
from slip.ast.module import Module
from slip.ast.statements import (
    AssignStmt,
    BlockStmt,
    CaseItem,
    CaseStmt,
    CombBlock,
    ForStmt,
    IfStmt,
    InitialBlock,
    LocalParamDecl,
    LValue,
    SeqBlock,
    SignalDecl,
    Statement,
)
from slip.errors.semantic import SlipSemanticError

_VERILOG_LITERAL_RE = re.compile(
    r"^(?:(\d+)'([bBdDhHoO])([0-9a-fA-F_xXzZ]+)|([0-9][0-9_]*))$"
)

_MAX_ITER = 1024


def _parse_int_literal(raw: str) -> int:
    m = _VERILOG_LITERAL_RE.match(raw)
    if not m:
        raise ValueError(f"invalid integer literal: {raw}")
    if m.group(4) is not None:
        return int(m.group(4).replace("_", ""))
    digits = m.group(3).replace("_", "")
    if any(c in digits for c in "xXzZ"):
        raise ValueError(f"cannot evaluate x/z literal at compile time: {raw}")
    radix_map = {"b": 2, "o": 8, "d": 10, "h": 16}
    return int(digits, radix_map[m.group(2).lower()])


def _eval_int(expr: Expr, params: dict[str, int], loc: SourceLocation) -> int:
    if isinstance(expr, IntLiteralExpr):
        return _parse_int_literal(expr.raw)
    if isinstance(expr, IdentExpr):
        if expr.name not in params:
            raise SlipSemanticError(
                loc.file, loc.line, loc.col,
                f"cannot evaluate '{expr.name}' at compile time"
            )
        return params[expr.name]
    if isinstance(expr, TickIdentExpr):
        if expr.name not in params:
            raise SlipSemanticError(
                loc.file, loc.line, loc.col,
                f"cannot evaluate '`{expr.name}' at compile time"
            )
        return params[expr.name]
    if isinstance(expr, BinaryExpr):
        # Handle 'inside' operator: expr inside {set}
        if expr.op == "inside":
            left = _eval_int(expr.left, params, loc)
            if isinstance(expr.right, ConcatExpr):
                set_vals = [_eval_int(p, params, loc) for p in expr.right.parts]
                return int(left in set_vals)
            raise SlipSemanticError(
                loc.file, loc.line, loc.col,
                "inside operator requires a set literal {v1, v2, ...} on the right"
            )
        left = _eval_int(expr.left, params, loc)
        right = _eval_int(expr.right, params, loc)
        ops: dict[str, int] = {
            "+": left + right, "-": left - right, "*": left * right,
            "/": left // right if right != 0 else 0,
            "%": left % right if right != 0 else 0,
            "**": left ** right,
            "<": int(left < right), ">": int(left > right),
            "<=": int(left <= right), ">=": int(left >= right),
            "==": int(left == right), "!=": int(left != right),
            "===": int(left == right), "!==": int(left != right),
            "&&": int(left and right), "||": int(left or right),
            "&": left & right, "|": left | right, "^": left ^ right,
            "<<": left << right, ">>": left >> right,
            "<<<": left << right, ">>>": left >> right,
        }
        if expr.op not in ops:
            raise SlipSemanticError(
                loc.file, loc.line, loc.col,
                f"unsupported operator '{expr.op}' in compile-time expression"
            )
        return ops[expr.op]
    if isinstance(expr, UnaryExpr):
        operand = _eval_int(expr.operand, params, loc)
        if expr.op == "-":
            return -operand
        if expr.op == "!":
            return int(not operand)
        if expr.op == "~":
            return ~operand
        raise SlipSemanticError(
            loc.file, loc.line, loc.col,
            f"unsupported unary operator '{expr.op}' in compile-time expression"
        )
    if isinstance(expr, ParenExpr):
        return _eval_int(expr.inner, params, loc)
    if isinstance(expr, TickConstExpr):
        raise SlipSemanticError(
            loc.file, loc.line, loc.col,
            f"'{expr.raw[1:]}' cannot be evaluated at compile time"
        )
    raise SlipSemanticError(
        loc.file, loc.line, loc.col,
        f"expression is not evaluable at compile time"
    )


# ── Constant folding helpers ──

def _int_val(expr: IntLiteralExpr) -> int | None:
    try:
        return _parse_int_literal(expr.raw)
    except ValueError:
        return None


def _try_fold_binary(loc: SourceLocation, op: str, left: Expr, right: Expr) -> Expr:
    if isinstance(left, IntLiteralExpr) and isinstance(right, IntLiteralExpr):
        try:
            result = _eval_int(BinaryExpr(loc, op, left, right), {}, loc)
            return IntLiteralExpr(loc, raw=str(result))
        except SlipSemanticError:
            pass
    if isinstance(right, IntLiteralExpr):
        rv = _int_val(right)
        if rv is not None:
            if op == "+" and rv == 0:
                return left
            if op == "-" and rv == 0:
                return left
            if op == "*" and rv == 1:
                return left
            if op == "*" and rv == 0:
                return IntLiteralExpr(loc, raw="0")
            if op == "/" and rv == 1:
                return left
    if isinstance(left, IntLiteralExpr):
        lv = _int_val(left)
        if lv is not None:
            if op == "+" and lv == 0:
                return right
            if op == "*" and lv == 1:
                return right
            if op == "*" and lv == 0:
                return IntLiteralExpr(loc, raw="0")
    return BinaryExpr(loc, op, left, right)


def _try_fold_unary(loc: SourceLocation, op: str, operand: Expr, prefix: bool) -> Expr:
    if isinstance(operand, IntLiteralExpr):
        try:
            result = _eval_int(UnaryExpr(loc, op, operand, prefix), {}, loc)
            return IntLiteralExpr(loc, raw=str(result))
        except SlipSemanticError:
            pass
    return UnaryExpr(loc, op, operand, prefix)


# ── Substitution: deep-copy with loop var replaced by int literal ──

def _sub_name(name: str, var: str, val: int) -> str:
    """Replace `var meta-variable in identifier names.

    Replaces backtick-prefixed variable: data_`i → data_3, inst_`i → inst_3.
    """
    return name.replace(f"`{var}", str(val))


def _sub_expr(expr: Expr, var: str, val: int) -> Expr:
    if isinstance(expr, IdentExpr):
        if expr.name == var:
            return IntLiteralExpr(expr.loc, raw=str(val))
        new_name = _sub_name(expr.name, var, val)
        if new_name != expr.name:
            return IdentExpr(expr.loc, name=new_name)
        return expr
    if isinstance(expr, TickIdentExpr):
        if expr.name == var:
            return IntLiteralExpr(expr.loc, raw=str(val))
        return expr
    if isinstance(expr, IntLiteralExpr):
        return expr
    if isinstance(expr, BinaryExpr):
        left = _sub_expr(expr.left, var, val)
        right = _sub_expr(expr.right, var, val)
        return _try_fold_binary(expr.loc, expr.op, left, right)
    if isinstance(expr, UnaryExpr):
        operand = _sub_expr(expr.operand, var, val)
        return _try_fold_unary(expr.loc, expr.op, operand, expr.prefix)
    if isinstance(expr, TernaryExpr):
        cond = _sub_expr(expr.cond, var, val)
        true_expr = _sub_expr(expr.true_expr, var, val)
        false_expr = _sub_expr(expr.false_expr, var, val)
        if isinstance(cond, IntLiteralExpr):
            cv = _int_val(cond)
            if cv is not None:
                return true_expr if cv else false_expr
        return TernaryExpr(expr.loc, cond=cond,
                           true_expr=true_expr, false_expr=false_expr)
    if isinstance(expr, IndexExpr):
        return IndexExpr(expr.loc,
                         base=_sub_expr(expr.base, var, val),
                         index=_sub_expr(expr.index, var, val) if expr.index is not None else None,
                         high=_sub_expr(expr.high, var, val) if expr.high is not None else None,
                         is_slice=expr.is_slice)
    if isinstance(expr, ConcatExpr):
        return ConcatExpr(expr.loc,
                          parts=tuple(_sub_expr(p, var, val) for p in expr.parts))
    if isinstance(expr, ReplicationExpr):
        return ReplicationExpr(expr.loc,
                               count=_sub_expr(expr.count, var, val),
                               inner=_sub_expr(expr.inner, var, val))
    if isinstance(expr, CastExpr):
        return CastExpr(expr.loc, target=expr.target,
                        inner=_sub_expr(expr.inner, var, val))
    if isinstance(expr, CallExpr):
        return CallExpr(expr.loc, func=expr.func,
                        args=tuple(_sub_expr(a, var, val) for a in expr.args))
    if isinstance(expr, ParenExpr):
        inner = _sub_expr(expr.inner, var, val)
        if isinstance(inner, IntLiteralExpr):
            return inner
        return ParenExpr(expr.loc, inner=inner)
    if isinstance(expr, StringLiteralExpr):
        return expr
    if isinstance(expr, TickConstExpr):
        return expr
    return expr


def _sub_lvalue(lv: LValue, var: str, val: int) -> LValue:
    new_indices = tuple(
        (_sub_expr(a, var, val), _sub_expr(b, var, val))
        if isinstance(idx, tuple) else _sub_expr(idx, var, val)
        for idx in lv.indices
    )
    return LValue(lv.loc, name=_sub_name(lv.name, var, val), indices=new_indices)


def _sub_stmt(stmt: Statement, var: str, val: int) -> Statement:
    if isinstance(stmt, AssignStmt):
        return AssignStmt(stmt.loc,
                          target=_sub_lvalue(stmt.target, var, val),
                          value=_sub_expr(stmt.value, var, val),
                          is_nonblocking=stmt.is_nonblocking)
    if isinstance(stmt, SignalDecl):
        new_width = _sub_expr(stmt.width, var, val) if stmt.width else None
        new_arr = (
            (_sub_expr(stmt.array_range[0], var, val),
             _sub_expr(stmt.array_range[1], var, val))
            if stmt.array_range else None
        )
        return SignalDecl(stmt.loc, is_signed=stmt.is_signed,
                          width=new_width, name=_sub_name(stmt.name, var, val),
                          array_range=new_arr)
    if isinstance(stmt, SeqBlock):
        return SeqBlock(stmt.loc, clock=stmt.clock, reset=stmt.reset,
                        body=_sub_block(stmt.body, var, val))
    if isinstance(stmt, CombBlock):
        return CombBlock(stmt.loc, body=_sub_block(stmt.body, var, val))
    if isinstance(stmt, InitialBlock):
        return InitialBlock(stmt.loc, body=_sub_block(stmt.body, var, val))
    if isinstance(stmt, IfStmt):
        return IfStmt(stmt.loc,
                      cond=_sub_expr(stmt.cond, var, val),
                      then_body=_sub_block(stmt.then_body, var, val),
                      else_body=_sub_block(stmt.else_body, var, val) if stmt.else_body else None)
    if isinstance(stmt, ForStmt):
        return ForStmt(stmt.loc, var=stmt.var,
                       init=_sub_expr(stmt.init, var, val),
                       cond=_sub_expr(stmt.cond, var, val),
                       step_var=stmt.step_var,
                       step=_sub_expr(stmt.step, var, val),
                       body=_sub_block(stmt.body, var, val))
    if isinstance(stmt, CaseStmt):
        new_items = tuple(
            CaseItem(ci.loc,
                     patterns=tuple(_sub_expr(p, var, val) for p in ci.patterns),
                     body=_sub_block(ci.body, var, val))
            for ci in stmt.items
        )
        return CaseStmt(stmt.loc, kind=stmt.kind,
                        expr=_sub_expr(stmt.expr, var, val),
                        items=new_items)
    if isinstance(stmt, InstanceStmt):
        new_params = tuple(
            NamedParam(np.loc, name=np.name, value=_sub_expr(np.value, var, val))
            for np in stmt.params
        )
        new_conns = []
        for c in stmt.connections:
            new_signal = _sub_expr(c.signal, var, val) if c.signal else None
            new_port = _sub_name(c.port, var, val) if c.port else None
            new_port_re = _sub_name(c.port_regex, var, val) if c.port_regex else None
            new_sig_re = _sub_name(c.signal_regex, var, val) if c.signal_regex else None
            new_conns.append(Connection(c.loc, port=new_port, signal=new_signal,
                                        port_regex=new_port_re, signal_regex=new_sig_re))
        return InstanceStmt(stmt.loc, module_name=_sub_name(stmt.module_name, var, val),
                            params=new_params, inst_name=_sub_name(stmt.inst_name, var, val),
                            connections=tuple(new_conns))
    if isinstance(stmt, BlockStmt):
        return _sub_block(stmt, var, val)
    if isinstance(stmt, LocalParamDecl):
        return LocalParamDecl(stmt.loc, name=stmt.name,
                              value=_sub_expr(stmt.value, var, val))
    if isinstance(stmt, GenForStmt):
        return GenForStmt(stmt.loc, var=stmt.var,
                          init=_sub_expr(stmt.init, var, val),
                          cond=_sub_expr(stmt.cond, var, val),
                          step_var=stmt.step_var,
                          step=_sub_expr(stmt.step, var, val),
                          body=_sub_block(stmt.body, var, val))
    if isinstance(stmt, GenIfStmt):
        return GenIfStmt(stmt.loc,
                         cond=_sub_expr(stmt.cond, var, val),
                         then_body=_sub_block(stmt.then_body, var, val),
                         else_body=_sub_block(stmt.else_body, var, val) if stmt.else_body else None)
    return stmt


def _sub_block(block: BlockStmt, var: str, val: int) -> BlockStmt:
    return BlockStmt(block.loc,
                     statements=tuple(_sub_stmt(s, var, val) for s in block.statements))


# ── Expansion: #for and #if ──

def _expand_gen_for(stmt: GenForStmt, params: dict[str, int]) -> list[Statement]:
    if stmt.step_var != stmt.var:
        raise SlipSemanticError(
            stmt.loc.file, stmt.loc.line, stmt.loc.col,
            f"#for step variable '{stmt.step_var}' must match loop variable "
            f"'{stmt.var}'; the step expression determines the next value of "
            f"the loop variable"
        )
    current = _eval_int(stmt.init, params, stmt.loc)
    result: list[Statement] = []
    count = 0
    while True:
        local_params = {**params, stmt.var: current}
        cond_val = _eval_int(stmt.cond, local_params, stmt.loc)
        if not cond_val:
            break
        expanded = _sub_block(stmt.body, stmt.var, current)
        result.extend(expanded.statements)
        current = _eval_int(stmt.step, local_params, stmt.loc)
        count += 1
        if count > _MAX_ITER:
            raise SlipSemanticError(
                stmt.loc.file, stmt.loc.line, stmt.loc.col,
                f"#for loop exceeded {_MAX_ITER} iterations"
            )
    return result


def _expand_gen_if(stmt: GenIfStmt, params: dict[str, int]) -> list[Statement]:
    cond_val = _eval_int(stmt.cond, params, stmt.loc)
    if cond_val:
        return list(stmt.then_body.statements)
    if stmt.else_body is not None:
        return list(stmt.else_body.statements)
    return []


# ── Recursive expansion into all block containers ──

def _expand_stmt(stmt: Statement, params: dict[str, int]) -> list[Statement]:
    if isinstance(stmt, GenForStmt):
        inner = _expand_gen_for(stmt, params)
        flat: list[Statement] = []
        for s in inner:
            flat.extend(_expand_stmt(s, params))
        return flat
    if isinstance(stmt, GenIfStmt):
        inner = _expand_gen_if(stmt, params)
        flat: list[Statement] = []
        for s in inner:
            flat.extend(_expand_stmt(s, params))
        return flat
    if isinstance(stmt, LocalParamDecl):
        return [stmt]
    if isinstance(stmt, BlockStmt):
        expanded = []
        for s in stmt.statements:
            expanded.extend(_expand_stmt(s, params))
        return [BlockStmt(stmt.loc, statements=tuple(expanded))]
    if isinstance(stmt, SeqBlock):
        new_body = []
        for s in stmt.body.statements:
            new_body.extend(_expand_stmt(s, params))
        return [SeqBlock(stmt.loc, clock=stmt.clock, reset=stmt.reset,
                         body=BlockStmt(stmt.body.loc, statements=tuple(new_body)))]
    if isinstance(stmt, CombBlock):
        new_body = []
        for s in stmt.body.statements:
            new_body.extend(_expand_stmt(s, params))
        return [CombBlock(stmt.loc, body=BlockStmt(stmt.body.loc, statements=tuple(new_body)))]
    if isinstance(stmt, InitialBlock):
        new_body = []
        for s in stmt.body.statements:
            new_body.extend(_expand_stmt(s, params))
        return [InitialBlock(stmt.loc, body=BlockStmt(stmt.body.loc, statements=tuple(new_body)))]
    if isinstance(stmt, IfStmt):
        new_then = []
        for s in stmt.then_body.statements:
            new_then.extend(_expand_stmt(s, params))
        new_else = None
        if stmt.else_body:
            ne = []
            for s in stmt.else_body.statements:
                ne.extend(_expand_stmt(s, params))
            new_else = BlockStmt(stmt.else_body.loc, statements=tuple(ne))
        return [IfStmt(stmt.loc, cond=stmt.cond,
                       then_body=BlockStmt(stmt.then_body.loc, statements=tuple(new_then)),
                       else_body=new_else)]
    if isinstance(stmt, ForStmt):
        new_body = []
        for s in stmt.body.statements:
            new_body.extend(_expand_stmt(s, params))
        return [ForStmt(stmt.loc, var=stmt.var, init=stmt.init, cond=stmt.cond,
                        step_var=stmt.step_var, step=stmt.step,
                        body=BlockStmt(stmt.body.loc, statements=tuple(new_body)))]
    if isinstance(stmt, CaseStmt):
        new_items = []
        for ci in stmt.items:
            new_ci_body = []
            for s in ci.body.statements:
                new_ci_body.extend(_expand_stmt(s, params))
            new_items.append(CaseItem(ci.loc, patterns=ci.patterns,
                                       body=BlockStmt(ci.body.loc,
                                                       statements=tuple(new_ci_body))))
        return [CaseStmt(stmt.loc, kind=stmt.kind, expr=stmt.expr,
                         items=tuple(new_items))]
    return [stmt]


# ── Public API ──

def expand_module(module: Module) -> Module:
    """Expand all #for and #if metaprogramming nodes in a module.

    Must run BEFORE symbol collection, driver analysis, and IR building.
    """
    params: dict[str, int] = {}
    for p in module.params:
        params[p.name] = _eval_int(p.default, {}, p.loc)
    # Collect top-level localparams for compile-time evaluation
    for stmt in module.body:
        if isinstance(stmt, LocalParamDecl):
            params[stmt.name] = _eval_int(stmt.value, params, stmt.loc)

    new_body: list[Statement] = []
    for stmt in module.body:
        new_body.extend(_expand_stmt(stmt, params))

    return Module(module.loc, name=module.name, params=module.params,
                  ports=module.ports, body=tuple(new_body))
