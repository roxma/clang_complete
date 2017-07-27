# -*- coding: utf-8 -*-

# For debugging
# NVIM_PYTHON_LOG_FILE=nvim.log NVIM_PYTHON_LOG_LEVEL=INFO nvim

# clang python bindings only supports python2
# https://github.com/llvm-mirror/clang/commit/abdad67b94ad4dad2d655d48ff5f81d6ccf3852e

from __future__ import absolute_import
from cm import register_source, getLogger, Base
register_source(name='clang_complete',
                priority=9,
                abbreviation='c',
                scoping=True,
                scopes=['c','cpp'],
                events=['BufEnter'],
                python='python2',
                cm_refresh_patterns=[r'(-\>|\.|::)'],
)

import sys
import os
import libclang

logger = getLogger(__name__)

class Source(Base):

    def __init__(self,nvim):

        Base.__init__(self,nvim)

        libclang_base = nvim.eval("globpath(&rtp,'plugin/clang',1)").split("\n")[0]
        libclang_base = os.path.dirname(libclang_base)
        logger.info("libclang_base: %s", libclang_base)
        sys.path.append(libclang_base)

        # hack, libclang has 'import vim'
        sys.modules['vim'] = nvim
        self._clang_wrapper = libclang.ClangWrapper(nvim)

        # init global variables for plugin/clang_complete.vim
        nvim.call('g:ClangCompleteInit')

        self._clang_wrapper.init()

    def cm_refresh(self,info,ctx,*args):

        lnum = ctx['lnum']
        col = ctx['col']
        typed = ctx['typed']
        path = ctx['filepath']

        debug = False

        startcol = ctx['startcol']

        src = self.get_src(ctx)
        if not src.strip():
            return

        file = (path, str(src))

        params = self._clang_wrapper.getCompileParams(path,ctx['scope'])
        cr = self._clang_wrapper.getCurrentCompletionResults(lnum,
                                                             startcol,
                                                             params['args'],
                                                             file,
                                                             path)

        if cr is None:
            logger.error("Cannot parse this source file. The following arguments are used for clang: %s", params['args'])
            return

        results = cr.results

        matches = list(map(self._clang_wrapper.format_complete_item, results))

        # logger.info("src: %s", src)
        logger.info("completion result: %s", matches)

        self.nvim.call('cm#complete', info['name'], ctx, startcol, matches, async=True)


