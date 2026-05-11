from __future__ import annotations

import re

from slip.ast.expressions import Expr, IdentExpr, IntLiteralExpr
from slip.ast.instance import InstanceStmt
from slip.ast.metaprogram import GenForStmt, GenIfStmt
from slip.ast.module import Module, Param, PortItem
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
from slip.errors.semantic import SlipSemanticError
from slip.ir import (
    HDLAssignment,
    HDLInstance,
    HDLModule,
    HDLParam,
    HDLPort,
    HDLSignal,
    HDLType,
    LogicBlock,
)
from slip.semantic.driver_analysis import DriverInfo, infer_port_directions
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
        for name in symbols.ports
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
    for name in symbols.all_refs:
        if name == "_":
            continue
        if name in declared_signals or name in symbols.params or name in symbols.localparams or name in symbols.instances:
            continue
        if explicit_ports and name in symbols.ports:
            continue
        if not explicit_ports and name in directions:
            continue
        if name.startswith("$"):
            continue  # system functions
        signals.append(HDLSignal(name, HDLType()))

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
        elif isinstance(stmt, InstanceStmt):
            _process_instance(stmt, instances)
        elif isinstance(stmt, (GenForStmt, GenIfStmt)):
            pass  # Phase 2

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
    return items


def _convert_if(stmt: IfStmt) -> object:
    from slip.ir.logic_block import HDLIfBlock
    cond_sv = expr_to_sv(stmt.cond)
    then_items = tuple(_convert_block(stmt.then_body))
    else_items = tuple(_convert_block(stmt.else_body)) if stmt.else_body else None
    return HDLIfBlock(cond_sv, then_items, else_items)


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
