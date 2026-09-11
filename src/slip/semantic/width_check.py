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
from slip.semantic.expr_serializer import expr_to_sv
from slip.semantic.gen_expand import _eval_int, _parse_int_literal
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


def _int_literal_bit_width(raw: str) -> int | None:
    """Determine the bit width of a sized integer literal.

    Sized: 8'hFF → 8, 4'b1010 → 4.
    Unsized literals return None — their width in SV is context-dependent
    (at least 32 bits), so a plain equality check would misfire on the
    common ``y = 0;`` idiom.  Unsized values are range-checked instead
    (see _check_assign).
    """
    import re
    m = re.match(r"(\d+)'", raw)
    if m:
        return int(m.group(1))
    return None  # unsized literal


def _unsized_literal_value(raw: str) -> int | None:
    """Return the value of a plain (unsized, decimal) literal, or None."""
    import re
    if re.fullmatch(r"-?[0-9][0-9_]*", raw):
        try:
            return _parse_int_literal(raw)
        except ValueError:
            return None
    return None


def _expr_bit_width(
    expr: Expr,
    registry: dict[str, int],
    params: dict[str, int],
    arrays: set[str] | None = None,
) -> int | None:
    """Estimate the bit width of an expression.

    Returns None if width cannot be determined.
    """
    arrays = arrays or set()
    if isinstance(expr, IntLiteralExpr):
        return _int_literal_bit_width(expr.raw)
    if isinstance(expr, IdentExpr):
        return registry.get(expr.name)
    if isinstance(expr, IndexExpr):
        if expr.is_slice:
            high = _try_eval_width(expr.index, params) if expr.index is not None else None
            low = _try_eval_width(expr.high, params) if expr.high is not None else None
            if high is not None and low is not None:
                return abs(high - low) + 1
            return None
        # Indexing an unpacked array selects a whole element (declared
        # width); indexing a vector selects a single bit.
        if isinstance(expr.base, IdentExpr) and expr.base.name in arrays:
            return registry.get(expr.base.name)
        return 1
    # For binary/unary/ternary/etc, width is hard to determine
    return None


def _target_select_width(
    stmt: AssignStmt,
    params: dict[str, int],
    arrays: set[str] | None = None,
) -> int | None:
    """Width of the selected part of the assignment target.

    No indices → None (caller uses the full signal width).
    Unpacked-array element → None (the element is the full declared width).
    Single index on a vector → 1 bit; constant range [hi:lo] → |hi - lo| + 1;
    non-constant ranges → None (skip check).
    """
    arrays = arrays or set()
    if not stmt.target.indices:
        return None
    if stmt.target.name in arrays:
        return None  # element select: full declared width applies
    idx = stmt.target.indices[-1]
    if isinstance(idx, tuple):
        high = _try_eval_width(idx[0], params)
        low = _try_eval_width(idx[1], params)
        if high is None or low is None:
            return None
        return abs(high - low) + 1
    return 1


def _build_registry(
    module: Module,
    params: dict[str, int],
    arrays: set[str] | None = None,
) -> dict[str, int]:
    """Build a mapping of signal/port names to their concrete widths.

    *arrays* is populated with names declared as unpacked arrays, whose
    element select yields the declared width rather than one bit.
    """
    from slip.semantic.symbol_collector import iter_signal_decls

    registry: dict[str, int] = {}

    # Ports
    for p in module.ports:
        if p.width:
            w = _extract_width_from_expr(p.width, params)
            if w is not None:
                registry[p.name] = w

    # Signals in body (including block-nested declarations)
    for decl in iter_signal_decls(module.body):
        if decl.width:
            w = _extract_width_from_expr(decl.width, params)
            if w is not None:
                registry[decl.name] = w
        if decl.array_range is not None and arrays is not None:
            arrays.add(decl.name)

    return registry


def _check_assign(
    stmt: AssignStmt,
    registry: dict[str, int],
    params: dict[str, int],
    warnings: list[WidthWarning],
    arrays: set[str] | None = None,
):
    """Check width mismatch in an assignment."""
    arrays = arrays or set()
    target_name = stmt.target.name
    target_width = registry.get(target_name)
    if target_width is None:
        return

    # A bit- or part-select target constrains only the selected bits
    select_width = _target_select_width(stmt, params, arrays)
    if select_width is not None:
        target_width = select_width

    # Unsized plain literals are width-context-dependent in SV; check
    # that the value fits the target instead of assuming 32 bits.
    if isinstance(stmt.value, IntLiteralExpr):
        value = _unsized_literal_value(stmt.value.raw)
        if value is not None:
            if value < 0 or value >= (1 << target_width):
                warnings.append(WidthWarning(
                    stmt.loc.file, stmt.loc.line, stmt.loc.col,
                    f"value {value} does not fit in '{target_name}' "
                    f"({target_width} bits)"
                ))
            return

    value_width = _expr_bit_width(stmt.value, registry, params, arrays)
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
    params: dict[str, int],
    warnings: list[WidthWarning],
    arrays: set[str] | None = None,
):
    """Check width mismatch in instance port connections."""
    target_mod = module_index.get(stmt.module_name)
    if target_mod is None:
        return  # external module, skip
    arrays = arrays or set()

    # Build target port width registry from default parameter values,
    # then apply this instance's parameter overrides on top.
    target_params: dict[str, int] = {}
    for p in target_mod.params:
        w = _try_eval_width(p.default, target_params)
        if w is not None:
            target_params[p.name] = w
    for np in stmt.params:
        w = _try_eval_width(np.value, target_params)
        if w is not None:
            target_params[np.name] = w
    target_registry = _build_registry(target_mod, target_params)

    for conn in stmt.connections:
        if conn.port is None or conn.signal is None:
            continue
        port_width = target_registry.get(conn.port)
        if port_width is None:
            continue
        signal_width = _expr_bit_width(conn.signal, registry, params, arrays)
        if signal_width is None:
            continue
        if port_width != signal_width:
            warnings.append(WidthWarning(
                stmt.loc.file, stmt.loc.line, stmt.loc.col,
                f"port width mismatch: '{conn.port}' expects {port_width} bits, "
                f"but '{expr_to_sv(conn.signal)}' is {signal_width} bits"
            ))


def _walk_stmt_widths(
    stmt: Statement,
    registry: dict[str, int],
    params: dict[str, int],
    module_index: dict[str, Module],
    warnings: list[WidthWarning],
    arrays: set[str] | None = None,
):
    """Recursively walk statements checking widths."""
    if isinstance(stmt, AssignStmt):
        _check_assign(stmt, registry, params, warnings, arrays)
    elif isinstance(stmt, InstanceStmt):
        _check_instance(stmt, module_index, registry, params, warnings, arrays)
    elif isinstance(stmt, SeqBlock):
        for s in stmt.body.statements:
            _walk_stmt_widths(s, registry, params, module_index, warnings, arrays)
    elif isinstance(stmt, CombBlock):
        for s in stmt.body.statements:
            _walk_stmt_widths(s, registry, params, module_index, warnings, arrays)
    elif isinstance(stmt, InitialBlock):
        for s in stmt.body.statements:
            _walk_stmt_widths(s, registry, params, module_index, warnings, arrays)
    elif isinstance(stmt, IfStmt):
        for s in stmt.then_body.statements:
            _walk_stmt_widths(s, registry, params, module_index, warnings, arrays)
        if stmt.else_body:
            for s in stmt.else_body.statements:
                _walk_stmt_widths(s, registry, params, module_index, warnings, arrays)
    elif isinstance(stmt, ForStmt):
        for s in stmt.body.statements:
            _walk_stmt_widths(s, registry, params, module_index, warnings, arrays)
    elif isinstance(stmt, CaseStmt):
        for ci in stmt.items:
            for s in ci.body.statements:
                _walk_stmt_widths(s, registry, params, module_index, warnings, arrays)


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

    arrays: set[str] = set()
    registry = _build_registry(module, params, arrays)
    warnings: list[WidthWarning] = []

    for stmt in module.body:
        _walk_stmt_widths(stmt, registry, params, module_index or {}, warnings, arrays)

    return warnings
