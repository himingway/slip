# Slip Vim / Neovim 插件

[English](README.md)

Vim 与 Neovim 共用一个插件目录，支持：

- `.slip` 文件识别、语法高亮、嵌套注释和缩进。
- 后台检查、构建，错误和告警写入 quickfix，可跳转到源文件。
- 自动查找上级 `slip.conf`，支持 profile 和编译信息查看。
- 当前缓冲区格式化，保留表达式、注释、语句换行和 `defun` 缩进。
- Neovim 原生 LSP：端口补全、定义跳转、悬停、符号和诊断。
- Vim 安装 `vim-lsp` 后自动注册同一个语言服务器。
- 可选 UltiSnips 模板：`module`、`seq`、`comb`、`genfor`、`inst`。

要求 Vim 8.2+（带 `+job`、`+channel`、`+eval`）或 Neovim 0.8+。
检查和构建只需要原生 `slip`；格式化及 LSP 另需 Python 3.10+，无需额外
Python 包或 npm 包。请使用同一版本仓库中的编译器、插件与语言服务器。

## 安装

先按根目录 README 构建编译器。在 `~/.vimrc` 或 `init.vim` 中加入：

```vim
execute 'set runtimepath^=' . fnameescape('/绝对路径/slip/editors/vim')
let g:slip_compiler = '/绝对路径/slip/build/release/slip'
filetype plugin indent on
syntax enable
```

Neovim 的 `init.lua` 可以使用：

```lua
vim.opt.runtimepath:prepend('/绝对路径/slip/editors/vim')
require('slip').setup({
  compiler = '/绝对路径/slip/build/release/slip',
  -- python = '/Python解释器的绝对路径/python3',
  -- profile = 'fpga',
  on_attach = function(_, buffer)
    vim.keymap.set('n', 'gd', vim.lsp.buf.definition, { buffer = buffer })
    vim.keymap.set('n', 'K', vim.lsp.buf.hover, { buffer = buffer })
  end,
})
vim.cmd('filetype plugin indent on')
vim.cmd('syntax enable')
```

vim-plug 安装方式：

```vim
Plug 'himingway/slip', { 'rtp': 'editors/vim' }
```

lazy.nvim 的本地目录配置、完整选项及 Vim LSP 配置见 [英文说明](README.md)。
如果只复制插件目录，请用 `cmake --install` 安装 `slip-lsp` 并加入 PATH，
或设置 `g:slip_server_cmd = ['python3', '/绝对路径/slip_lsp.py']`。
完整仓库中可自动使用 `editors/vscode/server/slip_lsp.py`；PATH 中的
`slip-lsp` 优先。Neovim 打开 Slip 文件时会自动启动原生 LSP。

执行 `:helptags /绝对路径/slip/editors/vim/doc` 后可通过 `:help slip` 查看帮助。

## 日常操作

| 命令 / 按键 | 功能 |
| --- | --- |
| `:SlipCheck` | 检查已保存文件或项目，诊断进入 quickfix。 |
| `:SlipBuild` | 构建项目，输出位置遵循项目配置。 |
| `:SlipInspect` | 在临时窗口查看模块、信号、推断来源、驱动、使用及连接信息。 |
| `:SlipFormat` | 格式化当前缓冲区，可处理尚未保存的修改。 |
| `:copen` / `:cnext` / `:cprevious` | 打开诊断列表、下一条 / 上一条诊断。 |
| `:SlipLspStart` / `:SlipLspStop` / `:SlipLspRestart` | 启动、脱离、重启 Neovim 原生 LSP。 |
| `CTRL-X CTRL-O` | Neovim 的端口及关键字补全。 |
| `CTRL-]` | Neovim 的定义跳转。 |

插件不设置快捷键。存在 `slip.conf` 时检查项目配置的入口，否则处理当前文件。
检查、构建、查看编译信息前需保存项目中已修改的缓冲区。单文件构建在源文件目录
运行，默认输出到其中的 `build/`；项目构建遵循 `out_dir`。

格式化遵循当前缓冲区的 `shiftwidth`、`expandtab`，保留文件换行格式，不自动保存。
任务执行期间继续编辑时会丢弃旧结果；格式化结果仅应用到可见缓冲区。
LSP 在打开和保存时检查，编辑后清除旧诊断；项目检查读取磁盘文件。
不完整的实例也能补全端口，包括外部 SV 模块。暂不支持重命名、引用搜索和代码操作。

## 常用配置

```vim
let g:slip_compiler = '/绝对路径/slip'
let g:slip_python = 'python3'
let g:slip_project = '/绝对路径/slip.conf'  " 留空时自动查找
let g:slip_profile = 'fpga'
let g:slip_indent_width = 4
let g:slip_check_on_save = 0  " 设为 1 可在保存后额外更新 quickfix
let g:slip_open_quickfix = 1
let g:slip_lsp_auto_start = 1  " Neovim 原生 LSP
let g:slip_vim_lsp = 1         " Vim 的 vim-lsp 自动注册
```

除 `slip_vim_lsp` 外，上述选项也支持 `b:slip_*` 缓冲区配置；Neovim 的
`setup()` 接受省略 `g:slip_` 的同名选项。启用 LSP 时通常不必再开启
`check_on_save`。修改编译器、项目或 profile 后，Neovim 执行
`:SlipLspRestart`，Vim 则重启对应语言客户端。
