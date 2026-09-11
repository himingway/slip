"""Two-pass IP scanner for building module indices.

Pass 1: Collect files, defines, and include paths from filelist and IP directories.
Pass 2: Parse all IP files together with shared preprocessor context via pyslang.

Diagnostics: files that cannot be read are hard errors (a filelist entry
that does not exist is almost always a typo).  Duplicate module names and
modules that fail to reflect are reported as warnings — the index keeps
the first definition but the user is told that the choice was arbitrary.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path

from pyslang import Compilation, SourceManager, SyntaxTree

from slip.errors.semantic import SlipSemanticError
from slip.slang_integration.filelist import FilelistData, parse_filelist
from slip.slang_integration.reflection import ModuleInfo


@dataclass
class IPIndex:
    """IP module index for fast lookup."""
    _modules: dict[str, ModuleInfo] = field(default_factory=dict)

    def get_module(self, name: str) -> ModuleInfo | None:
        """Get module info by name, or None if not found."""
        return self._modules.get(name)

    def get_ports(self, name: str) -> list[tuple[str, str, str | None]] | None:
        """Get ports as (name, direction, width) tuples, or None if not found."""
        info = self._modules.get(name)
        if info is None:
            return None
        return [(p.name, p.direction, p.width) for p in info.ports]

    def get_localparams(self, name: str) -> set[str]:
        """Get localparam names for a module, or empty set if not found."""
        info = self._modules.get(name)
        if info is None:
            return set()
        return {p.name for p in info.params if p.is_local}


def build_ip_index(
    filelists: list[Path] | None,
    ip_dirs: list[Path],
) -> IPIndex:
    """Build IP module index via two-pass scanning.

    Args:
        filelists: Paths to VCS-format .f files (optional).
        ip_dirs: IP source directories to scan recursively.

    Returns:
        IPIndex with all discovered modules.

    Raises:
        SlipSemanticError: If a file listed in a filelist does not exist
            or cannot be read.
    """
    # Pass 1: Collect all files, incdirs, defines
    all_files: list[Path] = []
    all_incdirs: list[Path] = []
    all_defines: list[str] = []
    seen_files: set[Path] = set()

    # Parse filelists
    for fl_path in (filelists or []):
        fl_data = parse_filelist(fl_path)
        for f in fl_data.files:
            resolved = f.resolve()
            if not resolved.exists():
                raise SlipSemanticError(
                    str(fl_path), 0, 0,
                    f"file listed in filelist does not exist: {f}"
                )
            if not resolved.is_file():
                raise SlipSemanticError(
                    str(fl_path), 0, 0,
                    f"filelist entry is not a regular file: {f}"
                )
            if resolved not in seen_files:
                seen_files.add(resolved)
                all_files.append(f)
        for d in fl_data.incdirs:
            if d not in all_incdirs:
                all_incdirs.append(d)
        for d in fl_data.defines:
            if d not in all_defines:
                all_defines.append(d)

    # Scan IP directories recursively
    for ip_dir in ip_dirs:
        if not ip_dir.is_dir():
            continue
        for ext in ("*.sv", "*.v"):
            for f in sorted(ip_dir.rglob(ext)):
                resolved = f.resolve()
                if resolved not in seen_files:
                    seen_files.add(resolved)
                    all_files.append(f)

    if not all_files:
        return IPIndex()

    # Pass 2: Parse all files together and reflect modules
    return _reflect_all_modules(all_files, all_incdirs, all_defines)


def _reflect_all_modules(
    files: list[Path],
    incdirs: list[Path],
    defines: list[str],
) -> IPIndex:
    """Parse all IP files together and extract module information."""
    index = IPIndex()

    popts = _make_preprocessor_options(incdirs, defines)
    file_paths = [str(f) for f in files]

    try:
        tree = SyntaxTree.fromFiles(file_paths, SourceManager(), _bag(popts))
    except Exception:
        # If batch parsing fails, fall back to per-file parsing
        return _reflect_per_file(files, defines)

    comp = Compilation()
    comp.addSyntaxTree(tree)
    _extract_modules_from_compilation(comp, index, source_label=", ".join(file_paths[:3]))
    return index


def _make_preprocessor_options(incdirs: list[Path], defines: list[str]):
    from pyslang import PreprocessorOptions

    popts = PreprocessorOptions()
    # Note: the `predefines` span must be assigned wholesale — appending to
    # the attribute silently does nothing (it returns a copy).
    for d in incdirs:
        popts.additionalIncludePaths.append(str(d))
    if defines:
        popts.predefines = list(defines)
    return popts


def _bag(popts):
    from pyslang import Bag
    return Bag([popts])


def _extract_modules_from_compilation(
    comp: Compilation,
    index: IPIndex,
    source_label: str = "",
) -> None:
    """Extract module info from a pyslang Compilation."""
    from slip.slang_integration.reflection import _reflect_body

    root = comp.getRoot()

    # Iterate all definitions in the compilation
    for defn in comp.getDefinitions():
        name = defn.name
        if name in index._modules:
            warnings.warn(
                f"duplicate module '{name}' in IP sources — keeping the "
                f"first definition (from {source_label or 'IP index'})"
            )
            continue
        try:
            top = root.lookupName(name)
            if top is None:
                continue
            index._modules[name] = _reflect_body(top.body)
        except Exception as e:
            warnings.warn(
                f"could not reflect module '{name}' from IP sources: {e}"
            )
            continue


def _reflect_per_file(files: list[Path], defines: list[str] | None = None) -> IPIndex:
    """Fallback: reflect modules from individual files."""
    from slip.slang_integration.reflection import reflect_module

    index = IPIndex()
    for f in files:
        if not f.exists():
            continue
        try:
            source = f.read_text(encoding="utf-8")
        except OSError as e:
            warnings.warn(f"could not read IP file '{f}': {e}")
            continue
        try:
            tree = SyntaxTree.fromText(source, str(f))
            comp = Compilation()
            comp.addSyntaxTree(tree)

            for defn in comp.getDefinitions():
                name = defn.name
                if name in index._modules:
                    continue
                try:
                    info = reflect_module(f, name)
                    index._modules[name] = info
                except Exception as e:
                    warnings.warn(
                        f"could not reflect module '{name}' from '{f}': {e}"
                    )
                    continue
        except Exception as e:
            warnings.warn(f"could not parse IP file '{f}': {e}")
            continue

    return index
