from slip.ast.expressions import Expr
from slip.ast.module import Module
from slip.ast.statements import (
    AssignStmt,
    BlockStmt,
    CombBlock,
    ForStmt,
    IfStmt,
    SeqBlock,
    Statement,
)
from slip.ast.base import SourceLocation


def correct(module: Module) -> Module:
    """Correct all blocking assignments inside seq blocks to nonblocking.

    CombBlock bodies are left unchanged (blocking stays blocking).
    """
    new_body = tuple(_correct_stmt(s) for s in module.body)
    return Module(
        module.loc,
        name=module.name,
        params=module.params,
        ports=module.ports,
        body=new_body,
    )


def _correct_stmt(stmt: Statement) -> Statement:
    if isinstance(stmt, SeqBlock):
        new_body = _correct_block(stmt.body)
        return SeqBlock(stmt.loc, clock=stmt.clock, reset=stmt.reset, body=new_body)
    if isinstance(stmt, CombBlock):
        return stmt  # no correction for combinational blocks
    if isinstance(stmt, IfStmt):
        new_then = _correct_block(stmt.then_body)
        new_else = _correct_block(stmt.else_body) if stmt.else_body else None
        return IfStmt(stmt.loc, cond=stmt.cond, then_body=new_then, else_body=new_else)
    if isinstance(stmt, ForStmt):
        new_body = _correct_block(stmt.body)
        return ForStmt(
            stmt.loc, var=stmt.var, init=stmt.init,
            cond=stmt.cond, step_var=stmt.step_var, step=stmt.step, body=new_body,
        )
    return stmt


def _correct_block(block: BlockStmt) -> BlockStmt:
    new_stmts = tuple(_correct_assign_in_stmt(s) for s in block.statements)
    return BlockStmt(block.loc, statements=new_stmts)


def _correct_assign_in_stmt(stmt: Statement) -> Statement:
    if isinstance(stmt, AssignStmt) and not stmt.is_nonblocking:
        return AssignStmt(
            stmt.loc, target=stmt.target, value=stmt.value, is_nonblocking=True
        )
    if isinstance(stmt, IfStmt):
        new_then = _correct_block(stmt.then_body)
        new_else = _correct_block(stmt.else_body) if stmt.else_body else None
        return IfStmt(stmt.loc, cond=stmt.cond, then_body=new_then, else_body=new_else)
    if isinstance(stmt, ForStmt):
        new_body = _correct_block(stmt.body)
        return ForStmt(
            stmt.loc, var=stmt.var, init=stmt.init,
            cond=stmt.cond, step_var=stmt.step_var, step=stmt.step, body=new_body,
        )
    return stmt
