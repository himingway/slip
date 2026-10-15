if exists('b:did_indent')
  finish
endif
let b:did_indent = 1
setlocal autoindent
setlocal indentexpr=slip#indent#get(v:lnum)
setlocal indentkeys=0{,0},0),0],:,!^F,o,O,e
let b:undo_indent = 'setlocal autoindent< indentexpr< indentkeys< | unlet! b:slip_indent_cache'
