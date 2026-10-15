let s:runtime = fnamemodify(resolve(expand('<sfile>:p')), ':h:h')
let s:jobs = {}
let s:diagnostic_sequence = 0

function! slip#setting(name, default) abort
  return get(b:, 'slip_' . a:name, get(g:, 'slip_' . a:name, a:default))
endfunction

function! s:executable(name) abort
  return a:name =~# '[/\\]' ? fnamemodify(expand(a:name), ':p') : a:name
endfunction

function! slip#server_command() abort
  let cmd = slip#setting('server_cmd', [])
  if !empty(cmd)
    return copy(cmd)
  endif
  if executable('slip-lsp')
    return ['slip-lsp']
  endif
  let server = s:runtime . '/../vscode/server/slip_lsp.py'
  let python = s:executable(slip#setting('python', 'python3'))
  return filereadable(server) && executable(python) ? [python, server] : []
endfunction

function! slip#context() abort
  let file = expand('%:p')
  let project = slip#setting('project', '')
  if !empty(project)
    let project = fnamemodify(expand(project), ':p')
  elseif !empty(file)
    let dir = fnamemodify(file, ':h')
    while 1
      if filereadable(dir . '/slip.conf')
        let project = dir . '/slip.conf'
        break
      endif
      let parent = fnamemodify(dir, ':h')
      if parent ==# dir
        break
      endif
      let dir = parent
    endwhile
  endif
  return {'file': file, 'project': project,
        \ 'root': empty(project) ? fnamemodify(file, ':h') : fnamemodify(project, ':h'),
        \ 'profile': slip#setting('profile', ''),
        \ 'compiler': s:executable(slip#setting('compiler', 'slip'))}
endfunction

function! slip#vim_lsp_command(info) abort
  let context = slip#context()
  let cmd = slip#server_command()
  if empty(cmd)
    return []
  endif
  call extend(cmd, ['--slip', context.compiler])
  if !empty(context.project)
    call extend(cmd, ['--project', context.project])
  endif
  if !empty(context.profile)
    call extend(cmd, ['--profile', context.profile])
  endif
  return cmd
endfunction

function! slip#register_vim_lsp() abort
  call lsp#register_server({'name': 'slip',
        \ 'cmd': function('slip#vim_lsp_command'), 'allowlist': ['slip'],
        \ 'root_uri': {info -> lsp#utils#path_to_uri(slip#context().root)}})
endfunction

function! s:message(text, error) abort
  if a:error
    echohl WarningMsg
  endif
  echomsg '[Slip] ' . a:text
  echohl None
endfunction

function! s:available() abort
  if has_key(s:jobs, string(bufnr('%')))
    call s:message('A Slip command is already running for this buffer.', 1)
    return 0
  endif
  if !has('nvim') && !exists('*job_start')
    call s:message('Background commands require Vim with +job or Neovim.', 1)
    return 0
  endif
  return 1
endfunction

function! s:saved(context) abort
  if empty(a:context.file) || !filereadable(a:context.file)
    call s:message('Save this file before checking, building or inspecting.', 1)
    return 0
  endif
  for info in getbufinfo({'bufmodified': 1})
    if getbufvar(info.bufnr, '&buftype') !=# ''
      continue
    endif
    let name = fnamemodify(info.name, ':p')
    let in_project = !empty(a:context.project) &&
          \ stridx(name, a:context.root . '/') == 0
    if info.bufnr == bufnr('%') || in_project
      call s:message('Save modified project buffers first: ' . info.name, 1)
      return 0
    endif
  endfor
  return 1
endfunction

function! s:new_state(kind, context, automatic) abort
  let state = {'kind': a:kind, 'context': a:context, 'automatic': a:automatic,
        \ 'buffer': bufnr('%'), 'tick': b:changedtick,
        \ 'stdout': '', 'stderr': '', 'temporary': [], 'done': 0}
  if a:kind !=# 'format'
    let s:diagnostic_sequence += 1
  endif
  let state.sequence = s:diagnostic_sequence
  let state.open_quickfix = !a:automatic && slip#setting('open_quickfix', 1)
  return state
endfunction

function! s:nvim_data(state, stream, job, data, event) abort
  let a:state[a:stream] .= join(a:data, "\n")
  let a:state[a:stream . '_closed'] = 1
  call s:nvim_done(a:state)
endfunction

function! s:nvim_exit(state, job, status, event) abort
  let a:state.exit_status = a:status
  call s:nvim_done(a:state)
endfunction

function! s:nvim_done(state) abort
  " Buffered callbacks arrive at EOF; wait for both streams and process exit.
  if has_key(a:state, 'exit_status') && get(a:state, 'stdout_closed', 0)
        \ && get(a:state, 'stderr_closed', 0)
    call s:finish(a:state, a:state.exit_status)
  endif
endfunction

function! s:vim_exit(state, job, status) abort
  " File redirection avoids the exit/pipe-callback ordering race in Vim.
  for stream in ['stdout', 'stderr']
    let path = a:state[stream . '_file']
    if filereadable(path)
      let a:state[stream] = join(readfile(path, 'b'), "\n")
    endif
  endfor
  call s:finish(a:state, a:status)
endfunction

function! s:start(state, command) abort
  let s:jobs[string(a:state.buffer)] = a:state
  try
    if has('nvim')
      let job = jobstart(a:command, {'cwd': a:state.context.root,
            \ 'stdout_buffered': v:true, 'stderr_buffered': v:true,
            \ 'on_stdout': function('s:nvim_data', [a:state, 'stdout']),
            \ 'on_stderr': function('s:nvim_data', [a:state, 'stderr']),
            \ 'on_exit': function('s:nvim_exit', [a:state])})
      if job <= 0
        throw 'Could not start ' . a:command[0]
      endif
      call chanclose(job, 'stdin')
    else
      let a:state.stdout_file = tempname()
      let a:state.stderr_file = tempname()
      call extend(a:state.temporary, [a:state.stdout_file, a:state.stderr_file])
      let job = job_start(a:command, {'cwd': a:state.context.root, 'in_io': 'null',
            \ 'out_io': 'file', 'out_name': a:state.stdout_file,
            \ 'err_io': 'file', 'err_name': a:state.stderr_file,
            \ 'exit_cb': function('s:vim_exit', [a:state])})
      if job_status(job) ==# 'fail'
        throw 'Could not start ' . a:command[0]
      endif
    endif
    let a:state.job = job
    if !a:state.automatic
      call s:message(a:state.kind . ' started', 0)
    endif
  catch
    let a:state.stderr = v:exception
    call s:finish(a:state, -1)
  endtry
endfunction

function! s:diagnostics(state, status) abort
  if a:state.sequence != s:diagnostic_sequence
    return
  endif
  let items = []
  for line in split(a:state.stderr, "\n")
    try
      let d = json_decode(line)
      let item = {'lnum': get(d, 'line', 0), 'col': get(d, 'column', 0),
            \ 'type': get(d, 'severity', 'error') ==# 'warning' ? 'W' : 'E',
            \ 'text': '[' . get(d, 'code', 'Slip') . '] ' . get(d, 'message', line)}
      if !empty(get(d, 'expansion', ''))
        let item.text .= ' (' . d.expansion . ')'
      endif
      let file = get(d, 'file', '')
      if !empty(file) && file !~# '^<'
        let item.filename = file =~# '^\%(/\|[A-Za-z]:[/\\]\|\\\\\)' ? file : a:state.context.root . '/' . file
      else
        let item.bufnr = a:state.buffer
      endif
      call add(items, item)
    catch
      call add(items, {'text': line, 'valid': 0})
    endtry
  endfor
  if a:status != 0 && empty(items)
    call add(items, {'text': 'Slip exited with status ' . a:status, 'valid': 0})
  endif
  call setqflist([], ' ', {'title': 'Slip ' . a:state.kind,
        \ 'items': items, 'context': {'slip': 1, 'root': a:state.context.root}})
  if !empty(items) && a:state.open_quickfix
    copen
  endif
  if !a:state.automatic || !empty(items)
    call s:message(a:state.kind . (a:status == 0 ? ' succeeded' : ' failed')
          \ . ' (' . len(items) . ' diagnostics; :copen)', a:status != 0)
  endif
endfunction

function! s:apply_format(state) abort
  let lines = split(a:state.stdout, "\n", 1)
  if !empty(lines) && lines[-1] ==# ''
    call remove(lines, -1)
  endif
  call map(lines, 'substitute(v:val, "\r$", "", "")')
  if empty(lines)
    let lines = ['']
  endif
  if getbufline(a:state.buffer, 1, '$') ==# lines
    return
  endif
  " Apply to the invoking window to keep the edit in one undo block.
  let winid = bufwinid(a:state.buffer)
  if winid < 0
    call s:message('Buffer is hidden; run :SlipFormat again when visible.', 1)
    return
  endif
  let a:state.formatted = lines
  call win_execute(winid, 'call slip#apply_format(' . a:state.buffer . ')')
endfunction

function! slip#apply_format(buffer) abort
  let state = get(s:jobs, string(a:buffer), {})
  if empty(state) || bufnr('%') != a:buffer || !&l:modifiable
    return
  endif
  let view = winsaveview()
  let old_count = line('$')
  call setline(1, state.formatted)
  if old_count > len(state.formatted)
    undojoin
    call deletebufline(a:buffer, len(state.formatted) + 1, old_count)
  endif
  call winrestview(view)
endfunction

function! s:finish(state, status) abort
  if a:state.done
    return
  endif
  let a:state.done = 1
  try
    if !bufloaded(a:state.buffer)
      return
    endif
    if getbufvar(a:state.buffer, 'changedtick') != a:state.tick
      if !a:state.automatic
        call s:message('Buffer changed while ' . a:state.kind . ' was running; run it again.', 1)
      endif
      return
    endif
    if a:state.kind ==# 'format'
      if a:status == 0
        call s:apply_format(a:state)
      else
        call s:message('Formatter failed: ' . a:state.stderr, 1)
      endif
    else
      call s:diagnostics(a:state, a:status)
      if a:state.kind ==# 'inspect' && a:status == 0
        botright new
        setlocal buftype=nofile bufhidden=wipe noswapfile
        call setline(1, split(a:state.stdout, "\n"))
        setlocal filetype=text nomodifiable
      endif
    endif
  finally
    for path in a:state.temporary
      call delete(path)
    endfor
    call remove(s:jobs, string(a:state.buffer))
  endtry
endfunction

function! slip#run(kind, automatic) abort
  if !s:available()
    return
  endif
  let context = slip#context()
  if !s:saved(context)
    return
  endif
  if !executable(context.compiler)
    call s:message('Compiler not found; set g:slip_compiler.', 1)
    return
  endif
  if !empty(context.profile) && empty(context.project)
    call s:message('A profile requires slip.conf; set g:slip_project.', 1)
    return
  endif
  let cmd = [context.compiler, a:kind, '--diagnostics=json']
  if empty(context.project)
    call add(cmd, context.file)
  else
    call extend(cmd, ['--project', context.project])
  endif
  if !empty(context.profile)
    call extend(cmd, ['--profile', context.profile])
  endif
  let state = s:new_state(a:kind, context, a:automatic)
  call s:start(state, cmd)
endfunction

function! slip#format() abort
  if !s:available() || !&l:modifiable
    return
  endif
  let cmd = slip#server_command()
  if empty(cmd)
    call s:message('Formatting requires slip-lsp or Python 3.10+ with the repository server.', 1)
    return
  endif
  let context = slip#context()
  if empty(context.file)
    let context.root = getcwd()
  endif
  let state = s:new_state('format', context, 0)
  let snapshot = tempname() . '.slip'
  call add(state.temporary, snapshot)
  try
    call writefile(getline(1, '$'), snapshot, &l:endofline ? '' : 'b')
  catch
    call delete(snapshot)
    call s:message('Could not create formatter snapshot: ' . v:exception, 1)
    return
  endtry
  call extend(cmd, ['--format', snapshot, '--tab-size', string(shiftwidth())])
  if !&l:expandtab
    call add(cmd, '--use-tabs')
  endif
  call s:start(state, cmd)
endfunction
