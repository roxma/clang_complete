from __future__ import print_function

from clang.cindex import Config, Index, CompilationDatabase, TranslationUnit, File, SourceLocation, Cursor, TranslationUnitLoadError
from clang.cindex import CodeCompletionResult
import time
import threading
import os
import shlex
import importlib
import logging
import sys

def getLogger(name):
    def get_loglevel():
        # logging setup
        level = logging.INFO
        if 'NVIM_PYTHON_LOG_LEVEL' in os.environ:
            l = getattr(logging,
                    os.environ['NVIM_PYTHON_LOG_LEVEL'].strip(),
                    level)
            if isinstance(l, int):
                level = l
        if 'NVIM_NCM_LOG_LEVEL' in os.environ:
            l = getattr(logging,
                    os.environ['NVIM_NCM_LOG_LEVEL'].strip(),
                    level)
            if isinstance(l, int):
                level = l
        return level
    logger = logging.getLogger(__name__)
    logger.setLevel(get_loglevel())
    # for vim8, avoid the no handler error
    logger.addHandler(logging.NullHandler())
    return logger

logger = getLogger(__name__)

class ClangWrapper():

  def __init__(self,vim):
    self.vim = vim

    self.last_query           = { 'args': [], 'cwd': None }
    self.compilation_database = None
    self.index                = None
    self.builtinHeaderPath    = None
    self.translationUnits     = dict()

  def init(self):

    clang_complete_flags       = self.vim.eval('g:clang_complete_lib_flags')
    library_path               = self.vim.eval('g:clang_library_path')
    clang_compilation_database = self.vim.eval('g:clang_compilation_database')

    if library_path:
      if os.path.isdir(library_path):
        Config.set_library_path(library_path)
      else:
        Config.set_library_file(library_path)

    Config.set_compatibility_check(False)

    try:
      self.index = Index.create()
    except Exception as e:
      if library_path:
        suggestion = "Are you sure '%s' contains libclang?" % library_path
      else:
        suggestion = "Consider setting g:clang_library_path."

      logger.exception("Loading libclang failed, completion won't be available. %s %s ",
                       suggestion,
                       exception_msg)
      return 0

    if not self.canFindBuiltinHeaders(self.index):
      self.builtinHeaderPath = self.getBuiltinHeaderPath(library_path)

      if not self.builtinHeaderPath:
        logger.warn("libclang find builtin header path failed: %s", self.builtinHeaderPath)

    self.complete_flags = int(clang_complete_flags)
    if clang_compilation_database != '':
      self.compilation_database = CompilationDatabase.fromDirectory(clang_compilation_database)
    else:
      self.compilation_database = None
    return 1

  def _decode(self, value):
    if sys.version_info[0] == 2:
      return value

    try:
      return value.decode('utf-8')
    except AttributeError:
      return value

  # Get the compilation parameters from the compilation database for source
  # 'fileName'. The parameters are returned as map with the following keys :
  #
  #   'args' : compiler arguments.
  #            Compilation database returns the complete command line. We need
  #            to filter at least the compiler invocation, the '-o' + output
  #            file, the input file and the '-c' arguments. We alter -I paths
  #            to make them absolute, so that we can launch clang from wherever
  #            we are.
  #            Note : we behave differently from cc_args.py which only keeps
  #            '-I', '-D' and '-include' options.
  #
  #    'cwd' : the compiler working directory
  #
  # The last found args and cwd are remembered and reused whenever a file is
  # not found in the compilation database. For example, this is the case for
  # all headers. This achieve very good results in practice.
  def getCompilationDBParams(self, fileName):
    if self.compilation_database:
      cmds = self.compilation_database.getCompileCommands(fileName)
      if cmds != None:
        cwd = self._decode(cmds[0].directory)
        args = []
        skip_next = 1 # Skip compiler invocation
        for arg in (self._decode(x) for x in cmds[0].arguments):
          if skip_next:
            skip_next = 0;
            continue
          if arg == '-c':
            continue
          if arg == fileName or \
             os.path.realpath(os.path.join(cwd, arg)) == fileName:
            continue
          if arg == '-o':
            skip_next = 1;
            continue
          if arg.startswith('-I'):
            includePath = arg[2:]
            if not os.path.isabs(includePath):
              includePath = os.path.normpath(os.path.join(cwd, includePath))
            args.append('-I'+includePath)
            continue
          args.append(arg)
        self.last_query = { 'args': args, 'cwd': cwd }

    # Do not directly return last_query, but make sure we return a deep copy.
    # Otherwise users of that result may accidently change it and store invalid
    # values in our cache.
    query = self.last_query
    return { 'args': list(query['args']), 'cwd': query['cwd']}

  # Get a tuple (fileName, fileContent) for the file opened in the current
  # vim buffer. The fileContent contains the unsafed buffer content.
  def getCurrentFile(self):
    file = "\n".join(self.vim.current.buffer[:] + ["\n"])
    return (self.vim.current.buffer.name, file)

  def getCompileParams(self, fileName,filetype=None):
    params = self.getCompilationDBParams(fileName)
    args = params['args']
    args += self.splitOptions(self.vim.eval("g:clang_user_options"))
    args += self.splitOptions(self.vim.eval("b:clang_user_options"))

    if filetype is None:
      filetype = self._decode(self.vim.current.buffer.options['filetype'])

    ftype_param = '-x c'

    if 'objc' in filetype:
      ftype_param = '-x objective-c'

    if filetype == 'cpp' or filetype == 'objcpp' or filetype[0:3] == 'cpp' or filetype[0:6] == 'objcpp':
      ftype_param += '++'

    _,ext = os.path.splitext(fileName)
    if 'h' in ext:
      ftype_param += '-header'

    args += self.splitOptions(ftype_param)

    if self.builtinHeaderPath:
      args.append("-I" + self.builtinHeaderPath)

    return { 'args' : args,
             'cwd' : params['cwd'] }

  def getCurrentCompletionResults(self, line, column, args, currentFile, fileName):

    tu = self.getCurrentTranslationUnit(args, currentFile, fileName)

    if tu == None:
      return None

    cr = tu.codeComplete(fileName, line, column, [currentFile], self.complete_flags)
    return cr

  def getCurrentTranslationUnit(self, args, currentFile, fileName, update = False):
    tu = self.translationUnits.get(fileName)
    if tu != None:
      if update:
        tu.reparse([currentFile])
      return tu

    flags = TranslationUnit.PARSE_PRECOMPILED_PREAMBLE | \
            TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
    try:
      tu = self.index.parse(fileName, args, [currentFile], flags)
    except TranslationUnitLoadError as e:
      return None

    self.translationUnits[fileName] = tu

    # Reparse to initialize the PCH cache even for auto completion
    # This should be done by index.parse(), however it is not.
    # So we need to reparse ourselves.
    tu.reparse([currentFile])
    return tu

  # Check if libclang is able to find the builtin include files.
  #
  # libclang sometimes fails to correctly locate its builtin include files. This
  # happens especially if libclang is not installed at a standard location. This
  # function checks if the builtin includes are available.
  def canFindBuiltinHeaders(self, index, args = []):
    flags = 0
    currentFile = ("test.c", '#include "stddef.h"')
    try:
      tu = index.parse("test.c", args, [currentFile], flags)
    except TranslationUnitLoadError as e:
      return 0
    return len(tu.diagnostics) == 0

  # Derive path to clang builtin headers.
  #
  # This function tries to derive a path to clang's builtin header files. We are
  # just guessing, but the guess is very educated. In fact, we should be right
  # for all manual installations (the ones where the builtin header path problem
  # is very common) as well as a set of very common distributions.
  def getBuiltinHeaderPath(self, library_path):
    if os.path.isfile(library_path):
      library_path = os.path.dirname(library_path)

    knownPaths = [
            library_path + "/../lib/clang",  # default value
            library_path + "/../clang",      # gentoo
            library_path + "/clang",         # opensuse
            library_path + "/",              # Google
            "/usr/lib64/clang",              # x86_64 (openSUSE, Fedora)
            "/usr/lib/clang"
    ]

    for path in knownPaths:
      try:
        subDirs = [f for f in os.listdir(path) if os.path.isdir(path + "/" + f)]
        subDirs = sorted(subDirs) or ['.']
        path = path + "/" + subDirs[-1] + "/include"
        if self.canFindBuiltinHeaders(self.index, ["-I" + path]):
          return path
      except:
        pass

    return None

  def splitOptions(self, options):
    # Use python's shell command lexer to correctly split the list of options in
    # accordance with the POSIX standard
    return shlex.split(options)

  def format_complete_item(self, result):
    """
    @type result:  CodeCompletionResult
    """

    returnValue = None
    abbr = ""
    snippet = ""
    info = ""

    def roll_out_optional(chunks):
      result = []
      word = ""
      for chunk in chunks:
        if chunk.isKindInformative() or chunk.isKindResultType() or chunk.isKindTypedText():
          continue

        word += self._decode(chunk.spelling)
        if chunk.isKindOptional():
          result += roll_out_optional(chunk.string)

      return [word] + result


    placeholder_num = 1
    for chunk in result.string:

      if chunk.isKindInformative():
        continue

      if chunk.isKindResultType():
        returnValue = chunk
        continue

      chunk_spelling = self._decode(chunk.spelling)

      if chunk.isKindTypedText():
        abbr = chunk_spelling

      if chunk.isKindOptional():
        for optional_arg in roll_out_optional(chunk.string):
          snippet += ('${%s:[%s]}' % (placeholder_num, optional_arg))
          placeholder_num += 1
          info += "["+optional_arg+"]"

      if chunk.isKindPlaceHolder():
        snippet += ('${%s:%s}' % (placeholder_num, chunk_spelling))
        placeholder_num += 1
      else:
        snippet += chunk_spelling

      info += chunk_spelling

    menu = info

    if returnValue:
      menu = self._decode(returnValue.spelling) + " " + menu

    completion = dict()
    completion['word'] = abbr
    completion['abbr'] = abbr
    if snippet!=abbr:
      completion['snippet'] = snippet
    completion['menu'] = menu
    completion['info'] = info
    completion['dup']  = 1
    return completion

  def getAbbr(self, strings):
    for chunks in strings:
      if chunks.isKindTypedText():
        return self._decode(chunks.spelling)
    return ""

  def jumpToLocation(self, filename, line, column, preview):
    filenameEscaped = self._decode(filename).replace(" ", "\\ ")
    if preview:
      command = "pedit +%d %s" % (line, filenameEscaped)
    elif filename != self.vim.current.buffer.name:
      command = "edit %s" % filenameEscaped
    else:
      command = "normal! m'"
    try:
      self.vim.command(command)
    except:
      # For some unknown reason, whenever an exception occurs in
      # vim.command, vim goes crazy and output tons of useless python
      # errors, catch those.
      return
    if not preview:
      self.vim.current.window.cursor = (line, column - 1)


  def gotoDeclaration(self, preview=True):
    params = self.getCompileParams(self.vim.current.buffer.name)
    line, col = self.vim.current.window.cursor

    tu = self.getCurrentTranslationUnit(params['args'], self.getCurrentFile(),
                                   self.vim.current.buffer.name,
                                   update = True)
    if tu is None:
      print("Couldn't get the TranslationUnit")
      return

    f      = File.from_name(tu, self.vim.current.buffer.name)
    loc    = SourceLocation.from_position(tu, f, line, col + 1)
    cursor = Cursor.from_location(tu, loc)
    defs   = [cursor.get_definition(), cursor.referenced]

    for d in defs:
      if d is not None and loc != d.location:
        loc = d.location
        if loc.file is not None:
          self.jumpToLocation(loc.file.name, loc.line, loc.column, preview)
        break

# vim: set ts=2 sts=2 sw=2 expandtab :
