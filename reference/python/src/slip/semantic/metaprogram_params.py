"""Track parameters whose defaults determine Slip's expanded structure."""

from dataclasses import fields, is_dataclass

from slip.ast.expressions import IdentExpr, TickIdentExpr
from slip.ast.metaprogram import GenForStmt, GenIfStmt
from slip.semantic.expr_serializer import expr_to_sv
from slip.semantic.symbol_collector import iter_localparam_decls
from slip.slang_integration.constants import evaluate_constant


def _walk(node):
    yield node
    if is_dataclass(node):
        for field in fields(node):
            if field.name != "loc":
                yield from _walk(getattr(node, field.name))
    elif isinstance(node, (tuple, list)):
        for item in node:
            yield from _walk(item)


def frozen_parameters(module) -> tuple[tuple[str, int], ...]:
    dependencies = set()
    for node in _walk(module.body):
        controls = ()
        if isinstance(node, GenIfStmt):
            controls = (node.cond,)
        elif isinstance(node, GenForStmt):
            controls = (node.init, node.cond, node.step)
        for expr in controls:
            dependencies.update(
                n.name for n in _walk(expr) if isinstance(n, (IdentExpr, TickIdentExpr))
            )
    declarations = {p.name: p.default for p in module.params}
    declarations.update({p.name: p.value for p in iter_localparam_decls(module.body)})
    pending = list(dependencies)
    while pending:
        name = pending.pop()
        if name in declarations:
            for node in _walk(declarations[name]):
                if isinstance(node, IdentExpr) and node.name not in dependencies:
                    dependencies.add(node.name)
                    pending.append(node.name)
    values = {}
    result = []
    for param in module.params:
        value = evaluate_constant(expr_to_sv(param.default), values)
        values[param.name] = expr_to_sv(param.default)
        if param.name in dependencies:
            result.append((param.name, value))
    return tuple(result)
