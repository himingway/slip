if exists('g:loaded_slip')
  finish
endif
let g:loaded_slip = 1

" Vim users with vim-lsp get the same server as the native Neovim client.
augroup slip_vim_lsp
  autocmd!
  autocmd User lsp_setup if !has('nvim') && get(g:, 'slip_vim_lsp', 1) | call slip#register_vim_lsp() | endif
augroup END
