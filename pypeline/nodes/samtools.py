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
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
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

from pypeline.node import CommandNode
from pypeline.atomiccmd import AtomicCmd
from pypeline.atomicset import ParallelCmds
from pypeline.common.fileutils import reroot_path, swap_ext


class GenotypeNode(CommandNode):
    pileup_args = "-EA"
    caller_args = "-g"

    def __init__(self, reference, infile, outfile, regions = None, dependencies = ()):
        assert outfile.lower().endswith(".vcf.bgz")

        call_pileup = ["samtools", "mpileup", 
                       GenotypeNode.pileup_args,
                       "-uf", "%(IN_REFERENCE)s",
                       "%(IN_BAMFILE)s"]
        if regions:
            call_pileup[-1:-1] = ["-l", "%(IN_REGIONS)s"]

        pileup   = AtomicCmd(call_pileup,
                             IN_REFERENCE = reference,
                             IN_BAMFILE   = infile,
                             IN_REGIONS   = regions,
                             OUT_STDOUT   = AtomicCmd.PIPE)
        
        genotype = AtomicCmd(["bcftools", "view", GenotypeNode.caller_args, "-"],
                             IN_STDIN     = pileup,
                             OUT_STDOUT   = AtomicCmd.PIPE)

        bgzip    = AtomicCmd(["bgzip"],
                             IN_STDIN     = genotype,
                             OUT_STDOUT   = outfile)

        description = "<Genotyper: '%s' -> '%s'>" % (infile, outfile)
        CommandNode.__init__(self, 
                             description  = description,
                             command      = ParallelCmds([pileup, genotype, bgzip]),
                             dependencies = dependencies)


class MPileupNode(CommandNode):
    pileup_args = "-EA"

    def __init__(self, reference, infile, outfile, regions = None, dependencies = ()):
        call = ["samtools", "mpileup", 
                MPileupNode.pileup_args,
                "-f", "%(IN_REFERENCE)s",
                "%(IN_BAMFILE)s"]
        if regions:
            call[-1:-1] = ["-l", "%(IN_REGIONS)s"]

        pileup   = AtomicCmd(call,
                             IN_REFERENCE = reference,
                             IN_BAMFILE   = infile,
                             IN_REGIONS   = regions,
                             OUT_STDOUT   = AtomicCmd.PIPE)

        bgzip    = AtomicCmd(["bgzip"],
                             IN_STDIN     = pileup,
                             OUT_STDOUT   = outfile)

        description = "<MPileup: '%s' -> '%s'>" % (infile, outfile)
        CommandNode.__init__(self, 
                             description  = description,
                             command      = ParallelCmds([pileup, bgzip]),
                             dependencies = dependencies)



class TabixIndexNode(CommandNode):
    def __init__(self, infile, preset = "vcf", dependencies = ()):
        assert infile.lower().endswith(".bgz")
        if preset == "pileup":
            call = ["tabix", "-s", 1, "-b", 2, "-e", 2]
        else:
            call = ["tabix", "-p", preset]


        self._infile = infile
        cmd_tabix = AtomicCmd(call + ["%(TEMP_IN_VCFFILE)s"],
                              TEMP_IN_VCFFILE = os.path.basename(infile),
                              IN_VCFFILE      = infile,
                              OUT_TBI         = infile + ".tbi")

        CommandNode.__init__(self, 
                             description  = "<TabixIndex (%s): '%s'>" % (preset, infile,),
                             command      = cmd_tabix,
                             dependencies = dependencies)

    def _setup(self, config, temp):
        infile  = os.path.abspath(self._infile)
        outfile = reroot_path(temp, self._infile)
        os.symlink(infile, outfile)

        CommandNode._setup(self, config, temp)


    def _teardown(self, config, temp):
        os.remove(reroot_path(temp, self._infile))

        CommandNode._teardown(self, config, temp)




class FastaIndexNode(CommandNode):
    def __init__(self, infile, dependencies = ()):
        self._infile = infile
        cmd_faidx = AtomicCmd(["samtools", "faidx", "%(TEMP_IN_FASTA)s"],
                              TEMP_IN_FASTA = os.path.basename(infile),
                              IN_FASTA      = infile,
                              OUT_TBI       = infile + ".fai")

        CommandNode.__init__(self, 
                             description  = "<FastaIndex: '%s'>" % (infile,),
                             command      = cmd_faidx,
                             dependencies = dependencies)


    def _setup(self, config, temp):
        infile  = os.path.abspath(self._infile)
        outfile = reroot_path(temp, self._infile)
        os.symlink(infile, outfile)

        CommandNode._setup(self, config, temp)


    def _teardown(self, config, temp):
        os.remove(reroot_path(temp, self._infile))

        CommandNode._teardown(self, config, temp)




class BAMIndexNode(CommandNode):
    def __init__(self, infile, dependencies = ()):
        cmd_index = AtomicCmd(["samtools", "index", "%(IN_BAM)s", "%(OUT_BAI)s"],
                              IN_BAM      = infile,
                              OUT_BAI     = swap_ext(infile, ".bai"))

        CommandNode.__init__(self, 
                             description  = "<BAMIndex: '%s'>" % (infile,),
                             command      = cmd_index,
                             dependencies = dependencies)