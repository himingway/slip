"""VCS-format filelist parser.

Supports the Synopsys VCS filelist format:
    // line comments
    /​* block comments */
    +incdir+/path/to/includes
    +define+MACRO=value
    +define+MACRO
    /path/to/file1.sv
    -f another_filelist.f
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FilelistData:
    """Parsed filelist data."""
    files: tuple[Path, ...]      # source files in order
    incdirs: tuple[Path, ...]    # include search directories
    defines: tuple[str, ...]     # macro definitions ("MACRO=value" or "MACRO")


def parse_filelist(filelist_path: Path) -> FilelistData:
    """Parse a VCS-format filelist, recursively handling -f references.

    Diamond references are allowed: a sub-filelist shared by two sibling
    filelists is parsed twice harmlessly (source files are deduplicated).
    Only a filelist that directly includes one of its own ancestors is a
    cycle.

    Args:
        filelist_path: Path to the .f file.

    Returns:
        FilelistData with files, incdirs, and defines.

    Raises:
        FileNotFoundError: If filelist or referenced file doesn't exist.
        ValueError: On circular -f references.
    """
    files: list[Path] = []
    incdirs: list[Path] = []
    defines: list[str] = []

    _parse_file(filelist_path, files, incdirs, defines, chain=())

    return FilelistData(
        files=tuple(files),
        incdirs=tuple(incdirs),
        defines=tuple(defines),
    )


def _parse_file(
    filelist_path: Path,
    files: list[Path],
    incdirs: list[Path],
    defines: list[str],
    chain: tuple[Path, ...],
) -> None:
    """Recursively parse a single filelist file.

    *chain* holds the ancestor filelist paths (absolute), so a ``-f``
    reference back to any ancestor is detected as a cycle while shared
    (diamond) sub-filelists remain legal.
    """
    resolved = filelist_path.resolve()
    if resolved in chain:
        chain_str = " -> ".join(str(p) for p in (*chain, resolved))
        raise ValueError(f"circular filelist reference: {chain_str}")

    if not filelist_path.exists():
        raise FileNotFoundError(f"filelist not found: {filelist_path}")

    base_dir = filelist_path.parent
    text = filelist_path.read_text(encoding="utf-8")

    for line in _strip_comments(text).splitlines():
        line = line.strip()

        if not line:
            continue

        # +incdir+path[,+path2...]  (multiple paths separated by +)
        if line.startswith("+incdir+"):
            path_str = line[len("+incdir+"):]
            for p in path_str.split("+"):
                p = p.strip()
                if p:
                    incdir = _resolve_path(p, base_dir)
                    if incdir not in incdirs:
                        incdirs.append(incdir)
            continue

        # +define+MACRO=value or +define+MACRO — VCS separates multiple
        # defines on one line with '+'
        if line.startswith("+define+"):
            rest = line[len("+define+"):]
            for macro in rest.split("+"):
                macro = macro.strip()
                if macro and macro not in defines:
                    defines.append(macro)
            continue

        # -f subfilelist (whitespace-separated)
        if line.startswith("-f"):
            sub_path = line[2:].strip()
            if sub_path:
                sub_filelist = _resolve_path(sub_path, base_dir)
                _parse_file(
                    sub_filelist, files, incdirs, defines,
                    chain=(*chain, resolved),
                )
            continue

        # Skip other + options
        if line.startswith("+"):
            continue

        # Skip other - flags
        if line.startswith("-"):
            continue

        # Source file path
        file_path = _resolve_path(line, base_dir)
        if file_path not in files:
            files.append(file_path)


_LINE_COMMENT_START = "//"
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(text: str) -> str:
    """Remove /* block comments */ (possibly multi-line) and // line comments.

    ``//`` is only treated as a comment start when preceded by whitespace
    or at the start of a line, so doubled slashes inside paths survive.
    Block comments are replaced by whitespace (newlines preserved) so the
    remaining lines keep their structure.
    """
    text = _BLOCK_COMMENT_RE.sub(_whitespace_for, text)
    out_lines = []
    for line in text.splitlines():
        idx = _find_line_comment(line)
        out_lines.append(line[:idx] if idx != -1 else line)
    return "\n".join(out_lines)


def _whitespace_for(match: re.Match) -> str:
    return "".join(ch if ch == "\n" else " " for ch in match.group(0))


def _find_line_comment(line: str) -> int:
    """Index of a // line comment, or -1. Requires preceding whitespace."""
    for i, ch in enumerate(line):
        if ch == "/" and line.startswith(_LINE_COMMENT_START, i) and (i == 0 or line[i - 1].isspace()):
            return i
    return -1


def _strip_line_comments(text: str) -> str:
    out_lines = []
    for line in text.splitlines():
        idx = _find_line_comment(line)
        out_lines.append(line[:idx] if idx != -1 else line)
    return "\n".join(out_lines)


def _find_line_comment(line: str) -> int:
    """Index of a // line comment, or -1. Requires preceding whitespace."""
    for i, ch in enumerate(line):
        if ch == "/" and line.startswith("//", i) and (i == 0 or line[i - 1].isspace()):
            return i
    return -1


def _resolve_path(path_str: str, base_dir: Path) -> Path:
    """Resolve a path relative to base_dir."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()
