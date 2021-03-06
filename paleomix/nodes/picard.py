#!/usr/bin/python
#
# Copyright (c) 2012 Mikkel Schubert <MikkelSch@gmail.com>
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
import getpass

from paleomix.node import CommandNode
from paleomix.atomiccmd.builder import \
    AtomicJavaCmdBuilder, \
    create_customizable_cli_parameters, \
    use_customizable_cli_parameters
from paleomix.atomiccmd.sets import \
    ParallelCmds
from paleomix.common.fileutils import \
    swap_ext, \
    try_rmtree, \
    reroot_path, \
    describe_files
from paleomix.common.utilities import \
    safe_coerce_to_tuple
import paleomix.common.versions as versions
import paleomix.common.system


class PicardNode(CommandNode):
    """Base class for nodes using Picard Tools; adds an additional cleanup
    step, in order to allow the jars to be run using the same temporary folder
    as any other commands associated with the node. This is nessesary as some
    Picard tools create a large number of temporary files, leading to potential
    performance issues if these are located in the same folder.
    """

    def _teardown(self, config, temp):
        # Picard creates a folder named after the user in the temp-root
        try_rmtree(os.path.join(temp, getpass.getuser()))
        # Some JREs may create a folder for temporary performance counters
        try_rmtree(os.path.join(temp, "hsperfdata_" + getpass.getuser()))

        CommandNode._teardown(self, config, temp)


class ValidateBAMNode(PicardNode):
    def __init__(self, config, input_bam, input_index=None, output_log=None,
                 ignored_checks=(), dependencies=()):
        builder = picard_command(config, "ValidateSamFile")
        _set_max_open_files(builder, "MAX_OPEN_TEMP_FILES")

        builder.set_option("I", "%(IN_BAM)s", sep="=")
        for check in ignored_checks:
            builder.add_option("IGNORE", check, sep="=")

        output_log = output_log or swap_ext(input_bam, ".validated")
        builder.set_kwargs(IN_BAM=input_bam,
                           IN_INDEX=input_index,
                           OUT_STDOUT=output_log)

        description = "<Validate BAM: '%s'>" % (input_bam,)
        PicardNode.__init__(self,
                            command=builder.finalize(),
                            description=description,
                            dependencies=dependencies)


class BuildSequenceDictNode(PicardNode):
    def __init__(self, config, reference, dependencies=()):
        self._in_reference = os.path.abspath(reference)

        builder = picard_command(config, "CreateSequenceDictionary")

        builder.set_option("R", "%(TEMP_OUT_REF)s", sep="=")
        builder.set_option("O", "%(OUT_DICT)s", sep="=")
        builder.set_kwargs(IN_REFERENCE=reference,
                           TEMP_OUT_REF=os.path.basename(reference),
                           OUT_DICT=swap_ext(reference, ".dict"))

        description = "<SequenceDictionary: '%s'>" % (reference,)

        PicardNode.__init__(self,
                            command=builder.finalize(),
                            description=description,
                            dependencies=dependencies)

    def _setup(self, _config, temp):
        # Ensure that Picard CreateSequenceDict cannot reuse any existing
        # sequence dictionaries, if the underlying files have changed.
        os.symlink(self._in_reference, reroot_path(temp, self._in_reference))


class MarkDuplicatesNode(PicardNode):
    @create_customizable_cli_parameters
    def customize(cls, config, input_bams, output_bam, output_metrics=None,
                  keep_dupes=False, dependencies=()):
        params = picard_command(config, "MarkDuplicates")
        _set_max_open_files(params, "MAX_FILE_HANDLES")

        params.set_option("OUTPUT", "%(OUT_BAM)s", sep="=")
        params.set_option("METRICS_FILE", "%(OUT_METRICS)s", sep="=")
        # Validation is mostly left to manual ValidateSamFile runs; required
        # because .csi indexed BAM records can have "invalid" bins.
        params.set_option("VALIDATION_STRINGENCY", "LENIENT", sep="=")
        params.add_multiple_options("I", input_bams, sep="=")

        if not keep_dupes:
            # Remove duplicates from output by default to save disk-space
            params.set_option("REMOVE_DUPLICATES", "True",
                              sep="=", fixed=False)

        output_metrics = output_metrics or swap_ext(output_bam, ".metrics")
        params.set_kwargs(OUT_BAM=output_bam,
                          OUT_METRICS=output_metrics)

        return {"command": params,
                "dependencies": dependencies}

    @use_customizable_cli_parameters
    def __init__(self, parameters):
        description = "<MarkDuplicates: %s>" \
            % (describe_files(parameters.input_bams),)
        PicardNode.__init__(self,
                            command=parameters.command.finalize(),
                            description=description,
                            dependencies=parameters.dependencies)


class MergeSamFilesNode(PicardNode):
    def __init__(self, config, input_bams, output_bam, dependencies=()):
        builder = picard_command(config, "MergeSamFiles")
        builder.set_option("OUTPUT", "%(OUT_BAM)s", sep="=")
        builder.set_option("SO", "coordinate", sep="=")
        # Validation is mostly left to manual ValidateSamFile runs; required
        # because .csi indexed BAM records can have "invalid" bins.
        builder.set_option("VALIDATION_STRINGENCY", "LENIENT", sep="=")
        builder.add_multiple_options("I", input_bams, sep="=")

        builder.set_kwargs(OUT_BAM=output_bam)
        description = "<Merge BAMs: %i file(s) -> '%s'>" \
            % (len(input_bams), output_bam)
        PicardNode.__init__(self,
                            command=builder.finalize(),
                            description=description,
                            dependencies=dependencies)


class MultiBAMInputNode(CommandNode):
    PIPE_FILE = "input.bam"

    def __init__(self, config, input_bams, command, index_format=None,
                 description=None, threads=1, dependencies=()):
        self._input_bams = safe_coerce_to_tuple(input_bams)
        self._index_format = index_format

        if not self._input_bams:
            raise ValueError("No input BAM files specified!")
        elif len(self._input_bams) > 1 and index_format:
            raise ValueError("BAM index cannot be required for > 1 file")
        elif index_format not in (None, ".bai", ".csi"):
            raise ValueError("Unknown index format %r" % (index_format,))

        if len(self._input_bams) > 1:
            merge = picard_command(config, "MergeSamFiles")
            merge.set_option("SO", "coordinate", sep="=")
            merge.set_option("COMPRESSION_LEVEL", 0, sep="=")
            merge.set_option("OUTPUT", "%(TEMP_OUT_BAM)s", sep="=")
            # Validation is mostly left to manual ValidateSamFile runs; this
            # is because .csi indexed BAM records can have "invalid" bins.
            merge.set_option("VALIDATION_STRINGENCY", "LENIENT", sep="=")
            merge.add_multiple_options("I", input_bams, sep="=")

            merge.set_kwargs(TEMP_OUT_BAM=self.PIPE_FILE)

            command = ParallelCmds([merge.finalize(), command])

        CommandNode.__init__(self,
                             command=command,
                             description=description,
                             threads=threads,
                             dependencies=dependencies)

    def _setup(self, config, temp):
        CommandNode._setup(self, config, temp)

        pipe_fname = os.path.join(temp, self.PIPE_FILE)
        if len(self._input_bams) > 1:
            os.mkfifo(pipe_fname)
        else:
            source_fname = os.path.abspath(self._input_bams[0])
            os.symlink(source_fname, pipe_fname)

            if self._index_format:
                os.symlink(swap_ext(source_fname, self._index_format),
                           swap_ext(pipe_fname, self._index_format))

    def _teardown(self, config, temp):
        os.remove(os.path.join(temp, self.PIPE_FILE))
        if self._index_format:
            os.remove(os.path.join(temp, swap_ext(self.PIPE_FILE,
                                                  self._index_format)))

        CommandNode._teardown(self, config, temp)


###############################################################################

_PICARD_JAR = "picard.jar"
_PICARD_VERSION_CACHE = {}


def picard_command(config, command):
    """Returns basic AtomicJavaCmdBuilder for Picard tools commands."""
    jar_path = os.path.join(config.jar_root, _PICARD_JAR)

    if jar_path not in _PICARD_VERSION_CACHE:
        params = AtomicJavaCmdBuilder(jar_path,
                                      temp_root=config.temp_root,
                                      jre_options=config.jre_options)

        # Arbitrary command, since just '--version' does not work
        params.set_option("MarkDuplicates")
        params.set_option("--version")

        requirement = versions.Requirement(call=params.finalized_call,
                                           name="Picard tools",
                                           search=r"^(\d+)\.(\d+)",
                                           checks=versions.GE(1, 137))
        _PICARD_VERSION_CACHE[jar_path] = requirement

    version = _PICARD_VERSION_CACHE[jar_path]
    params = AtomicJavaCmdBuilder(jar_path,
                                  temp_root=config.temp_root,
                                  jre_options=config.jre_options,
                                  CHECK_JAR=version)
    params.set_option(command)

    return params


# Fraction of per-process max open files to use
_FRAC_MAX_OPEN_FILES = 0.95
# Default maximum number of open temporary files used by Picard
_DEFAULT_MAX_OPEN_FILES = 8000


def _set_max_open_files(params, key):
    """Sets the maximum number of open files a picard process
    should use, at most. Conservatively lowered than the actual
    ulimit.
    """
    max_open_files = paleomix.common.system.get_max_open_files()
    if max_open_files:
        max_open_files = int(max_open_files * _FRAC_MAX_OPEN_FILES)

        if max_open_files < _DEFAULT_MAX_OPEN_FILES:
            params.set_option(key, max_open_files, sep="=")
