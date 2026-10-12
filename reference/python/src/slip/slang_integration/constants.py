"""SystemVerilog constant evaluation used by Slip's metaprogram controls."""

from functools import lru_cache

from pyslang import Compilation, DiagnosticEngine, SyntaxTree


def evaluate_constant(expression: str, parameters: dict[str, int | str]) -> int:
    # Declaration order and typed literal text are part of SV semantics.
    return _evaluate(expression, tuple(parameters.items()))


@lru_cache(maxsize=4096)
def _evaluate(expression: str, parameters: tuple[tuple[str, int | str], ...]) -> int:
    # Use a name outside the supplied environment for the result symbol.
    names = {name for name, _ in parameters}
    result_name = "__slip_constant"
    while result_name in names:
        result_name += "_"
    declarations = "\n".join(
        f"localparam {name} = {value};" for name, value in parameters
    )
    tree = SyntaxTree.fromText(
        f"module __slip_eval; {declarations}\n"
        f"localparam {result_name} = {expression}; endmodule"
    )
    compilation = Compilation()
    compilation.addSyntaxTree(tree)
    body = compilation.getRoot().lookupName("__slip_eval").body
    errors = [d for d in compilation.getAllDiagnostics() if d.isError()]
    if errors:
        raise ValueError(DiagnosticEngine.reportAll(compilation.sourceManager, errors))
    value = body.lookupName(result_name).value
    if value.value is None or value.hasUnknown():
        raise ValueError("constant has an unknown value (x/z or division by zero)")
    if not hasattr(value.value, "__int__"):
        raise ValueError("constant is not an integer")
    return int(value.value)
