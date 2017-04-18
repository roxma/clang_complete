
## Introduction

The original [clang_complete](https://github.com/Rip-Rip/clang_complete) was
created by [Xavier Deguillard](https://github.com/Rip-Rip) and [Tobias
Grosser](https://github.com/tobig).

I'm maintaining this fork, with lots of code refactored and simplified, for
better integration with [NCM](https://github.com/roxma/nvim-complete-manager).

Here's some of the work in brief.

- Builtin parameter expansion snippet engine removed in favor of ultisnips.
- Quickfix feature removed in favor of neomake or syntastic, etc.
- Builtin `omnifunc`/`completefunc` with threading, and some default insert
  mode mapping removed, in favor of NCM.

## Requirements

- `clang` installed on your system. (eg. `yum install clang clang-devel` or
  `apt-get install libclang-dev`)

## Installation

Assuming you're using [vim-plug](https://github.com/junegunn/vim-plug).

```vim
Plug 'roxma/clang_complete'
```

## Configuration tips

- Set the `clang_library_path` to the directory containing file named
  libclang.{dll,so,dylib} (for Windows, Unix variants and OS X respectively)
  or the file itself, example:

```vim
" path to directory where library can be found
let g:clang_library_path='/usr/lib/llvm-3.8/lib'
" or path directly to the library file
let g:clang_library_path='/usr/lib64/libclang.so.3.8'
```

- Goto declaration.

```vim
" <Plug>(clang_complete_goto_declaration_preview)
au FileType c,cpp  nmap gd <Plug>(clang_complete_goto_declaration)
```

- Compiler options can be configured in a `.clang_complete` file in each project
  root.  Example of `.clang_complete` file:

```
-DDEBUG
-include ../config.h
-I../common
-I/usr/include/c++/4.5.3/
-I/usr/include/c++/4.5.3/x86_64-slackware-linux/
```

- Makefile example for auto-generating `.clang_complete`

```make
.clang_complete: Makefile
	echo $(CXXFLAGS) > $@
```

- Integrate with neomake

```vim
	let g:neomake_cpp_enabled_makers = ['clang']
	let g:neomake_c_enabled_makers = ['clang']
```

## License

See doc/clang_complete.txt for help and license.

