"""VCS-format filelist parser.

Supports the Synopsys VCS filelist format:
    // comments
    +incdir+/path/to/includes
    +define+MACRO=value
    +define+MACRO
    /path/to/file1.sv
    -f another_filelist.f
"""

from __future__ import annotations

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
    seen: set[Path] = set()

    _parse_file(filelist_path, files, incdirs, defines, seen)

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
    seen: set[Path],
) -> None:
    """Recursively parse a single filelist file."""
    resolved = filelist_path.resolve()
    if resolved in seen:
        raise ValueError(f"circular filelist reference: {filelist_path}")
    seen.add(resolved)

    if not filelist_path.exists():
        raise FileNotFoundError(f"filelist not found: {filelist_path}")

    base_dir = filelist_path.parent
    lines = filelist_path.read_text().splitlines()

    for line in lines:
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("//"):
            continue

        # Handle inline comments
        if "//" in line:
            line = line[:line.index("//")].strip()

        if not line:
            continue

        # +incdir+path
        if line.startswith("+incdir+"):
            path_str = line[len("+incdir+"):]
            # Handle multiple paths separated by +
            for p in path_str.split("+"):
                p = p.strip()
                if p:
                    incdir = _resolve_path(p, base_dir)
                    if incdir not in incdirs:
                        incdirs.append(incdir)
            continue

        # +define+MACRO or +define+MACRO=value
        if line.startswith("+define+"):
            macro = line[len("+define+"):]
            if macro and macro not in defines:
                defines.append(macro)
            continue

        # -f subfilelist
        if line.startswith("-f "):
            sub_path = line[3:].strip()
            if sub_path:
                sub_filelist = _resolve_path(sub_path, base_dir)
                _parse_file(sub_filelist, files, incdirs, defines, seen)
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


def _resolve_path(path_str: str, base_dir: Path) -> Path:
    """Resolve a path relative to base_dir."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()
