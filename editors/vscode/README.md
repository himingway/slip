# Slip HDL for VS Code

Provides syntax highlighting, snippets, compiler diagnostics on open/save,
instance-port completion (including external SV modules), module/signal
navigation, signal hover, document symbols and formatting.

Install a Slip compiler and Python 3.10 or newer. Set `slip.compilerPath` to the
compiler executable, or put `slip` on PATH. Configure `slip.pythonPath` if the
Python executable has another name. The extension has no npm runtime dependencies.

Build and install a local extension package:

```sh
cd editors/vscode
npx --yes @vscode/vsce@4.0.0 package --no-dependencies
code --install-extension slip-language-0.1.0.vsix
```

Opening a `.slip` file starts the bundled LSP server. The server finds the nearest
`slip.conf` in the source's parent directories. `slip.project` selects an explicit
configuration; `slip.profile` selects a named profile. Saving checks the complete
configured project on disk. In standalone files the current document is checked
through stdin. Completion uses current buffer text and compiler metadata, so
partially written instances can still offer ports. Unsaved edits clear stale
diagnostics; they are checked when saved.

Use **Format Document** to normalize indentation and trailing whitespace. The
formatter preserves token text, comments, line breaks within statements and
`defun` body indentation. It does not rewrite HDL expressions or split compact
statements. `editor.formatOnSave` works with the standard VS Code setting.

Use **Slip: Restart Language Server** after replacing a compiler binary. Settings
changes restart the server automatically. Compiler/server messages are available
in the **Slip** output channel.

The [Vim / Neovim runtime package](../vim/README.md) includes highlighting,
indentation, background compiler commands and formatting. Neovim attaches its
native LSP client automatically; Vim can use the same server through vim-lsp.

Other editors can run the standalone stdio server:

```sh
python3 editors/vscode/server/slip_lsp.py --slip /absolute/path/to/slip
# Or, after cmake --install:
slip-lsp --slip /absolute/path/to/slip
```

Standalone formatting accepts `slip-lsp --format design.slip --tab-size 2`;
add `--use-tabs` to indent with tabs. The Vim package passes the buffer's
indentation settings to these options.

The server uses the [Language Server Protocol](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/)
with UTF-16 positions and full-document synchronization. It supports initialize,
shutdown, document open/change/save/close, completion, definition, hover, document
symbols and formatting. The native compiler itself does not require Python.
