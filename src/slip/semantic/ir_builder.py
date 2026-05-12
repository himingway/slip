from __future__ import annotations

import re

from slip.ast.expressions import Expr, IdentExpr, IntLiteralExpr
from slip.ast.instance import InstanceStmt
from slip.ast.metaprogram import GenForStmt, GenIfStmt
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
from slip.semantic.symbol_collector import SymbolTable


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

    # Collect signal type info from declarations (for enriching ports with width info)
    signal_types: dict[str, SignalDecl] = {}
    for stmt in module.body:
        if isinstance(stmt, SignalDecl):
            signal_types[stmt.name] = stmt

    # Update ports with width info from signal declarations
    if explicit_ports:
        enriched_ports = []
        for p in ports:
            if p.name in signal_types:
                decl = signal_types[p.name]
                width_sv = None
                if decl.width:
                    width_sv = _width_to_sv(decl.width)
                enriched_ports.append(HDLPort(
                    name=p.name,
                    direction=p.direction,
                    type_=HDLType(width_sv=width_sv, is_signed=decl.is_signed),
                ))
            else:
                enriched_ports.append(p)
        ports = tuple(enriched_ports)

    # Collect explicitly declared signals (skip those already declared as ports)
    declared_signals: set[str] = set()
    for stmt in module.body:
        if isinstance(stmt, SignalDecl):
            declared_signals.add(stmt.name)
            if stmt.name not in directions:
                signals.append(_make_signal(stmt))

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

    # Process statements
    for stmt in module.body:
        if isinstance(stmt, SignalDecl):
            continue  # already handled
        elif isinstance(stmt, LocalParamDecl):
            localparams.append(HDLParam(stmt.name, expr_to_sv(stmt.value)))
            continue
        elif isinstance(stmt, AssignStmt):
            _process_assign(stmt, assigns, logic_blocks, drivers)
        elif isinstance(stmt, SeqBlock):
            _process_seq(stmt, logic_blocks)
        elif isinstance(stmt, CombBlock):
            _process_comb(stmt, logic_blocks)
        elif isinstance(stmt, InitialBlock):
            _process_initial(stmt, logic_blocks)
        elif isinstance(stmt, InstanceStmt):
            _process_instance(stmt, instances)
        elif isinstance(stmt, (GenForStmt, GenIfStmt)):
            pass  # Phase 2

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


def _process_assign(
    stmt: AssignStmt,
    assigns: list,
    logic_blocks: list,
    drivers: DriverInfo,
):
    target_sv = stmt.target.name
    for idx in stmt.target.indices:
        if isinstance(idx, tuple):
            target_sv += f"[{expr_to_sv(idx[0])}:{expr_to_sv(idx[1])}]"
        else:
            target_sv += f"[{expr_to_sv(idx)}]"
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
            target_sv = stmt.target.name
            for idx in stmt.target.indices:
                if isinstance(idx, tuple):
                    target_sv += f"[{expr_to_sv(idx[0])}:{expr_to_sv(idx[1])}]"
                else:
                    target_sv += f"[{expr_to_sv(idx)}]"
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
    return vars


def _check_multi_driver(
    body: tuple[Statement, ...],
    declared_signals: set[str],
    symbols: SymbolTable,
):
    """Check that no signal is driven by multiple procedural blocks."""
    # Map signal name -> block identifier
    driven_by: dict[str, str] = {}

    for stmt in body:
        if isinstance(stmt, SeqBlock):
            block_id = f"seq({stmt.clock})"
            driven = _collect_driven_signals(stmt.body)
            for sig in driven:
                if sig in driven_by:
                    loc = symbols.all_refs.get(sig, [None])[0]
                    file = loc.file if loc else "<unknown>"
                    line = loc.line if loc else 0
                    col = loc.col if loc else 0
                    raise SlipSemanticError(
                        file, line, col,
                        f"signal '{sig}' driven by multiple blocks "
                        f"({driven_by[sig]} and {block_id})"
                    )
                driven_by[sig] = block_id
        elif isinstance(stmt, CombBlock):
            block_id = "comb"
            driven = _collect_driven_signals(stmt.body)
            for sig in driven:
                if sig in driven_by:
                    loc = symbols.all_refs.get(sig, [None])[0]
                    file = loc.file if loc else "<unknown>"
                    line = loc.line if loc else 0
                    col = loc.col if loc else 0
                    raise SlipSemanticError(
                        file, line, col,
                        f"signal '{sig}' driven by multiple blocks "
                        f"({driven_by[sig]} and {block_id})"
                    )
                driven_by[sig] = block_id
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


def _collect_driven_signals(block: BlockStmt) -> set[str]:
    """Collect all signal names that are assigned in a block."""
    driven: set[str] = set()
    for stmt in block.statements:
        if isinstance(stmt, AssignStmt):
            driven.add(stmt.target.name)
        elif isinstance(stmt, IfStmt):
            driven |= _collect_driven_signals(stmt.then_body)
            if stmt.else_body:
                driven |= _collect_driven_signals(stmt.else_body)
        elif isinstance(stmt, ForStmt):
            driven |= _collect_driven_signals(stmt.body)
        elif isinstance(stmt, CaseStmt):
            for ci in stmt.items:
                driven |= _collect_driven_signals(ci.body)
    return driven
