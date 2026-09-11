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
from slip.semantic.indexing import index_spec, refs_of_assign, specs_overlap
from slip.semantic.symbol_collector import SymbolTable


@dataclass
class DriverInfo:
    drivers: set[str] = field(default_factory=set)  # internally driven
    readers: set[str] = field(default_factory=set)   # read (not just driven)


def analyze(module: Module, symbols: SymbolTable) -> DriverInfo:
    """Analyze which identifiers are driven and/or read within the module."""
    info = DriverInfo()

    for stmt in module.body:
        _scan_stmt(stmt, info)

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


def _scan_stmt(stmt: Statement, info: DriverInfo):
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
            _scan_stmt(s, info)
    elif isinstance(stmt, CombBlock):
        for s in stmt.body.statements:
            _scan_stmt(s, info)
    elif isinstance(stmt, InitialBlock):
        for s in stmt.body.statements:
            _scan_stmt(s, info)
    elif isinstance(stmt, IfStmt):
        _read_expr(stmt.cond, info)
        for s in stmt.then_body.statements:
            _scan_stmt(s, info)
        if stmt.else_body:
            for s in stmt.else_body.statements:
                _scan_stmt(s, info)
    elif isinstance(stmt, ForStmt):
        info.readers.add(stmt.var)
        _read_expr(stmt.init, info)
        _read_expr(stmt.cond, info)
        _read_expr(stmt.step, info)
        for s in stmt.body.statements:
            _scan_stmt(s, info)
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
            _scan_stmt(s, info)
    elif isinstance(stmt, (GenForStmt, GenIfStmt)):
        pass  # unreachable: metaprogramming expansion runs before analysis
    elif isinstance(stmt, CaseStmt):
        _read_expr(stmt.expr, info)
        for ci in stmt.items:
            for p in ci.patterns:
                _read_expr(p, info)
            for s in ci.body.statements:
                _scan_stmt(s, info)


# A graph node is (signal name, index spec) — the storage a value lives in.
# Specs make element-disjoint accesses independent, so the standard
# register-file / shift chains (``st[1] = st[0]``) are not mistaken for
# feedback, while whole-variable or overlapping accesses still connect.
def _fmt_node(node) -> str:
    name, spec = node
    if not spec:
        return name
    parts = []
    for lo, hi in spec:
        parts.append(str(lo) if lo == hi else f"{hi}:{lo}")
    return f"{name}[{']['.join(parts)}]"


def detect_comb_loops(module: Module) -> list[str]:
    """Detect combinational loops in a module.

    Builds one dependency graph per module covering every CombBlock plus all
    top-level continuous assignments, so loops that cross block boundaries
    are also caught.  Graph nodes are (signal, index spec) pairs, so
    element-disjoint storage stays independent.

    Within a CombBlock, SystemVerilog blocking (last-assignment-wins)
    semantics apply: each read resolves to the most recent prior
    assignment of the storage it reads, walking the driver chain
    transitively.  A read with no prior assignment resolves to the
    storage's pre-entry (external) value.  This keeps the
    init-then-accumulate idiom (``y = 0; y = y + b;``) loop-free — the
    read of ``y`` resolves to the constant 0 — while genuine feedback
    (``y = y & a;``, or ``a = b; b = a;``) still produces a cycle.

    Continuous assignments are concurrent processes, so each one is
    analysed independently: a read sees the net values, i.e. whatever
    every other assignment drives.

    Returns a list of error messages (one per cycle), or an empty list.
    """
    graph: dict[tuple, set[tuple]] = {}
    for stmt in module.body:
        if isinstance(stmt, CombBlock):
            _scan_comb_block(stmt.body, graph, {})
        elif isinstance(stmt, AssignStmt):
            # Continuous assignments: no prior-assignment context.
            _add_comb_assignment(stmt, graph, {})
    cycles = _find_cycles(graph)
    return [
        f"combinational loop detected: {' -> '.join(_fmt_node(n) for n in c)}"
        for c in cycles
    ]


def _resolve_reads(refs, state: dict) -> set[tuple]:
    """Resolve each reference to the element nodes it depends on."""
    resolved: set[tuple] = set()
    for r_name, r_spec in refs:
        matched = False
        for (w_name, w_spec), w_reads in state.items():
            if w_name != r_name:
                continue
            if specs_overlap(r_spec, w_spec):
                resolved |= w_reads
                matched = True
        if not matched:
            resolved.add((r_name, r_spec))
    return resolved


def _add_comb_assignment(
    stmt: AssignStmt,
    graph: dict[tuple, set[tuple]],
    state: dict,
):
    """Record one assignment in *state* and add its dependency edges.

    *state* maps the storage each write targets — ``(name, index spec)`` —
    to the element nodes its driver reads.  SSA-style resolution replaces
    reads of storage written earlier in the same block with that
    assignment's own sources, which is what makes ``y = 0; y = y + b;``
    loop-free.
    """
    target = stmt.target.name
    if target == "_":
        return
    target_spec = index_spec(stmt.target.indices)

    resolved = _resolve_reads(refs_of_assign(stmt), state)

    graph.setdefault((target, target_spec), set()).update(resolved)
    state[(target, target_spec)] = resolved


def _merge_branch_states(
    state: dict,
    branches: list[dict],
    all_assign: bool,
):
    """Merge per-branch storage states after a conditional.

    *branches* holds the final state of each branch (empty dict for a
    missing else/default).  Storage written in every branch takes the
    union of the branch drivers (a mux); storage written in only some
    branches keeps a fallback edge to its previous driver.
    """
    all_keys = set()
    for b in branches:
        all_keys |= set(b)
    for key in all_keys:
        assigned = [b[key] for b in branches if key in b]
        if len(assigned) == len(branches) and all_assign:
            state[key] = set().union(*assigned)
        else:
            state[key] = set().union(*assigned, {key})


def _scan_comb_block(
    block: BlockStmt,
    graph: dict[tuple, set[tuple]],
    state: dict,
):
    """Walk statements of a CombBlock, maintaining the driver-read state."""
    for stmt in block.statements:
        if isinstance(stmt, AssignStmt):
            _add_comb_assignment(stmt, graph, state)
        elif isinstance(stmt, IfStmt):
            then_state = dict(state)
            _scan_comb_block(stmt.then_body, graph, then_state)
            else_state = dict(state)
            if stmt.else_body:
                _scan_comb_block(stmt.else_body, graph, else_state)
            _merge_branch_states(state, [then_state, else_state], all_assign=True)
        elif isinstance(stmt, CaseStmt):
            branch_states = [dict(state) for _ in stmt.items]
            has_default = any(not ci.patterns for ci in stmt.items)
            for ci, bs in zip(stmt.items, branch_states):
                _scan_comb_block(ci.body, graph, bs)
            _merge_branch_states(state, branch_states, all_assign=has_default)
        elif isinstance(stmt, ForStmt):
            # The body may execute zero or more times: resolve reads
            # against the pre-loop state, then union the results.
            body_state = dict(state)
            _scan_comb_block(stmt.body, graph, body_state)
            for key, st in body_state.items():
                state[key] = st | state.get(key, {key})


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


def _find_cycles(graph: dict) -> list[list]:
    """Find all simple cycles in a directed graph using DFS.

    Nodes are opaque hashables — here (signal, index spec) pairs.  Returns
    a list of cycles, each a list of nodes forming the loop.
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

    def dfs(u) -> None:
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

    for node in sorted(graph.keys(), key=_fmt_node):
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
    return all_used - symbols.params - symbols.localparams - symbols.signals - symbols.instances
