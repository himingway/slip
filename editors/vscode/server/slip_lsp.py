#!/usr/bin/env python3
"""Slip language server (LSP 3.17, stdio), using only the Python standard library.

The compiler stays authoritative for diagnostics and elaborated interfaces. The
lexical index supplies completion even while a document is incomplete. The
formatter preserves token text, comments and defun indentation semantics.
"""
from __future__ import annotations

import argparse
import concurrent.futures
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
from urllib.parse import urlparse
from urllib.request import url2pathname


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int
    kind: str = "symbol"


IDENTIFIER = re.compile(r"(?:`?[A-Za-z_$][A-Za-z0-9_$]*)(?:`[A-Za-z_][A-Za-z0-9_]*)*")
KEYWORDS = "module param localparam logic signed assign seq comb initial pos neg if else for case casez casex default inside include typedef enum struct packed function automatic return assert static_assert bundle master slave bus input output inout int bit interface".split()


def scan(source: str) -> list[Token]:
    result = []
    pos = 0
    while pos < len(source):
        start = pos
        if source[pos].isspace():
            pos += 1
            continue
        if source.startswith("//", pos):
            end = source.find("\n", pos)
            pos = len(source) if end < 0 else end
            result.append(Token(source[start:pos], start, pos, "comment"))
            continue
        if source.startswith("/*", pos):
            pos += 2
            depth = 1
            while pos < len(source) and depth:
                if source.startswith("/*", pos):
                    depth += 1
                    pos += 2
                elif source.startswith("*/", pos):
                    depth -= 1
                    pos += 2
                else:
                    pos += 1
            result.append(Token(source[start:pos], start, pos, "comment"))
            continue
        if source[pos] == '"':
            pos += 1
            while pos < len(source):
                if source[pos] == "\\":
                    pos = min(pos + 2, len(source))
                elif source[pos] == '"':
                    pos += 1
                    break
                else:
                    pos += 1
            result.append(Token(source[start:pos], start, pos, "string"))
            continue
        name = IDENTIFIER.match(source, pos)
        if name:
            pos = name.end()
            result.append(Token(source[start:pos], start, pos, "name"))
            continue
        pos += 1
        result.append(Token(source[start:pos], start, pos))
    return result


def offset_at(source: str, position: dict) -> int:
    """Convert a UTF-16 LSP position to a Python character offset."""
    lines = source.splitlines(keepends=True)
    line = max(0, int(position.get("line", 0)))
    if line >= len(lines):
        return len(source)
    units = max(0, int(position.get("character", 0)))
    count = 0
    index = 0
    for char in lines[line].rstrip("\r\n"):
        size = len(char.encode("utf-16-le")) // 2
        if count + size > units:
            break
        count += size
        index += 1
    return sum(map(len, lines[:line])) + index


def position_at(source: str, offset: int) -> dict:
    offset = min(max(offset, 0), len(source))
    before = source[:offset]
    start = before.rfind("\n") + 1
    return {"line": before.count("\n"), "character": len(before[start:].encode("utf-16-le")) // 2}


def token_range(source: str, token: Token) -> dict:
    return {"start": position_at(source, token.start), "end": position_at(source, token.end)}


def file_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path = url2pathname(parsed.path)
    if parsed.netloc and parsed.netloc != "localhost":
        path = "//" + parsed.netloc + path
    return Path(path)


def format_source(source: str, tab_size: int = 4, spaces: bool = True) -> str:
    """Normalize existing-line indentation without rewriting syntax or comments."""
    newline = "\r\n" if "\r\n" in source else "\n"
    lines = source.splitlines()
    tokens = scan(source)
    by_line: dict[int, list[Token]] = {}
    literal_lines = set()
    for token in tokens:
        first = source.count("\n", 0, token.start)
        last = source.count("\n", 0, token.end)
        if token.kind == "string" and first != last:
            literal_lines.update(range(first + 1, last + 1))
        if token.kind not in {"string", "comment"}:
            by_line.setdefault(first, []).append(token)
    unit = " " * max(1, min(tab_size, 16)) if spaces else "\t"
    braces = parens = brackets = 0
    defun_column = None
    result = []
    for number, line in enumerate(lines):
        items = by_line.get(number, [])
        leading = len(line) - len(line.lstrip())
        if defun_column is not None and items and leading <= defun_column:
            defun_column = None
        if number in literal_lines or defun_column is not None:
            result.append(line if number in literal_lines else line.rstrip())
            continue
        if items and items[0].text == "defun":
            defun_column = leading
            result.append(line.rstrip())
            continue
        closes = 0
        for token in items:
            if token.text != "}":
                break
            closes += 1
        continuation = int(parens > 0 or brackets > 0)
        if items and items[0].text in {')', ']'}:
            continuation = 0
        indent = max(0, braces - closes) + continuation
        result.append(unit * indent + line.strip() if line.strip() else "")
        for token in items:
            braces = max(0, braces + (token.text == "{") - (token.text == "}"))
            parens = max(0, parens + (token.text == "(") - (token.text == ")"))
            brackets = max(0, brackets + (token.text == "[") - (token.text == "]"))
    return newline.join(result).rstrip("\r\n") + newline if result else ""


def module_index(source: str) -> list[dict]:
    tokens = [token for token in scan(source) if token.kind != "comment"]
    result = []
    for index, token in enumerate(tokens[:-1]):
        if token.text != "module" or tokens[index + 1].kind != "name":
            continue
        name = tokens[index + 1]
        pos = index + 2
        if pos < len(tokens) and tokens[pos].text == "#":
            pos += 1
            depth = 0
            while pos < len(tokens):
                depth += (tokens[pos].text == "(") - (tokens[pos].text == ")")
                pos += 1
                if depth == 0:
                    break
        ports = []
        if pos < len(tokens) and tokens[pos].text == "(":
            pos += 1
            want_name = True
            brackets = 0
            while pos < len(tokens) and not (tokens[pos].text == ")" and brackets == 0):
                item = tokens[pos]
                if want_name and item.kind == "name":
                    ports.append(item.text)
                    want_name = False
                brackets += (item.text == "[") - (item.text == "]")
                if item.text == "," and brackets == 0:
                    want_name = True
                pos += 1
        while pos < len(tokens) and tokens[pos].text != "{":
            pos += 1
        depth = 0
        end = len(source)
        for item in tokens[pos:]:
            depth += (item.text == "{") - (item.text == "}")
            if depth == 0:
                end = item.end
                break
        result.append({"name": name.text, "ports": ports, "token": name, "start": token.start, "end": end})
    return result


def instance_context(source: str, offset: int) -> str | None:
    tokens = [t for t in scan(source[:offset]) if t.kind not in {"comment", "string"}]
    frames = []
    parens = brackets = 0
    for index, token in enumerate(tokens):
        parens += (token.text == "(") - (token.text == ")")
        brackets += (token.text == "[") - (token.text == "]")
        if token.text == "{":
            target = None
            if index >= 2 and tokens[index - 1].kind == "name":
                before = index - 2
                if tokens[before].text == ")":
                    depth = 1
                    before -= 1
                    while before >= 0 and depth:
                        depth += (tokens[before].text == ")") - (tokens[before].text == "(")
                        before -= 1
                    if before >= 0 and tokens[before].text == "#":
                        before -= 1
                if before >= 0 and tokens[before].kind == "name" and tokens[before].text not in KEYWORDS:
                    target = tokens[before].text
            frames.append((target, parens, brackets))
        elif token.text == "}" and frames:
            frames.pop()
    return frames[-1][0] if frames and frames[-1][1:] == (parens, brackets) else None


class Server:
    def __init__(self, compiler: str, project: str = "", profile: str = ""):
        self.compiler = str(Path(compiler).resolve()) if Path(compiler).is_file() else compiler
        self.project, self.profile = project, profile
        self.documents: dict[str, dict] = {}
        self.cache: dict[str, dict] = {}
        self.external_cache: dict[tuple[str, str], list[dict]] = {}
        self.published: dict[str, set[str]] = {}
        self.output_lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.shutdown = False
        self.initialized = False

    def send(self, value: dict):
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with self.output_lock:
            sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data)
            sys.stdout.buffer.flush()

    def notify(self, method: str, params: dict):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def context(self, uri: str) -> tuple[Path, Path | None, str]:
        path = file_path(uri)
        if path is None:
            raise ValueError("Slip language services require a file URI")
        if self.project:
            config = Path(self.project).expanduser().resolve()
        else:
            config = next((base / "slip.conf" for base in (path.parent, *path.parent.parents) if (base / "slip.conf").is_file()), None)
        return path, config, str(config) if config else str(path.parent.resolve())

    def arguments(self, config: Path | None) -> list[str]:
        args = ["--project", str(config)] if config else []
        if self.profile and config:
            args += ["--profile", self.profile]
        return args

    def run_compiler(self, args: list[str], cwd: Path, text: str | None = None):
        return subprocess.run([self.compiler, *args], cwd=cwd, input=text, text=True,
                              encoding="utf-8", errors="replace", capture_output=True, timeout=20)

    def diagnose(self, uri: str, version: int, text: str):
        try:
            path, config, key = self.context(uri)
            args = self.arguments(config)
            cwd = config.parent if config else path.parent
            # Save checks elaborate the full project. Standalone buffers can be
            # checked through stdin without changing any workspace file.
            input_args = [] if config else ["-"]
            result = self.run_compiler(["check", *input_args, *args, "--diagnostics=json"], cwd, None if config else text)
            grouped: dict[str, list] = {}
            for line in result.stderr.splitlines():
                try:
                    item = json.loads(line)
                except (ValueError, TypeError):
                    continue
                name = item.get("file", "<stdin>")
                target = uri if name.startswith("<") else (cwd / name).resolve().as_uri()
                target_text = text if target == uri else ""
                if not target_text:
                    with self.state_lock:
                        target_text = self.documents.get(target, {}).get("text", "")
                    if not target_text:
                        target_path = file_path(target)
                        if target_path and target_path.is_file():
                            target_text = target_path.read_text(encoding="utf-8", errors="replace")
                source_lines = target_text.splitlines()
                row = max(0, int(item.get("line", 1)) - 1)
                column = max(0, int(item.get("column", 1)) - 1)
                # C++ source columns count UTF-8 bytes; LSP columns count UTF-16 units.
                source_line = source_lines[row] if row < len(source_lines) else ""
                prefix = source_line.encode("utf-8")[:column].decode("utf-8", errors="ignore")
                character = len(prefix.encode("utf-16-le")) // 2
                next_character = source_line[len(prefix):len(prefix) + 1]
                end_character = character + len(next_character.encode("utf-16-le")) // 2
                message = item.get("message", "Compilation failed")
                if item.get("expansion"):
                    message += "\nExpanded with " + item["expansion"]
                grouped.setdefault(target, []).append({
                    "range": {"start": {"line": row, "character": character}, "end": {"line": row, "character": end_character}},
                    "severity": 1 if item.get("severity") == "error" else 2,
                    "code": item.get("code", "E_COMPILER"), "source": "slip", "message": message,
                })
            if result.returncode == 0:
                report = self.run_compiler(["inspect", *input_args, *args, "--format=json"], cwd, None if config else text)
                if report.returncode == 0:
                    with self.state_lock:
                        self.cache[key] = json.loads(report.stdout)
                        self.external_cache = {entry: value for entry, value in self.external_cache.items() if entry[0] != key}
            elif not grouped:
                grouped[uri] = [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
                                 "severity": 1, "source": "slip", "message": result.stderr.strip() or "Compiler exited without diagnostics"}]
            with self.state_lock:
                if self.shutdown or uri not in self.documents or self.documents[uri]["version"] != version:
                    return
                previous = self.published.get(key, set())
                for target in previous | set(grouped) | {uri}:
                    current_version = self.documents.get(target, {}).get("version")
                    params = {"uri": target, "diagnostics": grouped.get(target, [])}
                    if current_version is not None:
                        params["version"] = current_version
                    self.notify("textDocument/publishDiagnostics", params)
                self.published[key] = set(grouped)
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            with self.state_lock:
                if uri in self.documents and self.documents[uri]["version"] == version:
                    self.notify("window/logMessage", {"type": 1, "message": "Slip: " + str(error)})

    def schedule(self, uri: str):
        with self.state_lock:
            document = dict(self.documents[uri])
        self.executor.submit(self.diagnose, uri, document["version"], document["text"])

    def sources(self, uri: str) -> dict[str, str]:
        path, _, key = self.context(uri)
        with self.state_lock:
            sources = {uri: self.documents[uri]["text"]}
            report = self.cache.get(key, {})
        pending = [path]
        for module in report.get("modules", []):
            name = module.get("location", {}).get("file", "")
            if name and not name.startswith("<"):
                pending.append(Path(name))
        visited = set()
        while pending and len(visited) < 256:
            current = pending.pop().resolve()
            if current in visited:
                continue
            visited.add(current)
            current_uri = current.as_uri()
            if current_uri not in sources:
                with self.state_lock:
                    opened = self.documents.get(current_uri)
                try:
                    sources[current_uri] = opened["text"] if opened else current.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    continue
            tokens = scan(sources[current_uri])
            for index, token in enumerate(tokens[:-1]):
                if token.text == "include" and tokens[index + 1].kind == "string":
                    try:
                        pending.append(current.parent / json.loads(tokens[index + 1].text))
                    except ValueError:
                        pass
        return sources

    def completion(self, uri: str, position: dict) -> list[dict]:
        text = self.documents[uri]["text"]
        offset = offset_at(text, position)
        if any(token.kind == "comment" and token.start <= offset <= token.end for token in scan(text)):
            return []
        target = instance_context(text, offset)
        _, config, key = self.context(uri)
        if target:
            ports = []
            for _, source in self.sources(uri).items():
                for module in module_index(source):
                    if module["name"] == target:
                        ports = [{"name": name} for name in module["ports"]]
            with self.state_lock:
                modules = self.cache.get(key, {}).get("modules", [])
            for module in modules:
                if module["name"] == target:
                    ports = module.get("ports", [])
                for instance in module.get("instances", []):
                    if not ports and instance["module"] == target:
                        ports = [{"name": item["port"], **item} for item in instance.get("connections", [])]
            if not ports:
                cache_key = (key, target)
                with self.state_lock:
                    cached = self.external_cache.get(cache_key)
                if cached is None:
                    path = file_path(uri)
                    try:
                        reflected = self.run_compiler(["inspect", "--interface", target, *self.arguments(config), "--format=json"], config.parent if config else path.parent)
                        cached = json.loads(reflected.stdout).get("modules", [{}])[0].get("ports", []) if reflected.returncode == 0 else []
                    except (OSError, ValueError, subprocess.TimeoutExpired):
                        cached = []
                    with self.state_lock:
                        self.external_cache[cache_key] = cached
                ports = cached
            has_dot = re.search(r"\.[A-Za-z0-9_$]*$", text[:offset]) is not None
            return [{"label": port["name"], "kind": 5,
                     "detail": " ".join(str(port.get(part, "")) for part in ("direction", "type", "width")).strip(),
                     "insertText": ("" if has_dot else ".") + port["name"]} for port in ports]
        names = {name: 14 for name in KEYWORDS}
        for source in self.sources(uri).values():
            for token in scan(source):
                if token.kind == "name" and token.text not in KEYWORDS:
                    names[token.text] = 6
            for module in module_index(source):
                names[module["name"]] = 9
        return [{"label": name, "kind": kind} for name, kind in sorted(names.items())]

    def definition(self, uri: str, position: dict) -> list[dict]:
        text = self.documents[uri]["text"]
        offset = offset_at(text, position)
        word = next((token.text for token in scan(text) if token.start <= offset <= token.end and token.kind == "name"), "")
        if not word:
            return []
        _, _, key = self.context(uri)
        current_module = next((m["name"] for m in module_index(text) if m["start"] <= offset <= m["end"]), None)
        with self.state_lock:
            modules = self.cache.get(key, {}).get("modules", [])
        for module in modules:
            if module["name"] == current_module:
                for signal in [*module.get("ports", []), *module.get("signals", [])]:
                    if signal["name"] == word:
                        loc = signal["location"]
                        destination = uri if loc["file"].startswith("<") else Path(loc["file"]).resolve().as_uri()
                        source = self.sources(uri).get(destination, text)
                        lines = source.splitlines(keepends=True)
                        line = max(0, loc["line"] - 1)
                        start = sum(map(len, lines[:line]))
                        column_text = (lines[line] if line < len(lines) else "").encode("utf-8")[:max(0, loc["column"] - 1)].decode("utf-8", errors="ignore")
                        start += len(column_text)
                        return [{"uri": destination, "range": token_range(source, Token(word, start, start + len(word)))}]
        for destination, source in self.sources(uri).items():
            for module in module_index(source):
                if module["name"] == word:
                    return [{"uri": destination, "range": token_range(source, module["token"])}]
        return []

    def hover(self, uri: str, position: dict):
        source = self.documents[uri]["text"]
        offset = offset_at(source, position)
        word = next((token for token in scan(source) if token.start <= offset <= token.end and token.kind == "name"), None)
        if not word:
            return None
        _, _, key = self.context(uri)
        current = next((m["name"] for m in module_index(source) if m["start"] <= offset <= m["end"]), None)
        with self.state_lock:
            modules = self.cache.get(key, {}).get("modules", [])
        for module in modules:
            if module["name"] != current:
                continue
            for signal in [*module.get("ports", []), *module.get("signals", [])]:
                if signal["name"] == word.text:
                    declaration = " ".join(str(signal.get(field, "")) for field in ("direction", "type", "width", "name", "array")).strip()
                    notes = []
                    if signal.get("inferred_from"):
                        notes.append("Inferred from " + signal["inferred_from"])
                    notes.append(f"{len(signal.get('drivers', []))} drivers, {len(signal.get('uses', []))} uses")
                    return {"contents": {"kind": "markdown", "value": "```systemverilog\n" + declaration + "\n```\n" + "\n\n".join(notes)}, "range": token_range(source, word)}
        return None

    def dispatch(self, method: str, params: dict):
        if method == "initialize":
            options = params.get("initializationOptions") or {}
            compiler = options.get("compilerPath", self.compiler)
            self.compiler = str(Path(compiler).resolve()) if Path(compiler).is_file() else compiler
            self.project = options.get("project", self.project)
            self.profile = options.get("profile", self.profile)
            self.initialized = True
            return {"capabilities": {"positionEncoding": "utf-16", "textDocumentSync": {"openClose": True, "change": 1, "save": {"includeText": True}},
                                     "completionProvider": {"triggerCharacters": ["."]}, "definitionProvider": True, "hoverProvider": True,
                                     "documentSymbolProvider": True, "documentFormattingProvider": True},
                    "serverInfo": {"name": "slip-lsp", "version": "0.1.0"}}
        if method == "shutdown":
            self.shutdown = True
            return None
        if not self.initialized:
            raise RuntimeError("Server is not initialized")
        if method == "textDocument/didOpen":
            document = params["textDocument"]
            with self.state_lock:
                self.documents[document["uri"]] = {"text": document["text"], "version": document.get("version", 0)}
            self.schedule(document["uri"])
            return None
        if method == "textDocument/didChange":
            document = params["textDocument"]
            uri = document["uri"]
            with self.state_lock:
                previous = self.documents[uri]["text"]
                for change in params["contentChanges"]:
                    if "range" in change:
                        previous = previous[:offset_at(previous, change["range"]["start"])] + change["text"] + previous[offset_at(previous, change["range"]["end"]):]
                    else:
                        previous = change["text"]
                self.documents[uri] = {"text": previous, "version": document["version"]}
            self.notify("textDocument/publishDiagnostics", {"uri": uri, "version": document["version"], "diagnostics": []})
            return None
        if method == "textDocument/didSave":
            uri = params["textDocument"]["uri"]
            with self.state_lock:
                if "text" in params:
                    self.documents[uri]["text"] = params["text"]
            self.schedule(uri)
            return None
        if method == "textDocument/didClose":
            uri = params["textDocument"]["uri"]
            with self.state_lock:
                self.documents.pop(uri, None)
            self.notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": []})
            return None
        if method in {"initialized", "$/cancelRequest", "$/setTrace", "workspace/didChangeConfiguration"}:
            return None
        uri = params.get("textDocument", {}).get("uri", "")
        if method == "textDocument/completion":
            return self.completion(uri, params["position"])
        if method == "textDocument/definition":
            return self.definition(uri, params["position"])
        if method == "textDocument/hover":
            return self.hover(uri, params["position"])
        if method == "textDocument/documentSymbol":
            source = self.documents[uri]["text"]
            return [{"name": module["name"], "kind": 2, "range": {"start": position_at(source, module["start"]), "end": position_at(source, module["end"])},
                     "selectionRange": token_range(source, module["token"])} for module in module_index(source)]
        if method == "textDocument/formatting":
            source = self.documents[uri]["text"]
            options = params.get("options", {})
            formatted = format_source(source, options.get("tabSize", 4), options.get("insertSpaces", True))
            return [] if source == formatted else [{"range": {"start": {"line": 0, "character": 0}, "end": position_at(source, len(source))}, "newText": formatted}]
        raise LookupError("Method not found: " + method)

    def serve(self) -> int:
        try:
            while True:
                headers = {}
                while True:
                    line = sys.stdin.buffer.readline()
                    if not line:
                        return 0 if self.shutdown else 1
                    if line in {b"\r\n", b"\n"}:
                        break
                    key, value = line.decode("ascii").split(":", 1)
                    headers[key.lower()] = value.strip()
                length = int(headers["content-length"])
                if not 0 <= length <= 8_000_000:
                    raise ValueError("Invalid Content-Length")
                payload = sys.stdin.buffer.read(length)
                if len(payload) != length:
                    raise ValueError("Truncated message")
                message = json.loads(payload)
                method = message.get("method", "")
                if method == "exit":
                    return 0 if self.shutdown else 1
                try:
                    if self.shutdown and method != "exit":
                        raise ValueError("Server has shut down")
                    result = self.dispatch(method, message.get("params") or {})
                    if "id" in message:
                        self.send({"jsonrpc": "2.0", "id": message["id"], "result": result})
                except (ValueError, KeyError, LookupError, RuntimeError, OSError) as error:
                    if "id" in message:
                        code = -32601 if isinstance(error, LookupError) and not isinstance(error, KeyError) else -32002 if isinstance(error, RuntimeError) else -32602
                        self.send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": code, "message": str(error)}})
                    else:
                        self.notify("window/logMessage", {"type": 1, "message": "Slip: " + str(error)})
        finally:
            self.executor.shutdown(wait=True, cancel_futures=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slip", default="slip", help="Compiler executable")
    parser.add_argument("--project", default="", help="Explicit slip.conf; otherwise search parent directories")
    parser.add_argument("--profile", default="", help="Project profile")
    parser.add_argument("--format", type=Path, help="Format a file and write the result to stdout")
    parser.add_argument("--tab-size", type=int, default=4, help="Formatter indentation width (1-16)")
    parser.add_argument("--use-tabs", action="store_true", help="Indent formatted output with tabs")
    args = parser.parse_args()
    if args.format:
        with args.format.open(encoding="utf-8", newline="") as stream:
            sys.stdout.buffer.write(format_source(stream.read(), args.tab_size, not args.use_tabs).encode("utf-8"))
        return 0
    try:
        return Server(args.slip, args.project, args.profile).serve()
    except (OSError, ValueError, KeyError) as error:
        print("slip-lsp: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
