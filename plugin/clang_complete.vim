"
" File: clang_complete.vim
" Author: Xavier Deguillard <deguilx@gmail.com>
"
" Description: Use of clang to complete in C/C++.
"
" Help: Use :help clang_complete
"

if exists('g:clang_complete_loaded')
  finish
endif
let g:clang_complete_loaded = 1

au FileType c,cpp      if g:ClangCompleteInit()  | call s:ClangCompleteBuffer() | endif
au FileType c.*,cpp.*  if g:ClangCompleteInit() | call s:ClangCompleteBuffer() | endif


if has('pythonx')
  let s:py_cmd = 'pythonx'
elseif has('python')
  let s:py_cmd = 'python'
elseif has('python3')
  let s:py_cmd = 'python3'
endif

if !has('python') && !has('python3')
  echoe 'clang_complete: No python support available.'
  echoe 'Cannot use clang library'
  echoe 'Compile vim with python support to use libclang'
  finish
endif

" global options

let g:clang_complete_copen = get(g:,'clang_complete_copen',0)

let g:clang_user_options = get(g:,'clang_user_options','')

let g:clang_compilation_database = get(g:,'clang_compilation_database','')

let g:clang_library_path = get(g:,'clang_library_path','')

let g:clang_complete_macros = get(g:,'clang_complete_macros',0)

let g:clang_complete_patterns = get(g:,'clang_complete_patterns',0)

let g:clang_auto_user_options = get(g:,'clang_auto_user_options','.clang_complete, path')

let g:clang_complete_lib_flags = 0

if g:clang_complete_macros == 1
  let g:clang_complete_lib_flags = 1
endif

if g:clang_complete_patterns == 1
  let g:clang_complete_lib_flags += 2
endif


function! g:ClangCompleteInit()

  call g:ClangLoadUserOptions()

  let b:clang_complete_changedtick = b:changedtick

  if s:initClangCompletePython() != 1
    return 0
  endif

  return 1

endfunction

" key mappings, options, autocmd for buffer
function! s:ClangCompleteBuffer()

  " Disable every autocmd that could have been set for this buffer
  augroup ClangComplete
    autocmd! * <buffer>
  augroup end

endfunc

function! g:ClangLoadUserOptions()
  let b:clang_user_options = ''

  let l:option_sources = split(g:clang_auto_user_options, ',')
  let l:remove_spaces_cmd = 'substitute(v:val, "\\s*\\(.*\\)\\s*", "\\1", "")'
  let l:option_sources = map(l:option_sources, l:remove_spaces_cmd)

  for l:source in l:option_sources
    if l:source == 'path'
      call s:parsePathOption()
    elseif l:source == 'compile_commands.json'
      call s:findCompilationDatase(l:source)
    elseif l:source == '.clang_complete'
      call s:parseConfig()
    else
      let l:getopts = 'getopts#' . l:source . '#getopts'
      silent call eval(l:getopts . '()')
    endif
  endfor
endfunction

" Used to tell if a flag needs a space between the flag and file
let s:flagInfo = {
\   '-I': {
\     'pattern': '-I\s*',
\     'output': '-I'
\   },
\   '-F': {
\     'pattern': '-F\s*',
\     'output': '-F'
\   },
\   '-iquote': {
\     'pattern': '-iquote\s*',
\     'output': '-iquote'
\   },
\   '-include': {
\     'pattern': '-include\s\+',
\     'output': '-include '
\   }
\ }

let s:flagPatterns = []
for s:flag in values(s:flagInfo)
  let s:flagPatterns = add(s:flagPatterns, s:flag.pattern)
endfor
let s:flagPattern = '\%(' . join(s:flagPatterns, '\|') . '\)'


function! s:processFilename(filename, root)
  " Handle Unix absolute path
  if matchstr(a:filename, '\C^[''"\\]\=/') != ''
    let l:filename = a:filename
  " Handle Windows absolute path
  elseif s:isWindows() 
       \ && matchstr(a:filename, '\C^"\=[a-zA-Z]:[/\\]') != ''
    let l:filename = a:filename
  " Convert relative path to absolute path
  else
    " If a windows file, the filename may need to be quoted.
    if s:isWindows()
      let l:root = substitute(a:root, '\\', '/', 'g')
      if matchstr(a:filename, '\C^".*"\s*$') == ''
        let l:filename = substitute(a:filename, '\C^\(.\{-}\)\s*$'
                                            \ , '"' . l:root . '\1"', 'g')
      else
        " Strip first double-quote and prepend the root.
        let l:filename = substitute(a:filename, '\C^"\(.\{-}\)"\s*$'
                                            \ , '"' . l:root . '\1"', 'g')
      endif
      let l:filename = substitute(l:filename, '/', '\\', 'g')
    else
      " For Unix, assume the filename is already escaped/quoted correctly
      let l:filename = shellescape(a:root) . a:filename
    endif
  endif
  
  return l:filename
endfunction

function! s:parseConfig()
  let l:local_conf = findfile('.clang_complete', getcwd() . ',.;')
  if l:local_conf == '' || !filereadable(l:local_conf)
    return
  endif

  let l:sep = '/'
  if s:isWindows()
    let l:sep = '\'
  endif

  let l:root = fnamemodify(l:local_conf, ':p:h') . l:sep

  let l:opts = readfile(l:local_conf)
  for l:opt in l:opts
    " Ensure passed filenames are absolute. Only performed on flags which
    " require a filename/directory as an argument, as specified in s:flagInfo
    if matchstr(l:opt, '\C^\s*' . s:flagPattern . '\s*') != ''
      let l:flag = substitute(l:opt, '\C^\s*\(' . s:flagPattern . '\).*'
                            \ , '\1', 'g')
      let l:flag = substitute(l:flag, '^\(.\{-}\)\s*$', '\1', 'g')
      let l:filename = substitute(l:opt,
                                \ '\C^\s*' . s:flagPattern . '\(.\{-}\)\s*$',
                                \ '\1', 'g')
      let l:filename = s:processFilename(l:filename, l:root)
      let l:opt = s:flagInfo[l:flag].output . l:filename
    endif

    let b:clang_user_options .= ' ' . l:opt
  endfor
endfunction

function! s:findCompilationDatase(cdb)
  if g:clang_compilation_database == ''
    let l:local_conf = findfile(a:cdb, getcwd() . ',.;')
    if l:local_conf != '' && filereadable(l:local_conf)
      let g:clang_compilation_database = fnamemodify(l:local_conf, ":p:h")
    endif
  endif
endfunction

function! s:parsePathOption()
  let l:dirs = map(split(&path, '\\\@<![, ]'), 'substitute(v:val, ''\\\([, ]\)'', ''\1'', ''g'')')
  for l:dir in l:dirs
    if len(l:dir) == 0 || !isdirectory(l:dir)
      continue
    endif

    " Add only absolute paths
    if matchstr(l:dir, '\s*/') != ''
      let l:opt = '-I' . shellescape(l:dir)
      let b:clang_user_options .= ' ' . l:opt
    endif
  endfor
endfunction

function! s:initClangCompletePython()

  " Only parse the python library once
  if !exists('s:libclang_loaded')
    execute s:py_cmd 'from libclang import ClangWrapper'
    execute s:py_cmd 'import vim'
    execute s:py_cmd 'clangWrapper = ClangWrapper(vim)'
    execute s:py_cmd "vim.command('let l:res = ' + str(clangWrapper.init()))"
    if l:res == 0
      return 0
    endif
    let s:libclang_loaded = 1
  endif
  return 1
endfunction

function! s:escapeCommand(command)
    return s:isWindows() ? a:command : escape(a:command, '()')
endfunction

function! s:isWindows()
  " Check for win32 is enough since it's true on win64
  return has('win32')
endfunction

function! s:GotoDeclaration(preview)
  try
    execute s:py_cmd "clangWrapper.gotoDeclaration(vim.eval('a:preview') == '1')"
  catch /^Vim\%((\a\+)\)\=:E37/
    echoe "The current file is not saved, and 'hidden' is not set."
          \ "Either save the file or add 'set hidden' in your vimrc."
  endtry
  return ''
endfunction

function! g:ClangGotoDeclaration()
  call s:GotoDeclaration(0)
  return ''
endfunction

function! g:ClangGotoDeclarationPreview()
  call s:GotoDeclaration(1)
  return ''
endfunction

" vim: set ts=2 sts=2 sw=2 expandtab :
