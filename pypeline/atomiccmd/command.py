#!/usr/bin/python
#
# Copyright (c) 2012 Mikkel Schubert <MSchubert@snm.ku.dk>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
import os
import re
import sys
import signal
import types
import weakref
import subprocess
import collections

import pypeline.atomiccmd.pprint as atomicpp
import pypeline.common.fileutils as fileutils
import pypeline.common.signals as signals
from pypeline.common.utilities import safe_coerce_to_tuple

_PIPES = (("IN", "IN_STDIN"),
          ("OUT", "OUT_STDOUT"),
          ("OUT", "OUT_STDERR"))
_KEY_RE = re.compile("^(IN|OUT|EXEC|AUX|CHECK|TEMP_IN|TEMP_OUT)_[A-Z0-9_]+")
_FILE_MAP = {"IN": "input",
             "OUT": "output",
             "TEMP_IN": None,
             "TEMP_OUT": "temporary_fname",
             "EXEC": "executable",
             "AUX": "auxiliary",
             "CHECK": "requirements"}


class CmdError(RuntimeError):
    def __init__(self, msg):
        RuntimeError.__init__(self, msg)


class AtomicCmd(object):
    """Executes a command, only moving resulting files to the destination
    directory if the command was succesful. This helps prevent the
    accidential use of partial files in downstream analysis, and eases
    restarting of a pipeline following errors (no cleanup).

    Inividual files/paths in the command are specified using keywords (see
    the documentation for the constructor), allowing the command to be
    transparently modified to execute in a temporary directory.

    When an AtomicCmd is run(), a signal handler is installed for SIGTERM,
    which ensures that any running processes are terminated. In the absence
    of this, AtomicCmds run in terminated subprocesses can result in still
    running children after the termination of the parents."""
    PIPE = subprocess.PIPE

    def __init__(self, command, set_cwd=False, **kwargs):
        """Takes a command and a set of files.

        The command is expected to be an iterable starting with the name of an
        executable, with each item representing one string on the command line.
        Thus, the command "find /etc -name 'profile*'" might be represented as
        the list ["find", "/etc", "-name", "profile*"].

        Commands typically consist of an executable, one or more input files,
        one or more output files, and one or more pipes. In atomic command,
        such files are not specified directly, but instead are specified using
        keywords, which allows easy tracking of requirements and other
        features. Note that only files, and not directories, are supported as
        input/output!

        Each keyword represents a type of file, as determined by the prefix:
           IN_    -- Path to input file transformed/analysed the executable.
           OUT_   -- Path to output file generated by the executable. During
                     execution of the AtomicCmd, these paths are modified to
                     point to the temporary directory.
           EXEC_  -- Name of / path to executable. The first item in the
                     command is always one of the executables, even if not
                     specified in this manner.
           AUX_   -- Auxillery files required by the executable(s), which are
                     themselves not executable. Examples include scripts,
                     config files, data-bases, and the like.
           CHECK_ -- A callable, which upon calling does version checking,
                     raising an exception in the case of requirements not being
                     met. This may be used to ensure that prerequisites are met
                     before running the command. The function is not called by
                     AtomicCmd itself.

        EXAMPLE 1: Creating a gzipped tar-archive from two files
        The command "tar cjf output-file input-file-1 input-file-2" could be
        represented using the following AtomicCmd:
        cmd = AtomicCmd(["tar", "cjf", "%(OUT_FILE)s",
                         "%(IN_FILE_1)s", "%(IN_FILE_2)s"],
                        OUT_FILE  = "output-file",
                        IN_FILE_1 = "input-file-1",
                        IN_FILE_2 = "input-file-2")

        Note that files that are not directly invoked may be included above,
        in order to allow the specification of requirements. This could include
        required data files, or executables indirectly executed by a script.

        If the above is prefixed with "TEMP_", files are read from / written
        to the temporary folder in which the command is executed. Note that all
        TEMP_OUT_ files are deleted when commit is called (if they exist), and
        only filenames (not dirname component) are allowed for TEMP_ values.

        In addition, the follow special names may be used with the above:
           STDIN_  -- Takes a filename, or an AtomicCmd, in which case stdout
                      of that command is piped to the stdin of this instance.
           STDOUT_ -- Takes a filename, or the special value PIPE to allow
                      another AtomicCmd instance to use the output directly.
           STDERR_ -- Takes a filename.

        Each pipe can only be used once, with or without the TEMP_ prefix.

        EXAMPLE 2: zcat'ing an archive
        The command "zcat input-file > output-file" could be represented using
        the following AtomicCmd:
        cmd = AtomicCmd(["zcat", "%(IN_FILE)s"],
                        OUT_STDOUT = "output-file")

        If 'set_cwd' is True, the current working directory is set to the
        temporary directory before the command is executed. Input paths are
        automatically turned into absolute paths in this case."""
        self._proc = None
        self._temp = None
        self._running = False
        self._command = map(str, safe_coerce_to_tuple(command))
        self._set_cwd = set_cwd
        if not self._command or not self._command[0]:
            raise ValueError("Empty command in AtomicCmd constructor")

        arguments = self._process_arguments(id(self), self._command, kwargs)
        self._files = self._build_files_dict(arguments)
        self._file_sets = self._build_files_map(self._command, arguments)

        # Dry-run, to catch errors early
        self._generate_call("/tmp")

    def run(self, temp, wrap_errors=True):
        """Runs the given command, saving files in the specified temp folder.
        To move files to their final destination, call commit(). Note that in
        contexts where the *Cmds classes are used, this function may block.

        """
        if self._running:
            raise CmdError("Calling 'run' on already running command.")
        self._temp = temp
        self._running = True

        # kwords for pipes are always built relative to the current directory,
        # since these are opened before (possibly) CD'ing to the temp
        # directory.
        stdin = stdout = stderr = None
        try:
            kwords = self._generate_filenames(self._files, root=temp)
            stdin = self._open_pipe(kwords, "IN_STDIN", "rb")
            stdout = self._open_pipe(kwords, "OUT_STDOUT", "wb")
            stderr = self._open_pipe(kwords, "OUT_STDERR", "wb")

            cwd = temp if self._set_cwd else None
            temp = "" if self._set_cwd else os.path.abspath(temp)
            call = self._generate_call(temp)

            self._proc = subprocess.Popen(call,
                                          stdin=stdin,
                                          stdout=stdout,
                                          stderr=stderr,
                                          cwd=cwd,
                                          preexec_fn=os.setsid,
                                          close_fds=True)
        except StandardError, error:
            if not wrap_errors:
                raise

            message = \
                "Error running commands:\n" \
                "  Call = %r\n" \
                "  Error = %r"
            raise CmdError(message % (self._command, error))
        finally:
            # Close pipes to allow the command to recieve SIGPIPE
            for handle in (stdin, stdout, stderr):
                if handle not in (None, self.PIPE):
                    handle.close()

        # Allow subprocesses to be killed in case of a SIGTERM
        _add_to_killlist(self._proc)

    def ready(self):
        """Returns true if the command has been run to completion,
        regardless of wether or not an error occured."""
        return self._proc and self._proc.poll() is not None

    def join(self):
        """Similar to Popen.wait(), but returns the value wrapped in a list,
        and ensures that any opened handles are closed. Must be called before
        calling commit."""
        if not self._proc:
            return [None]

        self._running = False
        return_code = self._proc.wait()
        if return_code < 0:
            return_code = signals.to_str(-return_code)
        return [return_code]

    def wait(self):
        """Equivalent to Subproces.wait. This function should only
        be used in contexts where a AtomicCmd needs to be combined
        with Subprocesses, as it does not exist for AtomicSets."""
        return self.join()[0]

    def terminate(self):
        """Sends SIGTERM to process if it is still running.
        Has no effect if the command has already finished."""
        if self._proc and self._proc.poll() is None:
            try:
                os.killpg(self._proc.pid, signal.SIGTERM)
            except OSError:
                pass  # Already dead / finished process

    # Properties, returning filenames from self._file_sets
    def _property_file_sets(key):  # pylint: disable=E0213
        def _get_property_files(self):
            return self._file_sets[key]  # pylint: disable=W0212
        return property(_get_property_files)

    executables = _property_file_sets("executable")
    requirements = _property_file_sets("requirements")
    input_files = _property_file_sets("input")
    output_files = _property_file_sets("output")
    auxiliary_files = _property_file_sets("auxiliary")
    expected_temp_files = _property_file_sets("output_fname")
    optional_temp_files = _property_file_sets("temporary_fname")

    def commit(self, temp):
        if not self.ready():
            raise CmdError("Attempting to commit before command has completed")
        elif self._running:
            raise CmdError("Called 'commit' before calling 'join'")
        elif not os.path.samefile(self._temp, temp):
            raise CmdError("Mismatch between previous and current temp folders"
                           ": %r != %s" % (self._temp, temp))

        missing_files = self.expected_temp_files - set(os.listdir(temp))
        if missing_files:
            raise CmdError("Expected files not created: %s"
                           % (", ".join(missing_files)))

        temp = os.path.abspath(temp)
        filenames = self._generate_filenames(self._files, temp)
        committed_files = set()
        try:
            for (key, filename) in filenames.iteritems():
                if isinstance(filename, types.StringTypes):
                    if key.startswith("OUT_"):
                        fileutils.move_file(filename, self._files[key])
                        committed_files.add(self._files[key])
                    elif key.startswith("TEMP_OUT_"):
                        fileutils.try_remove(filename)
        except:
            # Cleanup after failed commit
            for fpath in committed_files:
                fileutils.try_remove(fpath)
            raise

        self._proc = None
        self._temp = None

    def __str__(self):
        return atomicpp.pformat(self)

    def _generate_call(self, temp):
        kwords = self._generate_filenames(self._files, root=temp)

        try:
            return [(field % kwords) for field in self._command]
        except (TypeError, ValueError), error:
            raise CmdError("Error building Atomic Command:\n"
                           "  Call = %s\n  Error = %s: %s"
                           % (self._command, error.__class__.__name__, error))
        except KeyError, error:
            raise CmdError("Error building Atomic Command:\n"
                           "  Call = %s\n  Value not specified for path = %s"
                           % (self._command, error))

    @classmethod
    def _process_arguments(cls, proc_id, command, kwargs):
        arguments = collections.defaultdict(dict)
        for (key, value) in kwargs.iteritems():
            match = _KEY_RE.match(key)
            if not match:
                raise ValueError("Invalid keyword argument %r" % (key,))

            # None is ignored, to make use of default arguments easier
            if value is not None:
                group, = match.groups()
                arguments[group][key] = value

        # Pipe stdout/err to files by default
        executable = os.path.basename(command[0])
        for pipe in ("STDOUT", "STDERR"):
            has_out_pipe = ("OUT_" + pipe) in arguments["OUT"]
            has_temp_out_pipe = ("TEMP_OUT_" + pipe) in arguments["TEMP_OUT"]
            if not (has_out_pipe or has_temp_out_pipe):
                filename = "pipe_%s_%i.%s" % (executable, proc_id,
                                              pipe.lower())
                arguments["TEMP_OUT"]["TEMP_OUT_" + pipe] = filename

        cls._validate_arguments(arguments)
        cls._validate_output_files(arguments)
        cls._validate_pipes(arguments)

        return arguments

    @classmethod
    def _validate_arguments(cls, arguments):
        # Output files
        for group in ("OUT", "TEMP_OUT"):
            for (key, value) in arguments.get(group, {}).iteritems():
                if isinstance(value, types.StringTypes):
                    continue

                if key in ("OUT_STDOUT", "TEMP_OUT_STDOUT"):
                    if value != cls.PIPE:
                        raise TypeError("STDOUT must be a string or "
                                        "AtomicCmd.PIPE, not %r" % (value,))
                else:
                    raise TypeError("%s must be string, not %r" % (key, value))

        # Input files, including executables and auxiliary files
        for group in ("IN", "TEMP_IN", "EXEC", "AUX"):
            for (key, value) in arguments.get(group, {}).iteritems():
                if isinstance(value, types.StringTypes):
                    continue

                if key in ("IN_STDIN", "TEMP_IN_STDIN"):
                    if not isinstance(value, AtomicCmd):
                        raise TypeError("STDIN must be string or AtomicCmd, "
                                        "not %r" % (value,))
                else:
                    raise TypeError("%s must be string, not %r" % (key, value))

        for (key, value) in arguments.get("CHECK", {}).iteritems():
            if not isinstance(value, collections.Callable):
                raise TypeError("%s must be callable, not %r" % (key, value))

        for group in ("TEMP_IN", "TEMP_OUT"):
            for (key, value) in arguments.get(group, {}).iteritems():
                is_string = isinstance(value, types.StringTypes)
                if is_string and os.path.dirname(value):
                    raise ValueError("%s cannot contain dir component: %r"
                                     % (key, value))

        return True

    @classmethod
    def _validate_output_files(cls, arguments):
        output_files = collections.defaultdict(list)
        for group in ("OUT", "TEMP_OUT"):
            for (key, value) in arguments.get(group, {}).iteritems():
                if isinstance(value, types.StringTypes):
                    filename = os.path.basename(value)
                    output_files[filename].append(key)

        for (filename, keys) in output_files.iteritems():
            if len(keys) > 1:
                raise ValueError("Same output filename (%s) is specified for "
                                 "multiple keys: %s"
                                 % (filename, ", ".join(sorted(keys))))

    @classmethod
    def _validate_pipes(cls, arguments):
        for (group, pipe) in _PIPES:
            has_pipe = pipe in arguments[group]
            has_temp_pipe = ("TEMP_" + pipe) in arguments["TEMP_" + group]
            if has_pipe and has_temp_pipe:
                raise CmdError("Pipes may only be specified once")

    @classmethod
    def _open_pipe(cls, kwords, pipe, mode):
        filename = kwords.get(pipe, kwords.get("TEMP_" + pipe))
        if filename in (None, cls.PIPE):
            return filename
        elif isinstance(filename, AtomicCmd):
            # pylint: disable=W0212
            return filename._proc and filename._proc.stdout

        return open(filename, mode)

    @classmethod
    def _generate_filenames(cls, files, root):
        filenames = {"TEMP_DIR": root}
        for (key, filename) in files.iteritems():
            if isinstance(filename, types.StringTypes):
                if key.startswith("TEMP_") or key.startswith("OUT_"):
                    filename = os.path.join(root, os.path.basename(filename))
                elif not root and (key.startswith("IN_") or key.startswith("AUX_")):
                    filename = os.path.abspath(filename)
            filenames[key] = filename

        return filenames

    @classmethod
    def _build_files_dict(cls, arguments):
        files = {}
        for groups in arguments.itervalues():
            for (key, value) in groups.iteritems():
                files[key] = value

        return files

    @classmethod
    def _build_files_map(cls, command, arguments):
        file_sets = dict((key, set()) for key in _FILE_MAP.itervalues())

        file_sets["executable"].add(command[0])
        for (group, files) in arguments.iteritems():
            group_set = file_sets[_FILE_MAP[group]]

            for (key, filename) in files.iteritems():
                is_string = isinstance(filename, types.StringTypes)
                if is_string or key.startswith("CHECK_"):
                    group_set.add(filename)

        file_sets["output_fname"] = map(os.path.basename, file_sets["output"])

        return dict(zip(file_sets.iterkeys(),
                        map(frozenset, file_sets.itervalues())))


# The following ensures proper cleanup of child processes, for example in the
# case where multiprocessing.Pool.terminate() is called.
_PROCS = set()


def _cleanup_children(signum, _frame):
    for proc_ref in list(_PROCS):
        proc = proc_ref()
        if proc:
            os.killpg(proc.pid, signal.SIGTERM)
    sys.exit(-signum)


def _add_to_killlist(proc):
    if not _PROCS:
        signal.signal(signal.SIGTERM, _cleanup_children)

    _PROCS.add(weakref.ref(proc, _PROCS.remove))
