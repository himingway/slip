if exists('b:did_ftplugin')
  finish
endif
let b:did_ftplugin = 1

setlocal commentstring=//\ %s
setlocal comments=s1:/*,mb:*,ex:*/,://
setlocal suffixesadd=.slip
setlocal expandtab
let &l:shiftwidth = get(b:, 'slip_indent_width', get(g:, 'slip_indent_width', 4))
let &l:softtabstop = &l:shiftwidth
setlocal formatoptions-=t
setlocal formatoptions+=croql

command! -buffer SlipCheck call slip#run('check', 0)
command! -buffer SlipBuild call slip#run('build', 0)
command! -buffer SlipInspect call slip#run('inspect', 0)
command! -buffer SlipFormat call slip#format()

augroup slip_buffer
  autocmd! * <buffer>
  autocmd BufWritePost <buffer> if get(b:, 'slip_check_on_save', get(g:, 'slip_check_on_save', 0)) | call slip#run('check', 1) | endif
augroup END

let b:undo_ftplugin = 'setlocal commentstring< comments< suffixesadd< expandtab< shiftwidth< softtabstop< formatoptions<'
      \ . ' | silent! delcommand SlipCheck | silent! delcommand SlipBuild'
      \ . ' | silent! delcommand SlipInspect | silent! delcommand SlipFormat'
      \ . ' | autocmd! slip_buffer * <buffer>'

if has('nvim-0.8')
  command! -buffer SlipLspStart lua require('slip').start()
  command! -buffer SlipLspStop lua require('slip').stop()
  command! -buffer SlipLspRestart lua require('slip').restart()
  let b:undo_ftplugin .= ' | silent! delcommand SlipLspStart | silent! delcommand SlipLspStop | silent! delcommand SlipLspRestart | setlocal omnifunc< tagfunc<'
  lua require('slip').autostart()
endif
