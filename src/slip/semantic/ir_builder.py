from __future__ import annotations

import re

from slip.ast.expressions import Expr, IdentExpr, IntLiteralExpr
from slip.ast.instance import InstanceStmt
from slip.ast.module import Module, Param, PortItem
from slip.ast.statements import (
    AssignStmt,
    BlockStmt,
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
from slip.ir import (
    HDLAssignment,
    HDLCaseBlock,
    HDLCaseItem,
    HDLForLoop,
    HDLInstance,
    HDLModule,
    HDLParam,
    HDLPort,
    HDLSignal,
    HDLType,
    LogicBlock,
)
from slip.semantic.driver_analysis import DriverInfo, detect_comb_loops, infer_port_directions
from slip.semantic.expr_serializer import expr_to_sv
from slip.semantic.symbol_collector import (
    SymbolTable,
    iter_localparam_decls,
    iter_signal_decls,
)


def build(
    module: Module,
    symbols: SymbolTable,
    drivers: DriverInfo,
) -> HDLModule:
    """Transform a corrected AST module into an HDLModule IR."""
    explicit_ports = len(module.ports) > 0
    directions = infer_port_directions(symbols, drivers, explicit_ports)

    # Params
    params = tuple(
        HDLParam(p.name, expr_to_sv(p.default))
        for p in module.params
    )

    # Ports
    ports = tuple(
        _make_port(p, directions)
        for p in module.ports
    ) if explicit_ports else tuple(
        _make_implicit_port(name, directions)
        for name in directions
    )

    # Collect signals and process statements
    signals: list[HDLSignal] = []
    assigns: list[HDLAssignment] = []
    logic_blocks: list[LogicBlock] = []
    instances: list[HDLInstance] = []
    localparams: list[HDLParam] = []

    # Collect signal type info from all declarations, including ones nested
    # inside comb/seq/if/for/case blocks (for enriching ports with width info)
    signal_types: dict[str, SignalDecl] = {}
    for decl in iter_signal_decls(module.body):
        signal_types[decl.name] = decl

    # Update ports with width, signedness, and array info from signal declarations
    if explicit_ports:
        enriched_ports = []
        for p in ports:
            if p.name in signal_types:
                decl = signal_types[p.name]
                width_sv = None
                if decl.width:
                    width_sv = _width_to_sv(decl.width)
                array_dim = None
                if decl.array_range:
                    array_dim = f"[{expr_to_sv(decl.array_range[0])}:{expr_to_sv(decl.array_range[1])}]"
                enriched_ports.append(HDLPort(
                    name=p.name,
                    direction=p.direction,
                    type_=HDLType(width_sv=width_sv, is_signed=decl.is_signed),
                    array_dim=array_dim,
                ))
            else:
                enriched_ports.append(p)
        ports = tuple(enriched_ports)

    # Collect explicitly declared signals (skip those already declared as ports)
    declared_signals: set[str] = set()
    for decl in iter_signal_decls(module.body):
        declared_signals.add(decl.name)
        if decl.name not in directions:
            signals.append(_make_signal(decl))

    # Implicit signals: referenced names that aren't params, ports, instances, or declared signals
    # Note: for-loop variables are excluded from implicit signal creation
    for_vars = _collect_for_vars(module.body)
    for name in symbols.all_refs:
        if name == "_":
            continue
        if name in declared_signals or name in symbols.params or name in symbols.localparams or name in symbols.instances:
            continue
        if name in for_vars:
            continue
        if explicit_ports and name in symbols.ports:
            continue
        if not explicit_ports and name in directions:
            continue
        if name.startswith("$"):
            continue  # system functions
        signals.append(HDLSignal(name, HDLType(), declared=False))

    # Collect localparams, including block-nested ones
    for decl in iter_localparam_decls(module.body):
        localparams.append(HDLParam(decl.name, expr_to_sv(decl.value)))

    # Process statements
    for stmt in module.body:
        if isinstance(stmt, SignalDecl):
            continue  # already handled
        elif isinstance(stmt, LocalParamDecl):
            continue  # already handled
        elif isinstance(stmt, AssignStmt):
            if stmt.is_nonblocking:
                raise SlipSemanticError(
                    stmt.loc.file, stmt.loc.line, stmt.loc.col,
                    "nonblocking assignment '<=' is not allowed at module level; "
                    "use a seq (clk) { } block for sequential logic, or blocking "
                    "'=' for a continuous assignment"
                )
            _process_assign(stmt, assigns)
        elif isinstance(stmt, SeqBlock):
            _process_seq(stmt, logic_blocks)
        elif isinstance(stmt, CombBlock):
            _process_comb(stmt, logic_blocks)
        elif isinstance(stmt, InitialBlock):
            _process_initial(stmt, logic_blocks)
        elif isinstance(stmt, InstanceStmt):
            _process_instance(stmt, instances)
        elif isinstance(stmt, IfStmt):
            raise SlipSemanticError(
                stmt.loc.file, stmt.loc.line, stmt.loc.col,
                "'if' is not supported at module level; wrap it in a "
                "comb { } or seq (clk) { } block "
                "(use `if for compile-time conditionals)"
            )
        elif isinstance(stmt, ForStmt):
            raise SlipSemanticError(
                stmt.loc.file, stmt.loc.line, stmt.loc.col,
                "'for' is not supported at module level; wrap it in a "
                "comb { } or seq (clk) { } block "
                "(use `for for compile-time loops)"
            )
        elif isinstance(stmt, CaseStmt):
            raise SlipSemanticError(
                stmt.loc.file, stmt.loc.line, stmt.loc.col,
                "'case' is not supported at module level; wrap it in a "
                "comb { } or seq (clk) { } block"
            )
        elif isinstance(stmt, BlockStmt):
            continue  # comma-separated localparam group — already handled

    # BUG-014: Check for multi-driver conflicts
    _check_multi_driver(module.body, declared_signals, symbols)

    # BUG-028: Check for reset polarity inconsistency
    _check_reset_polarity(module.body)

    # BUG-015: Check for combinational loops
    comb_loop_errors = detect_comb_loops(module)
    if comb_loop_errors:
        raise SlipSemanticError(
            module.loc.file, module.loc.line, module.loc.col,
            comb_loop_errors[0]
        )

    return HDLModule(
        name=module.name,
        params=params,
        localparams=tuple(localparams),
        ports=ports,
        signals=tuple(signals),
        assigns=tuple(assigns),
        logic_blocks=tuple(logic_blocks),
        instances=tuple(instances),
    )


def _make_port(p: PortItem, directions: dict[str, str]) -> HDLPort:
    width_sv = None
    if p.width:
        width_sv = _width_to_sv(p.width)
    is_signed = False
    return HDLPort(
        name=p.name,
        direction=directions.get(p.name, "input"),
        type_=HDLType(width_sv=width_sv, is_signed=is_signed),
    )


def _make_implicit_port(name: str, directions: dict[str, str]) -> HDLPort:
    return HDLPort(
        name=name,
        direction=directions.get(name, "input"),
        type_=HDLType(),
        declared=False,
    )


def _make_signal(stmt: SignalDecl) -> HDLSignal:
    width_sv = None
    if stmt.width:
        width_sv = _width_to_sv(stmt.width)
    array_dim = None
    if stmt.array_range:
        array_dim = f"[{expr_to_sv(stmt.array_range[0])}:{expr_to_sv(stmt.array_range[1])}]"
    return HDLSignal(
        name=stmt.name,
        type_=HDLType(width_sv=width_sv, is_signed=stmt.is_signed),
        array_dim=array_dim,
    )


def _width_to_sv(expr: Expr) -> str:
    """Convert a width expression to SV bracket text like [7:0]."""
    from slip.ast.expressions import BinaryExpr
    if isinstance(expr, BinaryExpr) and expr.op == ":":
        return f"[{expr_to_sv(expr.left)}:{expr_to_sv(expr.right)}]"
    # Single number: assume [N-1:0]
    sv = expr_to_sv(expr)
    return f"[{sv}-1:0]"


def _lvalue_sv(target: LValue) -> str:
    """Serialize an LValue to SV text like 'x[3:0]'."""
    sv = target.name
    for idx in target.indices:
        if isinstance(idx, tuple):
            sv += f"[{expr_to_sv(idx[0])}:{expr_to_sv(idx[1])}]"
        else:
            sv += f"[{expr_to_sv(idx)}]"
    return sv


def _process_assign(
    stmt: AssignStmt,
    assigns: list,
):
    target_sv = _lvalue_sv(stmt.target)
    value_sv = expr_to_sv(stmt.value)
    assigns.append(HDLAssignment(target_sv, value_sv, stmt.is_nonblocking))


def _process_seq(stmt: SeqBlock, logic_blocks: list):
    sens_parts = [f"posedge {stmt.clock}"]
    if stmt.reset:
        edge = "posedge" if stmt.reset[0] == "pos" else "negedge"
        sens_parts.append(f"{edge} {stmt.reset[1]}")
    sensitivity = " or ".join(sens_parts)

    body_items = _convert_block(stmt.body)
    logic_blocks.append(LogicBlock(sensitivity, tuple(body_items)))


def _process_comb(stmt: CombBlock, logic_blocks: list):
    body_items = _convert_block(stmt.body)
    logic_blocks.append(LogicBlock("", tuple(body_items), kind="always_comb"))


def _process_initial(stmt: InitialBlock, logic_blocks: list):
    body_items = _convert_block(stmt.body)
    logic_blocks.append(LogicBlock("", tuple(body_items), kind="initial"))


def _convert_block(block: BlockStmt) -> list:
    items: list = []
    for stmt in block.statements:
        if isinstance(stmt, AssignStmt):
            target_sv = _lvalue_sv(stmt.target)
            value_sv = expr_to_sv(stmt.value)
            items.append(HDLAssignment(target_sv, value_sv, stmt.is_nonblocking))
        elif isinstance(stmt, IfStmt):
            items.append(_convert_if(stmt))
        elif isinstance(stmt, ForStmt):
            items.append(_convert_for(stmt))
        elif isinstance(stmt, CaseStmt):
            items.append(_convert_case(stmt))
    return items


def _convert_if(stmt: IfStmt) -> object:
    from slip.ir.logic_block import HDLIfBlock
    cond_sv = expr_to_sv(stmt.cond)
    then_items = tuple(_convert_block(stmt.then_body))
    else_items = tuple(_convert_block(stmt.else_body)) if stmt.else_body else None
    return HDLIfBlock(cond_sv, then_items, else_items)


def _convert_for(stmt: ForStmt) -> HDLForLoop:
    init_sv = f"{stmt.var} = {expr_to_sv(stmt.init)}"
    cond_sv = expr_to_sv(stmt.cond)
    step_sv = f"{stmt.step_var} = {expr_to_sv(stmt.step)}"
    body_items = tuple(_convert_block(stmt.body))
    return HDLForLoop(stmt.var, init_sv, cond_sv, step_sv, body_items)


def _convert_case(stmt: CaseStmt) -> HDLCaseBlock:
    expr_sv = expr_to_sv(stmt.expr)
    items = tuple(
        HDLCaseItem(
            patterns=tuple(expr_to_sv(p) for p in ci.patterns),
            body=tuple(_convert_block(ci.body)),
        )
        for ci in stmt.items
    )
    return HDLCaseBlock(kind=stmt.kind, expr=expr_sv, items=items)


_BARE_INT_RE = re.compile(r'^[0-9][0-9_]*$')


def _validate_port_constant(signal: Expr, loc):
    """Reject bare integer constants in port connections."""
    if isinstance(signal, IntLiteralExpr) and _BARE_INT_RE.match(signal.raw):
        raise SlipSemanticError(
            loc.file, loc.line, loc.col,
            f"bare integer '{signal.raw}' in port connection must have explicit width "
            f"(e.g. 1'b0) or use '0/'1"
        )


def _process_instance(stmt: InstanceStmt, instances: list):
    # Validate port connection constants
    for conn in stmt.connections:
        if conn.port is not None and conn.signal is not None:
            _validate_port_constant(conn.signal, stmt.loc)

    param_map = tuple(
        (np.name, expr_to_sv(np.value))
        for np in stmt.params
    )
    named_conns = []
    regex_rules = []
    for conn in stmt.connections:
        if conn.port is not None:
            signal_sv = expr_to_sv(conn.signal) if conn.signal else conn.port
            named_conns.append((conn.port, signal_sv))
        elif conn.port_regex is not None:
            regex_rules.append((conn.port_regex, conn.signal_regex))
    instances.append(HDLInstance(
        inst_name=stmt.inst_name,
        target=stmt.module_name,
        param_map=param_map,
        port_map=tuple(named_conns),
        regex_rules=tuple(regex_rules),
        loc=stmt.loc,
    ))


def _collect_for_vars(body: tuple[Statement, ...]) -> set[str]:
    """Collect all for-loop variable names from the module body."""
    vars: set[str] = set()
    for stmt in body:
        if isinstance(stmt, ForStmt):
            vars.add(stmt.var)
            vars |= _collect_for_vars(stmt.body.statements)
        elif isinstance(stmt, SeqBlock):
            vars |= _collect_for_vars(stmt.body.statements)
        elif isinstance(stmt, CombBlock):
            vars |= _collect_for_vars(stmt.body.statements)
        elif isinstance(stmt, InitialBlock):
            vars |= _collect_for_vars(stmt.body.statements)
        elif isinstance(stmt, IfStmt):
            vars |= _collect_for_vars(stmt.then_body.statements)
            if stmt.else_body:
                vars |= _collect_for_vars(stmt.else_body.statements)
        elif isinstance(stmt, BlockStmt):
            vars |= _collect_for_vars(stmt.statements)
        elif isinstance(stmt, CaseStmt):
            for ci in stmt.items:
                vars |= _collect_for_vars(ci.body.statements)
    return vars


def _const_bit(expr: Expr) -> int | None:
    """Evaluate a constant bit index, or None if not a constant."""
    if isinstance(expr, IntLiteralExpr):
        from slip.semantic.gen_expand import _parse_int_literal
        try:
            return _parse_int_literal(expr.raw)
        except ValueError:
            return None
    return None


def _target_range(target: LValue) -> tuple[int, int] | None:
    """Constant bit range driven by an lvalue, or None for whole/unknown.

    Bit- and part-selects with constant indices yield ``(lo, hi)``; a
    whole-variable assignment or a non-constant select yields None,
    which conservatively overlaps everything.
    """
    if not target.indices:
        return None
    idx = target.indices[-1]
    if isinstance(idx, tuple):
        hi = _const_bit(idx[0])
        lo = _const_bit(idx[1])
        if hi is None or lo is None:
            return None
        return (min(hi, lo), max(hi, lo))
    v = _const_bit(idx)
    if v is None:
        return None
    return (v, v)


def _ranges_overlap(a: tuple[int, int] | None, b: tuple[int, int] | None) -> bool:
    if a is None or b is None:
        return True  # whole/unknown overlaps anything
    return a[0] <= b[1] and b[0] <= a[1]


def _check_multi_driver(
    body: tuple[Statement, ...],
    declared_signals: set[str],
    symbols: SymbolTable,
):
    """Check that no signal bit is driven by multiple sources.

    Drivers are seq blocks, comb blocks, and top-level continuous
    assignments.  The check is bit-aware: driving disjoint bits of the
    same variable from separate continuous assignments (a common result
    of ``for`` loop unrolling) is legal; overlapping or whole-variable
    drivers are a conflict.
    """
    # Map signal name -> list of (range, block identifier) already driving
    driven_by: dict[str, list[tuple[tuple[int, int] | None, str]]] = {}

    def _check(sig: str, rng: tuple[int, int] | None, block_id: str, fallback_loc):
        for prev_range, prev_id in driven_by.get(sig, ()):
            if _ranges_overlap(prev_range, rng):
                loc = symbols.all_refs.get(sig, [fallback_loc])[0]
                raise SlipSemanticError(
                    loc.file, loc.line, loc.col,
                    f"signal '{sig}' driven by multiple drivers "
                    f"({prev_id} and {block_id})"
                )
        driven_by.setdefault(sig, []).append((rng, block_id))

    def _check_block(body_stmt, block: BlockStmt, block_id: str):
        # Multiple assignments to one signal inside the same procedural
        # block are a single driver, not a conflict.
        seen: set[str] = set()
        for sig, rng in _collect_driven_signals(block, whole=True):
            if sig in seen:
                continue
            seen.add(sig)
            _check(sig, rng, block_id, body_stmt.loc)

    for stmt in body:
        if isinstance(stmt, SeqBlock):
            _check_block(stmt, stmt.body, f"seq({stmt.clock})")
        elif isinstance(stmt, CombBlock):
            _check_block(stmt, stmt.body, "comb")
        elif isinstance(stmt, AssignStmt):
            _check(
                stmt.target.name,
                _target_range(stmt.target),
                "continuous assignment",
                stmt.loc,
            )
        # Initial blocks are excluded from multi-driver checks because
        # they legitimately initialize signals driven by seq/comb blocks.


def _check_reset_polarity(body: tuple[Statement, ...]):
    """Check that each reset signal is used with consistent polarity across seq blocks."""
    # Map reset signal name -> polarity string ('pos' or 'neg')
    reset_polarities: dict[str, str] = {}
    for stmt in body:
        if isinstance(stmt, SeqBlock) and stmt.reset is not None:
            polarity, signal = stmt.reset
            if signal in reset_polarities:
                prev = reset_polarities[signal]
                if prev != polarity:
                    raise SlipSemanticError(
                        stmt.loc.file, stmt.loc.line, stmt.loc.col,
                        f"reset signal '{signal}' used with conflicting polarity: "
                        f"'{prev}' vs '{polarity}'"
                    )
            else:
                reset_polarities[signal] = polarity


def _collect_driven_signals(block: BlockStmt, whole: bool = False) -> list[tuple[str, tuple[int, int] | None]]:
    """Collect (signal, bit-range) pairs assigned in a block.

    *whole* forces the range to None (whole-variable) — used for seq and
    comb blocks, where any assignment inside the block drives the signal
    as a single process regardless of the select used.
    """
    driven: list[tuple[str, tuple[int, int] | None]] = []
    for stmt in block.statements:
        if isinstance(stmt, AssignStmt):
            rng = None if whole else _target_range(stmt.target)
            driven.append((stmt.target.name, rng))
        elif isinstance(stmt, IfStmt):
            driven.extend(_collect_driven_signals(stmt.then_body, whole))
            if stmt.else_body:
                driven.extend(_collect_driven_signals(stmt.else_body, whole))
        elif isinstance(stmt, ForStmt):
            driven.extend(_collect_driven_signals(stmt.body, whole))
        elif isinstance(stmt, CaseStmt):
            for ci in stmt.items:
                driven.extend(_collect_driven_signals(ci.body, whole))
    return driven
