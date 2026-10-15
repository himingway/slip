" Strip literals/comments before counting delimiters, including nested comments.
function! s:code(text, state) abort
  let result = ''
  let chars = split(a:text, '\zs')
  let i = 0
  while i < len(chars)
    let c = chars[i]
    let pair = c . get(chars, i + 1, '')
    if a:state.comment
      if pair ==# '/*'
        let a:state.comment += 1
        let i += 1
      elseif pair ==# '*/'
        let a:state.comment -= 1
        let i += 1
      endif
      let result .= ' '
    elseif a:state.string
      if a:state.escape
        let a:state.escape = 0
      elseif c ==# '\'
        let a:state.escape = 1
      elseif c ==# '"'
        let a:state.string = 0
      endif
      let result .= ' '
    elseif pair ==# '//'
      break
    elseif pair ==# '/*'
      let a:state.comment = 1
      let result .= ' '
      let i += 1
    elseif c ==# '"'
      let a:state.string = 1
      let result .= ' '
    else
      let result .= c
    endif
    let i += 1
  endwhile
  let a:state.escape = 0
  return result
endfunction

function! s:advance(state, lnum) abort
  if a:state.defun >= 0 && (getline(a:lnum) !~# '\S' || indent(a:lnum) > a:state.defun)
    " Defun bodies have their own syntax; their quotes/comments cannot open
    " HDL strings or comments extending into the following module.
    return
  endif
  let code = s:code(getline(a:lnum), a:state)
  if a:state.defun >= 0 && code =~# '\S' && indent(a:lnum) <= a:state.defun
    let a:state.defun = -1
  endif
  if code =~# '^\s*defun\>'
    let a:state.defun = indent(a:lnum)
  endif
  if a:state.defun < 0
    for c in split(code, '\zs')
      if c ==# '{'
        let a:state.braces += 1
      elseif c ==# '}'
        let a:state.braces = max([0, a:state.braces - 1])
      elseif c ==# '('
        let a:state.parens += 1
      elseif c ==# ')'
        let a:state.parens = max([0, a:state.parens - 1])
      elseif c ==# '['
        let a:state.brackets += 1
      elseif c ==# ']'
        let a:state.brackets = max([0, a:state.brackets - 1])
      endif
    endfor
  endif
endfunction

function! slip#indent#get(lnum) abort
  if !exists('b:slip_indent_cache')
    let b:slip_indent_cache = {'tick': b:changedtick, 'lines': [
          \ {'comment': 0, 'string': 0, 'escape': 0, 'braces': 0,
          \ 'parens': 0, 'brackets': 0, 'defun': -1}], 'text': getline(1, '$')}
  elseif b:slip_indent_cache.tick != b:changedtick
    " Reuse states before the first changed line, including during gg=G.
    " Compare prefixes in native list operations instead of rescanning tokens
    " from the beginning of a large design after every keystroke.
    let current = getline(1, '$')
    let old = b:slip_indent_cache.text
    let lo = 0
    let hi = min([len(old), len(current), len(b:slip_indent_cache.lines) - 1])
    while lo < hi
      let mid = (lo + hi + 1) / 2
      if old[0 : mid - 1] ==# current[0 : mid - 1]
        let lo = mid
      else
        let hi = mid - 1
      endif
    endwhile
    if len(b:slip_indent_cache.lines) > lo + 1
      call remove(b:slip_indent_cache.lines, lo + 1, -1)
    endif
    let b:slip_indent_cache.text = current
    let b:slip_indent_cache.tick = b:changedtick
  endif
  let states = b:slip_indent_cache.lines
  while len(states) < a:lnum
    let state = copy(states[-1])
    call s:advance(state, len(states))
    call add(states, state)
  endwhile
  let state = copy(states[a:lnum - 1])
  " Reindenting must preserve the content of multiline strings and defun bodies.
  if state.string || state.comment
    return -1
  endif
  let text = getline(a:lnum)
  if state.defun >= 0 && (text !~# '\S' || indent(a:lnum) > state.defun)
    if text =~# '\S'
      return -1
    endif
    let prev = prevnonblank(a:lnum - 1)
    return indent(prev) + (getline(prev) =~# ':\s*$' ? shiftwidth() : 0)
  endif
  let code = s:code(text, state)
  let closes = strlen(substitute(matchstr(code, '^\s*\%(}\s*\)*'), '\s', '', 'g'))
  let continuation = (state.parens > 0 || state.brackets > 0)
        \ && index([')', ']'], matchstr(code, '\S')) < 0
  return (max([0, state.braces - closes]) + continuation) * shiftwidth()
endfunction
