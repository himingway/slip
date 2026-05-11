from __future__ import annotations

from dataclasses import dataclass, field

from slip.ast.base import SourceLocation
from slip.ast.expressions import Expr, IdentExpr
from slip.ast.instance import InstanceStmt
from slip.ast.metaprogram import GenForStmt, GenIfStmt
from slip.ast.module import Module
from slip.ast.statements import (
    AssignStmt,
    BlockStmt,
    CombBlock,
    ForStmt,
    IfStmt,
    LocalParamDecl,
    SeqBlock,
    SignalDecl,
    Statement,
)


def _collect_expr_idents(expr: Expr, refs: dict[str, list[SourceLocation]], loc: SourceLocation):
    from slip.ast.expressions import (
        BinaryExpr, UnaryExpr, TernaryExpr, IndexExpr,
        ConcatExpr, ReplicationExpr, CastExpr, CallExpr, ParenExpr,
    )
    if isinstance(expr, IdentExpr):
        if expr.name != "_":
            refs.setdefault(expr.name, []).append(loc)
    elif isinstance(expr, BinaryExpr):
        _collect_expr_idents(expr.left, refs, loc)
        _collect_expr_idents(expr.right, refs, loc)
    elif isinstance(expr, UnaryExpr):
        _collect_expr_idents(expr.operand, refs, loc)
    elif isinstance(expr, TernaryExpr):
        _collect_expr_idents(expr.cond, refs, loc)
        _collect_expr_idents(expr.true_expr, refs, loc)
        _collect_expr_idents(expr.false_expr, refs, loc)
    elif isinstance(expr, IndexExpr):
        _collect_expr_idents(expr.base, refs, loc)
        _collect_expr_idents(expr.index, refs, loc)
        if expr.high is not None:
            _collect_expr_idents(expr.high, refs, loc)
    elif isinstance(expr, ConcatExpr):
        for p in expr.parts:
            _collect_expr_idents(p, refs, loc)
    elif isinstance(expr, ReplicationExpr):
        _collect_expr_idents(expr.count, refs, loc)
        _collect_expr_idents(expr.inner, refs, loc)
    elif isinstance(expr, CastExpr):
        _collect_expr_idents(expr.inner, refs, loc)
    elif isinstance(expr, CallExpr):
        for a in expr.args:
            _collect_expr_idents(a, refs, loc)
    elif isinstance(expr, ParenExpr):
        _collect_expr_idents(expr.inner, refs, loc)


def _collect_lvalue_name(lvalue) -> str:
    """Extract the base identifier name from an LValue."""
    return lvalue.name


@dataclass
class SymbolTable:
    params: set[str] = field(default_factory=set)
    localparams: set[str] = field(default_factory=set)
    ports: set[str] = field(default_factory=set)
    signals: set[str] = field(default_factory=set)
    instances: set[str] = field(default_factory=set)
    all_refs: dict[str, list[SourceLocation]] = field(default_factory=dict)

    @property
    def declared(self) -> set[str]:
        return self.params | self.localparams | self.ports | self.signals | self.instances


def collect(module: Module) -> SymbolTable:
    """Collect all declarations and identifier references from a module."""
    syms = SymbolTable()

    # Collect params
    for p in module.params:
        syms.params.add(p.name)

    # Collect ports
    for p in module.ports:
        syms.ports.add(p.name)

    # Walk body
    for stmt in module.body:
        _walk_stmt(stmt, syms)

    return syms


def _walk_stmt(stmt: Statement, syms: SymbolTable):
    if isinstance(stmt, SignalDecl):
        syms.signals.add(stmt.name)
        if stmt.width:
            _collect_expr_idents(stmt.width, syms.all_refs, stmt.loc)
        if stmt.array_range:
            _collect_expr_idents(stmt.array_range[0], syms.all_refs, stmt.loc)
            _collect_expr_idents(stmt.array_range[1], syms.all_refs, stmt.loc)
    elif isinstance(stmt, AssignStmt):
        name = _collect_lvalue_name(stmt.target)
        syms.all_refs.setdefault(name, []).append(stmt.loc)
        for idx in stmt.target.indices:
            if isinstance(idx, tuple):
                _collect_expr_idents(idx[0], syms.all_refs, stmt.loc)
                _collect_expr_idents(idx[1], syms.all_refs, stmt.loc)
            else:
                _collect_expr_idents(idx, syms.all_refs, stmt.loc)
        _collect_expr_idents(stmt.value, syms.all_refs, stmt.loc)
    elif isinstance(stmt, SeqBlock):
        _collect_expr_idents(IdentExpr(stmt.loc, stmt.clock), syms.all_refs, stmt.loc)
        if stmt.reset:
            _collect_expr_idents(IdentExpr(stmt.loc, stmt.reset[1]), syms.all_refs, stmt.loc)
        for s in stmt.body.statements:
            _walk_stmt(s, syms)
    elif isinstance(stmt, CombBlock):
        for s in stmt.body.statements:
            _walk_stmt(s, syms)
    elif isinstance(stmt, IfStmt):
        _collect_expr_idents(stmt.cond, syms.all_refs, stmt.loc)
        for s in stmt.then_body.statements:
            _walk_stmt(s, syms)
        if stmt.else_body:
            for s in stmt.else_body.statements:
                _walk_stmt(s, syms)
    elif isinstance(stmt, ForStmt):
        syms.all_refs.setdefault(stmt.var, []).append(stmt.loc)
        _collect_expr_idents(stmt.init, syms.all_refs, stmt.loc)
        _collect_expr_idents(stmt.cond, syms.all_refs, stmt.loc)
        _collect_expr_idents(stmt.step, syms.all_refs, stmt.loc)
        for s in stmt.body.statements:
            _walk_stmt(s, syms)
    elif isinstance(stmt, InstanceStmt):
        syms.instances.add(stmt.inst_name)
        for np in stmt.params:
            _collect_expr_idents(np.value, syms.all_refs, stmt.loc)
        for conn in stmt.connections:
            if conn.signal:
                _collect_expr_idents(conn.signal, syms.all_refs, stmt.loc)
    elif isinstance(stmt, (GenForStmt, GenIfStmt)):
        pass  # Phase 2
    elif isinstance(stmt, LocalParamDecl):
        syms.localparams.add(stmt.name)
    elif isinstance(stmt, BlockStmt):
        for s in stmt.statements:
            _walk_stmt(s, syms)
