"""Width mismatch detection for assignments and instance connections.

Collects concrete widths from signal/port declarations and checks for
width mismatches. Only reports when both sides have evaluable integer
widths — parameterized widths (e.g. [W-1:0]) are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from slip.ast.expressions import BinaryExpr, Expr, IdentExpr, IndexExpr, IntLiteralExpr
from slip.ast.instance import InstanceStmt
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
from slip.errors.semantic import SlipSemanticError
from slip.semantic.gen_expand import _eval_int
from slip.ast.base import SourceLocation


@dataclass
class WidthWarning:
    file: str
    line: int
    col: int
    message: str


def _try_eval_width(expr: Expr, params: dict[str, int]) -> int | None:
    """Try to evaluate a width expression to a concrete integer.

    Returns None if the expression is parameterized or cannot be evaluated.
    """
    try:
        return _eval_int(expr, params, SourceLocation("", 0, 0))
    except (SlipSemanticError, ValueError, ZeroDivisionError):
        return None


def _extract_width_from_expr(width_expr: Expr, params: dict[str, int]) -> int | None:
    """Extract concrete bit width from a width expression.

    Handles:
    - BinaryExpr(":", high, low) → high - low + 1
    - Single expression → that value (interpreted as total bits)
    """
    if isinstance(width_expr, BinaryExpr) and width_expr.op == ":":
        high = _try_eval_width(width_expr.left, params)
        low = _try_eval_width(width_expr.right, params)
        if high is not None and low is not None:
            return high - low + 1
        return None
    return _try_eval_width(width_expr, params)


def _int_literal_bit_width(raw: str) -> int:
    """Determine the bit width of a sized integer literal.

    Sized: 8'hFF → 8, 4'b1010 → 4
    Unsized: 42 → 32 (SV default)
    """
    import re
    m = re.match(r"(\d+)'", raw)
    if m:
        return int(m.group(1))
    return 32  # unsized literal default in SV


def _expr_bit_width(expr: Expr, registry: dict[str, int]) -> int | None:
    """Estimate the bit width of an expression.

    Returns None if width cannot be determined.
    """
    if isinstance(expr, IntLiteralExpr):
        return _int_literal_bit_width(expr.raw)
    if isinstance(expr, IdentExpr):
        return registry.get(expr.name)
    if isinstance(expr, IndexExpr):
        if expr.is_slice:
            # Bit-select range: [high:low] → high - low + 1
            # But we can't easily evaluate; skip
            return None
        # Single bit select → 1 bit
        return 1
    # For binary/unary/ternary/etc, width is hard to determine
    return None


def _build_registry(module: Module, params: dict[str, int]) -> dict[str, int]:
    """Build a mapping of signal/port names to their concrete widths."""
    registry: dict[str, int] = {}

    # Ports
    for p in module.ports:
        if p.width:
            w = _extract_width_from_expr(p.width, params)
            if w is not None:
                registry[p.name] = w

    # Signals in body
    for stmt in module.body:
        if isinstance(stmt, SignalDecl) and stmt.width:
            w = _extract_width_from_expr(stmt.width, params)
            if w is not None:
                registry[stmt.name] = w

    return registry


def _check_assign(
    stmt: AssignStmt,
    registry: dict[str, int],
    warnings: list[WidthWarning],
):
    """Check width mismatch in an assignment."""
    target_name = stmt.target.name
    target_width = registry.get(target_name)
    if target_width is None:
        return

    value_width = _expr_bit_width(stmt.value, registry)
    if value_width is None:
        return

    if target_width != value_width:
        warnings.append(WidthWarning(
            stmt.loc.file, stmt.loc.line, stmt.loc.col,
            f"width mismatch: '{target_name}' is {target_width} bits, "
            f"but value is {value_width} bits"
        ))


def _check_instance(
    stmt: InstanceStmt,
    module_index: dict[str, Module],
    registry: dict[str, int],
    warnings: list[WidthWarning],
):
    """Check width mismatch in instance port connections."""
    target_mod = module_index.get(stmt.module_name)
    if target_mod is None:
        return  # external module, skip

    # Build target port width registry
    target_params: dict[str, int] = {}
    for p in target_mod.params:
        w = _try_eval_width(p.default, target_params)
        if w is not None:
            target_params[p.name] = w
    target_registry = _build_registry(target_mod, target_params)

    for conn in stmt.connections:
        if conn.port is None or conn.signal is None:
            continue
        port_width = target_registry.get(conn.port)
        if port_width is None:
            continue
        signal_width = _expr_bit_width(conn.signal, registry)
        if signal_width is None:
            continue
        if port_width != signal_width:
            warnings.append(WidthWarning(
                stmt.loc.file, stmt.loc.line, stmt.loc.col,
                f"port width mismatch: '{conn.port}' expects {port_width} bits, "
                f"but '{conn.signal}' is {signal_width} bits"
            ))


def _walk_stmt_widths(
    stmt: Statement,
    registry: dict[str, int],
    module_index: dict[str, Module],
    warnings: list[WidthWarning],
):
    """Recursively walk statements checking widths."""
    if isinstance(stmt, AssignStmt):
        _check_assign(stmt, registry, warnings)
    elif isinstance(stmt, InstanceStmt):
        _check_instance(stmt, module_index, registry, warnings)
    elif isinstance(stmt, SeqBlock):
        for s in stmt.body.statements:
            _walk_stmt_widths(s, registry, module_index, warnings)
    elif isinstance(stmt, CombBlock):
        for s in stmt.body.statements:
            _walk_stmt_widths(s, registry, module_index, warnings)
    elif isinstance(stmt, InitialBlock):
        for s in stmt.body.statements:
            _walk_stmt_widths(s, registry, module_index, warnings)
    elif isinstance(stmt, IfStmt):
        for s in stmt.then_body.statements:
            _walk_stmt_widths(s, registry, module_index, warnings)
        if stmt.else_body:
            for s in stmt.else_body.statements:
                _walk_stmt_widths(s, registry, module_index, warnings)
    elif isinstance(stmt, ForStmt):
        for s in stmt.body.statements:
            _walk_stmt_widths(s, registry, module_index, warnings)
    elif isinstance(stmt, CaseStmt):
        for ci in stmt.items:
            for s in ci.body.statements:
                _walk_stmt_widths(s, registry, module_index, warnings)


def check_width_mismatches(
    module: Module,
    module_index: dict[str, Module] | None = None,
) -> list[WidthWarning]:
    """Check for width mismatches in assignments and instance connections.

    Returns a list of warnings. Only reports when both sides have concrete
    integer widths — parameterized widths are skipped.
    """
    params: dict[str, int] = {}
    for p in module.params:
        w = _try_eval_width(p.default, params)
        if w is not None:
            params[p.name] = w

    registry = _build_registry(module, params)
    warnings: list[WidthWarning] = []

    for stmt in module.body:
        _walk_stmt_widths(stmt, registry, module_index or {}, warnings)

    return warnings
