"""Blocking-to-nonblocking correction for seq blocks.

All blocking assignments inside a ``seq`` block are converted to
nonblocking assignments (see the user manual, "Automatic
Blocking-to-Nonblocking Conversion").  This is what makes the standard
register idioms work: a shift register written as::

    seq (clk) { stage_0 = din; stage_1 = stage_0; }

becomes ``stage_0 <= din; stage_1 <= stage_0;`` — every stage samples the
pre-clock value, as intended in ``always_ff``.

One family of assignments cannot survive the conversion: those whose own
value feeds their next execution — a self-reference (``q = q + 1`` used
later in the block) or a loop-carried dependency (``for (...) { sum = sum
+ b; }``).  Under blocking semantics the second execution reads the first
one's result; under nonblocking semantics every scheduled assignment
reads the pre-clock value and only the last one takes effect.  Those
assignments are detected here and reported as warnings so the change in
meaning is never silent.
"""

import warnings

from slip.ast.expressions import (
    BinaryExpr,
    CallExpr,
    CastExpr,
    ConcatExpr,
    Expr,
    IdentExpr,
    IndexExpr,
    ParenExpr,
    ReplicationExpr,
    TernaryExpr,
    UnaryExpr,
)
from slip.ast.module import Module
from slip.semantic.indexing import (
    collect_refs,
    index_spec,
    refs_of_assign,
    specs_overlap,
)
from slip.ast.statements import (
    AssignStmt,
    BlockStmt,
    CaseItem,
    CaseStmt,
    CombBlock,
    ForStmt,
    IfStmt,
    InitialBlock,
    SeqBlock,
    Statement,
)


def correct(module: Module) -> Module:
    """Convert blocking assignments inside seq blocks to nonblocking.

    CombBlock and InitialBlock bodies are left unchanged.
    """
    new_body = tuple(_correct_top(s, module.name) for s in module.body)
    return Module(
        module.loc,
        name=module.name,
        params=module.params,
        ports=module.ports,
        body=new_body,
    )


def _correct_top(stmt: Statement, module_name: str) -> Statement:
    if isinstance(stmt, SeqBlock):
        return _correct_seq(stmt, module_name)
    return stmt


# ── Self-reference detection ───────────────────────────────────────

def _reads_prior_write(stmt: AssignStmt, written: dict[str, list]) -> bool:
    """Whether *stmt* re-reads storage it writes, after a prior write.

    A read-modify-write of overlapping storage — ``s = 0; s = s + b;``,
    or a loop accumulator whose next iteration reads this one's result —
    means something different once the assignment is nonblocking: the
    read sees the pre-clock value, not the value just written.

    Two conditions must both hold for a read R of storage S:

    * S overlaps the statement's own target storage (so this is a
      read-modify-write, not a transfer), and
    * a write to storage overlapping S already happened on this path
      (otherwise blocking and nonblocking read the same pre-clock value).

    Register transfers (``stage[1] = stage[0]``, ``t = a + 1; o = t;``)
    are *not* flagged: the statement's target does not overlap the
    storage it reads, and the documented conversion semantics — every
    read observes the pre-clock value — is exactly what those idioms
    want.
    """
    target_name = stmt.target.name
    target_spec = index_spec(stmt.target.indices)

    for name, spec in refs_of_assign(stmt):
        if name != target_name:
            continue
        # (1) read-modify-write: this statement re-reads what it writes
        if spec is None or target_spec is None:
            overlaps_target = True
        else:
            overlaps_target = specs_overlap(spec, target_spec)
        if not overlaps_target:
            continue
        # (2) and that storage was written earlier on this path
        for prior_spec in written.get(name, ()):
            if spec is None or prior_spec is None:
                return True  # non-constant indices — assume overlap
            if specs_overlap(spec, prior_spec):
                return True
    return False


def _find_self_referential(stmts: tuple[Statement, ...]) -> list[AssignStmt]:
    """Assignments whose blocking semantics the conversion would change.

    Walks the block tracking, per variable, which index specs have been
    written on the current path (exclusive branches are analysed
    separately, loops to a fixpoint so that body writes reach later
    iterations).  An assignment is reported when one of its reads
    observes a prior write to overlapping storage.
    """
    warns: list[AssignStmt] = []
    state: dict[str, list] = {}  # variable -> index specs written on this path
    _scan(stmts, state, warns)
    # The loop fixpoint re-scans bodies; keep one warning per statement.
    seen: set[int] = set()
    unique: list[AssignStmt] = []
    for w in warns:
        if id(w) not in seen:
            seen.add(id(w))
            unique.append(w)
    return unique


def _scan(stmts: tuple[Statement, ...], state: dict[str, list], warns: list[AssignStmt]):
    for stmt in stmts:
        if isinstance(stmt, AssignStmt):
            if _reads_prior_write(stmt, state):
                warns.append(stmt)
            spec = index_spec(stmt.target.indices)
            state.setdefault(stmt.target.name, []).append(spec)
        elif isinstance(stmt, IfStmt):
            then_state = {k: list(v) for k, v in state.items()}
            _scan(stmt.then_body.statements, then_state, warns)
            merge_states = [then_state]
            if stmt.else_body:
                else_state = {k: list(v) for k, v in state.items()}
                _scan(stmt.else_body.statements, else_state, warns)
                merge_states.append(else_state)
            # A write in any branch may be observed after the if.
            for var in set().union(*(set(s) for s in merge_states)):
                specs: list = []
                for s in merge_states:
                    specs.extend(s.get(var, ()))
                state[var] = specs
        elif isinstance(stmt, ForStmt):
            # The body may run more than once, so writes inside it reach
            # reads in later iterations: iterate to a fixpoint.
            for _ in range(len(stmt.body.statements) + 1):
                before = {k: list(v) for k, v in state.items()}
                _scan(stmt.body.statements, state, warns)
                if state == before:
                    break
        elif isinstance(stmt, CaseStmt):
            branch_states = []
            for ci in stmt.items:
                bs = {k: list(v) for k, v in state.items()}
                _scan(ci.body.statements, bs, warns)
                branch_states.append(bs)
            merged_vars: set[str] = set()
            for bs in branch_states:
                merged_vars |= set(bs)
            for var in merged_vars:
                specs = []
                for bs in branch_states:
                    specs.extend(bs.get(var, ()))
                state[var] = specs
        elif isinstance(stmt, (SeqBlock, CombBlock, InitialBlock)):
            _scan(stmt.body.statements, state, warns)


# ── Rewriting ──────────────────────────────────────────────────────

def _correct_seq(stmt: SeqBlock, module_name: str = "") -> SeqBlock:
    self_ref = [
        a for a in _find_self_referential(stmt.body.statements)
        if not a.is_nonblocking
    ]
    if self_ref:
        names = sorted({a.target.name for a in self_ref})
        joined = ", ".join(f"'{n}'" for n in names)
        loc = self_ref[0].loc
        warnings.warn(
            f"{loc.file}:{loc.line}:{loc.col}: in seq block of module "
            f"'{module_name}', the blocking assignment to {joined} reads its "
            f"own previous value; after conversion to non-blocking the read "
            f"observes the pre-clock value instead of the updated one "
            f"(standard always_ff semantics). If the intent was to observe "
            f"the updated value, restructure or use a comb block.",
            stacklevel=2,
        )

    new_body = _rewrite_block(stmt.body)
    return SeqBlock(stmt.loc, clock=stmt.clock, reset=stmt.reset, body=new_body)


def _rewrite_block(block: BlockStmt) -> BlockStmt:
    new_stmts = tuple(_rewrite_stmt(s) for s in block.statements)
    return BlockStmt(block.loc, statements=new_stmts)


def _rewrite_stmt(stmt: Statement) -> Statement:
    if isinstance(stmt, AssignStmt):
        if stmt.is_nonblocking:
            return stmt
        return AssignStmt(
            stmt.loc, target=stmt.target, value=stmt.value, is_nonblocking=True
        )
    if isinstance(stmt, IfStmt):
        new_then = _rewrite_block(stmt.then_body)
        new_else = _rewrite_block(stmt.else_body) if stmt.else_body else None
        return IfStmt(stmt.loc, cond=stmt.cond, then_body=new_then, else_body=new_else)
    if isinstance(stmt, ForStmt):
        new_body = _rewrite_block(stmt.body)
        return ForStmt(
            stmt.loc, var=stmt.var, init=stmt.init,
            cond=stmt.cond, step_var=stmt.step_var, step=stmt.step, body=new_body,
        )
    if isinstance(stmt, CaseStmt):
        new_items = tuple(
            CaseItem(ci.loc, patterns=ci.patterns, body=_rewrite_block(ci.body))
            for ci in stmt.items
        )
        return CaseStmt(stmt.loc, kind=stmt.kind, expr=stmt.expr, items=new_items)
    return stmt
