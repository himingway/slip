from __future__ import annotations

from dataclasses import dataclass, field

from slip.ast.expressions import Expr, IdentExpr
from slip.ast.instance import InstanceStmt
from slip.ast.metaprogram import GenForStmt, GenIfStmt
from slip.ast.module import Module
from slip.ast.statements import (
    AssignStmt,
    BlockStmt,
    CaseStmt,
    CombBlock,
    ForStmt,
    IfStmt,
    InitialBlock,
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
        if expr.index is not None:
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
    elif isinstance(stmt, InitialBlock):
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
            elif conn.port:
                # Same-name shorthand: .port is equivalent to .port(port)
                info.readers.add(conn.port)
    elif isinstance(stmt, BlockStmt):
        for s in stmt.statements:
            _scan_stmt(s, info, is_inside_seq)
    elif isinstance(stmt, (GenForStmt, GenIfStmt)):
        pass  # Phase 2
    elif isinstance(stmt, CaseStmt):
        _read_expr(stmt.expr, info)
        for ci in stmt.items:
            for p in ci.patterns:
                _read_expr(p, info)
            for s in ci.body.statements:
                _scan_stmt(s, info, is_inside_seq)


def detect_comb_loops(module: Module) -> list[str]:
    """Detect combinational loops within CombBlocks of a module.

    Builds a dependency graph for each CombBlock: for ``target = value``,
    ``target`` depends on every signal read in ``value``.  Uses DFS-based
    cycle detection (O(V+E)) to find loops.

    Returns a list of error messages (one per cycle), or an empty list.
    """
    errors: list[str] = []
    for stmt in module.body:
        if isinstance(stmt, CombBlock):
            graph: dict[str, set[str]] = {}
            _collect_comb_deps(stmt.body, graph)
            cycles = _find_cycles(graph)
            for cycle in cycles:
                errors.append(
                    f"combinational loop detected: {' -> '.join(cycle)}"
                )
    return errors


def _collect_comb_deps(block: BlockStmt, graph: dict[str, set[str]]):
    """Recursively collect signal dependencies from statements in a block."""
    for stmt in block.statements:
        if isinstance(stmt, AssignStmt):
            target = stmt.target.name
            if target == "_":
                continue
            reads: set[str] = set()
            _collect_reads_expr(stmt.value, reads)
            for idx in stmt.target.indices:
                if isinstance(idx, tuple):
                    _collect_reads_expr(idx[0], reads)
                    _collect_reads_expr(idx[1], reads)
                else:
                    _collect_reads_expr(idx, reads)
            reads.discard("_")
            graph.setdefault(target, set()).update(reads)
        elif isinstance(stmt, IfStmt):
            cond_reads: set[str] = set()
            _collect_reads_expr(stmt.cond, cond_reads)
            # The condition signals affect every assignment in branches,
            # but for loop detection we care about data-flow through
            # assignments, so we just recurse into bodies.
            _collect_comb_deps(stmt.then_body, graph)
            if stmt.else_body:
                _collect_comb_deps(stmt.else_body, graph)
        elif isinstance(stmt, ForStmt):
            _collect_comb_deps(stmt.body, graph)
        elif isinstance(stmt, CaseStmt):
            for ci in stmt.items:
                _collect_comb_deps(ci.body, graph)


def _collect_reads_expr(expr: Expr, reads: set[str]):
    """Collect all identifier names read by an expression into *reads*."""
    from slip.ast.expressions import (
        BinaryExpr, UnaryExpr, TernaryExpr, IndexExpr,
        ConcatExpr, ReplicationExpr, CastExpr, CallExpr, ParenExpr,
    )
    if isinstance(expr, IdentExpr):
        if expr.name != "_":
            reads.add(expr.name)
    elif isinstance(expr, BinaryExpr):
        _collect_reads_expr(expr.left, reads)
        _collect_reads_expr(expr.right, reads)
    elif isinstance(expr, UnaryExpr):
        _collect_reads_expr(expr.operand, reads)
    elif isinstance(expr, TernaryExpr):
        _collect_reads_expr(expr.cond, reads)
        _collect_reads_expr(expr.true_expr, reads)
        _collect_reads_expr(expr.false_expr, reads)
    elif isinstance(expr, IndexExpr):
        _collect_reads_expr(expr.base, reads)
        if expr.index is not None:
            _collect_reads_expr(expr.index, reads)
        if expr.high is not None:
            _collect_reads_expr(expr.high, reads)
    elif isinstance(expr, ConcatExpr):
        for p in expr.parts:
            _collect_reads_expr(p, reads)
    elif isinstance(expr, ReplicationExpr):
        _collect_reads_expr(expr.count, reads)
        _collect_reads_expr(expr.inner, reads)
    elif isinstance(expr, CastExpr):
        _collect_reads_expr(expr.inner, reads)
    elif isinstance(expr, CallExpr):
        for a in expr.args:
            _collect_reads_expr(a, reads)
    elif isinstance(expr, ParenExpr):
        _collect_reads_expr(expr.inner, reads)


def _find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Find all simple cycles in a directed graph using DFS.

    Returns a list of cycles, where each cycle is a list of node names
    forming the loop (first element repeated at the end).
    Uses O(V+E) time per DFS tree traversal.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    cycles: list[list[str]] = []

    for node in graph:
        color.setdefault(node, WHITE)

    all_nodes = set(graph.keys())
    for targets in graph.values():
        all_nodes.update(targets)
    for node in all_nodes:
        color.setdefault(node, WHITE)

    def dfs(u: str) -> None:
        color[u] = GRAY
        for v in graph.get(u, set()):
            if color.get(v, WHITE) == GRAY:
                # Found a back edge — reconstruct cycle
                cycle = [v, u]
                cur = u
                while cur != v:
                    cur = parent.get(cur)
                    if cur is None:
                        break
                    cycle.append(cur)
                cycle.reverse()
                cycles.append(cycle)
            elif color.get(v, WHITE) == WHITE:
                parent[v] = u
                dfs(v)
        color[u] = BLACK

    for node in sorted(graph.keys()):
        if color[node] == WHITE:
            dfs(node)

    return cycles


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

        # If internally driven, it's an output (even if also read internally).
        # inout requires explicit syntax and is not inferred — the driver analysis
        # cannot distinguish "read inside" from "driven from outside".
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
