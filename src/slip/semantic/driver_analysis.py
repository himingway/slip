from __future__ import annotations

from dataclasses import dataclass, field

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
    SeqBlock,
    SignalDecl,
    Statement,
)
from slip.semantic.symbol_collector import SymbolTable


@dataclass
class DriverInfo:
    drivers: set[str] = field(default_factory=set)  # internally driven
    readers: set[str] = field(default_factory=set)   # read (not just driven)


def analyze(module: Module, symbols: SymbolTable) -> DriverInfo:
    """Analyze which identifiers are driven and/or read within the module."""
    info = DriverInfo()

    for stmt in module.body:
        _scan_stmt(stmt, info, is_inside_seq=False)

    return info


def _read_expr(expr: Expr, info: DriverInfo):
    from slip.ast.expressions import (
        BinaryExpr, UnaryExpr, TernaryExpr, IndexExpr,
        ConcatExpr, ReplicationExpr, CastExpr, CallExpr, ParenExpr,
    )
    if isinstance(expr, IdentExpr):
        if expr.name != "_":
            info.readers.add(expr.name)
    elif isinstance(expr, BinaryExpr):
        _read_expr(expr.left, info)
        _read_expr(expr.right, info)
    elif isinstance(expr, UnaryExpr):
        _read_expr(expr.operand, info)
    elif isinstance(expr, TernaryExpr):
        _read_expr(expr.cond, info)
        _read_expr(expr.true_expr, info)
        _read_expr(expr.false_expr, info)
    elif isinstance(expr, IndexExpr):
        _read_expr(expr.base, info)
        _read_expr(expr.index, info)
        if expr.high is not None:
            _read_expr(expr.high, info)
    elif isinstance(expr, ConcatExpr):
        for p in expr.parts:
            _read_expr(p, info)
    elif isinstance(expr, ReplicationExpr):
        _read_expr(expr.count, info)
        _read_expr(expr.inner, info)
    elif isinstance(expr, CastExpr):
        _read_expr(expr.inner, info)
    elif isinstance(expr, CallExpr):
        for a in expr.args:
            _read_expr(a, info)
    elif isinstance(expr, ParenExpr):
        _read_expr(expr.inner, info)


def _scan_stmt(stmt: Statement, info: DriverInfo, is_inside_seq: bool):
    if isinstance(stmt, AssignStmt):
        info.drivers.add(stmt.target.name)
        _read_expr(stmt.value, info)
        for idx in stmt.target.indices:
            if isinstance(idx, tuple):
                _read_expr(idx[0], info)
                _read_expr(idx[1], info)
            else:
                _read_expr(idx, info)
    elif isinstance(stmt, SeqBlock):
        info.readers.add(stmt.clock)
        if stmt.reset:
            info.readers.add(stmt.reset[1])
        for s in stmt.body.statements:
            _scan_stmt(s, info, is_inside_seq=True)
    elif isinstance(stmt, CombBlock):
        for s in stmt.body.statements:
            _scan_stmt(s, info, is_inside_seq=False)
    elif isinstance(stmt, IfStmt):
        _read_expr(stmt.cond, info)
        for s in stmt.then_body.statements:
            _scan_stmt(s, info, is_inside_seq)
        if stmt.else_body:
            for s in stmt.else_body.statements:
                _scan_stmt(s, info, is_inside_seq)
    elif isinstance(stmt, ForStmt):
        info.readers.add(stmt.var)
        _read_expr(stmt.init, info)
        _read_expr(stmt.cond, info)
        _read_expr(stmt.step, info)
        for s in stmt.body.statements:
            _scan_stmt(s, info, is_inside_seq)
    elif isinstance(stmt, SignalDecl):
        pass  # declarations don't drive or read
    elif isinstance(stmt, InstanceStmt):
        for conn in stmt.connections:
            if conn.signal:
                _read_expr(conn.signal, info)
    elif isinstance(stmt, BlockStmt):
        for s in stmt.statements:
            _scan_stmt(s, info, is_inside_seq)
    elif isinstance(stmt, (GenForStmt, GenIfStmt)):
        pass  # Phase 2


def infer_port_directions(
    symbols: SymbolTable,
    drivers: DriverInfo,
    explicit_ports: bool,
) -> dict[str, str]:
    """Infer port directions based on driver analysis.

    Returns a mapping of port_name -> 'input' | 'output' | 'inout'.
    """
    directions: dict[str, str] = {}

    port_names = symbols.ports if explicit_ports else _implicit_port_candidates(symbols, drivers)

    for name in port_names:
        is_driven = name in drivers.drivers
        is_read = name in drivers.readers

        # If internally driven, it's an output (even if also read internally)
        if is_driven:
            directions[name] = "output"
        elif is_read:
            directions[name] = "input"
        else:
            directions[name] = "input"  # unused port

    return directions


def _implicit_port_candidates(symbols: SymbolTable, drivers: DriverInfo) -> set[str]:
    """Determine implicit port candidates: referenced names not declared internally."""
    all_used = set(drivers.drivers) | drivers.readers
    return all_used - symbols.params - symbols.signals - symbols.instances
