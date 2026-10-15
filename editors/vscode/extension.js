'use strict';

const vscode = require('vscode');
const { spawn } = require('child_process');
const path = require('path');
let activeSession;

class Connection {
    constructor(child, output, notification) {
        this.child = child;
        this.output = output;
        this.notification = notification;
        this.sequence = 0;
        this.pending = new Map();
        this.buffer = Buffer.alloc(0);
        this.closed = false;
        child.stdout.on('data', chunk => this.receive(chunk));
        child.stderr.on('data', chunk => output.append(chunk.toString()));
        child.on('error', error => this.fail(error));
        child.stdin.on('error', error => this.fail(error));
        child.on('exit', (code, signal) => this.fail(new Error(`Slip server exited (${code ?? signal})`)));
    }
    send(message) {
        if (this.closed) throw new Error('Slip server is disconnected');
        const payload = Buffer.from(JSON.stringify({ jsonrpc: '2.0', ...message }), 'utf8');
        this.child.stdin.write(Buffer.concat([Buffer.from(`Content-Length: ${payload.length}\r\n\r\n`), payload]));
    }
    notify(method, params) { if (!this.closed) this.send({ method, params }); }
    request(method, params, cancellation) {
        return new Promise((resolve, reject) => {
            const id = ++this.sequence;
            let disposable;
            const timer = setTimeout(() => finish(new Error(`Slip request timed out: ${method}`)), 30000);
            const finish = (error, result) => {
                clearTimeout(timer);
                disposable?.dispose();
                this.pending.delete(id);
                if (error) reject(error); else resolve(result);
            };
            this.pending.set(id, finish);
            if (cancellation) disposable = cancellation.onCancellationRequested(() => {
                this.notify('$/cancelRequest', { id });
                finish(new vscode.CancellationError());
            });
            try { this.send({ id, method, params }); } catch (error) { finish(error); }
        });
    }
    receive(chunk) {
        this.buffer = Buffer.concat([this.buffer, chunk]);
        while (true) {
            const boundary = this.buffer.indexOf('\r\n\r\n');
            if (boundary < 0) {
                if (this.buffer.length > 8192) this.fail(new Error('Invalid Slip protocol header'));
                return;
            }
            const match = /(?:^|\r\n)Content-Length:\s*(\d+)/i.exec(this.buffer.subarray(0, boundary).toString('ascii'));
            if (!match || Number(match[1]) > 8000000) { this.fail(new Error('Invalid Slip message length')); return; }
            const length = Number(match[1]);
            if (this.buffer.length < boundary + 4 + length) return;
            const body = this.buffer.subarray(boundary + 4, boundary + 4 + length);
            this.buffer = this.buffer.subarray(boundary + 4 + length);
            try {
                const message = JSON.parse(body.toString('utf8'));
                if (Object.hasOwn(message, 'id')) {
                    this.pending.get(message.id)?.(message.error ? new Error(message.error.message) : null, message.result);
                } else if (message.method) this.notification(message.method, message.params);
            } catch (error) { this.fail(error); return; }
        }
    }
    fail(error) {
        if (this.closed) return;
        this.closed = true;
        this.output.appendLine(String(error));
        for (const finish of [...this.pending.values()]) finish(error);
        this.child.kill();
    }
}

const lspPosition = position => ({ line: position.line, character: position.character });
const lspDocument = document => ({ uri: document.uri.toString() });
const editorRange = range => new vscode.Range(range.start.line, range.start.character, range.end.line, range.end.character);

async function start(context, output) {
    const settings = vscode.workspace.getConfiguration('slip');
    const diagnostics = vscode.languages.createDiagnosticCollection('slip');
    const child = spawn(settings.get('pythonPath', 'python3'), [path.join(context.extensionPath, 'server', 'slip_lsp.py'), '--slip', settings.get('compilerPath', 'slip')], { stdio: ['pipe', 'pipe', 'pipe'], cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath });
    const connection = new Connection(child, output, (method, params) => {
        if (method === 'textDocument/publishDiagnostics') {
            const uri = vscode.Uri.parse(params.uri);
            const open = vscode.workspace.textDocuments.find(document => document.uri.toString() === params.uri);
            if (open && params.version !== undefined && open.version !== params.version) return;
            diagnostics.set(uri, params.diagnostics.map(item => {
                const diagnostic = new vscode.Diagnostic(editorRange(item.range), item.message, (item.severity ?? 1) - 1);
                diagnostic.source = 'slip';
                diagnostic.code = item.code;
                return diagnostic;
            }));
        } else if (method === 'window/logMessage') output.appendLine(params.message);
    });
    const subscriptions = [diagnostics];
    const selector = { language: 'slip', scheme: 'file' };
    const isSlip = document => document.languageId === 'slip' && document.uri.scheme === 'file';
    const paramsAt = (document, position) => ({ textDocument: lspDocument(document), position: lspPosition(position) });
    try {
        await connection.request('initialize', { processId: process.pid, rootUri: vscode.workspace.workspaceFolders?.[0]?.uri.toString() ?? null,
            capabilities: { general: { positionEncodings: ['utf-16'] } },
            initializationOptions: { project: settings.get('project', ''), profile: settings.get('profile', '') } });
        connection.notify('initialized', {});
        const open = document => { if (isSlip(document)) connection.notify('textDocument/didOpen', { textDocument: { ...lspDocument(document), languageId: 'slip', version: document.version, text: document.getText() } }); };
        subscriptions.push(vscode.workspace.onDidOpenTextDocument(open));
        subscriptions.push(vscode.workspace.onDidChangeTextDocument(event => {
            if (isSlip(event.document)) connection.notify('textDocument/didChange', { textDocument: { ...lspDocument(event.document), version: event.document.version }, contentChanges: [{ text: event.document.getText() }] });
        }));
        subscriptions.push(vscode.workspace.onDidSaveTextDocument(document => {
            if (isSlip(document)) connection.notify('textDocument/didSave', { textDocument: lspDocument(document), text: document.getText() });
            else if (['systemverilog', 'verilog'].includes(document.languageId)) {
                for (const slip of vscode.workspace.textDocuments.filter(isSlip)) connection.notify('textDocument/didSave', { textDocument: lspDocument(slip), text: slip.getText() });
            }
        }));
        subscriptions.push(vscode.workspace.onDidCloseTextDocument(document => {
            if (isSlip(document)) connection.notify('textDocument/didClose', { textDocument: lspDocument(document) });
        }));
        subscriptions.push(vscode.languages.registerCompletionItemProvider(selector, {
            async provideCompletionItems(document, position, token) {
                const items = await connection.request('textDocument/completion', paramsAt(document, position), token);
                return items.map(item => {
                    const completion = new vscode.CompletionItem(item.label, (item.kind ?? 1) - 1);
                    completion.detail = item.detail;
                    completion.insertText = item.insertText ?? item.label;
                    return completion;
                });
            }
        }, '.'));
        subscriptions.push(vscode.languages.registerDefinitionProvider(selector, {
            async provideDefinition(document, position, token) {
                const items = await connection.request('textDocument/definition', paramsAt(document, position), token);
                return items.map(item => new vscode.Location(vscode.Uri.parse(item.uri), editorRange(item.range)));
            }
        }));
        subscriptions.push(vscode.languages.registerHoverProvider(selector, {
            async provideHover(document, position, token) {
                const item = await connection.request('textDocument/hover', paramsAt(document, position), token);
                return item ? new vscode.Hover(new vscode.MarkdownString(item.contents.value), item.range ? editorRange(item.range) : undefined) : undefined;
            }
        }));
        subscriptions.push(vscode.languages.registerDocumentSymbolProvider(selector, {
            async provideDocumentSymbols(document, token) {
                const items = await connection.request('textDocument/documentSymbol', { textDocument: lspDocument(document) }, token);
                return items.map(item => new vscode.DocumentSymbol(item.name, '', item.kind - 1, editorRange(item.range), editorRange(item.selectionRange)));
            }
        }));
        subscriptions.push(vscode.languages.registerDocumentFormattingEditProvider(selector, {
            async provideDocumentFormattingEdits(document, options, token) {
                const items = await connection.request('textDocument/formatting', { textDocument: lspDocument(document), options }, token);
                return items.map(item => vscode.TextEdit.replace(editorRange(item.range), item.newText));
            }
        }));
        for (const document of vscode.workspace.textDocuments) open(document);
    } catch (error) {
        for (const disposable of subscriptions) disposable.dispose();
        connection.fail(error);
        throw error;
    }
    return {
        async dispose() {
            for (const disposable of subscriptions) disposable.dispose();
            try {
                await Promise.race([connection.request('shutdown', null), new Promise(resolve => setTimeout(resolve, 2000))]);
                connection.notify('exit', null);
            } catch (error) { output.appendLine(String(error)); }
            finally { child.kill(); }
        }
    };
}

async function activate(context) {
    const output = vscode.window.createOutputChannel('Slip');
    context.subscriptions.push(output);
    let restarting = Promise.resolve();
    const performRestart = async () => {
        if (activeSession) { await activeSession.dispose(); activeSession = undefined; }
        try { activeSession = await start(context, output); }
        catch (error) { output.appendLine(String(error)); vscode.window.showErrorMessage(`Slip language server could not start: ${error.message}`); }
    };
    const restart = () => { restarting = restarting.then(performRestart); return restarting; };
    context.subscriptions.push(vscode.commands.registerCommand('slip.restartLanguageServer', restart));
    context.subscriptions.push(vscode.workspace.onDidChangeConfiguration(event => {
        if (event.affectsConfiguration('slip')) restart();
    }));
    await restart();
}
async function deactivate() { if (activeSession) { await activeSession.dispose(); activeSession = undefined; } }
module.exports = { activate, deactivate, Connection };
