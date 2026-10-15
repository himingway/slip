'use strict';
// Exercise the VS Code provider adapter against the actual server and compiler.
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const Module = require('module');
const { pathToFileURL, fileURLToPath } = require('url');
const root = path.resolve(__dirname, '../..');
const compiler = path.resolve(process.argv[2] || path.join(root, 'build/release/slip'));
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'slip-vscode-'));
const uri = value => ({ toString: () => value, fsPath: fileURLToPath(value), scheme: 'file' });
const file = path.join(directory, 'main.slip');
let source = 'module leaf(a,y) { logic a,y; assign y=a; }\nmodule m(a,y) {\nlogic a,y;\nleaf u {.a,.y};\n}\n';
fs.writeFileSync(file, source);
const document = { uri: uri(pathToFileURL(file).toString()), languageId: 'slip', version: 1, getText: () => source };
const events = {}, providers = {}, diagnostics = new Map();
const register = (target, name) => callback => {
    target[name] = callback;
    return { dispose() { delete target[name]; } };
};
class Range {
    constructor(startLine, startCharacter, endLine, endCharacter) {
        this.start = { line: startLine, character: startCharacter };
        this.end = { line: endLine, character: endCharacter };
    }
}
class Diagnostic { constructor(range, message, severity) { Object.assign(this, { range, message, severity }); } }
class CompletionItem { constructor(label, kind) { Object.assign(this, { label, kind }); } }
class Location { constructor(uri, range) { Object.assign(this, { uri, range }); } }
class MarkdownString { constructor(value) { this.value = value; } }
class Hover { constructor(contents, range) { Object.assign(this, { contents, range }); } }
class DocumentSymbol { constructor(name, detail, kind, range, selectionRange) { Object.assign(this, { name, detail, kind, range, selectionRange }); } }
const output = { append() {}, appendLine() {}, dispose() {} };
const vscode = {
    Range, Diagnostic, CompletionItem, Location, MarkdownString, Hover, DocumentSymbol,
    CancellationError: class CancellationError extends Error {},
    Uri: { parse: uri },
    TextEdit: { replace: (range, newText) => ({ range, newText }) },
    workspace: {
        textDocuments: [document], workspaceFolders: [{ uri: uri(pathToFileURL(directory).toString()) }],
        getConfiguration: () => ({ get: (key, fallback) => ({ compilerPath: compiler, pythonPath: process.env.SLIP_TEST_PYTHON || 'python3' }[key] ?? fallback) }),
        onDidOpenTextDocument: register(events, 'open'),
        onDidChangeTextDocument: register(events, 'change'),
        onDidSaveTextDocument: register(events, 'save'),
        onDidCloseTextDocument: register(events, 'close'),
        onDidChangeConfiguration: register(events, 'configuration')
    },
    languages: {
        createDiagnosticCollection: () => ({ set: (uri, items) => diagnostics.set(uri.toString(), items), dispose: () => diagnostics.clear() }),
        registerCompletionItemProvider: (_, provider) => register(providers, 'completion')(provider),
        registerDefinitionProvider: (_, provider) => register(providers, 'definition')(provider),
        registerHoverProvider: (_, provider) => register(providers, 'hover')(provider),
        registerDocumentSymbolProvider: (_, provider) => register(providers, 'symbols')(provider),
        registerDocumentFormattingEditProvider: (_, provider) => register(providers, 'formatting')(provider)
    },
    window: { createOutputChannel: () => output, showErrorMessage: message => { throw new Error(message); } },
    commands: { registerCommand: register(events, 'restart') }
};
const originalLoad = Module._load;
Module._load = function(name, ...args) { return name === 'vscode' ? vscode : originalLoad.call(this, name, ...args); };
const extension = require(path.join(root, 'editors/vscode/extension.js'));
Module._load = originalLoad;
const waitFor = async predicate => {
    const deadline = Date.now() + 10000;
    while (!predicate()) {
        if (Date.now() > deadline) throw new Error('VS Code adapter notification timed out');
        await new Promise(resolve => setTimeout(resolve, 20));
    }
};
(async () => {
    const context = { extensionPath: path.join(root, 'editors/vscode'), subscriptions: [] };
    try {
        await extension.activate(context);
        await waitFor(() => diagnostics.has(document.uri.toString()));
        assert.deepStrictEqual(diagnostics.get(document.uri.toString()), []);
        const hover = await providers.hover.provideHover(document, { line: 2, character: 6 });
        assert.match(hover.contents.value, /drivers/);
        const definition = await providers.definition.provideDefinition(document, { line: 3, character: 2 });
        assert.strictEqual(definition[0].range.start.line, 0);
        const symbols = await providers.symbols.provideDocumentSymbols(document);
        assert.deepStrictEqual(symbols.map(item => item.name), ['leaf', 'm']);
        const edits = await providers.formatting.provideDocumentFormattingEdits(document, { tabSize: 4, insertSpaces: true });
        assert.match(edits[0].newText, /    logic a,y;/);
        source = source.slice(0, source.indexOf('leaf u')) + 'leaf u { .';
        document.version++;
        events.change({ document });
        const completions = await providers.completion.provideCompletionItems(document, { line: 3, character: 10 });
        assert.deepStrictEqual(completions.map(item => item.label).sort(), ['a', 'y']);
        source = 'module m(y) { assign y=; }';
        document.version++;
        events.change({ document });
        events.save(document);
        await waitFor(() => diagnostics.get(document.uri.toString())?.some(item => item.code === 'E_PARSE'));
        assert(!fs.existsSync(path.join(directory, 'build')));
        await extension.deactivate();
        assert.strictEqual(Object.keys(providers).length, 0);
        console.log('VS Code adapter: real server diagnostics, completion, navigation, hover, symbols and formatting passed');
    } finally {
        await extension.deactivate();
        for (const disposable of context.subscriptions) disposable.dispose();
        fs.rmSync(directory, { recursive: true, force: true });
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
