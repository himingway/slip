#!/usr/bin/env python3
"""Exercise the actual stdio server and compiler, including incomplete buffers."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMPILER = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else ROOT / 'build/release/slip'
SERVER = ROOT / 'editors/vscode/server/slip_lsp.py'
spec = importlib.util.spec_from_file_location('slip_lsp', SERVER)
lsp = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = lsp
spec.loader.exec_module(lsp)


class Client:
    def __init__(self):
        self.process = subprocess.Popen([sys.executable, str(SERVER), '--slip', str(COMPILER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.messages = queue.Queue()
        self.sequence = 0
        self.backlog = []
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        try:
            while True:
                header = {}
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        return
                    if line == b'\r\n':
                        break
                    key, value = line.decode('ascii').split(':', 1)
                    header[key.lower()] = value.strip()
                self.messages.put(json.loads(self.process.stdout.read(int(header['content-length']))))
        except Exception as error:
            self.messages.put(error)

    def send(self, method, params=None, request=False):
        message = {'jsonrpc': '2.0', 'method': method, 'params': params or {}}
        if request:
            self.sequence += 1
            message['id'] = self.sequence
        body = json.dumps(message, ensure_ascii=False).encode()
        self.process.stdin.write(f'Content-Length: {len(body)}\r\n\r\n'.encode() + body)
        self.process.stdin.flush()
        return message.get('id')

    def wait(self, predicate):
        for index, item in enumerate(self.backlog):
            if predicate(item):
                return self.backlog.pop(index)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            item = self.messages.get(timeout=max(0.01, deadline-time.monotonic()))
            if isinstance(item, Exception):
                raise item
            if predicate(item):
                return item
            self.backlog.append(item)
        raise AssertionError('No matching LSP message')

    def request(self, method, params=None):
        request_id = self.send(method, params, True)
        reply = self.wait(lambda item: item.get('id') == request_id)
        if 'error' in reply:
            raise AssertionError(reply['error'])
        return reply['result']

    def diagnostics(self, uri, version, nonempty=None):
        return self.wait(lambda item: item.get('method') == 'textDocument/publishDiagnostics'
                         and item['params']['uri'] == uri and item['params'].get('version') == version
                         and (nonempty is None or bool(item['params']['diagnostics']) == nonempty))['params']['diagnostics']

    def close(self):
        try:
            self.request('shutdown')
            self.send('exit')
            self.process.wait(timeout=5)
            if self.process.returncode != 0:
                raise AssertionError(self.process.stderr.read().decode())
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                stream.close()


class LanguageServices(unittest.TestCase):
    def test_formatter_preserves_tokens_and_compilation(self):
        source = '''defun rename(s):
        return "pre_" + s

module leaf(p_x) { logic p_x; }
module m(a,y) {
logic a,y; // braces { } in comments
comb {
 if (a) {
y=1'b1;
} else {
y=1'b0;
}
}
leaf u { "p_(.*)" => "v_$rename(\\1)" };
}
'''
        formatted = lsp.format_source(source)
        self.assertEqual([(t.kind, t.text) for t in lsp.scan(source)], [(t.kind, t.text) for t in lsp.scan(formatted)])
        self.assertEqual(formatted, lsp.format_source(formatted))
        self.assertIn('        return "pre_"', formatted)
        self.assertIn('    logic a,y;', formatted)
        for text in (source, formatted):
            result = subprocess.run([str(COMPILER), 'build', '-', '--stdout'], input=text, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            if text == source:
                expected = result.stdout
            else:
                self.assertEqual(result.stdout, expected)
        self.assertEqual(lsp.format_source('module m {\r\nlogic a;\r\n}\r\n'), 'module m {\r\n    logic a;\r\n}\r\n')

    def test_utf16_positions_and_incomplete_instance_context(self):
        text = '😀 module leaf(clk,y) {} module top { leaf u { .'
        position = lsp.position_at(text, len(text))
        self.assertEqual(lsp.offset_at(text, position), len(text))
        self.assertEqual(position['character'], len(text)+1)
        self.assertEqual(lsp.instance_context(text, len(text)), 'leaf')
        argument = 'module m { leaf u { .a(signal.'
        self.assertIsNone(lsp.instance_context(argument, len(argument)))
        modules = lsp.module_index(text)
        self.assertEqual(modules[0]['ports'], ['clk', 'y'])
        self.assertEqual(lsp.instance_context('module m { comb {', 17), None)

    def test_real_server_diagnostics_navigation_completion_and_formatting(self):
        with tempfile.TemporaryDirectory(prefix='slip-editor-') as temporary:
            path = Path(temporary)/'main.slip'
            source = 'module leaf(a,y) { logic a,y; assign y=a; }\nmodule m(a,y) {\nlogic a,y;\nleaf u {.a,.y};\n}\n'
            path.write_text(source)
            uri = path.as_uri()
            client = Client()
            try:
                initialized = client.request('initialize', {'capabilities': {}})
                self.assertEqual(initialized['capabilities']['positionEncoding'], 'utf-16')
                client.send('initialized')
                client.send('textDocument/didOpen', {'textDocument': {'uri': uri, 'text': source, 'version': 1, 'languageId': 'slip'}})
                client.diagnostics(uri, 1)
                symbols = client.request('textDocument/documentSymbol', {'textDocument': {'uri': uri}})
                self.assertEqual([item['name'] for item in symbols], ['leaf', 'm'])
                hover = client.request('textDocument/hover', {'textDocument': {'uri': uri}, 'position': {'line': 2, 'character': 6}})
                self.assertIn('drivers', hover['contents']['value'])
                definition = client.request('textDocument/definition', {'textDocument': {'uri': uri}, 'position': {'line': 3, 'character': 2}})
                self.assertEqual(definition[0]['uri'], uri)
                self.assertEqual(definition[0]['range']['start']['line'], 0)
                edits = client.request('textDocument/formatting', {'textDocument': {'uri': uri}, 'options': {'tabSize': 4, 'insertSpaces': True}})
                self.assertIn('    logic a,y;', edits[0]['newText'])
                incomplete = source[:source.index('leaf u')] + 'leaf u { .'
                client.send('textDocument/didChange', {'textDocument': {'uri': uri, 'version': 2}, 'contentChanges': [{'text': incomplete}]})
                client.diagnostics(uri, 2)
                completions = client.request('textDocument/completion', {'textDocument': {'uri': uri}, 'position': lsp.position_at(incomplete, len(incomplete))})
                self.assertEqual({item['label'] for item in completions}, {'a', 'y'})
                self.assertEqual({item['insertText'] for item in completions}, {'a', 'y'})
                no_dot = incomplete[:-1]
                client.send('textDocument/didChange', {'textDocument': {'uri': uri, 'version': 3}, 'contentChanges': [{'text': no_dot}]})
                manual = client.request('textDocument/completion', {'textDocument': {'uri': uri}, 'position': lsp.position_at(no_dot, len(no_dot))})
                self.assertEqual({item['insertText'] for item in manual}, {'.a', '.y'})
                broken = 'module m(y) { initial { assert(1, "😀"); y=; } }\n'
                client.send('textDocument/didChange', {'textDocument': {'uri': uri, 'version': 4}, 'contentChanges': [{'text': broken}]})
                client.send('textDocument/didSave', {'textDocument': {'uri': uri}, 'text': broken})
                diagnostics = client.diagnostics(uri, 4, True)
                self.assertEqual(diagnostics[0]['code'], 'E_PARSE')
                expected = lsp.position_at(broken, broken.index('y=;')+2)
                self.assertEqual(diagnostics[0]['range']['start'], expected)
                self.assertFalse((Path(temporary)/'build').exists())
                client.send('textDocument/didClose', {'textDocument': {'uri': uri}})
                client.wait(lambda item: item.get('method') == 'textDocument/publishDiagnostics' and item['params']['uri'] == uri and not item['params']['diagnostics'])
            finally:
                client.close()

    def test_external_ports_complete_without_a_valid_design(self):
        with tempfile.TemporaryDirectory(prefix='slip-editor-ip-') as temporary:
            root = Path(temporary)
            (root/'ip').mkdir()
            (root/'ip/leaf.sv').write_text('module external(input logic clk, input logic [7:0] data, output logic ready); assign ready=clk & data[0]; endmodule\n')
            (root/'slip.conf').write_text('entry=top.slip\nip_dir=ip\ntop=top\n')
            source = 'module top { external u { .'
            path = root/'top.slip'
            path.write_text(source)
            client = Client()
            try:
                client.request('initialize')
                uri = path.as_uri()
                client.send('textDocument/didOpen', {'textDocument': {'uri': uri, 'text': source, 'version': 1}})
                client.diagnostics(uri, 1, True)
                result = client.request('textDocument/completion', {'textDocument': {'uri': uri}, 'position': lsp.position_at(source, len(source))})
                self.assertEqual({item['label'] for item in result}, {'clk', 'data', 'ready'})
                self.assertIn('[7:0]', next(item for item in result if item['label'] == 'data')['detail'])
                self.assertFalse((root/'build').exists())
            finally:
                client.close()


if __name__ == '__main__':
    unittest.main()
