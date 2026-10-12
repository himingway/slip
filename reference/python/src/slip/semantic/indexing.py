"""Index-spec analysis shared by the seq-correction and loop detectors.

Both need to distinguish "the same variable" from "the same storage":
``st[1] = st[0]`` is a shift between disjoint array elements (no loop, no
read-modify-write), while ``x[3:0] = x[2:0]`` (overlapping part-selects of
one vector) is a genuine feedback path.

An *index spec* is a tuple of (low, high) pairs, one per index, or None
when any index is not a constant.  A whole variable is the empty tuple;
None is treated conservatively as "overlaps everything".
"""

from __future__ import annotations

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
    TernaryExpr,
    UnaryExpr,
)

_UNKNOWN = object()

#: Index spec of something whose indices are not constant / not known.
UNKNOWN_SPEC = None


def _const_index(expr: Expr):
    if isinstance(expr, IntLiteralExpr):
        raw = expr.raw
        body = raw[1:] if raw.startswith("-") else raw
        if body.isdigit():
            return int(raw)
    return _UNKNOWN


def index_spec(indices) -> tuple | None:
    """Constant index spec of an lvalue, or None when not constant.

    A whole variable has spec ``()``; ``x[3]`` has ``((3, 3),)``;
    a range ``x[3:0]`` has ``((0, 3),)``.
    """
    spec = []
    for idx in indices:
        if isinstance(idx, tuple):
            hi = _const_index(idx[0])
            lo = _const_index(idx[1])
            if hi is _UNKNOWN or lo is _UNKNOWN:
                return None
            spec.append((min(hi, lo), max(hi, lo)))
        else:
            v = _const_index(idx)
            if v is _UNKNOWN:
                return None
            spec.append((v, v))
    return tuple(spec)


def specs_overlap(a: tuple | None, b: tuple | None) -> bool:
    """Whether two index specs address overlapping storage."""
    if a is None or b is None:
        return True  # unknown/whole overlaps anything
    if len(a) != len(b):
        return True  # e.g. x vs x[3]: one covers the other
    return all(a[i][0] <= b[i][1] and b[i][0] <= a[i][1] for i in range(len(a)))


def collect_refs(expr: Expr, refs: list[tuple[str, tuple | None]]):
    """Collect (base name, index spec) for every identifier reference."""
    if isinstance(expr, IdentExpr):
        refs.append((expr.name, ()))
        return
    if isinstance(expr, IndexExpr):
        spec = index_spec([(expr.index, expr.high)] if expr.is_slice else [expr.index])
        if isinstance(expr.base, IdentExpr):
            refs.append((expr.base.name, spec))
        else:
            collect_refs(expr.base, refs)
        if expr.index is not None:
            collect_refs(expr.index, refs)
        if expr.high is not None:
            collect_refs(expr.high, refs)
        return
    if isinstance(expr, BinaryExpr):
        collect_refs(expr.left, refs)
        collect_refs(expr.right, refs)
        return
    if isinstance(expr, UnaryExpr):
        collect_refs(expr.operand, refs)
        return
    if isinstance(expr, TernaryExpr):
        collect_refs(expr.cond, refs)
        collect_refs(expr.true_expr, refs)
        collect_refs(expr.false_expr, refs)
        return
    if isinstance(expr, ConcatExpr):
        for p in expr.parts:
            collect_refs(p, refs)
        return
    if isinstance(expr, ReplicationExpr):
        collect_refs(expr.count, refs)
        collect_refs(expr.inner, refs)
        return
    if isinstance(expr, CastExpr):
        collect_refs(expr.inner, refs)
        return
    if isinstance(expr, CallExpr):
        for a in expr.args:
            collect_refs(a, refs)
        return
    if isinstance(expr, ParenExpr):
        collect_refs(expr.inner, refs)
        return


def refs_of_assign(stmt) -> list[tuple[str, tuple | None]]:
    """Every reference (name, spec) read by an assignment."""
    refs: list[tuple[str, tuple | None]] = []
    collect_refs(stmt.value, refs)
    for idx in stmt.target.indices:
        if isinstance(idx, tuple):
            collect_refs(idx[0], refs)
            collect_refs(idx[1], refs)
        elif idx is not None:
            collect_refs(idx, refs)
    return [(n, s) for n, s in refs if n != "_"]
