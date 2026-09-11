from __future__ import annotations

from pathlib import Path

from slip.codegen import CodeGenerator
from slip.lexer import Lexer
from slip.parser import Parser
from slip.semantic import SemanticAnalyzer


def _resolve_includes(
    unit,
    base_dir: Path,
    seen: set[Path] | None = None,
) -> None:
    """Recursively resolve include directives, merging funcdefs and modules.

    Included files are lexed and parsed, and their funcdefs/modules are
    appended to *unit*.  Each file is merged at most once: absolute
    resolved paths are tracked in *seen*, which both deduplicates diamond
    include graphs and terminates include cycles.  Callers should seed
    *seen* with the entry file so a cycle back to it is caught too.
    """
    if seen is None:
        seen = set()

    for inc in unit.includes:
        inc_path = _resolve_include_path(inc.path, base_dir)

        if inc_path in seen:
            continue  # already merged (diamond or cycle)

        if not inc_path.exists():
            from slip.errors.semantic import SlipSemanticError
            raise SlipSemanticError(
                inc.loc.file, inc.loc.line, inc.loc.col,
                f"cannot find included file: {inc_path}"
            )

        seen.add(inc_path)
        text = inc_path.read_text(encoding="utf-8")
        tokens = Lexer(text, str(inc_path)).tokenize()
        included = Parser(tokens, str(inc_path)).parse()

        # Recurse into nested includes before merging
        _resolve_includes(included, inc_path.parent, seen)

        # Merge funcdefs and modules from included file
        unit.funcdefs.extend(included.funcdefs)
        unit.modules.extend(included.modules)

    # Clear processed includes
    unit.includes.clear()


def _resolve_include_path(path_str: str, base_dir: Path) -> Path:
    """Resolve an include path relative to *base_dir*."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()


def _frontend(source: Path):
    """Lex, parse, and resolve includes for a source file."""
    text = source.read_text(encoding="utf-8")
    filename = str(source)
    tokens = Lexer(text, filename).tokenize()
    unit = Parser(tokens, filename).parse()
    seen: set[Path] = {source.resolve()}
    _resolve_includes(unit, source.parent, seen=seen)
    return unit


def run_build(
    source: Path,
    out_dir: Path,
    ip_dirs: list[Path],
    filelists: list[Path] | None = None,
) -> dict[str, str]:
    """Full compilation pipeline: source -> SV files."""
    unit = _frontend(source)

    # Semantic analysis
    ir_modules = SemanticAnalyzer().analyze(unit, ip_dirs, filelists)

    # Generate
    return CodeGenerator().generate(ir_modules, output_dir=out_dir)


def run_check(
    source: Path,
    ip_dirs: list[Path],
    filelists: list[Path] | None = None,
) -> dict[str, str]:
    """Check pipeline: source -> full codegen validation, no output.

    Runs the same semantic analysis *and* codegen (including pyslang
    validation of the generated SystemVerilog) as run_build, so a file
    that passes `slip check` always builds.
    """
    unit = _frontend(source)

    ir_modules = SemanticAnalyzer().analyze(unit, ip_dirs, filelists)

    # Emit (and validate) every module, but write nothing to disk.
    return CodeGenerator().generate(ir_modules, output_dir=None)
