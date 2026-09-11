"""Compile-time evaluator for defun function bodies.

Function bodies are Python expressions evaluated with ``eval`` in a
sandboxed environment: no builtins are exposed beyond an explicit
allowlist matching the documented feature set, method calls are
restricted to a safe string-method allowlist, and free function calls
must be either built-in helpers or previously registered defun/regex
functions.  Compiling an untrusted .slip file therefore cannot reach
the interpreter, the filesystem, or module imports.
"""

from __future__ import annotations

from typing import Any

from slip.ast.expressions import (
    BinaryExpr,
    CallExpr,
    Expr,
    IdentExpr,
    IndexExpr,
    IntLiteralExpr,
    MethodCallExpr,
    ParenExpr,
    StringLiteralExpr,
    TernaryExpr,
    UnaryExpr,
)
from slip.ast.statements import FuncDef, ReturnStmt, Statement
from slip.errors.semantic import SlipSemanticError
from slip.semantic.regex_funcs import REGISTRY, register

# Builtins exposed to defun bodies. Everything else (open, eval, exec,
# __import__, getattr, ...) is unavailable.
_SAFE_BUILTINS: dict[str, Any] = {
    "len": len,
    "int": int,
    "str": str,
    "min": min,
    "max": max,
    "abs": abs,
}

# String methods callable on defun arguments/results.
_SAFE_METHODS = frozenset({
    "upper", "lower", "reverse", "replace", "strip", "lstrip", "rstrip",
    "split", "rsplit", "splitlines", "startswith", "endswith",
    "find", "rfind", "index", "count", "join", "zfill", "rjust", "ljust",
    "title", "capitalize", "swapcase", "casefold",
    "isdigit", "isalpha", "isalnum", "isnumeric", "islower", "isupper",
    "removeprefix", "removesuffix",
})


class SlipStr(str):
    """Custom string class that supports additional methods and operators."""

    def __add__(self, other):
        # Support string + int concatenation
        return SlipStr(str(self) + str(other))

    def __radd__(self, other):
        # Support int + string concatenation
        return SlipStr(str(other) + str(self))

    def upper(self):
        return SlipStr(super().upper())

    def lower(self):
        return SlipStr(super().lower())

    def reverse(self):
        """Reverse the string."""
        return SlipStr(self[::-1])


def register_funcdef(funcdef: FuncDef) -> None:
    """Evaluate a FuncDef and register the resulting callable in REGISTRY."""
    param_names = funcdef.params
    body = funcdef.body

    # Extract the return expression and convert to Python code
    return_expr = _extract_return_expr(body, funcdef.loc)
    py_code = _expr_to_python(return_expr)

    # Create the function using eval
    def _func(*args: str) -> str:
        if len(args) != len(param_names):
            raise ValueError(
                f"{funcdef.name}() takes {len(param_names)} arguments, got {len(args)}"
            )
        # Convert arguments: wrap strings in SlipStr, try int conversion
        converted_args = [_convert_arg(a) for a in args]
        env: dict[str, Any] = dict(zip(param_names, converted_args))
        # Sandboxed globals: empty __builtins__ plus the explicit allowlist.
        sandbox_globals: dict[str, Any] = {"__builtins__": {}}
        sandbox_globals.update(_SAFE_BUILTINS)
        sandbox_globals["SlipStr"] = SlipStr
        try:
            result = eval(py_code, sandbox_globals, env)
            return str(result)
        except Exception as e:
            raise SlipSemanticError(
                funcdef.loc.file, funcdef.loc.line, funcdef.loc.col,
                f"error in {funcdef.name}(): {e}"
            ) from e

    register(funcdef.name, _func)


def _convert_arg(val: str) -> Any:
    """Convert a string argument: try int, otherwise wrap in SlipStr."""
    try:
        return int(val)
    except ValueError:
        return SlipStr(val)


def _extract_return_expr(stmts: tuple[Statement, ...], loc) -> Expr:
    """Extract the return expression from function body."""
    for stmt in stmts:
        if isinstance(stmt, ReturnStmt):
            return stmt.value
    raise SlipSemanticError(loc.file, loc.line, loc.col, "function has no return statement")


def _expr_to_python(expr: Expr) -> str:
    """Convert an AST expression to a Python expression string."""
    if isinstance(expr, StringLiteralExpr):
        # Wrap string literals in SlipStr for custom operators
        return f"SlipStr({expr.value})"

    if isinstance(expr, IntLiteralExpr):
        return expr.raw

    if isinstance(expr, IdentExpr):
        return expr.name

    if isinstance(expr, ParenExpr):
        return f"({_expr_to_python(expr.inner)})"

    if isinstance(expr, UnaryExpr):
        return f"{expr.op}{_expr_to_python(expr.operand)}"

    if isinstance(expr, BinaryExpr):
        left = _expr_to_python(expr.left)
        right = _expr_to_python(expr.right)
        # Use // for integer division
        op = "//" if expr.op == "/" else expr.op
        return f"({left} {op} {right})"

    if isinstance(expr, TernaryExpr):
        cond = _expr_to_python(expr.cond)
        true_expr = _expr_to_python(expr.true_expr)
        false_expr = _expr_to_python(expr.false_expr)
        return f"({true_expr} if {cond} else {false_expr})"

    if isinstance(expr, MethodCallExpr):
        if expr.method not in _SAFE_METHODS:
            raise SlipSemanticError(
                expr.loc.file, expr.loc.line, expr.loc.col,
                f"method '.{expr.method}()' is not allowed in defun bodies "
                f"(allowed: {', '.join(sorted(_SAFE_METHODS))})"
            )
        obj = _expr_to_python(expr.obj)
        args = ", ".join(_expr_to_python(a) for a in expr.args)
        return f"({obj}.{expr.method}({args}))"

    if isinstance(expr, CallExpr):
        if expr.func not in _SAFE_BUILTINS and expr.func not in REGISTRY:
            raise SlipSemanticError(
                expr.loc.file, expr.loc.line, expr.loc.col,
                f"function '{expr.func}()' is not defined; defun bodies may "
                f"call built-in helpers (len, int, str, min, max, abs) or "
                f"registered defun/regex functions"
            )
        args = ", ".join(_expr_to_python(a) for a in expr.args)
        return f"{expr.func}({args})"

    if isinstance(expr, IndexExpr):
        base = _expr_to_python(expr.base)
        if expr.is_slice:
            # Slice: [start:end]
            start = _expr_to_python(expr.index) if expr.index is not None else ""
            end = _expr_to_python(expr.high) if expr.high is not None else ""
            return f"({base}[{start}:{end}])"
        else:
            # Single index
            index = _expr_to_python(expr.index)
            return f"({base}[{index}])"

    raise SlipSemanticError(
        "", 0, 0,
        f"unsupported expression type: {type(expr).__name__}"
    )
