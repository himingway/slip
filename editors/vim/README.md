# Slip for Vim and Neovim

[中文说明](README_CN.md)

One runtime package for both editors:

- `.slip` file detection, highlighting, nested comments and indentation.
- Background check/build commands with compiler errors and warnings in quickfix.
- Project discovery, profile selection and readable module/signal inspection.
- Buffer formatting with the shared Slip formatter; optional UltiSnips snippets.
- Neovim native LSP: port completion, definitions, hover, symbols and diagnostics.
- Automatic server registration for Vim users with
  [vim-lsp](https://github.com/prabirshrestha/vim-lsp#registering-servers).

Requires Vim 8.2+ with `+job`, `+channel` and `+eval`, or Neovim 0.8+.
Checking/building only needs the native `slip` compiler. Formatting and LSP also
need Python 3.10+ (standard library only). No npm packages are needed.

## Install

Build/install the compiler as described in the root README. Use the Vim runtime
from the same checkout as the server/compiler, since their interfaces evolve
together. Add this **before** filetype setup in `~/.vimrc` or `init.vim`:

```vim
execute 'set runtimepath^=' . fnameescape('/absolute/path/to/slip/editors/vim')
let g:slip_compiler = '/absolute/path/to/slip/build/release/slip'
filetype plugin indent on
syntax enable
```

For Neovim `init.lua`, the equivalent is:

```lua
vim.opt.runtimepath:prepend('/absolute/path/to/slip/editors/vim')
require('slip').setup({
  compiler = '/absolute/path/to/slip/build/release/slip',
  -- python = '/path/to/python3',
  -- profile = 'fpga',
})
vim.cmd('filetype plugin indent on')
vim.cmd('syntax enable')
```

Alternatively, vim-plug can install the repository with its runtime subdirectory:

```vim
Plug 'himingway/slip', { 'rtp': 'editors/vim' }
```

Or add a local plugin spec to lazy.nvim (load before opening Slip files):

```lua
{
  dir = '/absolute/path/to/slip/editors/vim',
  lazy = false,
  config = function()
    require('slip').setup({ compiler = '/absolute/path/to/slip/build/release/slip' })
  end,
}
```

If copying only this runtime package, install `slip-lsp` with `cmake --install`
or set `g:slip_server_cmd` to the Python server's absolute command. From a full
checkout the plugin finds `../vscode/server/slip_lsp.py` automatically. An installed
`slip-lsp` on PATH takes precedence over that fallback.

Generate help tags once with `:helptags /absolute/path/to/slip/editors/vim/doc`,
then read `:help slip`.

## Commands

| Command | Action |
| --- | --- |
| `:SlipCheck` | Check the saved file or the configured project; populate quickfix. |
| `:SlipBuild` | Build the saved file/project using the compiler's output settings. |
| `:SlipInspect` | Show modules, signals, inference, drivers, uses and connections in a scratch window. |
| `:SlipFormat` | Format the current buffer, including unsaved edits. |
| `:SlipLspStart` | Attach the native Neovim client. |
| `:SlipLspStop` | Detach this buffer; keep clients used by other buffers alive. |
| `:SlipLspRestart` | Restart the native server and reconnect its project buffers. |

The last three commands are Neovim only. Commands are buffer local. No keymaps
are installed. Use `:copen`, `:cnext` and `:cprevious` to navigate compiler
diagnostics. Explicit commands open quickfix when diagnostics exist; save checks
never open it. Successful checks create an empty quickfix list and retain older
lists in quickfix history (`:colder`).

`slip.conf` is found by walking up from the file directory. With a project,
commands use its entry and paths; standalone commands run from the source
directory. `:SlipBuild` writes to the project's `out_dir`, or `build/` below that
working directory. Save modified buffers belonging to the project before
check/build/inspect. These commands do not save files for you. Paths and arguments
are passed directly to background jobs, including paths containing spaces.

Formatting preserves expressions, comments, statement line breaks and `defun`
body indentation. It uses the buffer's `shiftwidth` and `expandtab`, preserves
its `fileformat`, and never writes the file. If the buffer changes during the
job, results are discarded. A hidden buffer must be shown before applying a
format result. Check/build/inspect also discard stale buffer diagnostics.

## Settings

Set these before opening files. Each `g:slip_*` option also accepts a `b:slip_*`
override for a particular buffer.

| Variable | Default | Meaning |
| --- | --- | --- |
| `g:slip_compiler` | `'slip'` | Compiler executable; PATH name or path. |
| `g:slip_python` | `'python3'` | Python executable for the repository server. |
| `g:slip_server_cmd` | `[]` | Explicit server argv, e.g. `['python3', '/path/slip_lsp.py']`. Also used for formatting. |
| `g:slip_project` | `''` | Explicit config file; empty discovers parent `slip.conf`. |
| `g:slip_profile` | `''` | Named project profile. |
| `g:slip_indent_width` | `4` | Initial `shiftwidth` and `softtabstop`. |
| `g:slip_check_on_save` | `0` | Also run compiler checks into quickfix after saving. |
| `g:slip_open_quickfix` | `1` | Open quickfix for explicit commands with diagnostics. |
| `g:slip_lsp_auto_start` | `1` | Start native Neovim LSP on Slip filetype. |

`g:slip_vim_lsp` (default `1`, global only) enables automatic vim-lsp registration
in Vim. Native Neovim LSP starts automatically when compiler/server are available.
Keep `check_on_save` off when LSP diagnostics suffice. Changing compiler/project/
profile settings requires `:SlipLspRestart` in Neovim or restarting the Vim LSP
client. Neovim `setup()` accepts the settings above without `g:slip_`, plus
`capabilities` and `on_attach` for completion clients and your own buffer maps.

## Completion and navigation

Neovim users can press **CTRL-X CTRL-O** for omnifunc completion and **CTRL-]**
for definitions. Example optional maps inside `setup()`:

```lua
on_attach = function(_, buffer)
  vim.keymap.set('n', 'gd', vim.lsp.buf.definition, { buffer = buffer })
  vim.keymap.set('n', 'K', vim.lsp.buf.hover, { buffer = buffer })
  vim.keymap.set('n', '<leader>ss', vim.lsp.buf.document_symbol, { buffer = buffer })
  vim.keymap.set('n', '<leader>sf', function()
    vim.lsp.buf.format({ bufnr = buffer, async = false })
  end, { buffer = buffer })
end,
```

In Vim, installing vim-lsp is enough to register the server. To enable omnifunc:

```vim
augroup my_slip_lsp
  autocmd!
  autocmd User lsp_buffer_enabled if &filetype ==# 'slip' | setlocal omnifunc=lsp#complete | endif
augroup END
```

Use `:LspDefinition`, `:LspHover`, `:LspDocumentSymbol` and
`:LspDocumentFormat`. Do not also configure a second Slip server for the same
buffer. Without vim-lsp the Vim syntax, indentation and four compiler/formatter
commands still work.

The LSP server reports diagnostics on open/save, clears them after edits and
checks configured projects on disk. Completion reads current buffer text, so
partially written instances still offer ports, including reflected external SV
modules. Project checks use saved sources. Rename, references and code actions
are not implemented by the server.

If UltiSnips is installed, snippets `module`, `seq`, `comb`, `genfor` and `inst`
are available. `genfor` emits the required literal backticks for compile-time
loops. No snippet engine is required for other features.
